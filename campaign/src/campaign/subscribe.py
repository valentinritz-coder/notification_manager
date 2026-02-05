from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .hafas_gate import HafasGate
from .io import ensure_dir, timestamped_run_dir, write_json, write_json_redacted
from .models import Scenario


def _secrets_map(aid: str, user_id: str, channel_id: str) -> Dict[str, str]:
    return {aid: "<AID>", user_id: "<USER_ID>", channel_id: "<CHANNEL_ID>"}


def run_subscribe(
    scenario_path: Path,
    out_root: Path,
    hafas: HafasGate,
    save_logs: bool = True,
) -> Path:
    scenario_data = json.loads(scenario_path.read_text(encoding="utf-8"))
    scenario = Scenario.from_dict(scenario_data)
    run_dir = timestamped_run_dir(out_root, scenario.campaignName)
    write_json(run_dir / "scenario.json", scenario.to_dict())

    subs_dir = run_dir / "subs"
    ensure_dir(subs_dir)

    for index, item in enumerate(scenario.items, start=1):
        response, corr_id, request_payload = hafas.subscr_create_con(item.__dict__)
        subscr_id = _extract_subscr_id(response)
        subscr_dir = subs_dir / f"subscr_{subscr_id or f'unknown_{index}'}"
        ensure_dir(subscr_dir / "raw")
        manifest = {
            "scenarioId": item.scenarioId,
            "ctxRecon": item.ctxRecon,
            "beginDate": item.beginDate,
            "endDate": item.endDate,
            "nPass": item.nPass,
            "hysteresisRequested": item.hysteresis,
            "hysteresisStored": _extract_hysteresis(response),
            "subscrId": subscr_id,
        }
        write_json(subscr_dir / "manifest.json", manifest)
        if save_logs:
            secrets = _secrets_map(hafas.config.aid, hafas.config.user_id, hafas.config.channel_id)
            write_json_redacted(subscr_dir / "raw/01_subscrcreate_req.json", request_payload, secrets)
            write_json_redacted(subscr_dir / "raw/01_subscrcreate_resp.json", response, secrets)
            (subscr_dir / "raw/01_subscrcreate_corrid.txt").write_text(corr_id, encoding="utf-8")

    ensure_dir(run_dir / "device")
    return run_dir


def _extract_subscr_id(response: Dict[str, Any]) -> int | None:
    try:
        return response["svcResL"][0]["res"]["subscrId"]
    except (KeyError, IndexError, TypeError):
        return None


def _extract_hysteresis(response: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return response["svcResL"][0]["res"]["hysteresis"]
    except (KeyError, IndexError, TypeError):
        return {}

