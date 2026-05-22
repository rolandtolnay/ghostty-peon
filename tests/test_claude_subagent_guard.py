import time
import unittest

from helpers import assert_hook_ok, hook_test_env, read_log, run_hook


SUBAGENT_FIELDS = {
    "agent_id": "agent-123",
    "agent_type": "general-purpose",
}


class ClaudeSubagentGuardTests(unittest.TestCase):
    def test_subagent_session_start_does_not_capture_parent_tab_or_assign_unit(self):
        with hook_test_env(namespace="claude", fake_term_id="term-parent") as (root, env, dirs):
            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "parent-session",
                    "cwd": str(root / "project"),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                    **SUBAGENT_FIELDS,
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertFalse((dirs["terminal"] / "parent-session").exists())
            self.assertFalse((dirs["session_index"] / "parent-session").exists())
            self.assertIn("skip: subagent", read_log(root))

    def test_agent_type_without_agent_id_is_not_treated_as_subagent(self):
        with hook_test_env(namespace="claude", fake_term_id="term-main-agent") as (root, env, dirs):
            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "main-agent-session",
                    "cwd": str(root / "project"),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                    "agent_type": "general-purpose",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["terminal"] / "main-agent-session").read_text(), "term-main-agent")

    def test_session_start_exports_nested_hook_guard_for_child_claude_processes(self):
        with hook_test_env(namespace="claude", fake_term_id="term-parent") as (root, env, dirs):
            env_file = root / "claude-env.sh"
            env["CLAUDE_ENV_FILE"] = str(env_file)
            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "parent-session",
                    "cwd": str(root / "project"),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertIn("export _CLAUDE_HOOK_NESTED=1\n", env_file.read_text())
            self.assertIn("nested hook guard exported", read_log(root))

            nested_env = env.copy()
            nested_env["_CLAUDE_HOOK_NESTED"] = "1"
            nested_result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "nested-session",
                    "cwd": str(root / "project"),
                    "hook_event_name": "SessionStart",
                    "source": "startup",
                },
                nested_env,
            )

            assert_hook_ok(self, nested_result)
            self.assertFalse((dirs["terminal"] / "nested-session").exists())
            self.assertFalse((dirs["session_index"] / "nested-session").exists())

    def test_subagent_prompt_does_not_change_parent_title_state(self):
        with hook_test_env(namespace="claude") as (root, env, dirs):
            session_id = "parent-session"
            original_state = f"{time.time()}\n🌿 parent-title"
            (dirs["debounce"] / session_id).write_text(original_state)
            (dirs["terminal"] / session_id).write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": session_id,
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Inspect the implementation and report only the relevant findings.",
                    **SUBAGENT_FIELDS,
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / session_id).read_text(), original_state)

    def test_subagent_attention_event_does_not_mark_parent_tab_blocked(self):
        with hook_test_env(namespace="claude") as (root, env, dirs):
            session_id = "parent-session"
            original_state = "123\n🌀 parent-title"
            (dirs["debounce"] / session_id).write_text(original_state)
            (dirs["terminal"] / session_id).write_text("term-test-1")

            result = run_hook(
                "tab-attention-hook.py",
                {
                    "session_id": session_id,
                    "cwd": str(root / "project"),
                    "hook_event_name": "PermissionRequest",
                    "tool_name": "Bash",
                    **SUBAGENT_FIELDS,
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / session_id).read_text(), original_state)

    def test_subagent_stop_does_not_mark_parent_tab_ready(self):
        with hook_test_env(namespace="claude") as (root, env, dirs):
            session_id = "parent-session"
            original_state = "123\n🌀 parent-title"
            (dirs["debounce"] / session_id).write_text(original_state)
            (dirs["terminal"] / session_id).write_text("term-test-1")

            result = run_hook(
                "tab-stop-question-hook.py",
                {
                    "session_id": session_id,
                    "cwd": str(root / "project"),
                    "hook_event_name": "Stop",
                    "last_assistant_message": "Done. The requested review is complete.",
                    **SUBAGENT_FIELDS,
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / session_id).read_text(), original_state)

    def test_subagent_stop_event_does_not_release_parent_terminal(self):
        with hook_test_env(namespace="claude") as (root, env, dirs):
            session_id = "parent-session"
            original_state = "123\n🌿 parent-title"
            (dirs["debounce"] / session_id).write_text(original_state)
            (dirs["terminal"] / session_id).write_text("term-test-1")

            result = run_hook(
                "session-end-hook.py",
                {
                    "session_id": session_id,
                    "cwd": str(root / "project"),
                    "hook_event_name": "SubagentStop",
                    "shutdown_reason": "other",
                    **SUBAGENT_FIELDS,
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / session_id).read_text(), original_state)
            self.assertEqual((dirs["terminal"] / session_id).read_text(), "term-test-1")

    def test_subagent_lifecycle_event_without_agent_id_does_not_release_parent_terminal(self):
        with hook_test_env(namespace="claude") as (root, env, dirs):
            session_id = "parent-session"
            original_state = "123\n🌿 parent-title"
            (dirs["debounce"] / session_id).write_text(original_state)
            (dirs["terminal"] / session_id).write_text("term-test-1")

            result = run_hook(
                "session-end-hook.py",
                {
                    "session_id": session_id,
                    "cwd": str(root / "project"),
                    "hook_event_name": "SubagentStop",
                    "shutdown_reason": "other",
                    "agent_type": "general-purpose",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / session_id).read_text(), original_state)
            self.assertEqual((dirs["terminal"] / session_id).read_text(), "term-test-1")


if __name__ == "__main__":
    unittest.main()
