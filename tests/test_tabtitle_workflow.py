import json
import os
import pathlib
import unittest

from helpers import assert_hook_ok, hook_test_env, read_log, run_hook


def install_fake_llm(root: pathlib.Path, env: dict, *, transition="NONE", slug="canonical-workflow-titles"):
    wrapper = root / "fake-llm"
    calls = root / "llm-calls.log"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import os, sys\n"
        "args = sys.argv[1:]\n"
        "tag = ''\n"
        "for i, arg in enumerate(args):\n"
        "    if arg == '--tag' and i + 1 < len(args):\n"
        "        tag = args[i + 1]\n"
        "with open(os.environ['GHOSTTY_PEON_FAKE_LLM_CALLS'], 'a') as f:\n"
        "    f.write(tag + '\\n')\n"
        "if tag == 'workflow-transition':\n"
        "    print(os.environ.get('GHOSTTY_PEON_FAKE_WORKFLOW_TRANSITION', 'NONE'))\n"
        "else:\n"
        "    print(os.environ.get('GHOSTTY_PEON_FAKE_TABTITLE_SLUG', 'canonical-workflow-titles'))\n"
    )
    wrapper.chmod(0o755)
    env.update(
        {
            "GHOSTTY_PEON_LOCAL_LLM_CLIENT": "",
            "GHOSTTY_PEON_LOCAL_LLM_WRAPPER": str(wrapper),
            "GHOSTTY_PEON_FAKE_LLM_CALLS": str(calls),
            "GHOSTTY_PEON_FAKE_WORKFLOW_TRANSITION": transition,
            "GHOSTTY_PEON_FAKE_TABTITLE_SLUG": slug,
        }
    )
    return calls


def call_tags(calls: pathlib.Path) -> list[str]:
    return calls.read_text().splitlines() if calls.exists() else []


