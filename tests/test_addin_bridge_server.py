import tempfile
import threading
import unittest
from pathlib import Path

from fusion_copilot.addin_bridge_server import CommandBroker, LocalBridgeServer
from fusion_copilot.bridge_client import FusionBridgeClient


class AddinBridgeServerTests(unittest.TestCase):
    def test_authenticated_http_request_runs_through_the_command_broker(self) -> None:
        processed: list[dict] = []
        broker: CommandBroker

        def trigger_fusion_event() -> None:
            def process_on_simulated_fusion_thread() -> None:
                pending = broker.take_next()
                processed.append(pending.command)
                broker.complete(
                    pending.command_id,
                    {
                        "ok": True,
                        "safety_mode": "off",
                        "action": pending.command["action"],
                    },
                )

            threading.Thread(
                target=process_on_simulated_fusion_thread,
                daemon=True,
            ).start()

        broker = CommandBroker(trigger_fusion_event, timeout_seconds=2)
        server = LocalBridgeServer(broker, token="local-secret", port=0)
        server.start()
        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                token_path = Path(temporary_directory) / "bridge-token"
                token_path.write_text("local-secret", encoding="utf-8")
                client = FusionBridgeClient(
                    base_url=f"http://127.0.0.1:{server.port}",
                    token_path=token_path,
                    timeout_seconds=2,
                )

                response = client.call("get_status")

            self.assertTrue(response["ok"])
            self.assertEqual(response["action"], "get_status")
            self.assertEqual(
                processed,
                [{"action": "get_status", "payload": {}}],
            )
        finally:
            server.stop()


if __name__ == "__main__":
    unittest.main()
