import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from campaign.io import update_state, write_json
from campaign.poll import _compute_planned_end


class PollingStopTests(unittest.TestCase):
    def test_compute_planned_end_prefers_arrival(self) -> None:
        details = {
            "svcResL": [
                {
                    "res": {
                        "connectionInfo": [
                            {
                                "departureTime": "2025-01-01T10:00:00Z",
                                "arrivalTime": "2025-01-01T11:00:00Z",
                            }
                        ]
                    }
                }
            ]
        }
        planned_end = _compute_planned_end(details, post_window_min=30)
        self.assertIsNotNone(planned_end)
        self.assertEqual(
            planned_end,
            datetime(2025, 1, 1, 11, 30, tzinfo=timezone.utc),
        )

    def test_compute_planned_end_falls_back_to_departure(self) -> None:
        details = {
            "svcResL": [
                {
                    "res": {
                        "connectionInfo": [
                            {
                                "departureTime": "2025-01-01T10:00:00Z",
                            }
                        ]
                    }
                }
            ]
        }
        planned_end = _compute_planned_end(details, post_window_min=15)
        self.assertIsNotNone(planned_end)
        self.assertEqual(
            planned_end,
            datetime(2025, 1, 1, 10, 15, tzinfo=timezone.utc),
        )

    def test_update_state_preserves_existing_fields(self) -> None:
        with TemporaryDirectory() as tmpdir:
            state_path = Path(tmpdir) / "state.json"
            write_json(
                state_path,
                {
                    "seenKeys": ["a"],
                    "lastPollUtc": "2025-01-01T00:00:00Z",
                    "pollCount": 1,
                    "lastActivityUtc": "2025-01-01T00:10:00Z",
                    "plannedEndUtc": "2025-01-01T00:20:00Z",
                    "done": False,
                    "customField": "keep",
                },
            )
            update_state(state_path, seen_keys=["b"], poll_count=2)
            state = state_path.read_text(encoding="utf-8")
            self.assertIn('"customField": "keep"', state)


if __name__ == "__main__":
    unittest.main()
