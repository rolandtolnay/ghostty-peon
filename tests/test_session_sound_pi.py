import os
import tempfile
import unittest
from unittest.mock import patch

from helpers import HOOKS_DIR, assert_hook_ok, hook_test_env, read_log, run_hook, seed_workflow_session

import sys
sys.path.insert(0, str(HOOKS_DIR))
import workflow_state


class PiSessionSoundHookTests(unittest.TestCase):
    def test_startup_does_not_steal_existing_terminal_owner(self):
        with hook_test_env(fake_term_id="term-owned") as (root, env, dirs):
            (dirs["terminal"] / "old-session").write_text("term-owned")
            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "new-session",
                    "cwd": str(root / "project"),
                    "source": "startup",
                    "pi_reason": "startup",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["terminal"] / "old-session").read_text(), "term-owned")
            self.assertFalse((dirs["terminal"] / "new-session").exists())
            self.assertIn("subagent detected (terminal owned by old-session)", read_log(root))

    def test_fork_replaces_existing_terminal_owner(self):
        with hook_test_env(fake_term_id="term-owned") as (root, env, dirs):
            (dirs["terminal"] / "old-session").write_text("term-owned")
            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "fork-session",
                    "cwd": str(root / "project"),
                    "source": "fork",
                    "pi_reason": "fork",
                    "session_file": "/tmp/fork-session.jsonl",
                    "previous_session_file": "/tmp/old-session.jsonl",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertFalse((dirs["terminal"] / "old-session").exists())
            self.assertEqual((dirs["terminal"] / "fork-session").read_text(), "term-owned")
            self.assertIn("fork -> replaced terminal owner 'old-session'", read_log(root))

    def test_fork_does_not_replace_peer_runtime_terminal_owner(self):
        with hook_test_env(fake_term_id="term-claude-owned") as (root, env, dirs):
            claude_terminal_dir = root / "claude-terminal"
            claude_terminal_dir.mkdir()
            env["GHOSTTY_PEON_PEER_TERMINAL_ID_DIRS"] = str(claude_terminal_dir)
            (claude_terminal_dir / "claude-session").write_text("term-claude-owned")

            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "fork-session",
                    "cwd": str(root / "project"),
                    "source": "fork",
                    "pi_reason": "fork",
                    "session_file": "/tmp/fork-session.jsonl",
                    "previous_session_file": "/tmp/old-session.jsonl",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((claude_terminal_dir / "claude-session").read_text(), "term-claude-owned")
            self.assertFalse((dirs["terminal"] / "fork-session").exists())
            self.assertFalse((dirs["session_index"] / "fork-session").exists())
            self.assertIn("subagent detected (terminal owned by claude:claude-session)", read_log(root))

    def test_pi_new_replacement_claims_outgoing_terminal_not_focused_tab(self):
        with hook_test_env(fake_term_id="term-focused-other") as (root, env, dirs):
            old_session = "old-session"
            new_session = "new-session"
            seed_workflow_session(
                dirs,
                env,
                session_id=old_session,
                terminal_id="term-outgoing",
                state="plan",
                slug="fix-pi-subagent-trust-error",
            )
            (dirs["terminal"] / "other-session").write_text("term-focused-other")

            end_result = run_hook(
                "session-end-hook.py",
                {
                    "session_id": old_session,
                    "cwd": str(root / "project"),
                    "shutdown_reason": "new",
                    "target_session_file": f"/tmp/{new_session}.jsonl",
                },
                env,
            )
            assert_hook_ok(self, end_result)

            start_result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": new_session,
                    "cwd": str(root / "project"),
                    "source": "new",
                    "pi_reason": "new",
                    "session_file": f"/tmp/{new_session}.jsonl",
                    "previous_session_file": f"/tmp/{old_session}.jsonl",
                },
                env,
            )

            assert_hook_ok(self, start_result)
            self.assertEqual((dirs["terminal"] / new_session).read_text(), "term-outgoing")
            self.assertEqual((dirs["terminal"] / "other-session").read_text(), "term-focused-other")
            self.assertEqual(
                (dirs["debounce"] / new_session).read_text(),
                "0\n🌿 plan-fix-pi-subagent-trust-error",
            )
            with patch.dict(os.environ, env, clear=True):
                self.assertIsNone(workflow_state.resolve_active(session_id=old_session))
                self.assertEqual(workflow_state.resolve_active(session_id=new_session).slug, "fix-pi-subagent-trust-error")
            log = read_log(root)
            self.assertIn("new -> restored replacement terminal_id='term-outgoing'", log)
            self.assertIn("new -> restored replacement title '🌿 plan-fix-pi-subagent-trust-error'", log)
            self.assertIn("new -> workflow binding transferred", log)

    def test_clear_deactivates_workflow_binding(self):
        with hook_test_env(fake_term_id="term-clear") as (root, env, dirs):
            seed_workflow_session(
                dirs,
                env,
                session_id="clear-session",
                terminal_id="term-clear",
                state="review",
                slug="skill-execution",
            )

            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "clear-session",
                    "cwd": str(root / "project"),
                    "source": "clear",
                    "pi_reason": "clear",
                },
                env,
            )

            assert_hook_ok(self, result)
            with patch.dict(os.environ, env, clear=True):
                self.assertIsNone(workflow_state.resolve_active(session_id="clear-session", terminal_id="term-clear"))
            self.assertIn("clear -> deactivated workflow bindings", read_log(root))

    def test_resume_without_handoff_or_title_resets_to_folder(self):
        with hook_test_env(fake_term_id="term-resume") as (root, env, dirs):
            project = root / "resume-project"
            project.mkdir()
            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "resume-session",
                    "cwd": str(project),
                    "source": "resume",
                    "pi_reason": "resume",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["terminal"] / "resume-session").read_text(), "term-resume")
            self.assertIn("resume -> title reset to 'resume-project'", read_log(root))

    def test_compact_restores_existing_title(self):
        with hook_test_env(fake_term_id="term-compact") as (root, env, dirs):
            (dirs["debounce"] / "compact-session").write_text("123\n🌀 existing-title")
            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "compact-session",
                    "cwd": str(root / "project"),
                    "source": "compact",
                    "pi_reason": "compact",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["terminal"] / "compact-session").read_text(), "term-compact")
            self.assertIn("restored existing title '🌀 existing-title'", read_log(root))

    def test_compact_keeps_existing_terminal_when_other_tab_is_focused(self):
        with hook_test_env(fake_term_id="term-focused-other") as (root, env, dirs):
            (dirs["terminal"] / "compact-session").write_text("term-existing")
            (dirs["terminal"] / "other-session").write_text("term-focused-other")
            (dirs["debounce"] / "compact-session").write_text("123\n🌿 review-skill-execution")

            result = run_hook(
                "session-sound-hook.py",
                {
                    "session_id": "compact-session",
                    "cwd": str(root / "project"),
                    "source": "compact",
                    "pi_reason": "compact",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["terminal"] / "compact-session").read_text(), "term-existing")
            self.assertEqual((dirs["terminal"] / "other-session").read_text(), "term-focused-other")
            self.assertIn("restored existing title '🌿 review-skill-execution'", read_log(root))


if __name__ == "__main__":
    unittest.main()
