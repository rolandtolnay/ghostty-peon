import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from helpers import HOOKS_DIR, hook_test_env

sys.path.insert(0, str(HOOKS_DIR))
import ghostty_tab


class GhosttyTabTests(unittest.TestCase):
    def test_terminal_ownership_is_terminal_scoped(self):
        with hook_test_env() as (_root, env, dirs):
            with patch.dict(os.environ, env, clear=True):
                (dirs["terminal"] / "owner-session").write_text("term-1")
                (dirs["terminal"] / "other-session").write_text("term-2")

                self.assertEqual(ghostty_tab.is_terminal_owned("term-1", "new-session"), "owner-session")
                self.assertIsNone(ghostty_tab.is_terminal_owned("term-1", "owner-session"))
                self.assertEqual(ghostty_tab.clear_terminal_owner("term-1", "new-session"), "owner-session")
                self.assertFalse((dirs["terminal"] / "owner-session").exists())
                self.assertTrue((dirs["terminal"] / "other-session").exists())

    def test_set_tab_title_refuses_session_without_captured_terminal(self):
        with hook_test_env() as (_root, env, _dirs):
            logs = []
            with patch.dict(os.environ, env, clear=True), patch("ghostty_tab.subprocess.run") as run:
                result = ghostty_tab.set_tab_title("fix-tabs", "missing-session", log_fn=lambda *args: logs.append(args))

                self.assertFalse(result)
                run.assert_not_called()
                self.assertIn(
                    ("missing-session", "tabtitle", "target: SKIPPED (no term_id, refusing unsafe fallback)"),
                    logs,
                )

    def test_set_tab_title_targets_captured_terminal(self):
        with hook_test_env() as (_root, env, dirs):
            with patch.dict(os.environ, env, clear=True), patch("ghostty_tab.subprocess.run") as run:
                (dirs["terminal"] / "session-1").write_text("term-42")
                run.return_value = SimpleNamespace(returncode=0, stderr=b"")

                self.assertTrue(ghostty_tab.set_tab_title("fix-tabs", "session-1"))

                args = run.call_args.args[0]
                self.assertEqual(args[:2], ["osascript", "-e"])
                self.assertIn('first terminal whose id is "term-42"', args[2])
                self.assertIn('set_tab_title:fix-tabs', args[2])

    def test_set_tab_title_releases_stale_terminal_id_on_ghostty_not_found(self):
        with hook_test_env() as (_root, env, dirs):
            logs = []
            with patch.dict(os.environ, env, clear=True), patch("ghostty_tab.subprocess.run") as run:
                (dirs["terminal"] / "session-1").write_text("term-42")
                run.return_value = SimpleNamespace(
                    returncode=1,
                    stderr='25:159: execution error: Ghostty got an error: Can’t get terminal 1 whose id = "term-42". (-1728)',
                )

                self.assertFalse(ghostty_tab.set_tab_title("fix-tabs", "session-1", log_fn=lambda *args: logs.append(args)))

                self.assertFalse((dirs["terminal"] / "session-1").exists())
                self.assertIn(("session-1", "tabtitle", "stale terminal id released: 'term-42'"), logs)

    def test_set_tab_title_keeps_terminal_id_on_generic_osascript_failure(self):
        with hook_test_env() as (_root, env, dirs):
            with patch.dict(os.environ, env, clear=True), patch("ghostty_tab.subprocess.run") as run:
                (dirs["terminal"] / "session-1").write_text("term-42")
                run.return_value = SimpleNamespace(returncode=1, stderr="permission denied")

                self.assertFalse(ghostty_tab.set_tab_title("fix-tabs", "session-1"))

                self.assertEqual((dirs["terminal"] / "session-1").read_text(), "term-42")


if __name__ == "__main__":
    unittest.main()
