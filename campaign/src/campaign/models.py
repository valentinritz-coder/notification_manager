from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ScenarioItem:
    scenarioId: str
    beginDate: str
    endDate: str
    nPass: int
    ctxRecon: str
    hysteresis: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScenarioItem":
        return cls(
            scenarioId=data["scenarioId"],
            beginDate=data["beginDate"],
            endDate=data["endDate"],
            nPass=int(data.get("nPass", 1)),
            ctxRecon=data["ctxRecon"],
            hysteresis=dict(data.get("hysteresis") or {}),
        )


@dataclass
class Scenario:
    campaignName: str
    pollSec: int = 120
    preWindowMin: int = 10
    postWindowMin: int = 30
    maxRuntimeMin: int = 0
    items: List[ScenarioItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Scenario":
        return cls(
            campaignName=data["campaignName"],
            pollSec=int(data.get("pollSec", 120)),
            preWindowMin=int(data.get("preWindowMin", 10)),
            postWindowMin=int(data.get("postWindowMin", 30)),
            maxRuntimeMin=int(data.get("maxRuntimeMin", 0) or 0),
            items=[ScenarioItem.from_dict(item) for item in data.get("items", [])],
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "campaignName": self.campaignName,
            "pollSec": self.pollSec,
            "preWindowMin": self.preWindowMin,
            "postWindowMin": self.postWindowMin,
            "maxRuntimeMin": self.maxRuntimeMin,
            "items": [
                {
                    "scenarioId": item.scenarioId,
                    "beginDate": item.beginDate,
                    "endDate": item.endDate,
                    "nPass": item.nPass,
                    "ctxRecon": item.ctxRecon,
                    "hysteresis": item.hysteresis,
                }
                for item in self.items
            ],
        }

