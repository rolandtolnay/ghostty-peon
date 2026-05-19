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
            "current-path",
            "fix auth token",
            "a" * 61,
        ]
        for slug in invalid:
            with self.subTest(slug=slug):
                self.assertFalse(self.tabtitle.is_valid_slug(slug))

    def test_image_count_from_payload_uses_count_without_image_data(self):
        self.assertEqual(self.tabtitle.image_count_from_payload({"image_count": 2}), 2)
        self.assertEqual(self.tabtitle.image_count_from_payload({"image_count": "1"}), 1)
        self.assertEqual(self.tabtitle.image_count_from_payload({"images": [{"data": "..."}]}), 1)

    def test_image_prompt_context_mentions_attachments_without_bytes(self):
        message = self.tabtitle.build_llm_user_message(
            "Can you look into this bug with the question tool?",
            "",
            image_count=1,
        )

        self.assertIn("<attachments>1 image attached", message)
        self.assertIn(
            "<current_message>Can you look into this bug with the question tool?</current_message>",
            message,
        )
        self.assertNotIn("data", message)

    def test_image_prompt_fallback_uses_text_topic(self):
        slug = self.tabtitle.fallback_slug_for_image_prompt(
            "I attached a screenshot. Please look into a bug with the question tool."
        )

        self.assertEqual(slug, "debug-question-tool")


if __name__ == "__main__":
    unittest.main()
