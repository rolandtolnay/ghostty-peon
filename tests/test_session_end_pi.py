import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from helpers import HOOKS_DIR, assert_hook_ok, hook_test_env, read_log, run_hook

import sys
sys.path.insert(0, str(HOOKS_DIR))
import workflow_state


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

    def test_pi_new_preserves_ready_status_in_replacement_handoff(self):
        session_id = "session-new"
        target_session = "new-session"
        term_id = "term-new-1"
        with hook_test_env(fake_term_id=term_id) as (root, env, dirs):
            (dirs["debounce"] / session_id).write_text("123\n🌿 investigate-filesystem-footer\n")
            (dirs["debounce"] / f"{session_id}.origin").write_text("original prompt")
            (dirs["terminal"] / session_id).write_text(term_id)
            with tempfile.TemporaryDirectory() as cwd:
                result = run_hook(
                    "session-end-hook.py",
                    {
                        "session_id": session_id,
                        "cwd": cwd,
                        "shutdown_reason": "new",
                        "target_session_file": f"/tmp/{target_session}.jsonl",
                    },
                    env,
                )

            assert_hook_ok(self, result)
            self.assertTrue((dirs["debounce"] / session_id).exists())
            self.assertTrue((dirs["debounce"] / f"{session_id}.origin").exists())
            self.assertFalse((dirs["terminal"] / session_id).exists())

            handoff_key = hashlib.sha256(target_session.encode("utf-8")).hexdigest()[:24]
            handoff = json.loads((dirs["handoff"] / f"replacement-{handoff_key}").read_text())
            self.assertEqual(handoff["terminal_id"], term_id)
            self.assertEqual(handoff["title"], "🌿 investigate-filesystem-footer")

            log = read_log(root)
            self.assertIn("end -> replacement handoff written for Pi new", log)
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

    def test_pi_quit_deactivates_workflow_bindings_but_preserves_artifact_attachment(self):
        session_id = "session-workflow-quit"
        term_id = "term-workflow-quit"
        artifact = "/repo/etc/prd/canonical-pi-workflow-titles.md"
        with hook_test_env(fake_term_id=term_id) as (_root, env, dirs):
            self.seed_session(dirs, session_id=session_id, term_id=term_id)
            with patch.dict(os.environ, env, clear=True):
                original = workflow_state.create_workstream(
                    session_id=session_id,
                    terminal_id=term_id,
                    state="plan",
                    slug="canonical-pi-workflow-titles",
                    artifacts=(artifact,),
                )
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
            with patch.dict(os.environ, env, clear=True):
                self.assertIsNone(workflow_state.resolve_active(session_id=session_id))
                self.assertIsNone(workflow_state.resolve_active(terminal_id=term_id))
                self.assertEqual(workflow_state.resolve_by_artifact((artifact,)).id, original.id)


if __name__ == "__main__":
    unittest.main()
