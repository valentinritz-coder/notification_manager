from __future__ import annotations

import hashlib
import heapq
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as dt_parser

from .hafas_gate import HafasGate
from .io import append_ndjson, ensure_dir, ensure_state, read_json, update_state, write_json_redacted


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = dt_parser.isoparse(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None

def _get_connection_info0(details: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        res = details["svcResL"][0]["res"]
    except Exception:
        return None

    # Preferred: res.details.conSubscr.connectionInfo[0]
    try:
        ci = res["details"]["conSubscr"]["connectionInfo"][0]
        if isinstance(ci, dict):
            return ci
    except Exception:
        pass

    # Alt: res.details.intvlSubscr.connectionInfo[0] (si jamais)
    try:
        ci = res["details"]["intvlSubscr"]["connectionInfo"][0]
        if isinstance(ci, dict):
            return ci
    except Exception:
        pass

    # Fallback: take conSecInfo from latest rtEvent
    try:
        eh = res["details"]["eventHistory"]
        rt = eh.get("rtEvents") or []
        if isinstance(rt, list) and rt:
            last = rt[-1]
            sec = (last.get("rtConSecInfos") or [])[0]
            ci = (sec.get("conSecInfo") or {})
            if isinstance(ci, dict) and ci:
                return ci
    except Exception:
        pass

    # Legacy fallback: res.connectionInfo[0]
    try:
        ci = res["connectionInfo"][0]
        if isinstance(ci, dict):
            return ci
    except Exception:
        pass

    return None

def _extract_departure_time(details: Dict[str, Any]) -> Optional[datetime]:
    ci0 = _get_connection_info0(details)
    return _parse_dt(ci0.get("departureTime")) if ci0 else None


def _extract_arrival_time(details: Dict[str, Any]) -> Optional[datetime]:
    ci0 = _get_connection_info0(details)
    return _parse_dt(ci0.get("arrivalTime")) if ci0 else None


def _extract_rt_events(details: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        res = details["svcResL"][0]["res"]
    except Exception:
        return []

    # Preferred: SubscrDetails -> res.details.eventHistory.rtEvents
    try:
        eh = res["details"]["eventHistory"]
        rt = eh.get("rtEvents") or []
        return rt if isinstance(rt, list) else []
    except Exception:
        pass

    # Fallback legacy: res.rtInfo.rtEventL
    try:
        rt = (res.get("rtInfo") or {}).get("rtEventL") or []
        return rt if isinstance(rt, list) else []
    except Exception:
        return []


def _compute_planned_end(details: Dict[str, Any], post_window_min: int) -> Optional[datetime]:
    arrival = _extract_arrival_time(details)
    departure = _extract_departure_time(details)
    base = arrival or departure
    if not base:
        return None
    return base + timedelta(minutes=post_window_min)


def _event_key(event: Dict[str, Any]) -> str:
    change_id = event.get("changeId")
    if change_id:
        return str(change_id)
    raw = json.dumps(event, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _normalize_event(
    event: Dict[str, Any],
    scenario_id: str,
    subscr_id: int | None,
    corr_id: str,
    ts_poll_utc: str,
    include_raw: bool,
) -> Dict[str, Any]:
    normalized: Dict[str, Any] = {
        "tsPollUtc": ts_poll_utc,
        "corrId": corr_id,
        "subscrId": subscr_id,
        "scenarioId": scenario_id,
        "key": _event_key(event),
        "changeId": event.get("changeId"),
        "changeType": event.get("changeType"),
        "title": event.get("title"),
        "msg": event.get("msg"),
        "received": event.get("received"),
        "date": event.get("date"),
        "planrtTS": event.get("planrtTS"),
    }
    if include_raw:
        normalized["raw"] = event
    return normalized


def run_poll(
    run_dir: Path,
    hafas: HafasGate,
    poll_sec: int,
    pre_window_min: int,
    post_window_min: int,
    idle_grace_min: int = 15,
    max_runtime_min: int = 0,
    include_raw: bool = False,
    save_logs: bool = True,
) -> None:
    subs_dir = run_dir / "subs"
    if not subs_dir.exists():
        # Rien à poll
        return

    subscr_dirs = sorted([p for p in subs_dir.iterdir() if p.is_dir()])
    if not subscr_dirs:
        return

    start_time = datetime.now(timezone.utc)
    deadline = start_time + timedelta(minutes=max_runtime_min) if max_runtime_min else None

    # Scheduler: each subscription has its own next_due (monotonic seconds).
    # Initial staggering spreads the first round across poll_sec to avoid bursts.
    n = len(subscr_dirs)
    base = time.monotonic()
    slot = poll_sec / max(1, n)

    # heap entries: (due_monotonic, idx, subscr_dir)
    heap: List[Tuple[float, int, Path]] = []
    for i, d in enumerate(subscr_dirs):
        heapq.heappush(heap, (base + i * slot, i, d))

    def _deadline_reached() -> bool:
        return bool(deadline and datetime.now(timezone.utc) >= deadline)

    def _sleep_until(due_mono: float) -> bool:
        """Sleep until due_mono or until deadline. Returns False if deadline reached."""
        while True:
            if _deadline_reached():
                return False
            now_mono = time.monotonic()
            wait = due_mono - now_mono
            if wait <= 0:
                return True

            if deadline:
                remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
                if remaining <= 0:
                    return False
                time.sleep(min(wait, remaining))
            else:
                time.sleep(wait)

    def _reschedule(idx: int, subscr_dir: Path, after_sec: float) -> None:
        """Reschedule a subscription after after_sec seconds (monotonic)."""
        next_due = time.monotonic() + max(0.0, float(after_sec))
        heapq.heappush(heap, (next_due, idx, subscr_dir))

    # Changelog: add dynamic idle grace stop logic after planned arrival windows.
    while True:
        if not heap:
            break
        if _deadline_reached():
            break

        due_mono, idx, subscr_dir = heapq.heappop(heap)
        if not _sleep_until(due_mono):
            break

        # --- Read manifest safely ---
        try:
            manifest = read_json(subscr_dir / "manifest.json")
        except Exception:
            # Pas de manifest -> on réessaie plus tard (et on évite de tuer tout le poll)
            _reschedule(idx, subscr_dir, min(poll_sec * 2, 900))
            continue

        subscr_id = manifest.get("subscrId")
        scenario_id = manifest.get("scenarioId", "unknown")

        if not subscr_id:
            # Sub sans subscrId -> on réessaie plus tard
            _reschedule(idx, subscr_dir, min(poll_sec * 2, 900))
            continue

        poll_state_dir = subscr_dir / "poll"
        ensure_dir(poll_state_dir)

        state_path = poll_state_dir / "state.json"
        state = ensure_state(state_path)
        if state.get("done"):
            continue
        seen_keys = set(state.get("seenKeys", []))
        poll_count = int(state.get("pollCount") or 0)
        last_activity = _parse_dt(state.get("lastActivityUtc"))
        planned_end_state = _parse_dt(state.get("plannedEndUtc"))

        # --- Call HAFAS safely ---
        try:
            details, corr_id, request_payload = hafas.subscr_details(subscr_id)
        except Exception:
            # Réseau/500/timeout: on backoff sans tout arrêter
            _reschedule(idx, subscr_dir, min(poll_sec * 2, 900))
            continue

        # --- Logs ---
        if save_logs:
            try:
                secrets = {
                    hafas.config.aid: "<AID>",
                    hafas.config.user_id: "<USER_ID>",
                    hafas.config.channel_id: "<CHANNEL_ID>",
                }
                raw_dir = subscr_dir / "raw"
                ensure_dir(raw_dir)
                write_json_redacted(raw_dir / f"{poll_count:02d}_subscrdetails_resp.json", details, secrets)
                write_json_redacted(raw_dir / f"{poll_count:02d}_subscrdetails_req.json", request_payload, secrets)
                (raw_dir / f"{poll_count:02d}_subscrdetails_corrid.txt").write_text(corr_id, encoding="utf-8")
            except Exception:
                # Logging ne doit jamais casser le poll
                pass

        now = datetime.now(timezone.utc)
        arr_time = _extract_arrival_time(details)
        dep_time = _extract_departure_time(details)
        planned_end = _compute_planned_end(details, post_window_min) or planned_end_state
        planned_end_utc = planned_end.astimezone(timezone.utc).isoformat() if planned_end else None

        if dep_time:
            window_start = dep_time - timedelta(minutes=pre_window_min)
            window_end = (arr_time or dep_time) + timedelta(minutes=post_window_min)
            in_window = window_start <= now <= window_end
        else:
            window_start = None
            window_end = None
            in_window = False

        activity = False
        events = _extract_rt_events(details)
        ts_poll_utc = now.isoformat()
        normalized_rows: List[Dict[str, Any]] = []

        for event in events:
            key = _event_key(event)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            normalized_rows.append(
                _normalize_event(event, scenario_id, int(subscr_id), corr_id, ts_poll_utc, include_raw)
            )

        if normalized_rows:
            append_ndjson(poll_state_dir / "rt_events.ndjson", normalized_rows)
            activity = True

        if activity:
            last_activity = now
        elif last_activity is None and planned_end:
            last_activity = planned_end

        poll_count += 1
        done = False
        if planned_end:
            if last_activity is None:
                last_activity = planned_end
            idle_deadline = last_activity + timedelta(minutes=idle_grace_min)
            if now > planned_end and now > idle_deadline:
                done = True
        update_state(
            state_path,
            seen_keys,
            poll_count=poll_count,
            last_activity_utc=last_activity.isoformat() if last_activity else None,
            planned_end_utc=planned_end_utc,
            done=done,
            extra_fields={
                "dep_time": dep_time.astimezone(timezone.utc).isoformat() if dep_time else None,
                "arr_time": arr_time.astimezone(timezone.utc).isoformat() if arr_time else None,
                "window_start": window_start.astimezone(timezone.utc).isoformat() if window_start else None,
                "window_end": window_end.astimezone(timezone.utc).isoformat() if window_end else None,
                "in_window": in_window,
            },
        )
        if done:
            continue

        # --- Reschedule this subscription ---
        if dep_time is None:
            interval = float(poll_sec)
        else:
            if now < window_start:
                interval = float(min(poll_sec * 2, 900))
            elif in_window:
                interval = float(poll_sec)
            else:
                interval = float(min(poll_sec * 2, 900))

        next_due = due_mono + interval

        # If we fell behind (slow network), don't schedule in the past.
        now_mono = time.monotonic()
        if next_due < now_mono:
            next_due = now_mono

        heapq.heappush(heap, (next_due, idx, subscr_dir))

        if _deadline_reached():
            break