class TabtitleWorkflowHookTests(unittest.TestCase):
    def test_first_prompt_judged_as_check_sets_canonical_title_with_generated_slug(self):
        with hook_test_env() as (root, env, dirs):
            install_fake_llm(root, env, transition="CHECK", slug="canonical-workflow-titles")
            (dirs["terminal"] / "session-check").write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-check",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Can you sanity check MIN-180 before I turn it into a plan?",
                    "selected_skills": [],
                    "branch_name": "feature/branch-should-not-matter",
                },
                env,
            )

            assert_hook_ok(self, result)
            lines = (dirs["debounce"] / "session-check").read_text().splitlines()
            self.assertEqual(lines[1], "🌀 check-canonical-workflow-titles")
            log = read_log(root)
            self.assertIn("workflow -> 🌀 renamed ('check-canonical-workflow-titles')", log)
            self.assertEqual(log.count("skip task.acknowledge: class=none"), 1)

    def test_canonical_followup_without_transition_keeps_title_without_slug_generation(self):
        with hook_test_env() as (root, env, dirs):
            calls = install_fake_llm(root, env, transition="NONE", slug="should-not-be-used")
            (dirs["terminal"] / "session-check").write_text("term-test-1")
            (dirs["debounce"] / "session-check").write_text("123\n🌀 check-canonical-workflow-titles")

            import sys
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "hooks"))
            import workflow_state
            from unittest.mock import patch
            with patch.dict(os.environ, env, clear=True):
                workflow_state.attach(
                    session_id="session-check",
                    terminal_id="term-test-1",
                    state="check",
                    slug="canonical-workflow-titles",
                )

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-check",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "thanks",
                    "selected_skills": [],
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-check").read_text(), "123\n🌀 check-canonical-workflow-titles")
            self.assertIn("workflow -> keep ('check-canonical-workflow-titles')", read_log(root))
            self.assertNotIn("tabtitle", calls.read_text())

    def test_cook_plan_metadata_sets_canonical_cook_title_once_without_slug_generation(self):
        with hook_test_env() as (root, env, dirs):
            calls = install_fake_llm(root, env, transition="NONE", slug="should-not-be-used")
            session_file = root / "session-cook.jsonl"
            plan_path = root / ".pi" / "plans" / "ghostty-peon" / "canonical-pi-workflow-titles.md"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text("# Plan")
            session_file.write_text(
                json.dumps(
                    {
                        "type": "custom",
                        "kind": "cook-plan",
                        "metadata": {
                            "kind": "cook-plan",
                            "sourceKind": "explicit",
                            "sourcePath": str(plan_path),
                            "sourceAbsolutePath": str(plan_path),
                            "sourceSessionFile": str(root / "source-session.jsonl"),
                        },
                    }
                )
                + "\n"
            )
            (dirs["terminal"] / "session-cook").write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-cook",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Implement this plan now in the current repository. The plan content is included below.",
                    "selected_skills": [],
                    "session_file": str(session_file),
                    "transcript_path": str(session_file),
                },
                env,
            )

            assert_hook_ok(self, result)
            lines = (dirs["debounce"] / "session-cook").read_text().splitlines()
            self.assertEqual(lines[1], "🌀 cook-canonical-pi-workflow-titles")
            self.assertEqual(call_tags(calls), [])
            log = read_log(root)
            self.assertIn("workflow -> 🌀 renamed ('cook-canonical-pi-workflow-titles')", log)
            self.assertEqual(log.count("skip task.acknowledge: class=none"), 1)

    def test_uncertain_first_prompt_keeps_ordinary_pi_slug_flow(self):
        with hook_test_env() as (root, env, dirs):
            calls = install_fake_llm(root, env, transition="NONE", slug="ordinary-pi-title")
            (dirs["terminal"] / "session-ordinary").write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-ordinary",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Tell me about a small unrelated terminal customization idea.",
                    "selected_skills": [],
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-ordinary").read_text().splitlines()[1], "🌀 ordinary-pi-title")
            self.assertEqual(call_tags(calls), ["workflow-transition", "tabtitle"])

    def test_ordinary_pi_title_with_workflow_prefix_does_not_enter_canonical_mode(self):
        with hook_test_env() as (root, env, dirs):
            calls = install_fake_llm(root, env, transition="COOK", slug="ordinary-followup-title")
            (dirs["terminal"] / "session-prefix").write_text("term-test-1")
            (dirs["debounce"] / "session-prefix").write_text("123\n🌀 plan-invite-flow")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-prefix",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Implement the current plan details after checking the latest notes.",
                    "selected_skills": [],
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-prefix").read_text().splitlines()[1], "🌀 ordinary-followup-title")
            self.assertEqual(call_tags(calls), ["tabtitle"])
            self.assertNotIn("workflow ->", read_log(root))

    def test_review_skill_envelope_wins_over_loaded_cook_skill_metadata(self):
        with hook_test_env() as (root, env, dirs):
            install_fake_llm(root, env, transition="NONE", slug="review-linear-skill-changes")
            (dirs["terminal"] / "session-review").write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-review",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": '<skill name="review" location="/tmp/review/SKILL.md">Review the branch</skill>',
                    "selected_skills": ["review"],
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-review").read_text().splitlines()[1], "🌀 review-review-linear-skill-changes")
            self.assertIn("workflow -> 🌀 renamed ('review-review-linear-skill-changes')", read_log(root))

    def test_claude_payload_ignores_workflow_skills_and_uses_ordinary_slug_flow(self):
        with hook_test_env(namespace="claude") as (root, env, dirs):
            calls = install_fake_llm(root, env, transition="CHECK", slug="ordinary-claude-title")
            (dirs["terminal"] / "session-claude").write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-claude",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Use the plan skill but this is a Claude runtime payload.",
                    "selected_skills": ["plan"],
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-claude").read_text().splitlines()[1], "🌀 ordinary-claude-title")
            self.assertEqual(call_tags(calls), ["tabtitle"])


if __name__ == "__main__":
    unittest.main()
