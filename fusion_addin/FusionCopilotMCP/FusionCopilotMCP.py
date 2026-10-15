from __future__ import annotations

import json
import os
import queue
import secrets
import sys
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import adsk.core


ADDIN_DIRECTORY = Path(__file__).resolve().parent
VENDOR_DIRECTORY = ADDIN_DIRECTORY / "vendor"
if str(ADDIN_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(ADDIN_DIRECTORY))
if str(VENDOR_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(VENDOR_DIRECTORY))

from fusion_copilot.addin_bridge_server import (  # noqa: E402
    CommandBroker,
    LocalBridgeServer,
)
from fusion_copilot.security_settings import SecuritySettingsStore  # noqa: E402
from fusion_copilot.task_contract import parse_task_payload  # noqa: E402
from fusion_copilot.task_controller import SafetyMode, TaskController, TaskRequest  # noqa: E402
from fusion_adapter import FusionAdapter  # noqa: E402


CUSTOM_EVENT_ID = "FusionCopilotMCP_CommandReady"
SHOW_PALETTE_COMMAND_ID = "FusionCopilotMCP_ShowPalette"
EXECUTE_TASK_COMMAND_ID = "FusionCopilotMCP_ExecuteTask"
PALETTE_ID = "FusionCopilotMCP_Palette"

_app: adsk.core.Application | None = None
_ui: adsk.core.UserInterface | None = None
_handlers: list[Any] = []
_broker: CommandBroker | None = None
_bridge_server: LocalBridgeServer | None = None
_settings: SecuritySettingsStore | None = None
_active_execution: "ActiveExecution | None" = None


@dataclass
class ActiveExecution:
    command_id: str
    task: TaskRequest


def _data_directory() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        local_app_data = str(Path.home() / "AppData" / "Local")
    return Path(local_app_data) / "FusionCopilotMCP"


def _load_or_create_token() -> tuple[str, Path]:
    token_path = _data_directory() / "bridge-token"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    if not token:
        token = secrets.token_urlsafe(32)
        token_path.write_text(token + "\n", encoding="utf-8")
    return token, token_path


def _audit(event: str, payload: dict[str, Any]) -> None:
    path = _data_directory() / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **payload,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")


def _current_mode() -> SafetyMode:
    if _settings is None:
        return SafetyMode.ON
    return _settings.load()


def _send_palette_status(extra: dict[str, Any] | None = None) -> None:
    if _ui is None:
        return
    palette = _ui.palettes.itemById(PALETTE_ID)
    if palette is None:
        return
    payload: dict[str, Any] = {
        "safety_mode": _current_mode().value,
        "bridge_port": _bridge_server.port if _bridge_server else None,
        "busy": _active_execution is not None,
    }
    if extra:
        payload.update(extra)
    palette.sendInfoToHTML("status", json.dumps(payload, ensure_ascii=False))


def _show_palette() -> None:
    if _ui is None:
        return
    palette = _ui.palettes.itemById(PALETTE_ID)
    if palette is None:
        palette = _ui.palettes.add2(
            PALETTE_ID,
            "Fusion Copilot MCP",
            str(ADDIN_DIRECTORY / "palette.html"),
            True,
            True,
            True,
            360,
            520,
        )
        palette.dockingState = adsk.core.PaletteDockingStates.PaletteDockStateRight
        html_handler = PaletteHTMLHandler()
        palette.incomingFromHTML.add(html_handler)
        _handlers.append(html_handler)
    palette.isVisible = True
    _send_palette_status()


class ShowPaletteCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        execute_handler = ShowPaletteExecuteHandler()
        args.command.execute.add(execute_handler)
        _handlers.append(execute_handler)


class ShowPaletteExecuteHandler(adsk.core.CommandEventHandler):
    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        _show_palette()


class PaletteHTMLHandler(adsk.core.HTMLEventHandler):
    def notify(self, args: adsk.core.HTMLEventArgs) -> None:
        try:
            if args.action == "request_status":
                _send_palette_status()
                return
            if args.action != "set_safety_mode":
                return
            payload = json.loads(args.data)
            mode = SafetyMode(payload.get("mode"))
            if _settings is None:
                raise RuntimeError("Settings are not initialized")
            _settings.set_mode(mode)
            _audit("safety_mode_changed", {"mode": mode.value})
            _send_palette_status(
                {"message": f"Mode sécurité {mode.value.upper()} activé"}
            )
        except Exception as error:
            _send_palette_status({"error": str(error)})


