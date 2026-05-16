import importlib.util
import unittest

from helpers import HOOKS_DIR


def load_tabtitle_hook():
    path = HOOKS_DIR / "tabtitle-hook.py"
    spec = importlib.util.spec_from_file_location("tabtitle_hook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SlugValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tabtitle = load_tabtitle_hook()

    def test_allows_legitimate_error_topic_slugs(self):
        self.assertTrue(self.tabtitle.is_valid_slug("investigate-update-tool-error"))
        self.assertTrue(self.tabtitle.is_valid_slug("fix-auth-token"))

    def test_rejects_wrapper_and_failure_outputs(self):
        invalid = [
            "error",
            "error-timeout",
            "debug-error",
            "max-turns-reached",
            "truncated",
            "fix auth token",
            "a" * 61,
        ]
        for slug in invalid:
            with self.subTest(slug=slug):
                self.assertFalse(self.tabtitle.is_valid_slug(slug))


if __name__ == "__main__":
    unittest.main()
