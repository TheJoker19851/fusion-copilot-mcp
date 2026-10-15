import tempfile
import unittest
from pathlib import Path

from fusion_copilot.security_settings import SecuritySettingsStore
from fusion_copilot.task_controller import SafetyMode


class SecuritySettingsTests(unittest.TestCase):
    def test_safety_defaults_to_on_and_can_only_be_changed_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "settings.json"
            store = SecuritySettingsStore(path)

            self.assertEqual(store.load(), SafetyMode.ON)

            store.set_mode(SafetyMode.OFF)

            self.assertEqual(SecuritySettingsStore(path).load(), SafetyMode.OFF)


if __name__ == "__main__":
    unittest.main()
