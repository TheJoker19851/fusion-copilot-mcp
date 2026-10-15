from __future__ import annotations

import json
from pathlib import Path

from .task_controller import SafetyMode


class SecuritySettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> SafetyMode:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return SafetyMode.ON
        if not isinstance(payload, dict):
            return SafetyMode.ON
        try:
            return SafetyMode(payload.get("safety_mode", SafetyMode.ON.value))
        except ValueError:
            return SafetyMode.ON

    def set_mode(self, mode: SafetyMode) -> None:
        if not isinstance(mode, SafetyMode):
            raise TypeError("mode must be a SafetyMode")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temporary_path.write_text(
            json.dumps({"safety_mode": mode.value}, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_path.replace(self._path)
