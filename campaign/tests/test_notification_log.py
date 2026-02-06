import json
import tempfile
import unittest
from pathlib import Path

from campaign.notification_log import convert_notification_log_export


class NotificationLogExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.base_path = Path(self.temp_dir.name)

    def _write_export(self) -> Path:
        export_path = self.base_path / "export.json"
        payload = {
            "device": {"offset": 3600000, "timezone": "Europe/Luxembourg"},
            "posted": [
                {
                    "packageName": "de.hafas.android.cfl",
                    "postTime": 1738741200000,
                    "title": "Test Title",
                    "text": "Test Text",
                    "category": "service",
                    "nid": 101,
                }
            ],
            "removed": [
                {
                    "packageName": "de.hafas.android.cfl",
                    "when": 1738744800000,
                    "titleBig": "Removed Title",
                    "textBig": "Removed Text",
                    "key": "user0|de.hafas.android.cfl|tag|101",
                }
            ],
        }
        export_path.write_text(json.dumps(payload), encoding="utf-8")
        return export_path

    def test_convert_without_removed(self) -> None:
        export_path = self._write_export()
        out_path = self.base_path / "out.ndjson"
        written = convert_notification_log_export(export_path, out_path, include_removed=False)
        self.assertEqual(written, 1)
        lines = out_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        record = json.loads(lines[0])
        self.assertEqual(record["kind"], "posted")
        self.assertIn("tsDevice", record)
        self.assertIn("tsUtc", record)

    def test_convert_with_removed(self) -> None:
        export_path = self._write_export()
        out_path = self.base_path / "out.ndjson"
        written = convert_notification_log_export(export_path, out_path, include_removed=True)
        self.assertEqual(written, 2)
        lines = out_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        kinds = {json.loads(line)["kind"] for line in lines}
        self.assertEqual(kinds, {"posted", "removed"})


if __name__ == "__main__":
    unittest.main()