class BridgeEventHandler(adsk.core.CustomEventHandler):
    def notify(self, args: adsk.core.CustomEventArgs) -> None:
        if _broker is None:
            return
        while True:
            try:
                pending = _broker.take_next()
            except queue.Empty:
                return
            try:
                response = _dispatch_command(pending.command_id, pending.command)
                if response is not None:
                    _broker.complete(pending.command_id, response)
            except Exception as error:
                _audit(
                    "command_failed_before_execution",
                    {"command_id": pending.command_id, "error": str(error)},
                )
                _broker.complete(
                    pending.command_id,
                    {"ok": False, "error": str(error)},
                )


class ExecuteTaskCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def notify(self, args: adsk.core.CommandCreatedEventArgs) -> None:
        execute_handler = ExecuteTaskHandler()
        args.command.execute.add(execute_handler)
        _handlers.append(execute_handler)


class ExecuteTaskHandler(adsk.core.CommandEventHandler):
    def notify(self, args: adsk.core.CommandEventArgs) -> None:
        global _active_execution
        active = _active_execution
        if active is None or _broker is None or _app is None or _ui is None:
            args.executeFailed = True
            args.executeFailedMessage = "Fusion Copilot has no pending task"
            return

        adapter = FusionAdapter(_app, _ui)
        controller = TaskController(adapter)
        mode = _current_mode()
        try:
            result = controller.execute(active.task, mode)
            if result.completed:
                response = {
                    "ok": True,
                    "status": "completed",
                    "task_id": active.task.task_id,
                    "safety_mode": mode.value,
                    "operations_executed": len(active.task.operations),
                    "checkpoint": adapter.last_checkpoint,
                    "validation": adapter.validation_dict(adapter.last_validation),
                }
                _audit("task_completed", response)
            elif result.error:
                args.executeFailed = True
                args.executeFailedMessage = result.error
                response = {
                    "ok": False,
                    "status": "failed",
                    "task_id": active.task.task_id,
                    "safety_mode": mode.value,
                    "error": result.error,
                    "checkpoint": adapter.last_checkpoint,
                }
                _audit("task_failed", response)
            else:
                response = {
                    "ok": False,
                    "status": "rejected",
                    "task_id": active.task.task_id,
                    "safety_mode": mode.value,
                    "error": "The user rejected the complete task",
                }
                _audit("task_rejected", response)
            _broker.complete(active.command_id, response)
            _send_palette_status(
                {"last_task": response["status"], "task_id": active.task.task_id}
            )
        except Exception as error:
            args.executeFailed = True
            args.executeFailedMessage = str(error)
            response = {
                "ok": False,
                "status": "failed",
                "task_id": active.task.task_id,
                "safety_mode": mode.value,
                "error": str(error),
            }
            _audit("task_crashed", response)
            _broker.complete(active.command_id, response)
            _send_palette_status({"error": str(error), "task_id": active.task.task_id})
        finally:
            _active_execution = None


def _dispatch_command(
    command_id: str,
    command: dict[str, Any],
) -> dict[str, Any] | None:
    global _active_execution
    if _app is None or _ui is None:
        raise RuntimeError("Fusion Copilot is not initialized")
    action = command.get("action")
    payload = command.get("payload", {})
    if not isinstance(action, str) or not isinstance(payload, dict):
        raise ValueError("Invalid bridge command")
    adapter = FusionAdapter(_app, _ui)
    if action == "get_status":
        return adapter.status(_current_mode().value)
    if action == "inspect_design":
        return adapter.inspect_design()
    if action == "validate_design":
        return adapter.validate_design()
    if action != "execute_modeling_task":
        raise ValueError(f"Unsupported bridge action: {action}")
    if _active_execution is not None:
        return {
            "ok": False,
            "status": "busy",
            "error": "Another Fusion modeling task is already running",
        }
    task = parse_task_payload(payload)
    _active_execution = ActiveExecution(command_id=command_id, task=task)
    _audit(
        "task_received",
        {
            "command_id": command_id,
            "task_id": task.task_id,
            "summary": task.summary,
            "operation_count": len(task.operations),
            "safety_mode": _current_mode().value,
        },
    )
    command_definition = _ui.commandDefinitions.itemById(EXECUTE_TASK_COMMAND_ID)
    if command_definition is None:
        _active_execution = None
        raise RuntimeError("Fusion Copilot execution command is unavailable")
    command_definition.execute()
    _send_palette_status({"task_id": task.task_id})
    return None


