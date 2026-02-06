import argparse
import unittest

from campaign.cli import _add_hafas_args
from campaign.hafas_gate import HafasConfig, HafasGate


class HafasCliArgsTests(unittest.TestCase):
    def test_default_client_id(self) -> None:
        parser = argparse.ArgumentParser()
        _add_hafas_args(parser)
        args = parser.parse_args(
            [
                "--base-url",
                "https://example.test/gate",
                "--aid",
                "AID",
                "--user-id",
                "USER",
                "--channel-id",
                "ANDROID-123",
            ]
        )
        self.assertEqual(args.client_id, "HAFAS")

    def test_channel_id_does_not_set_envelope_client_id(self) -> None:
        config = HafasConfig(
            base_url="https://example.test/gate",
            aid="AID",
            user_id="USER",
            client_id="HAFAS",
            channel_id="ANDROID-123",
            lang="eng",
            ver="1.72",
            hci_client_type="AND",
            hci_client_version=1000680,
            hci_version="1.72",
            timeout_sec=30,
        )
        hafas = HafasGate(config)

        class DummyResponse:
            def raise_for_status(self) -> None:
                return None

            def json(self) -> dict:
                return {"ok": True}

        def fake_post(*_args, **_kwargs) -> DummyResponse:
            return DummyResponse()

        hafas.session.post = fake_post
        _, _, payload = hafas.subscr_search()
        self.assertEqual(payload["client"]["id"], config.client_id)
        self.assertNotEqual(payload["client"]["id"], config.channel_id)


if __name__ == "__main__":
    unittest.main()
