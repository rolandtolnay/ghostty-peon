import hashlib
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

from helpers import HOOKS_DIR, hook_test_env

sys.path.insert(0, str(HOOKS_DIR))
import title_handoff


class TitleHandoffTests(unittest.TestCase):
    def test_write_preserves_terminal_hash_path_and_json_shape(self):
        with hook_test_env() as (_root, env, dirs):
            with patch.dict(os.environ, env, clear=True):
                self.assertTrue(title_handoff.write("term-1", "🌀 fix-tabs"))

                key = hashlib.sha256("term-1".encode("utf-8")).hexdigest()[:24]
                handoff_path = dirs["handoff"] / key
                data = json.loads(handoff_path.read_text())
                self.assertEqual(data["title"], "🌀 fix-tabs")
                self.assertIsInstance(data["timestamp"], float)

    def test_consume_returns_fresh_stripped_title_and_deletes_file(self):
        with hook_test_env() as (_root, env, dirs):
            with patch.dict(os.environ, env, clear=True):
                key = hashlib.sha256("term-1".encode("utf-8")).hexdigest()[:24]
                handoff_path = dirs["handoff"] / key
                handoff_path.write_text(json.dumps({"timestamp": time.time(), "title": "  🌀 fix-tabs  "}))

                self.assertEqual(title_handoff.consume("term-1"), "🌀 fix-tabs")
                self.assertFalse(handoff_path.exists())

    def test_consume_deletes_and_rejects_stale_or_invalid_handoff(self):
        with hook_test_env() as (_root, env, dirs):
            with patch.dict(os.environ, env, clear=True):
                key = hashlib.sha256("term-1".encode("utf-8")).hexdigest()[:24]
                handoff_path = dirs["handoff"] / key
                handoff_path.write_text(json.dumps({"timestamp": time.time() - 999, "title": "🌀 stale"}))

                self.assertIsNone(title_handoff.consume("term-1", ttl_seconds=1))
                self.assertFalse(handoff_path.exists())


if __name__ == "__main__":
    unittest.main()
