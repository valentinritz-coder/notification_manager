from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def timestamped_run_dir(out_root: Path, campaign_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = campaign_name.replace(" ", "_")
    run_dir = out_root / f"RUN_{stamp}__{safe_name}"
    ensure_dir(run_dir)
    return run_dir


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def append_ndjson(path: Path, rows: Iterable[Dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False))
            handle.write("\n")


def read_ndjson(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _redact_value(value: Any, secrets: Dict[str, str]) -> Any:
    if isinstance(value, str):
        for secret, replacement in secrets.items():
            if secret and secret in value:
                value = value.replace(secret, replacement)
        return value
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(val, secrets) for key, val in value.items()}
    return value


def write_json_redacted(path: Path, data: Any, secrets: Dict[str, str]) -> None:
    redacted = _redact_value(data, secrets)
    write_json(path, redacted)


def redact_data(data: Any, secrets: Dict[str, str]) -> Any:
    return _redact_value(data, secrets)


def copy_file(src: Path, dest: Path) -> None:
    ensure_dir(dest.parent)
    shutil.copy2(src, dest)


def ensure_state(path: Path) -> Dict[str, Any]:
    if path.exists():
        return read_json(path)
    state = {"seenKeys": [], "lastPollUtc": None, "pollCount": 2}
    write_json(path, state)
    return state


def update_state(path: Path, seen_keys: Iterable[str], poll_count: int | None = None) -> None:
    state = {
        "seenKeys": sorted(set(seen_keys)),
        "lastPollUtc": utc_now_iso(),
        "pollCount": poll_count,
    }
    write_json(path, state)
