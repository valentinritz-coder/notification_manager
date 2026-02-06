from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests


@dataclass
class HafasConfig:
    base_url: str
    aid: str
    user_id: str
    client_id: str
    channel_id: str
    lang: str = "eng"
    ver: str = "1.72"
    hci_client_type: str = "AND"
    hci_client_version: int = 1000680
    hci_version: str = "1.72"
    timeout_sec: int = 30


class HafasGate:
    def __init__(self, config: HafasConfig) -> None:
        self.config = config
        self.session = requests.Session()

    def _post(self, method: str, req: Dict[str, Any]) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
        corr_id = str(uuid.uuid4())
        params = {
            "aid": self.config.aid,
            "hciClientType": self.config.hci_client_type,
            "hciClientVersion": self.config.hci_client_version,
            "hciVersion": self.config.hci_version,
            "hciMethod": method,
        }
        payload = {
            "auth": {"type": "AID", "aid": self.config.aid},
            "client": {
                "type": self.config.hci_client_type,
                "id": self.config.client_id,
                "name": "CFL mobile",
                "os": "Android 12",
                "ua": "Dalvik/2.1.0 (Linux; U; Android 12; Pixel 3 Build/SP1A.210812.016.C2)",
                "v": self.config.hci_client_version,
            },
            "lang": self.config.lang,
            "ver": self.config.ver,
            "svcReqL": [
                {
                    "meth": method,
                    "req": req,
                    "cfg": {},
                    "id": "0",
                }
            ],
        }
        headers = {"X-Correlation-ID": corr_id}
        response = self.session.post(
            self.config.base_url,
            params=params,
            json=payload,
            headers=headers,
            timeout=self.config.timeout_sec,
        )
        response.raise_for_status()
        return response.json(), corr_id, payload

    def subscr_create_con(self, item: Dict[str, Any]) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
        begin = item["beginDate"]
        end = item.get("endDate", begin)
    
        hysteresis_in = item.get("hysteresis") or {}
        hysteresis = {
            "minDeviationInterval": int(hysteresis_in.get("minDeviationInterval", 5)),
            "notificationStart": int(hysteresis_in.get("notificationStart", 60)),
        }
    
        req = {
            "userId": self.config.user_id,
            "channels": [{"channelId": self.config.channel_id}],
            "conSubscr": {
                "serviceDays": {"beginDate": begin, "endDate": end},
                "ctxRecon": item["ctxRecon"],
                "hysteresis": hysteresis,
            },
            "nPass": int(item.get("nPass", 1)),
        }
    return self._post("SubscrCreate", req)

    def subscr_details(self, subscr_id: int) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
        req = {
            "subscrId": subscr_id,
            "userId": self.config.user_id,
            "channelId": self.config.channel_id,
        }
        return self._post("SubscrDetails", req)
    
    def subscr_search(self) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
        req = {"userId": self.config.user_id}
        return self._post("SubscrSearch", req)
    
    def subscr_delete(self, subscr_id: int) -> Tuple[Dict[str, Any], str, Dict[str, Any]]:
        req = {"userId": self.config.user_id, "subscrId": subscr_id}
        return self._post("SubscrDelete", req)

