from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
    start_time = datetime.now(timezone.utc)
    deadline = start_time + timedelta(minutes=max_runtime_min) if max_runtime_min else None

    while True:
        for subscr_dir in subscr_dirs:
            manifest = read_json(subscr_dir / "manifest.json")
            subscr_id = manifest.get("subscrId")
            scenario_id = manifest.get("scenarioId", "unknown")
            state_path = subscr_dir / "poll/state.json"
            state = ensure_state(state_path)
            seen_keys = set(state.get("seenKeys", []))
            poll_count = int(state.get("pollCount") or 2)

            details, corr_id, request_payload = hafas.subscr_details(subscr_id)
            if save_logs:
                secrets = {
                    hafas.config.aid: "<AID>",
                    hafas.config.user_id: "<USER_ID>",
                    hafas.config.channel_id: "<CHANNEL_ID>",
                }
                ensure_dir(subscr_dir / "raw")
                write_json_redacted(subscr_dir / f"raw/{poll_count:02d}_subscrdetails_resp.json", details, secrets)
                write_json_redacted(subscr_dir / f"raw/{poll_count:02d}_subscrdetails_req.json", request_payload, secrets)
                (subscr_dir / f"raw/{poll_count:02d}_subscrdetails_corrid.txt").write_text(corr_id, encoding="utf-8")

            dep_time = _extract_departure_time(details)
            now = datetime.now(timezone.utc)
            if dep_time:
                window_start = dep_time - timedelta(minutes=pre_window_min)
                window_end = dep_time + timedelta(minutes=post_window_min)
                in_window = window_start <= now <= window_end
            else:
                in_window = False

            if in_window or dep_time is None:
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
                    append_ndjson(subscr_dir / "poll/rt_events.ndjson", normalized_rows)

            poll_count += 1
            update_state(state_path, seen_keys, poll_count=poll_count)

            if not in_window:
                time.sleep(min(poll_sec * 2, 900))
            else:
                time.sleep(poll_sec)

        if deadline and datetime.now(timezone.utc) >= deadline:
            break
