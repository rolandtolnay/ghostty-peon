import importlib.util
import io
import json
import unittest
from unittest.mock import Mock, patch

from helpers import REPO_ROOT, hook_test_env


SCRIPT_PATH = REPO_ROOT / "hooks" / "tab-stop-question-hook.py"


def load_hook_module():
    spec = importlib.util.spec_from_file_location("tab_stop_question_hook_under_test", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_main(module, payload):
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with unittest.TestCase().assertRaises(SystemExit) as cm:
            module.main()
    return cm.exception.code


class StopQuestionHookTests(unittest.TestCase):
    def test_llm_yes_sets_question_emoji_for_established_title(self):
        with hook_test_env() as (_root, env, dirs):
            session_id = "session-question"
            (dirs["debounce"] / session_id).write_text("123\n🌀 fix-tabs")

            with patch.dict("os.environ", env, clear=False):
                module = load_hook_module()
                classify = Mock(return_value=(True, "stub yes"))
                set_question = Mock(return_value=True)
                with patch.object(module, "llm_classifies_as_question", classify), patch.object(
                    module, "set_attention_emoji", set_question
                ), patch.object(module, "set_status_emoji", Mock()):
                    code = run_main(
                        module,
                        {
                            "session_id": session_id,
                            "hook_event_name": "Stop",
                            "last_assistant_message": "I can do A or B. Which approach do you prefer?",
                        },
                    )

            self.assertEqual(code, 0)
            classify.assert_called_once()
            set_question.assert_called_once_with(session_id, module.EMOJI_QUESTION, "fix-tabs", "123", "stop-q")

    def test_llm_no_sets_ready_emoji_for_established_title(self):
        with hook_test_env() as (_root, env, dirs):
            session_id = "session-rhetorical"
            (dirs["debounce"] / session_id).write_text("456\n🌀 fix-tabs")

            with patch.dict("os.environ", env, clear=False):
                module = load_hook_module()
                classify = Mock(return_value=(False, "stub no"))
                set_ready = Mock(return_value=True)
                with patch.object(module, "llm_classifies_as_question", classify), patch.object(
                    module, "set_status_emoji", set_ready
                ), patch.object(module, "set_attention_emoji", Mock()):
                    code = run_main(
                        module,
                        {
                            "session_id": session_id,
                            "hook_event_name": "Stop",
                            "last_assistant_message": (
                                "Done. The log includes the phrase 'What happened?' but no action is needed."
                            ),
                        },
                    )

            self.assertEqual(code, 0)
            classify.assert_called_once()
            set_ready.assert_called_once_with(session_id, module.EMOJI_READY, "fix-tabs", "456", "stop-q")

    def test_question_mark_outside_tail_skips_llm_and_sets_ready(self):
        with hook_test_env() as (_root, env, dirs):
            session_id = "session-tail-prefilter"
            (dirs["debounce"] / session_id).write_text("789\n🌀 fix-tabs")
            text = "Which approach should we take?\n" + ("x" * 600)

            with patch.dict("os.environ", env, clear=False):
                module = load_hook_module()
                classify = Mock(return_value=(True, "should not be called"))
                set_ready = Mock(return_value=True)
                with patch.object(module, "llm_classifies_as_question", classify), patch.object(
                    module, "set_status_emoji", set_ready
                ), patch.object(module, "set_attention_emoji", Mock()):
                    code = run_main(
                        module,
                        {
                            "session_id": session_id,
                            "hook_event_name": "Stop",
                            "last_assistant_message": text,
                        },
                    )

            self.assertEqual(code, 0)
            classify.assert_not_called()
            set_ready.assert_called_once_with(session_id, module.EMOJI_READY, "fix-tabs", "789", "stop-q")

    def test_existing_question_emoji_skips_llm_and_title_change(self):
        with hook_test_env() as (_root, env, dirs):
            session_id = "session-already-question"
            (dirs["debounce"] / session_id).write_text("321\n⭐ fix-tabs")

            with patch.dict("os.environ", env, clear=False):
                module = load_hook_module()
                classify = Mock(return_value=(True, "should not be called"))
                set_ready = Mock(return_value=True)
                set_question = Mock(return_value=True)
                with patch.object(module, "llm_classifies_as_question", classify), patch.object(
                    module, "set_status_emoji", set_ready
                ), patch.object(module, "set_attention_emoji", set_question):
                    code = run_main(
                        module,
                        {
                            "session_id": session_id,
                            "hook_event_name": "Stop",
                            "last_assistant_message": "Do you want me to continue?",
                        },
                    )

            self.assertEqual(code, 0)
            classify.assert_not_called()
            set_ready.assert_not_called()
            set_question.assert_not_called()


if __name__ == "__main__":
    unittest.main()
