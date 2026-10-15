from __future__ import annotations

import hmac
import json
import queue
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable


class CommandTimeoutError(TimeoutError):
    pass


@dataclass
class PendingCommand:
    command_id: str
    command: dict[str, Any]
    completed: threading.Event = field(default_factory=threading.Event)
    response: dict[str, Any] | None = None


class CommandBroker:
    """Moves HTTP-thread work onto Fusion's main thread through a custom event."""

    def __init__(
        self,
        trigger_fusion_event: Callable[[], None],
        timeout_seconds: float = 180.0,
    ) -> None:
        self._trigger_fusion_event = trigger_fusion_event
        self._timeout_seconds = timeout_seconds
        self._queue: queue.Queue[PendingCommand] = queue.Queue()
        self._pending: dict[str, PendingCommand] = {}
        self._lock = threading.Lock()

    def submit(self, command: dict[str, Any]) -> dict[str, Any]:
        pending = PendingCommand(command_id=str(uuid.uuid4()), command=command)
        with self._lock:
            self._pending[pending.command_id] = pending
        self._queue.put(pending)
        self._trigger_fusion_event()

        if not pending.completed.wait(self._timeout_seconds):
            with self._lock:
                self._pending.pop(pending.command_id, None)
            raise CommandTimeoutError(
                f"Fusion did not finish command {pending.command_id} in time"
            )
        if pending.response is None:
            raise RuntimeError("Fusion completed a command without a response")
        return pending.response

    def take_next(self) -> PendingCommand:
        return self._queue.get_nowait()

    def complete(self, command_id: str, response: dict[str, Any]) -> bool:
        with self._lock:
            pending = self._pending.pop(command_id, None)
        if pending is None:
            return False
        pending.response = response
        pending.completed.set()
        return True

    def fail_all(self, message: str) -> None:
        with self._lock:
            pending_commands = list(self._pending.values())
            self._pending.clear()
        for pending in pending_commands:
            pending.response = {"ok": False, "error": message}
            pending.completed.set()


def _make_handler(
    broker: CommandBroker,
    token: str,
    maximum_body_bytes: int,
) -> type[BaseHTTPRequestHandler]:
    class BridgeHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
            if self.path != "/command":
                self._send_json(404, {"ok": False, "error": "not found"})
                return
            authorization = self.headers.get("Authorization", "")
            if not hmac.compare_digest(authorization, f"Bearer {token}"):
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self._send_json(400, {"ok": False, "error": "invalid content length"})
                return
            if content_length <= 0 or content_length > maximum_body_bytes:
                self._send_json(413, {"ok": False, "error": "invalid request size"})
                return
            try:
                command = json.loads(self.rfile.read(content_length))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(400, {"ok": False, "error": "invalid JSON"})
                return
            if not isinstance(command, dict):
                self._send_json(400, {"ok": False, "error": "command must be an object"})
                return
            try:
                response = broker.submit(command)
            except CommandTimeoutError as error:
                self._send_json(504, {"ok": False, "error": str(error)})
                return
            except Exception as error:
                self._send_json(500, {"ok": False, "error": str(error)})
                return
            self._send_json(200, response)

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: object) -> None:
            return

    return BridgeHandler


class LocalBridgeServer:
    def __init__(
        self,
        broker: CommandBroker,
        token: str,
        host: str = "127.0.0.1",
        port: int = 27183,
        maximum_body_bytes: int = 1_048_576,
    ) -> None:
        if host != "127.0.0.1":
            raise ValueError("The Fusion bridge must bind to 127.0.0.1")
        if not token:
            raise ValueError("The Fusion bridge token must not be empty")
        self._host = host
        self._requested_port = port
        self._handler = _make_handler(broker, token, maximum_body_bytes)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self._server is None:
            return self._requested_port
        return int(self._server.server_port)

    def start(self) -> None:
        if self._server is not None:
            return
        self._server = ThreadingHTTPServer(
            (self._host, self._requested_port),
            self._handler,
        )
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="FusionCopilotBridge",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)
