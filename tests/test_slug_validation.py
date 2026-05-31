import importlib.util
import os
import unittest
from unittest.mock import Mock, patch

from helpers import HOOKS_DIR, REPO_ROOT, hook_test_env


def load_tabtitle_hook():
    path = HOOKS_DIR / "tabtitle-hook.py"
    spec = importlib.util.spec_from_file_location("tabtitle_hook", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_client():
    path = REPO_ROOT / "client.py"
    spec = importlib.util.spec_from_file_location("ghostty_peon_client_under_test", path)
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

    def test_fallback_working_title_is_retryable_not_semantic(self):
        fallback = self.tabtitle.title_state.TitleState("0", "🌀 merchant-app")
        established = self.tabtitle.title_state.TitleState("123", "🌀 fix-tabs")
        self.assertEqual(self.tabtitle.semantic_title_for_llm(fallback), "")
        self.assertEqual(self.tabtitle.semantic_title_for_llm(established), "fix-tabs")
        self.assertEqual(self.tabtitle.fallback_title_for_cwd("/tmp/merchant-app"), "merchant-app")

    def test_timeout_detection_is_specific_to_llm_timeouts(self):
        self.assertTrue(self.tabtitle.is_timeout_error(TimeoutError("timed out")))
        self.assertFalse(self.tabtitle.is_timeout_error(ValueError("bad response")))

    def test_should_skip_does_not_cool_down_fallback_title(self):
        with hook_test_env() as (_root, env, dirs), patch.dict(os.environ, env, clear=False):
            session_id = "session-fallback"
            (dirs["debounce"] / session_id).write_text("0\n🌀 merchant-app")

            skip_reason = self.tabtitle.should_skip(
                session_id,
                "Please diagnose why this active Pi tab lost its generated title.",
            )

            self.assertIsNone(skip_reason)

    def test_fallback_working_title_seeds_visible_retry_state(self):
        with hook_test_env() as (_root, env, dirs), patch.dict(os.environ, env, clear=False):
            session_id = "session-fallback-visible"
            (dirs["terminal"] / session_id).write_text("term-test-1")

            self.assertTrue(self.tabtitle.set_fallback_working_title(session_id, "/tmp/merchant-app"))
            self.assertEqual((dirs["debounce"] / session_id).read_text(), "0\n🌀 merchant-app")

    def test_optional_local_llm_wrapper_uses_high_priority_for_tabtitle(self):
        client = load_client()
        completed = Mock(returncode=0, stdout="generated-slug\n", stderr="")
        with patch.dict(os.environ, {"GHOSTTY_PEON_LOCAL_LLM_WRAPPER": "/tmp/llm"}, clear=False), patch.object(
            client.Path, "exists", return_value=True
        ), patch.object(client.subprocess, "run", return_value=completed) as run:
            result = client.llm(
                "prompt",
                system="system",
                temperature=0,
                max_tokens=5,
                num_ctx=4096,
                tag="tabtitle",
                timeout=10,
            )

        self.assertEqual("generated-slug", result)
        args = run.call_args.args[0]
        self.assertIn("--priority", args)
        self.assertEqual("high", args[args.index("--priority") + 1])
        self.assertEqual("4096", args[args.index("--num-ctx") + 1])
        self.assertEqual("tabtitle", args[args.index("--tag") + 1])

    def test_optional_local_llm_wrapper_failure_falls_back_to_bundled_client(self):
        client = load_client()
        with patch.dict(os.environ, {"GHOSTTY_PEON_LOCAL_LLM_WRAPPER": "/tmp/llm"}, clear=False), patch.object(
            client.Path, "exists", return_value=True
        ), patch.object(client.subprocess, "run", side_effect=FileNotFoundError("missing")), patch.object(
            client, "_direct_ollama_chat", return_value={"message": {"content": "fallback-slug"}}
        ) as direct:
            result = client.llm("prompt", tag="tabtitle", timeout=10)

        self.assertEqual("fallback-slug", result)
        direct.assert_called_once()


if __name__ == "__main__":
    unittest.main()
