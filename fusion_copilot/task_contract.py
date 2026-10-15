from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .task_controller import Operation, TaskRequest


class TaskContractError(ValueError):
    """Raised when an MCP modeling task does not satisfy the bridge contract."""


_OPERATION_MUTATION = {
    "set_user_parameter": True,
    "create_box": True,
    "create_cylinder": True,
    "cut_cylindrical_hole": True,
    "fillet_all_edges": True,
    "rename_body": True,
}


def _required_text(payload: Mapping[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise TaskContractError(f"{field_name} must be a non-empty string")
    return value.strip()


def parse_task_payload(payload: Mapping[str, Any]) -> TaskRequest:
    task_id = _required_text(payload, "task_id")
    summary = _required_text(payload, "summary")
    raw_operations = payload.get("operations")
    if not isinstance(raw_operations, list) or not raw_operations:
        raise TaskContractError("operations must be a non-empty list")

    operations: list[Operation] = []
    for index, raw_operation in enumerate(raw_operations):
        if not isinstance(raw_operation, Mapping):
            raise TaskContractError(f"operations[{index}] must be an object")
        if "mutates_model" in raw_operation:
            raise TaskContractError(
                "mutates_model is controlled by the connector and must not be supplied"
            )
        name = _required_text(raw_operation, "name")
        if name not in _OPERATION_MUTATION:
            raise TaskContractError(f"unsupported operation: {name}")
        arguments = raw_operation.get("arguments", {})
        if not isinstance(arguments, Mapping):
            raise TaskContractError(f"operations[{index}].arguments must be an object")
        operations.append(
            Operation(
                name=name,
                mutates_model=_OPERATION_MUTATION[name],
                arguments=dict(arguments),
            )
        )

    return TaskRequest(
        task_id=task_id,
        summary=summary,
        operations=tuple(operations),
    )
