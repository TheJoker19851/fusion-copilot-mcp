from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Protocol

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

from .bridge_client import FusionBridgeClient, FusionBridgeError


class Bridge(Protocol):
    def call(self, action: str, payload: dict[str, Any] | None = None) -> dict[str, Any]: ...


def create_server(bridge: Bridge) -> MCPServer:
    server = MCPServer(
        name="fusion-copilot-mcp",
        title="Fusion Copilot MCP",
        description="Control Autodesk Fusion through a local, safety-aware add-in.",
        version="0.1.0",
        instructions=(
            "Use fusion_get_status before other tools. Send every requested model "
            "change as one fusion_execute_modeling_task call. Fusion owns the safety "
            "switch: safety on approves the complete task once; safety off executes "
            "without additional approval. Never split a model into approval-sized calls."
        ),
    )

    def call_bridge(
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            return bridge.call(action, payload)
        except FusionBridgeError as error:
            return {
                "ok": False,
                "connected": False,
                "error": str(error),
            }

    @server.tool(
        name="fusion_get_status",
        title="Get Fusion bridge status",
        description=(
            "Check whether Fusion is connected and report its user-controlled safety "
            "mode before inspecting or changing a design."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def get_status() -> dict[str, Any]:
        return call_bridge("get_status")

    @server.tool(
        name="fusion_inspect_design",
        title="Inspect the active Fusion design",
        description=(
            "Read the active document, design units, components, bodies, parameters, "
            "selection, and validation summary without modifying the model."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def inspect_design() -> dict[str, Any]:
        return call_bridge("inspect_design")

    @server.tool(
        name="fusion_execute_modeling_task",
        title="Execute one complete Fusion modeling task",
        description=(
            "Execute a complete user-requested modeling plan as one Fusion transaction. "
            "Provide all operations needed for the task in order. Fusion applies its "
            "safety switch once to the whole task, keeps a recovery checkpoint, and "
            "validates the final model before committing."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def execute_modeling_task(
        task_id: str,
        summary: str,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return call_bridge(
            "execute_modeling_task",
            {
                "task_id": task_id,
                "summary": summary,
                "operations": operations,
            },
        )

    @server.tool(
        name="fusion_validate_design",
        title="Validate the active Fusion design",
        description=(
            "Check the active design for open bodies, invalid geometry, and other "
            "supported model-integrity problems without changing it."
        ),
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
        structured_output=True,
    )
    def validate_design() -> dict[str, Any]:
        return call_bridge("validate_design")

    return server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the local MCP sidecar for the Fusion Copilot add-in."
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=27184)
    parser.add_argument("--bridge-url", default="http://127.0.0.1:27183")
    parser.add_argument("--token-path", type=Path)
    arguments = parser.parse_args()

    bridge = FusionBridgeClient(
        base_url=arguments.bridge_url,
        token_path=arguments.token_path,
    )
    server = create_server(bridge)
    if arguments.transport == "stdio":
        server.run("stdio")
    else:
        server.run(
            "streamable-http",
            host=arguments.host,
            port=arguments.port,
            streamable_http_path="/mcp",
        )
