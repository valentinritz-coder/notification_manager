from __future__ import annotations

import csv
import json
from collections import defaultdict
from dataclasses import asdict
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, List, Optional

from .io import ensure_dir, read_ndjson, write_json
from .matching import MatchResult, match_events_to_notifications


def run_report(
    run_dir: Path,
    device_ndjson: Optional[Path],
    out_dir: Optional[Path],
    match_threshold: float = 70.0,
    write_markdown: bool = True,
) -> Path:
    report_dir = out_dir or (run_dir / "report")
    ensure_dir(report_dir)

    events = _load_events(run_dir)
    notifications = _load_notifications(run_dir, device_ndjson)
    matches, unmatched_events, unmatched_notifications = match_events_to_notifications(
        events, notifications, threshold=match_threshold
    )

    _write_matches(report_dir / "matches.csv", matches)
    _write_unmatched(report_dir / "unmatched_events.csv", unmatched_events)
    _write_unmatched(report_dir / "unmatched_notifications.csv", unmatched_notifications)

    summary = _compute_metrics(events, matches)
    write_json(report_dir / "report_summary.json", summary)
    _write_metrics_csv(report_dir, summary)

    if write_markdown:
        report_md = _render_markdown(summary)
        (report_dir / "report.md").write_text(report_md, encoding="utf-8")

    return report_dir


def _load_events(run_dir: Path) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for subscr_dir in (run_dir / "subs").iterdir():
        poll_path = subscr_dir / "poll/rt_events.ndjson"
        events.extend(read_ndjson(poll_path))
    return events


def _load_notifications(run_dir: Path, device_ndjson: Optional[Path]) -> List[Dict[str, Any]]:
    if device_ndjson and device_ndjson.exists():
        return read_ndjson(device_ndjson)
    return read_ndjson(run_dir / "device/notifications.ndjson")


def _write_matches(path: Path, matches: List[MatchResult]) -> None:
    fieldnames = [
        "subscrId",
        "scenarioId",
        "changeType",
        "eventReceivedUtc",
        "notifTsDevice",
        "latencySec",
        "score",
        "eventTitle",
        "notifTitle",
        "eventMsg",
        "notifText",
    ]
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for match in matches:
            event = match.event
            notif = match.notification
            writer.writerow(
                {
                    "subscrId": event.get("subscrId"),
                    "scenarioId": event.get("scenarioId"),
                    "changeType": event.get("changeType"),
                    "eventReceivedUtc": event.get("received") or event.get("tsPollUtc"),
                    "notifTsDevice": notif.get("tsDevice"),
                    "latencySec": match.latency_sec,
                    "score": match.score,
                    "eventTitle": event.get("title"),
                    "notifTitle": notif.get("title"),
                    "eventMsg": event.get("msg"),
                    "notifText": notif.get("text"),
                }
            )


def _write_unmatched(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        ensure_dir(path.parent)
        path.write_text("", encoding="utf-8")
        return
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _compute_metrics(events: List[Dict[str, Any]], matches: List[MatchResult]) -> Dict[str, Any]:
    total_events = len(events)
    matched_events = len(matches)
    delivery_rate = matched_events / total_events if total_events else 0.0
    latencies = [match.latency_sec for match in matches]

    summary = {
        "total_events": total_events,
        "matched_events": matched_events,
        "delivery_rate": delivery_rate,
        "latency": _latency_stats(latencies),
        "by_changeType": _group_metrics(events, matches, "changeType"),
        "by_subscr": _group_metrics(events, matches, "subscrId"),
        "by_scenario": _group_metrics(events, matches, "scenarioId"),
    }
    return summary


def _latency_stats(latencies: List[float]) -> Dict[str, float]:
    if not latencies:
        return {"mean": 0.0, "median": 0.0, "p90": 0.0, "p95": 0.0}
    latencies_sorted = sorted(latencies)
    return {
        "mean": mean(latencies_sorted),
        "median": median(latencies_sorted),
        "p90": _percentile(latencies_sorted, 0.9),
        "p95": _percentile(latencies_sorted, 0.95),
    }


def _percentile(values: List[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = int(round((len(values) - 1) * percentile))
    return values[index]


def _group_metrics(
    events: List[Dict[str, Any]],
    matches: List[MatchResult],
    key: str,
) -> Dict[str, Any]:
    totals = defaultdict(int)
    matched = defaultdict(int)
    for event in events:
        totals[str(event.get(key))] += 1
    for match in matches:
        matched[str(match.event.get(key))] += 1

    metrics = {}
    for group, total in totals.items():
        metrics[group] = {
            "total_events": total,
            "matched_events": matched.get(group, 0),
            "delivery_rate": matched.get(group, 0) / total if total else 0.0,
        }
    return metrics


def _write_metrics_csv(report_dir: Path, summary: Dict[str, Any]) -> None:
    _write_metrics_group(report_dir / "metrics_by_changeType.csv", summary["by_changeType"])
    _write_metrics_group(report_dir / "metrics_by_subscr.csv", summary["by_subscr"])
    _write_metrics_group(report_dir / "metrics_by_scenario.csv", summary["by_scenario"])


def _write_metrics_group(path: Path, group: Dict[str, Any]) -> None:
    fieldnames = ["group", "total_events", "matched_events", "delivery_rate"]
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for name, data in group.items():
            writer.writerow(
                {
                    "group": name,
                    "total_events": data["total_events"],
                    "matched_events": data["matched_events"],
                    "delivery_rate": data["delivery_rate"],
                }
            )


def _render_markdown(summary: Dict[str, Any]) -> str:
    lines = [
        "# Campaign Report",
        "",
        f"- Total events: {summary['total_events']}",
        f"- Matched events: {summary['matched_events']}",
        f"- Delivery rate: {summary['delivery_rate']:.2%}",
        "",
        "## Latency",
        f"- Mean: {summary['latency']['mean']:.1f}s",
        f"- Median: {summary['latency']['median']:.1f}s",
        f"- P90: {summary['latency']['p90']:.1f}s",
        f"- P95: {summary['latency']['p95']:.1f}s",
    ]
    return "\n".join(lines) + "\n"
