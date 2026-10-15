import asyncio
import unittest

from fusion_copilot.bridge_client import FusionBridgeError
from fusion_copilot.mcp_server import create_server


class RecordingBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def call(self, action: str, payload: dict | None = None) -> dict:
        actual_payload = payload or {}
        self.calls.append((action, actual_payload))
        return {
            "ok": True,
            "action": action,
            "received": actual_payload,
        }


class MCPServerTests(unittest.TestCase):
    def test_execute_modeling_task_forwards_one_complete_batch(self) -> None:
        bridge = RecordingBridge()
        server = create_server(bridge)

        result = asyncio.run(
            server.call_tool(
                "fusion_execute_modeling_task",
                {
                    "task_id": "complete-bracket",
                    "summary": "Build the complete bracket",
                    "operations": [
                        {
                            "name": "create_box",
                            "arguments": {
                                "reference": "base",
                                "width_mm": 80,
                                "depth_mm": 30,
                                "height_mm": 8,
                            },
                        },
                        {
                            "name": "cut_hole",
                            "arguments": {
                                "target": "base",
                                "diameter_mm": 6,
                            },
                        },
                    ],
                },
            )
        )

        self.assertFalse(result.is_error)
        self.assertEqual(len(bridge.calls), 1)
        action, payload = bridge.calls[0]
        self.assertEqual(action, "execute_modeling_task")
        self.assertEqual(payload["task_id"], "complete-bracket")
        self.assertEqual(len(payload["operations"]), 2)

    def test_safety_mode_cannot_be_changed_through_mcp(self) -> None:
        server = create_server(RecordingBridge())

        tool_names = {tool.name for tool in asyncio.run(server.list_tools())}

        self.assertIn("fusion_get_status", tool_names)
        self.assertIn("fusion_execute_modeling_task", tool_names)
        self.assertNotIn("fusion_set_safety_mode", tool_names)

    def test_disconnected_fusion_returns_actionable_status(self) -> None:
        class DisconnectedBridge:
            def call(self, action: str, payload: dict | None = None) -> dict:
                raise FusionBridgeError("Start Fusion and load the add-in")

        server = create_server(DisconnectedBridge())

        result = asyncio.run(server.call_tool("fusion_get_status", {}))

        self.assertFalse(result.is_error)
        self.assertEqual(
            result.structured_content,
            {
                "ok": False,
                "connected": False,
                "error": "Start Fusion and load the add-in",
            },
        )


if __name__ == "__main__":
    unittest.main()
