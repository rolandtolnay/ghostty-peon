import sys
import unittest

from helpers import HOOKS_DIR

sys.path.insert(0, str(HOOKS_DIR))
import lifecycle_policy


class LifecyclePolicyTests(unittest.TestCase):
    def test_pi_replacement_starts_may_replace_terminal_owner(self):
        for source in ("new", "fork", "resume", "compact"):
            self.assertTrue(lifecycle_policy.start_replaces_terminal_owner("pi", source))
        self.assertFalse(lifecycle_policy.start_replaces_terminal_owner("pi", "startup"))
        self.assertFalse(lifecycle_policy.start_replaces_terminal_owner("claude", "fork"))

    def test_pi_replacement_shutdowns_keep_title_state_and_skip_reset(self):
        for reason in ("fork", "resume", "new"):
            self.assertTrue(lifecycle_policy.is_replacement_shutdown("pi", reason))
            self.assertTrue(lifecycle_policy.should_keep_title_state_on_end("pi", reason))
            self.assertFalse(lifecycle_policy.should_reset_title_on_end("pi", reason, plan_accepted=False))

        self.assertFalse(lifecycle_policy.is_replacement_shutdown("pi", "quit"))
        self.assertFalse(lifecycle_policy.should_keep_title_state_on_end("pi", "quit"))
        self.assertTrue(lifecycle_policy.should_reset_title_on_end("pi", "quit", plan_accepted=False))

    def test_plan_pending_skips_reset_and_is_detected_from_existing_format(self):
        self.assertTrue(lifecycle_policy.is_plan_pending(["123", "🔥 fix-tabs", "planpending"]))
        self.assertFalse(lifecycle_policy.is_plan_pending(["123", "🔥 fix-tabs"]))
        self.assertFalse(lifecycle_policy.should_reset_title_on_end("claude", "logout", plan_accepted=True))

    def test_only_pi_fork_with_title_and_terminal_writes_fork_handoff(self):
        self.assertTrue(lifecycle_policy.should_write_fork_handoff("pi", "fork", False, True, True))
        self.assertFalse(lifecycle_policy.should_write_fork_handoff("pi", "resume", False, True, True))
        self.assertFalse(lifecycle_policy.should_write_fork_handoff("pi", "fork", True, True, True))
        self.assertFalse(lifecycle_policy.should_write_fork_handoff("pi", "fork", False, False, True))
        self.assertFalse(lifecycle_policy.should_write_fork_handoff("pi", "fork", False, True, False))
        self.assertFalse(lifecycle_policy.should_write_fork_handoff("claude", "fork", False, True, True))


if __name__ == "__main__":
    unittest.main()
