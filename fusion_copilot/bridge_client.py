from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class FusionBridgeError(RuntimeError):
    """Raised when the local Fusion add-in bridge cannot complete a request."""


def default_token_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise FusionBridgeError("LOCALAPPDATA is not available")
    return Path(local_app_data) / "FusionCopilotMCP" / "bridge-token"


class FusionBridgeClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:27183",
        token_path: Path | None = None,
        timeout_seconds: float = 180.0,
    ) -> None:
        parsed_url = urlparse(base_url)
        if parsed_url.scheme != "http" or parsed_url.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError("The Fusion bridge must use a loopback HTTP address")
        self._base_url = base_url.rstrip("/")
        self._token_path = token_path or default_token_path()
        self._timeout_seconds = timeout_seconds

    def call(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            token = self._token_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise FusionBridgeError(
                "Fusion bridge token is unavailable. Start the Fusion add-in first."
            ) from error
        if not token:
            raise FusionBridgeError("Fusion bridge token is empty")

        encoded_body = json.dumps(
            {"action": action, "payload": payload or {}},
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            f"{self._base_url}/command",
            data=encoded_body,
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                response_body = response.read()
        except HTTPError as error:
            details = error.read().decode("utf-8", errors="replace")
            raise FusionBridgeError(
                f"Fusion bridge rejected the request ({error.code}): {details}"
            ) from error
        except URLError as error:
            raise FusionBridgeError(
                "Fusion is not connected. Start Fusion and load the Fusion Copilot add-in."
            ) from error

        try:
            decoded = json.loads(response_body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise FusionBridgeError("Fusion bridge returned invalid JSON") from error
        if not isinstance(decoded, dict):
            raise FusionBridgeError("Fusion bridge returned a non-object response")
        return decoded
