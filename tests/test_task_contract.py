import unittest

from fusion_copilot.task_contract import TaskContractError, parse_task_payload


class TaskContractTests(unittest.TestCase):
    def test_mutation_classification_is_owned_by_the_connector(self) -> None:
        task = parse_task_payload(
            {
                "task_id": "complete-base",
                "summary": "Build a printable base",
                "operations": [
                    {
                        "name": "create_box",
                        "arguments": {
                            "reference": "base",
                            "width_mm": 80,
                            "depth_mm": 30,
                            "height_mm": 8,
                        },
                    }
                ],
            }
        )

        self.assertTrue(task.operations[0].mutates_model)

    def test_caller_cannot_spoof_an_operation_as_read_only(self) -> None:
        with self.assertRaisesRegex(
            TaskContractError,
            "mutates_model is controlled by the connector",
        ):
            parse_task_payload(
                {
                    "task_id": "spoofed-task",
                    "summary": "Attempt to bypass approval",
                    "operations": [
                        {
                            "name": "create_box",
                            "mutates_model": False,
                            "arguments": {
                                "reference": "base",
                                "width_mm": 80,
                                "depth_mm": 30,
                                "height_mm": 8,
                            },
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
