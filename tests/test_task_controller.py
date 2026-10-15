import unittest

from fusion_copilot.task_controller import (
    Operation,
    SafetyMode,
    TaskController,
    TaskRequest,
    ValidationReport,
)


class RecordingFusionAdapter:
    def __init__(
        self,
        fail_on: str | None = None,
        validation: ValidationReport | None = None,
    ) -> None:
        self.fail_on = fail_on
        self.validation = validation or ValidationReport(passed=True)
        self.approval_requests = 0
        self.checkpoints: list[str] = []
        self.undo_groups_started: list[str] = []
        self.undo_groups_committed: list[str] = []
        self.undo_groups_aborted: list[str] = []
        self.rolled_back_checkpoints: list[str] = []
        self.executed_operations: list[str] = []
        self.received_operations: list[Operation] = []

    def request_task_approval(self, task: TaskRequest) -> bool:
        self.approval_requests += 1
        return True

    def execute_operation(self, operation: Operation) -> None:
        self.executed_operations.append(operation.name)
        self.received_operations.append(operation)
        if operation.name == self.fail_on:
            raise RuntimeError(f"operation failed: {operation.name}")

    def create_checkpoint(self, task: TaskRequest) -> str:
        checkpoint_id = f"checkpoint:{task.task_id}"
        self.checkpoints.append(checkpoint_id)
        return checkpoint_id

    def begin_undo_group(self, task: TaskRequest) -> str:
        group_id = f"undo:{task.task_id}"
        self.undo_groups_started.append(group_id)
        return group_id

    def commit_undo_group(self, group_id: str) -> None:
        self.undo_groups_committed.append(group_id)

    def abort_undo_group(self, group_id: str) -> None:
        self.undo_groups_aborted.append(group_id)

    def rollback_to_checkpoint(self, checkpoint_id: str) -> None:
        self.rolled_back_checkpoints.append(checkpoint_id)

    def validate_task(self, task: TaskRequest) -> ValidationReport:
        return self.validation


class TaskControllerTests(unittest.TestCase):
    def test_safety_on_approves_the_whole_task_once(self) -> None:
        adapter = RecordingFusionAdapter()
        controller = TaskController(adapter)
        task = TaskRequest(
            task_id="model-bracket",
            summary="Build a complete mounting bracket",
            operations=(
                Operation("create_sketch", mutates_model=True),
                Operation("extrude", mutates_model=True),
                Operation("fillet", mutates_model=True),
            ),
        )

        result = controller.execute(task, SafetyMode.ON)

        self.assertTrue(result.completed)
        self.assertEqual(adapter.approval_requests, 1)
        self.assertEqual(
            adapter.executed_operations,
            ["create_sketch", "extrude", "fillet"],
        )

    def test_safety_off_runs_without_approval_but_keeps_recovery_guards(self) -> None:
        adapter = RecordingFusionAdapter()
        controller = TaskController(adapter)
        task = TaskRequest(
            task_id="model-enclosure",
            summary="Build a complete electronics enclosure",
            operations=(
                Operation("create_box", mutates_model=True),
                Operation("shell", mutates_model=True),
            ),
        )

        result = controller.execute(task, SafetyMode.OFF)

        self.assertTrue(result.completed)
        self.assertEqual(adapter.approval_requests, 0)
        self.assertEqual(adapter.checkpoints, ["checkpoint:model-enclosure"])
        self.assertEqual(adapter.undo_groups_started, ["undo:model-enclosure"])
        self.assertEqual(adapter.undo_groups_committed, ["undo:model-enclosure"])
        self.assertEqual(adapter.executed_operations, ["create_box", "shell"])

    def test_failed_task_rolls_back_without_requesting_step_approvals(self) -> None:
        adapter = RecordingFusionAdapter(fail_on="fillet")
        controller = TaskController(adapter)
        task = TaskRequest(
            task_id="model-housing",
            summary="Build a complete protective housing",
            operations=(
                Operation("create_profile", mutates_model=True),
                Operation("extrude", mutates_model=True),
                Operation("fillet", mutates_model=True),
            ),
        )

        result = controller.execute(task, SafetyMode.OFF)

        self.assertFalse(result.completed)
        self.assertEqual(result.error, "operation failed: fillet")
        self.assertEqual(adapter.approval_requests, 0)
        self.assertEqual(adapter.undo_groups_aborted, ["undo:model-housing"])
        self.assertEqual(
            adapter.rolled_back_checkpoints,
            ["checkpoint:model-housing"],
        )
        self.assertEqual(adapter.undo_groups_committed, [])

    def test_operation_arguments_reach_the_fusion_adapter_unchanged(self) -> None:
        adapter = RecordingFusionAdapter()
        controller = TaskController(adapter)
        operation = Operation(
            "create_box",
            mutates_model=True,
            arguments={
                "reference": "base",
                "width_mm": 80,
                "depth_mm": 30,
                "height_mm": 8,
            },
        )
        task = TaskRequest(
            task_id="box-with-dimensions",
            summary="Create a dimensioned box",
            operations=(operation,),
        )

        result = controller.execute(task, SafetyMode.OFF)

        self.assertTrue(result.completed)
        self.assertEqual(adapter.received_operations, [operation])

    def test_failed_final_validation_aborts_the_whole_task(self) -> None:
        adapter = RecordingFusionAdapter(
            validation=ValidationReport(
                passed=False,
                errors=("Body Bracket is open",),
            )
        )
        controller = TaskController(adapter)
        task = TaskRequest(
            task_id="model-bracket-validation",
            summary="Build and validate a printable bracket",
            operations=(Operation("build_bracket", mutates_model=True),),
        )

        result = controller.execute(task, SafetyMode.OFF)

        self.assertFalse(result.completed)
        self.assertEqual(result.error, "Body Bracket is open")
        self.assertEqual(
            adapter.rolled_back_checkpoints,
            ["checkpoint:model-bracket-validation"],
        )
        self.assertEqual(
            adapter.undo_groups_aborted,
            ["undo:model-bracket-validation"],
        )
        self.assertEqual(adapter.undo_groups_committed, [])


if __name__ == "__main__":
    unittest.main()
