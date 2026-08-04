import os
import sys
import unittest
from unittest.mock import patch

from helpers import HOOKS_DIR

sys.path.insert(0, str(HOOKS_DIR))
import runtime_config


class RuntimeConfigTests(unittest.TestCase):
    def test_defaults_preserve_claude_namespace_paths(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime_config.namespace(), "claude")
            self.assertEqual(runtime_config.tmp_path("tabtitle"), "/tmp/claude-tabtitle")
            self.assertEqual(runtime_config.debounce_dir(), "/tmp/claude-tabtitle")
            self.assertEqual(runtime_config.terminal_id_dir(), "/tmp/claude-tabterminal")
            self.assertEqual(runtime_config.default_weight_file_name(), "weights.json")

    def test_pi_namespace_changes_default_paths_and_weight_file(self):
        with patch.dict(os.environ, {"GHOSTTY_PEON_NAMESPACE": "pi"}, clear=True):
            self.assertEqual(runtime_config.namespace(), "pi")
            self.assertEqual(runtime_config.log_file(), "/tmp/pi-tab-hooks.log")
            self.assertEqual(runtime_config.plan_handoff_dir(), "/tmp/pi-plan-handoff")
            self.assertEqual(runtime_config.default_weight_file_name(), "pi-weights.json")

    def test_explicit_env_paths_override_namespace_defaults(self):
        with patch.dict(
            os.environ,
            {
                "GHOSTTY_PEON_NAMESPACE": "pi",
                "GHOSTTY_PEON_DEBOUNCE_DIR": "/custom/debounce",
                "GHOSTTY_PEON_TERMINAL_ID_DIR": "/custom/terminal",
                "GHOSTTY_PEON_WEIGHT_STATE_FILE": "/custom/weights.json",
            },
            clear=True,
        ):
            self.assertEqual(runtime_config.debounce_dir(), "/custom/debounce")
            self.assertEqual(runtime_config.terminal_id_dir(), "/custom/terminal")
            self.assertEqual(runtime_config.weight_state_file(), "/custom/weights.json")


if __name__ == "__main__":
    unittest.main()