def _install_commands() -> None:
    if _ui is None:
        return
    show_definition = _ui.commandDefinitions.itemById(SHOW_PALETTE_COMMAND_ID)
    if show_definition is None:
        show_definition = _ui.commandDefinitions.addButtonDefinition(
            SHOW_PALETTE_COMMAND_ID,
            "Fusion Copilot",
            "Afficher le connecteur IA et son mode de sécurité",
            "",
        )
    show_created = ShowPaletteCreatedHandler()
    show_definition.commandCreated.add(show_created)
    _handlers.append(show_created)

    execute_definition = _ui.commandDefinitions.itemById(EXECUTE_TASK_COMMAND_ID)
    if execute_definition is None:
        execute_definition = _ui.commandDefinitions.addButtonDefinition(
            EXECUTE_TASK_COMMAND_ID,
            "Fusion Copilot Internal Task",
            "Commande interne utilisée pour regrouper une tâche en une transaction",
            "",
        )
    execute_created = ExecuteTaskCreatedHandler()
    execute_definition.commandCreated.add(execute_created)
    _handlers.append(execute_created)

    panel = _ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
    if panel is not None and panel.controls.itemById(SHOW_PALETTE_COMMAND_ID) is None:
        panel.controls.addCommand(show_definition)


def run(context: str) -> None:
    global _app, _ui, _broker, _bridge_server, _settings
    try:
        _app = adsk.core.Application.get()
        _ui = _app.userInterface
        _settings = SecuritySettingsStore(_data_directory() / "settings.json")

        _install_commands()

        custom_event = _app.registerCustomEvent(CUSTOM_EVENT_ID)
        bridge_handler = BridgeEventHandler()
        custom_event.add(bridge_handler)
        _handlers.append(bridge_handler)

        _broker = CommandBroker(
            lambda: _app.fireCustomEvent(CUSTOM_EVENT_ID),
            timeout_seconds=300,
        )
        token, token_path = _load_or_create_token()
        _bridge_server = LocalBridgeServer(_broker, token=token, port=27183)
        _bridge_server.start()
        _audit(
            "addin_started",
            {
                "bridge_port": _bridge_server.port,
                "token_path": str(token_path),
                "safety_mode": _current_mode().value,
            },
        )
        _show_palette()
    except Exception:
        details = traceback.format_exc()
        try:
            _audit("addin_start_failed", {"traceback": details})
        except Exception:
            pass
        if _ui is not None:
            _ui.messageBox("Fusion Copilot failed to start:\n" + details)


def stop(context: str) -> None:
    global _bridge_server, _broker, _active_execution
    try:
        if _bridge_server is not None:
            _bridge_server.stop()
            _bridge_server = None
        if _broker is not None:
            _broker.fail_all("Fusion Copilot add-in stopped")
            _broker = None
        _active_execution = None
        if _app is not None:
            _app.unregisterCustomEvent(CUSTOM_EVENT_ID)
        if _ui is not None:
            palette = _ui.palettes.itemById(PALETTE_ID)
            if palette is not None:
                palette.deleteMe()
            panel = _ui.allToolbarPanels.itemById("SolidScriptsAddinsPanel")
            if panel is not None:
                control = panel.controls.itemById(SHOW_PALETTE_COMMAND_ID)
                if control is not None:
                    control.deleteMe()
            for command_id in (SHOW_PALETTE_COMMAND_ID, EXECUTE_TASK_COMMAND_ID):
                definition = _ui.commandDefinitions.itemById(command_id)
                if definition is not None:
                    definition.deleteMe()
        _handlers.clear()
    except Exception:
        if _ui is not None:
            _ui.messageBox("Fusion Copilot failed to stop cleanly:\n" + traceback.format_exc())
