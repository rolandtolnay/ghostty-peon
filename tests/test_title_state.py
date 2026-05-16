import os
import unittest
from unittest.mock import patch

from helpers import HOOKS_DIR, hook_test_env

import sys
sys.path.insert(0, str(HOOKS_DIR))
import title_state


class TitleStateTests(unittest.TestCase):
    def test_write_and_read_preserves_debounce_format_with_plan_state(self):
        with hook_test_env() as (_root, env, dirs):
            with patch.dict(os.environ, env, clear=True):
                title_state.write("session-1", "123.4", "🔥 fix-bug", plan_state="planpending")

                self.assertEqual((dirs["debounce"] / "session-1").read_text(), "123.4\n🔥 fix-bug\nplanpending")
                state = title_state.read("session-1")
                self.assertEqual(state.timestamp, "123.4")
                self.assertEqual(state.title, "🔥 fix-bug")
                self.assertEqual(state.plan_state, "planpending")
                self.assertTrue(state.is_plan_pending)

    def test_timestamp_only_state_preserves_existing_cooldown_semantics(self):
        with hook_test_env() as (_root, env, dirs):
            with patch.dict(os.environ, env, clear=True):
                (dirs["debounce"] / "session-1").write_text("999\n")

                state = title_state.read("session-1")
                self.assertEqual(state.timestamp, "999")
                self.assertEqual(state.title, "")
                self.assertEqual(state.plan_state, "")

    def test_origin_read_write_and_delete(self):
        with hook_test_env() as (_root, env, dirs):
            with patch.dict(os.environ, env, clear=True):
                title_state.write("session-1", "1", "🌀 existing")
                title_state.write_origin("session-1", "abcdef", max_chars=3)

                self.assertEqual(title_state.read_origin("session-1"), "abc")
                title_state.delete("session-1")
                self.assertFalse((dirs["debounce"] / "session-1").exists())
                self.assertFalse((dirs["debounce"] / "session-1.origin").exists())


if __name__ == "__main__":
    unittest.main()
