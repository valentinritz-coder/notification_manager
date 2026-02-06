from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional


def ms_to_dt(ms: int) -> datetime:
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)


def iso_utc(ms: int) -> str:
    return ms_to_dt(ms).isoformat().replace("+00:00", "Z")


def iso_local(ms: int, offset_ms: int | None) -> str:
    if offset_ms is None:
        return iso_utc(ms)
    tz = timezone(timedelta(milliseconds=int(offset_ms)))
    return ms_to_dt(ms).astimezone(tz).isoformat()


def pick(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return default


def parse_package_filter(packages: Optional[str]) -> Optional[set[str]]:
    if not packages:
        return None
    parsed = {pkg.strip() for pkg in packages.split(",") if pkg.strip()}
    return parsed or None


def convert_notification_log_export(
    export_json: Path,
    out_ndjson: Path,
    *,
    append: bool = False,
    include_removed: bool = False,
    packages: Optional[Iterable[str]] = None,
) -> int:
    with export_json.open("r", encoding="utf-8") as handle:
        obj = json.load(handle)

    default_offset = None
    device = obj.get("device") or {}
    if isinstance(device, dict):
        default_offset = device.get("offset")

    package_filter = set(packages) if packages is not None else None

    out_ndjson.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    written = 0

    def emit(items: Any, kind: str) -> None:
        nonlocal written
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            # Ignore Android group summary notifications (UI container, not real content)
            if item.get("isGroupSummary") is True:
                continue
            pkg = pick(item, "packageName", "package")
            if package_filter is not None and pkg not in package_filter:
                continue
            ts_ms = pick(item, "postTime", "when", "systemTime")
            if not isinstance(ts_ms, (int, float)):
                continue
            offset_ms = pick(item, "offset", default=default_offset)
            title = pick(item, "titleBig", "title", default="")
            text = pick(item, "textBig", "text", default="")
            record = {
                "tsDevice": iso_local(int(ts_ms), offset_ms),
                "tsUtc": iso_utc(int(ts_ms)),
                "package": pkg,
                "title": title,
                "text": text,
                "channel": pick(item, "category", default=None),
                "id": pick(item, "nid", "key", default=None),
                "kind": kind,
                "raw": item,
            }
            out_handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

    with out_ndjson.open(mode, encoding="utf-8") as out_handle:
        emit(obj.get("posted"), "posted")
        if include_removed:
            emit(obj.get("removed"), "removed")

    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--in", dest="inp", required=True, help="Notification Log export JSON")
    parser.add_argument("--out", dest="out", required=True, help="Output NDJSON path")
    parser.add_argument("--append", action="store_true", help="Append instead of overwrite")
    parser.add_argument(
        "--include-removed",
        action="store_true",
        help="Also include removed[] as events",
    )
    parser.add_argument(
        "--packages",
        default="",
        help="Comma-separated packageName filter (optional)",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    packages = parse_package_filter(args.packages)
    written = convert_notification_log_export(
        Path(args.inp),
        Path(args.out),
        append=args.append,
        include_removed=args.include_removed,
        packages=packages,
    )
    print(f"OK: wrote {written} NDJSON lines -> {args.out}")


if __name__ == "__main__":
    main()
