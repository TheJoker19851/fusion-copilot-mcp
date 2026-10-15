import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from fusion_copilot.bridge_client import FusionBridgeClient


class _RecordingHandler(BaseHTTPRequestHandler):
    received_path = ""
    received_authorization = ""
    received_json: dict = {}

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        content_length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(content_length)
        type(self).received_path = self.path
        type(self).received_authorization = self.headers.get("Authorization", "")
        type(self).received_json = json.loads(body)
        response = json.dumps({"ok": True, "safety_mode": "off"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, format: str, *args: object) -> None:
        return


class BridgeClientTests(unittest.TestCase):
    def test_call_uses_local_token_and_forwards_structured_command(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _RecordingHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temporary_directory:
                token_path = Path(temporary_directory) / "bridge-token"
                token_path.write_text("local-secret\n", encoding="utf-8")
                client = FusionBridgeClient(
                    base_url=f"http://127.0.0.1:{server.server_port}",
                    token_path=token_path,
                )

                response = client.call("get_status")

            self.assertTrue(response["ok"])
            self.assertEqual(_RecordingHandler.received_path, "/command")
            self.assertEqual(
                _RecordingHandler.received_authorization,
                "Bearer local-secret",
            )
            self.assertEqual(
                _RecordingHandler.received_json,
                {"action": "get_status", "payload": {}},
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
