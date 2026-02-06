from __future__ import annotations

import hashlib
import heapq
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
from dateutil import parser as dt_parser
from .hafas_gate import HafasGate
from .io import append_ndjson, ensure_dir, ensure_state, read_json, update_state, write_json_redacted

try:
    from zoneinfo import ZoneInfo

    def _load_local_tz():
        for name in ("Europe/Paris", "Europe/Brussels", "Europe/Luxembourg"):
            try:
                return ZoneInfo(name)
            except Exception:
                pass
        # dernier recours (mauvais en été, mais mieux que planter)
        return timezone(timedelta(hours=1))

    LOCAL_TZ = _load_local_tz()

except Exception:
    # fallback si zoneinfo vraiment indispo
    from dateutil.tz import gettz
    LOCAL_TZ = gettz("Europe/Paris") or timezone(timedelta(hours=1))

LOCAL_TZ_NAME = getattr(LOCAL_TZ, "key", "Europe/Paris")


def _iso_utc(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _iso_local(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.astimezone(LOCAL_TZ).isoformat()


def _iso_time_part(iso_value: Optional[str]) -> str:
    if not iso_value:
        return "--:--:--"
    time_part = iso_value.split("T")[-1]
    for sep in ("+", "-", "Z"):
        if sep in time_part:
            time_part = time_part.split(sep)[0]
    return time_part


def _format_console_line(record: Dict[str, Any]) -> str:
    ts_utc = _iso_time_part(record.get("tsUtc"))
    ts_local = _iso_time_part(record.get("tsLocal"))
    return (
        f"[UTC {ts_utc} | Local {ts_local}] "
        f"subscr={record.get('subscrId')} scen={record.get('scenarioId')} "
        f"poll={record.get('pollCount')} in_window={record.get('in_window')} "
        f"new_events={record.get('new_events')} interval={record.get('interval_sec')}s "
        f"done={record.get('done')}"
    )


def _log_poll_event(subscr_dir: Path, record: Dict[str, Any], verbose: bool, save_logs: bool) -> None:
    if save_logs:
        try:
            append_ndjson(subscr_dir / "poll" / "poll_log.ndjson", [record])
        except Exception:
            pass
    if verbose:
        print(_format_console_line(record))


def _log_major(message: str) -> None:
    print(message)


def _short_error_message(exc: Exception, limit: int = 200) -> str:
    msg = str(exc) or exc.__class__.__name__
    return msg[:limit]


def _parse_hafas_wallclock_to_utc(value: Optional[str]) -> Optional[datetime]:
    """
    HAFAS dep/arr timestamps: treat as local wall-clock time even if suffixed with 'Z'.
    Return UTC datetime for comparisons/storage.
    """
    if not value:
        return None
    try:
        s = value.strip()
        dt = dt_parser.isoparse(s)

        # If it has no tz -> local
        if dt.tzinfo is None:
            local = dt.replace(tzinfo=LOCAL_TZ)

        # If it says Z/+00:00 but is actually local -> IGNORE TZ and reattach local
        elif s.endswith("Z") or s.endswith("+00:00"):
            local = dt.replace(tzinfo=None).replace(tzinfo=LOCAL_TZ)

        # Otherwise trust provided offset
        else:
            local = dt.astimezone(LOCAL_TZ)

        return local.astimezone(timezone.utc)
    except Exception:
        return None
        
def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = dt_parser.isoparse(value)
        # If HAFAS omits TZ, assume Europe/Luxembourg (not UTC)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=DEFAULT_TZ)
        # Normalize everything to UTC for comparisons/storage
        return parsed.astimezone(timezone.utc)
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
    return _parse_hafas_wallclock_to_utc(ci0.get("departureTime")) if ci0 else None

def _extract_arrival_time(details: Dict[str, Any]) -> Optional[datetime]:
    ci0 = _get_connection_info0(details)
    return _parse_hafas_wallclock_to_utc(ci0.get("arrivalTime")) if ci0 else None

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
    verbose: bool = False,
) -> None:
    subs_dir = run_dir / "subs"
    if not subs_dir.exists():
        # Rien à poll
        _log_major(f"No subs directory found under {run_dir}")
        return

    subscr_dirs = sorted([p for p in subs_dir.iterdir() if p.is_dir()])
    if not subscr_dirs:
        _log_major(f"No subscriptions found under {subs_dir}")
        return

    start_time = datetime.now(timezone.utc)
    deadline = start_time + timedelta(minutes=max_runtime_min) if max_runtime_min else None
    _log_major(
        f"Polling {len(subscr_dirs)} subscriptions from {run_dir} "
        f"(pollSec={poll_sec}, preWindowMin={pre_window_min}, postWindowMin={post_window_min}, "
        f"idleGraceMin={idle_grace_min}, maxRuntimeMin={max_runtime_min}, "
        f"localTz={LOCAL_TZ_NAME})"
    )

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
            now = datetime.now(timezone.utc)
            _log_major(f"WARN: missing manifest for {subscr_dir} (backoff)")
            _log_poll_event(
                subscr_dir,
                {
                    "tsUtc": _iso_utc(now),
                    "tsLocal": _iso_local(now),
                    "subscrId": None,
                    "scenarioId": None,
                    "pollCount": None,
                    "in_window": None,
                    "window_start_utc": None,
                    "window_start_local": None,
                    "window_end_utc": None,
                    "window_end_local": None,
                    "dep_time_utc": None,
                    "dep_time_local": None,
                    "arr_time_utc": None,
                    "arr_time_local": None,
                    "planned_end_utc": None,
                    "planned_end_local": None,
                    "last_activity_utc": None,
                    "last_activity_local": None,
                    "idle_deadline_utc": None,
                    "idle_deadline_local": None,
                    "interval_sec": min(poll_sec * 2, 900),
                    "next_due_monotonic": None,
                    "next_due_utc": None,
                    "events_total": 0,
                    "new_events": 0,
                    "dedup_skipped": 0,
                    "done": False,
                    "done_reason": "missing_manifest",
                    "error_type": "manifest_read_error",
                    "error_msg": "missing manifest.json",
                    "where": "read_manifest",
                },
                verbose,
                save_logs,
            )
            _reschedule(idx, subscr_dir, min(poll_sec * 2, 900))
            continue

        subscr_id = manifest.get("subscrId")
        scenario_id = manifest.get("scenarioId", "unknown")

        if not subscr_id:
            # Sub sans subscrId -> on réessaie plus tard
            now = datetime.now(timezone.utc)
            _log_major(f"WARN: missing subscrId for {subscr_dir} (backoff)")
            _log_poll_event(
                subscr_dir,
                {
                    "tsUtc": _iso_utc(now),
                    "tsLocal": _iso_local(now),
                    "subscrId": None,
                    "scenarioId": scenario_id,
                    "pollCount": None,
                    "in_window": None,
                    "window_start_utc": None,
                    "window_start_local": None,
                    "window_end_utc": None,
                    "window_end_local": None,
                    "dep_time_utc": None,
                    "dep_time_local": None,
                    "arr_time_utc": None,
                    "arr_time_local": None,
                    "planned_end_utc": None,
                    "planned_end_local": None,
                    "last_activity_utc": None,
                    "last_activity_local": None,
                    "idle_deadline_utc": None,
                    "idle_deadline_local": None,
                    "interval_sec": min(poll_sec * 2, 900),
                    "next_due_monotonic": None,
                    "next_due_utc": None,
                    "events_total": 0,
                    "new_events": 0,
                    "dedup_skipped": 0,
                    "done": False,
                    "done_reason": "missing_subscr_id",
                    "error_type": "missing_subscr_id",
                    "error_msg": "manifest without subscrId",
                    "where": "read_manifest",
                },
                verbose,
                save_logs,
            )
            _reschedule(idx, subscr_dir, min(poll_sec * 2, 900))
            continue

        poll_state_dir = subscr_dir / "poll"
        ensure_dir(poll_state_dir)

        state_path = poll_state_dir / "state.json"
        try:
            state = ensure_state(state_path)
        except Exception as exc:
            now = datetime.now(timezone.utc)
            _log_major(f"ERROR: failed to read state for {subscr_dir} (backoff)")
            _log_poll_event(
                subscr_dir,
                {
                    "tsUtc": _iso_utc(now),
                    "tsLocal": _iso_local(now),
                    "subscrId": subscr_id,
                    "scenarioId": scenario_id,
                    "pollCount": None,
                    "in_window": None,
                    "window_start_utc": None,
                    "window_start_local": None,
                    "window_end_utc": None,
                    "window_end_local": None,
                    "dep_time_utc": None,
                    "dep_time_local": None,
                    "arr_time_utc": None,
                    "arr_time_local": None,
                    "planned_end_utc": None,
                    "planned_end_local": None,
                    "last_activity_utc": None,
                    "last_activity_local": None,
                    "idle_deadline_utc": None,
                    "idle_deadline_local": None,
                    "interval_sec": min(poll_sec * 2, 900),
                    "next_due_monotonic": None,
                    "next_due_utc": None,
                    "events_total": 0,
                    "new_events": 0,
                    "dedup_skipped": 0,
                    "done": False,
                    "done_reason": "state_read_error",
                    "error_type": exc.__class__.__name__,
                    "error_msg": _short_error_message(exc),
                    "where": "ensure_state",
                },
                verbose,
                save_logs,
            )
            _reschedule(idx, subscr_dir, min(poll_sec * 2, 900))
            continue
        if state.get("done"):
            continue
        seen_keys = set(state.get("seenKeys", []))
        poll_count = int(state.get("pollCount") or 0)
        last_activity = _parse_dt(state.get("lastActivityUtc"))
        planned_end_state = _parse_dt(state.get("plannedEndUtc"))

        # --- Call HAFAS safely ---
        try:
            details, corr_id, request_payload = hafas.subscr_details(subscr_id)
        except Exception as exc:
            # Réseau/500/timeout: on backoff sans tout arrêter
            now = datetime.now(timezone.utc)
            _log_major(f"ERROR: poll failed for subscr {subscr_id} (backoff)")
            _log_poll_event(
                subscr_dir,
                {
                    "tsUtc": _iso_utc(now),
                    "tsLocal": _iso_local(now),
                    "subscrId": subscr_id,
                    "scenarioId": scenario_id,
                    "pollCount": poll_count,
                    "in_window": None,
                    "window_start_utc": None,
                    "window_start_local": None,
                    "window_end_utc": None,
                    "window_end_local": None,
                    "dep_time_utc": None,
                    "dep_time_local": None,
                    "arr_time_utc": None,
                    "arr_time_local": None,
                    "planned_end_utc": _iso_utc(planned_end_state),
                    "planned_end_local": _iso_local(planned_end_state),
                    "last_activity_utc": _iso_utc(last_activity),
                    "last_activity_local": _iso_local(last_activity),
                    "idle_deadline_utc": None,
                    "idle_deadline_local": None,
                    "interval_sec": min(poll_sec * 2, 900),
                    "next_due_monotonic": None,
                    "next_due_utc": None,
                    "events_total": 0,
                    "new_events": 0,
                    "dedup_skipped": 0,
                    "done": False,
                    "done_reason": "network_error_backoff",
                    "error_type": exc.__class__.__name__,
                    "error_msg": _short_error_message(exc),
                    "where": "subscr_details",
                },
                verbose,
                save_logs,
            )
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
        planned_end_utc = _iso_utc(planned_end)

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
        done_reason = None
        idle_deadline = None
        if planned_end:
            if last_activity is None:
                last_activity = planned_end
            idle_deadline = last_activity + timedelta(minutes=idle_grace_min)
            if now > planned_end and now > idle_deadline:
                done = True
                done_reason = "idle_grace_elapsed"
        update_state(
            state_path,
            seen_keys,
            poll_count=poll_count,
            last_activity_utc=last_activity.isoformat() if last_activity else None,
            planned_end_utc=planned_end_utc,
            done=done,
            extra_fields={
                "dep_time": _iso_utc(dep_time),
                "arr_time": _iso_utc(arr_time),
                "window_start": _iso_utc(window_start),
                "window_end": _iso_utc(window_end),
                "in_window": in_window,
            },
        )
        interval = None
        next_due = None
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
        now_mono = time.monotonic()
        if next_due < now_mono:
            next_due = now_mono
        next_due_utc = now + timedelta(seconds=interval)

        _log_poll_event(
            subscr_dir,
            {
                "tsUtc": _iso_utc(now),
                "tsLocal": _iso_local(now),
                "subscrId": subscr_id,
                "scenarioId": scenario_id,
                "pollCount": poll_count,
                "in_window": in_window,
                "window_start_utc": _iso_utc(window_start),
                "window_start_local": _iso_local(window_start),
                "window_end_utc": _iso_utc(window_end),
                "window_end_local": _iso_local(window_end),
                "dep_time_utc": _iso_utc(dep_time),
                "dep_time_local": _iso_local(dep_time),
                "arr_time_utc": _iso_utc(arr_time),
                "arr_time_local": _iso_local(arr_time),
                "planned_end_utc": _iso_utc(planned_end),
                "planned_end_local": _iso_local(planned_end),
                "last_activity_utc": _iso_utc(last_activity),
                "last_activity_local": _iso_local(last_activity),
                "idle_deadline_utc": _iso_utc(idle_deadline),
                "idle_deadline_local": _iso_local(idle_deadline),
                "interval_sec": interval,
                "next_due_monotonic": next_due,
                "next_due_utc": _iso_utc(next_due_utc),
                "events_total": len(events),
                "new_events": len(normalized_rows),
                "dedup_skipped": len(events) - len(normalized_rows),
                "done": done,
                "done_reason": done_reason or ("completed" if done else "running"),
                "error_type": None,
                "error_msg": None,
                "where": None,
            },
            verbose,
            save_logs,
        )
        if done:
            _log_major(
                f"Done: subscr={subscr_id} scen={scenario_id} "
                f"reason={done_reason or 'completed'}"
            )
            continue

        # --- Reschedule this subscription ---
        heapq.heappush(heap, (next_due, idx, subscr_dir))

        if _deadline_reached():
            break

    if _deadline_reached():
        _log_major("Polling stopped: deadline_reached")
    elif not heap:
        _log_major("Polling stopped: no_pending_subscriptions")
