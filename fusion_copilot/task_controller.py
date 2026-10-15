from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol


class SafetyMode(str, Enum):
    ON = "on"
    OFF = "off"


@dataclass(frozen=True)
class Operation:
    name: str
    mutates_model: bool
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskRequest:
    task_id: str
    summary: str
    operations: tuple[Operation, ...]


@dataclass(frozen=True)
class TaskResult:
    completed: bool
    error: str | None = None


@dataclass(frozen=True)
class ValidationReport:
    passed: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class FusionAdapter(Protocol):
    def request_task_approval(self, task: TaskRequest) -> bool: ...

    def create_checkpoint(self, task: TaskRequest) -> str: ...

    def begin_undo_group(self, task: TaskRequest) -> str: ...

    def execute_operation(self, operation: Operation) -> None: ...

    def commit_undo_group(self, group_id: str) -> None: ...

    def abort_undo_group(self, group_id: str) -> None: ...

    def rollback_to_checkpoint(self, checkpoint_id: str) -> None: ...

    def validate_task(self, task: TaskRequest) -> ValidationReport: ...


class TaskController:
    def __init__(self, adapter: FusionAdapter) -> None:
        self._adapter = adapter

    def execute(self, task: TaskRequest, safety_mode: SafetyMode) -> TaskResult:
        requires_approval = any(operation.mutates_model for operation in task.operations)
        if (
            safety_mode is SafetyMode.ON
            and requires_approval
            and not self._adapter.request_task_approval(task)
        ):
            return TaskResult(completed=False)

        checkpoint_id: str | None = None
        undo_group_id: str | None = None
        if requires_approval:
            checkpoint_id = self._adapter.create_checkpoint(task)
            undo_group_id = self._adapter.begin_undo_group(task)

        try:
            for operation in task.operations:
                self._adapter.execute_operation(operation)
            if requires_approval:
                validation = self._adapter.validate_task(task)
                if not validation.passed:
                    message = "; ".join(validation.errors) or "Final validation failed"
                    raise RuntimeError(message)
        except Exception as error:
            if undo_group_id is not None:
                self._adapter.abort_undo_group(undo_group_id)
            if checkpoint_id is not None:
                self._adapter.rollback_to_checkpoint(checkpoint_id)
            return TaskResult(completed=False, error=str(error))

        if undo_group_id is not None:
            self._adapter.commit_undo_group(undo_group_id)

        return TaskResult(completed=True)
