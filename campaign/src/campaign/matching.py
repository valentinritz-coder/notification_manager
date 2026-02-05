from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dateutil import parser as dt_parser

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover
    fuzz = None


def _parse_dt(value: str | None) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = dt_parser.isoparse(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError):
        return None


def similarity(a: str | None, b: str | None) -> float:
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return 0.0
    if fuzz:
        return float(fuzz.token_set_ratio(a, b))
    return _fallback_similarity(a, b)


def _fallback_similarity(a: str, b: str) -> float:
    import difflib

    return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


@dataclass
class MatchResult:
    event: Dict[str, Any]
    notification: Dict[str, Any]
    score: float
    latency_sec: float


def match_events_to_notifications(
    events: List[Dict[str, Any]],
    notifications: List[Dict[str, Any]],
    threshold: float = 70.0,
    window_before_min: int = 5,
    window_after_min: int = 30,
) -> Tuple[List[MatchResult], List[Dict[str, Any]], List[Dict[str, Any]]]:
    unmatched_notifications = notifications[:]
    matches: List[MatchResult] = []
    unmatched_events: List[Dict[str, Any]] = []

    for event in events:
        received = _parse_dt(event.get("received")) or _parse_dt(event.get("tsPollUtc"))
        if not received:
            unmatched_events.append(event)
            continue

        window_start = received - timedelta(minutes=window_before_min)
        window_end = received + timedelta(minutes=window_after_min)

        candidates = []
        for notif in unmatched_notifications:
            notif_ts = _parse_dt(notif.get("tsDevice"))
            if not notif_ts:
                continue
            if window_start <= notif_ts <= window_end:
                candidates.append((notif, notif_ts))

        best_score = -1.0
        best_notif = None
        best_latency = None

        for notif, notif_ts in candidates:
            score = _score_event_notification(event, notif)
            if score > best_score:
                best_score = score
                best_notif = notif
                best_latency = (notif_ts - received).total_seconds()

        if best_notif and best_score >= threshold:
            matches.append(MatchResult(event=event, notification=best_notif, score=best_score, latency_sec=best_latency or 0.0))
            unmatched_notifications.remove(best_notif)
        else:
            unmatched_events.append(event)

    return matches, unmatched_events, unmatched_notifications


def _score_event_notification(event: Dict[str, Any], notif: Dict[str, Any]) -> float:
    title_score = similarity(event.get("title"), notif.get("title"))
    msg_score = similarity(event.get("msg"), notif.get("text"))
    base = 0.6 * msg_score + 0.4 * title_score

    keywords = ["delay", "cancel", "platform", "track", "suppressed"]
    event_text = f"{event.get('title', '')} {event.get('msg', '')}".lower()
    notif_text = f"{notif.get('title', '')} {notif.get('text', '')}".lower()
    overlap = sum(1 for word in keywords if word in event_text and word in notif_text)
    return min(100.0, base + overlap * 5.0)

