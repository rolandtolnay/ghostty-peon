import unittest

from helpers import assert_hook_ok, hook_test_env, run_hook


class TitleStateHookRegressionTests(unittest.TestCase):
    def test_exit_plan_permission_marks_planpending_without_changing_format(self):
        with hook_test_env() as (_root, env, dirs):
            session_id = "session-plan"
            (dirs["debounce"] / session_id).write_text("123\n🌀 refactor-hooks")

            result = run_hook(
                "tab-attention-hook.py",
                {
                    "session_id": session_id,
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "ExitPlanMode",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual(
                (dirs["debounce"] / session_id).read_text(),
                "123\n🔥 refactor-hooks\nplanpending",
            )

    def test_stop_without_question_sets_ready_and_preserves_timestamp(self):
        with hook_test_env() as (_root, env, dirs):
            session_id = "session-stop"
            (dirs["debounce"] / session_id).write_text("456\n🌀 fix-tabs")
            (dirs["terminal"] / session_id).write_text("term-test-1")

            result = run_hook(
                "tab-stop-question-hook.py",
                {
                    "session_id": session_id,
                    "hook_event_name": "Stop",
                    "last_assistant_message": "Done. The tests pass.",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / session_id).read_text(), "456\n🌿 fix-tabs")

    def test_non_question_tool_result_recovers_stale_ready_to_working(self):
        with hook_test_env() as (_root, env, dirs):
            session_id = "session-stale-ready"
            (dirs["debounce"] / session_id).write_text("789\n🌿 implement-plan")
            (dirs["terminal"] / session_id).write_text("term-test-1")

            result = run_hook(
                "tab-attention-hook.py",
                {
                    "session_id": session_id,
                    "hook_event_name": "PostToolUse",
                    "tool_name": "read",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / session_id).read_text(), "789\n🌀 implement-plan")


if __name__ == "__main__":
    unittest.main()
