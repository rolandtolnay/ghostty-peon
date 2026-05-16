import hashlib
import json
import tempfile
import unittest

from helpers import assert_hook_ok, hook_test_env, read_log, run_hook


class PiSessionEndHookTests(unittest.TestCase):
    def seed_session(self, dirs, session_id="session-new", term_id="term-test-1"):
        (dirs["debounce"] / session_id).write_text("123\n⭐ fix-bug\n")
        (dirs["debounce"] / f"{session_id}.origin").write_text("original prompt")
        (dirs["terminal"] / session_id).write_text(term_id)

    def test_pi_fork_preserves_debounce_releases_terminal_and_writes_handoff(self):
        session_id = "session-fork"
        term_id = "term-fork-1"
        with hook_test_env(fake_term_id=term_id) as (root, env, dirs):
            self.seed_session(dirs, session_id=session_id, term_id=term_id)
            with tempfile.TemporaryDirectory() as cwd:
                result = run_hook(
                    "session-end-hook.py",
                    {
                        "session_id": session_id,
                        "cwd": cwd,
                        "shutdown_reason": "fork",
                    },
                    env,
                )

            assert_hook_ok(self, result)
            self.assertTrue((dirs["debounce"] / session_id).exists())
            self.assertTrue((dirs["debounce"] / f"{session_id}.origin").exists())
            self.assertFalse((dirs["terminal"] / session_id).exists())

            handoff_key = hashlib.sha256(term_id.encode("utf-8")).hexdigest()[:24]
            handoff = json.loads((dirs["handoff"] / handoff_key).read_text())
            self.assertEqual(handoff["title"], "🌀 fix-bug")

            log = read_log(root)
            self.assertIn("end -> fork handoff written", log)
            self.assertIn("end -> kept debounce state for Pi replacement", log)
            self.assertIn("end -> unit + terminal_id released", log)

    def test_pi_quit_cleans_debounce_and_releases_terminal(self):
        session_id = "session-quit"
        term_id = "term-quit-1"
        with hook_test_env(fake_term_id=term_id) as (root, env, dirs):
            self.seed_session(dirs, session_id=session_id, term_id=term_id)
            with tempfile.TemporaryDirectory(prefix="ghostty-peon-project-") as cwd:
                result = run_hook(
                    "session-end-hook.py",
                    {
                        "session_id": session_id,
                        "cwd": cwd,
                        "shutdown_reason": "quit",
                    },
                    env,
                )

            assert_hook_ok(self, result)
            self.assertFalse((dirs["debounce"] / session_id).exists())
            self.assertFalse((dirs["debounce"] / f"{session_id}.origin").exists())
            self.assertFalse((dirs["terminal"] / session_id).exists())
            self.assertEqual(list(dirs["handoff"].iterdir()), [])

            log = read_log(root)
            self.assertIn("end -> title reset to", log)
            self.assertIn("end -> cleaned debounce state for Pi", log)
            self.assertIn("end -> unit + terminal_id released", log)


if __name__ == "__main__":
    unittest.main()
