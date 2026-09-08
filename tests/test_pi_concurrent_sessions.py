"""Exercise two Pi processes opening the same persisted conversation."""

import json
import subprocess
import unittest

from helpers import REPO_ROOT, assert_hook_ok, hook_test_env, run_hook


class PiConcurrentSessionTests(unittest.TestCase):
    def process_session_id(self):
        result = subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", """
                import { sessionId } from './pi-extension/event-mapping.ts';
                const ctx = { sessionManager: { getSessionId: () => 'shared-conversation' } };
                console.log(JSON.stringify({ id: sessionId(ctx), pid: String(process.pid) }));
            """],
            cwd=REPO_ROOT, text=True, capture_output=True, timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_quitting_resumed_copy_does_not_disable_original_tab(self):
        first = self.process_session_id()
        second = self.process_session_id()
        with hook_test_env(fake_term_id="term-original") as (root, env, dirs):
            first_env = {**env, "GHOSTTY_PEON_INSTANCE_ID": first["pid"]}
            second_env = {
                **env, "GHOSTTY_PEON_INSTANCE_ID": second["pid"],
                "GHOSTTY_PEON_FAKE_TERM_ID": "term-copy",
            }
            cwd = str(root / "project")
            target_file = "/tmp/2026-09-08_shared-conversation.jsonl"
            for instance, instance_env, source in (
                (first, first_env, "startup"), (second, second_env, "resume"),
            ):
                if source == "resume":
                    # Replay the real trace: a second tab switches from another
                    # conversation into the one still open in the original tab.
                    outgoing = second["pid"] + "-outgoing"
                    (dirs["terminal"] / outgoing).write_text("term-copy")
                    (dirs["debounce"] / outgoing).write_text("456\n🌿 other-work")
                    assert_hook_ok(self, run_hook("session-end-hook.py", {
                        "session_id": outgoing, "cwd": cwd, "shutdown_reason": "resume",
                        "target_session_file": target_file,
                    }, second_env))
                assert_hook_ok(self, run_hook("session-sound-hook.py", {
                    "session_id": instance["id"], "cwd": cwd, "source": source,
                    "session_file": target_file,
                }, instance_env))
                (dirs["debounce"] / instance["id"]).write_text("123\n🌿 test-async-subagent-rendering")

            assert_hook_ok(self, run_hook("session-end-hook.py", {
                "session_id": second["id"], "cwd": cwd, "shutdown_reason": "quit",
            }, second_env))
            assert_hook_ok(self, run_hook("tabtitle-hook.py", {
                "session_id": first["id"], "cwd": cwd, "prompt": "continue",
            }, first_env))

            state = dirs["debounce"] / first["id"]
            self.assertTrue(state.exists(), "Quitting the copy deleted the original tab's title state")
            self.assertEqual(state.read_text(), "123\n🌀 test-async-subagent-rendering")
            self.assertEqual((dirs["terminal"] / first["id"]).read_text(), "term-original")
            self.assertFalse((dirs["terminal"] / second["id"]).exists())


if __name__ == "__main__":
    unittest.main()
