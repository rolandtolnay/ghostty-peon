import tempfile
import unittest

from helpers import assert_hook_ok, hook_test_env, read_log, run_hook


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

    def test_pi_new_replacement_claims_outgoing_terminal_not_focused_tab(self):
        with hook_test_env(fake_term_id="term-focused-other") as (root, env, dirs):
            old_session = "old-session"
            new_session = "new-session"
            (dirs["terminal"] / old_session).write_text("term-outgoing")
            (dirs["terminal"] / "other-session").write_text("term-focused-other")
            (dirs["debounce"] / old_session).write_text("123\n🌿 fix-pi-subagent-trust-error\n")

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
                "0\n🌿 fix-pi-subagent-trust-error",
            )
            log = read_log(root)
            self.assertIn("new -> restored replacement terminal_id='term-outgoing'", log)
            self.assertIn("new -> restored replacement title '🌿 fix-pi-subagent-trust-error'", log)

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


if __name__ == "__main__":
    unittest.main()
