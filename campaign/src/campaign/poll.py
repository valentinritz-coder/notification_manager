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


def _extract_departure_time(details: Dict[str, Any]) -> Optional[datetime]:
    try:
        dep = details["svcResL"][0]["res"]["connectionInfo"][0]["departureTime"]
        return _parse_dt(dep)
    except (KeyError, IndexError, TypeError):
        return None


def _extract_rt_events(details: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return details["svcResL"][0]["res"]["rtInfo"]["rtEventL"] or []
    except (KeyError, IndexError, TypeError):
        return []


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
    max_runtime_min: int = 0,
    include_raw: bool = False,
    save_logs: bool = True,
) -> None:
    subs_dir = run_dir / "subs"
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

    def _sleep_until(due_mono: float) -> bool:
        """Sleep until due_mono or until deadline. Returns False if deadline reached."""
        while True:
            if deadline and datetime.now(timezone.utc) >= deadline:
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

    while True:
        if deadline and datetime.now(timezone.utc) >= deadline:
            break

        due_mono, idx, subscr_dir = heapq.heappop(heap)
        if not _sleep_until(due_mono):
            break

        manifest = read_json(subscr_dir / "manifest.json")
        subscr_id = manifest.get("subscrId")
        scenario_id = manifest.get("scenarioId", "unknown")

        poll_state_dir = subscr_dir / "poll"
        ensure_dir(poll_state_dir)

        state_path = poll_state_dir / "state.json"
        state = ensure_state(state_path)
        seen_keys = set(state.get("seenKeys", []))
        poll_count = int(state.get("pollCount") or 0)

        # --- Call HAFAS ---
        details, corr_id, request_payload = hafas.subscr_details(subscr_id)

        if save_logs:
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

        now = datetime.now(timezone.utc)
        dep_time = _extract_departure_time(details)

        if dep_time:
            window_start = dep_time - timedelta(minutes=pre_window_min)
            window_end = dep_time + timedelta(minutes=post_window_min)
            in_window = window_start <= now <= window_end
        else:
            in_window = False

        # If dep_time is unknown, keep polling normally and still harvest events.
        process_events = in_window or dep_time is None

        if process_events:
            events = _extract_rt_events(details)
            ts_poll_utc = now.isoformat()
            normalized_rows: List[Dict[str, Any]] = []

            for event in events:
                key = _event_key(event)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                normalized_rows.append(
                    _normalize_event(event, scenario_id, subscr_id, corr_id, ts_poll_utc, include_raw)
                )

            if normalized_rows:
                append_ndjson(poll_state_dir / "rt_events.ndjson", normalized_rows)

        poll_count += 1
        update_state(state_path, seen_keys, poll_count=poll_count)

        # --- Reschedule this subscription ---
        # Keep your existing behavior: slower outside window (x2, capped at 15 min).
        if dep_time is None:
            interval = float(poll_sec)
        else:
            interval = float(poll_sec) if in_window else float(min(poll_sec * 2, 900))

        next_due = due_mono + interval

        # If we fell behind (slow network), don't schedule in the past.
        now_mono = time.monotonic()
        if next_due < now_mono:
            next_due = now_mono

        heapq.heappush(heap, (next_due, idx, subscr_dir))

        if deadline and datetime.now(timezone.utc) >= deadline:
            break
