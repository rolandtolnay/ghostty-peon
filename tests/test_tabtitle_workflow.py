import json
import os
import pathlib
import subprocess
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
        "prompt_log = os.environ.get('GHOSTTY_PEON_FAKE_LLM_PROMPTS')\n"
        "if prompt_log:\n"
        "    import json\n"
        "    with open(prompt_log, 'a') as f:\n"
        "        f.write(json.dumps({'tag': tag, 'prompt': args[-1] if args else ''}) + '\\n')\n"
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
                workflow_state.create_workstream(
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
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-check").read_text(), "123\n🌀 check-canonical-workflow-titles")
            self.assertIn("workflow -> keep ('check-canonical-workflow-titles')", read_log(root))
            self.assertNotIn("tabtitle", calls.read_text())

    def test_backward_explicit_skill_signal_starts_new_active_workstream(self):
        with hook_test_env() as (root, env, dirs):
            install_fake_llm(root, env, transition="NONE", slug="new-product-brief")
            (dirs["terminal"] / "session-plan").write_text("term-test-1")
            (dirs["debounce"] / "session-plan").write_text("123\n🌀 plan-old-plan")

            import sys
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "hooks"))
            import workflow_state
            from unittest.mock import patch
            with patch.dict(os.environ, env, clear=True):
                original = workflow_state.create_workstream(
                    session_id="session-plan",
                    terminal_id="term-test-1",
                    state="plan",
                    slug="old-plan",
                )

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-plan",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": '<skill name="prep" location="/tmp/prep-skill">Prepare a new product brief</skill>',
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-plan").read_text().splitlines()[1], "🌀 prep-new-product-brief")
            with patch.dict(os.environ, env, clear=True):
                active = workflow_state.resolve_active(session_id="session-plan")
                self.assertEqual(active.slug, "new-product-brief")
                self.assertNotEqual(active.id, original.id)
            self.assertIn("workflow -> 🌀 renamed ('prep-new-product-brief')", read_log(root))

    def test_plan_quick_slug_uses_user_request_instead_of_skill_body(self):
        with hook_test_env() as (root, env, dirs):
            prompt_log = root / "llm-prompts.jsonl"
            install_fake_llm(root, env, transition="NONE", slug="ask-questions-shared-understanding")
            env["GHOSTTY_PEON_FAKE_LLM_PROMPTS"] = str(prompt_log)
            (dirs["terminal"] / "session-plan-quick").write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-plan-quick",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": (
                        '<skill name="plan-quick" location="/tmp/plan-quick/SKILL.md">\n'
                        "References are relative to /Users/example/.pi/agent\n\n"
                        "<user-request>\n"
                        "Ask me questions one by one until you are confident we have reached a shared understanding on what to build.\n"
                        "</user-request>\n\n"
                        "<skill-instructions>\n"
                        "Quick-validate conversation-agreed changes against the codebase.\n"
                        "Mention plan-quick many times in the skill body.\n"
                        "</skill-instructions>\n"
                        "</skill>"
                    ),
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-plan-quick").read_text().splitlines()[1], "🌀 plan-ask-questions-shared-understanding")
            self.assertEqual(
                (dirs["debounce"] / "session-plan-quick.origin").read_text(),
                "Ask me questions one by one until you are confident we have reached a shared understanding on what to build.",
            )
            records = [json.loads(line) for line in prompt_log.read_text().splitlines()]
            tabtitle_prompt = next(record["prompt"] for record in records if record["tag"] == "tabtitle")
            self.assertIn(
                "<current_message>Ask me questions one by one until you are confident we have reached a shared understanding on what to build.</current_message>",
                tabtitle_prompt,
            )
            self.assertNotIn("<skill", tabtitle_prompt)
            self.assertNotIn("plan-quick", tabtitle_prompt)
            self.assertNotIn("Quick-validate", tabtitle_prompt)

    def test_skill_recent_messages_use_user_requests_instead_of_skill_bodies(self):
        with hook_test_env() as (root, env, dirs):
            prompt_log = root / "llm-prompts.jsonl"
            install_fake_llm(root, env, transition="NONE", slug="source-footprint-plan")
            env["GHOSTTY_PEON_FAKE_LLM_PROMPTS"] = str(prompt_log)
            session_file = root / "session-plan-quick.jsonl"
            previous_prompt = (
                '<skill name="diagnose" location="/tmp/diagnose/SKILL.md">\n'
                "<user-request>Diagnose why the source-based session footprint plan is unclear.</user-request>\n"
                "<skill-instructions>Verbose diagnose instructions that should not reach tabtitle.</skill-instructions>\n"
                "</skill>"
            )
            current_prompt = (
                '<skill name="plan-quick" location="/tmp/plan-quick/SKILL.md">\n'
                "<user-request>Turn that diagnosis into an implementation plan.</user-request>\n"
                "<skill-instructions>Verbose plan-quick instructions that should not reach tabtitle.</skill-instructions>\n"
                "</skill>"
            )
            session_file.write_text(
                json.dumps({"message": {"role": "user", "content": previous_prompt}})
                + "\n"
                + json.dumps({"message": {"role": "user", "content": current_prompt}})
                + "\n"
            )
            (dirs["terminal"] / "session-plan-quick-recent").write_text("term-test-1")
            (dirs["debounce"] / "session-plan-quick-recent").write_text("0\n")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-plan-quick-recent",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": current_prompt,
                    "transcript_path": str(session_file),
                    "session_file": str(session_file),
                },
                env,
            )

            assert_hook_ok(self, result)
            records = [json.loads(line) for line in prompt_log.read_text().splitlines()]
            tabtitle_prompt = next(record["prompt"] for record in records if record["tag"] == "tabtitle")
            self.assertIn(
                "<recent_message>Diagnose why the source-based session footprint plan is unclear.</recent_message>",
                tabtitle_prompt,
            )
            self.assertIn(
                "<current_message>Turn that diagnosis into an implementation plan.</current_message>",
                tabtitle_prompt,
            )
            self.assertNotIn("Verbose diagnose instructions", tabtitle_prompt)
            self.assertNotIn("Verbose plan-quick instructions", tabtitle_prompt)

    def test_workflow_transition_normalizes_existing_skill_origin(self):
        with hook_test_env() as (root, env, dirs):
            prompt_log = root / "llm-prompts.jsonl"
            install_fake_llm(root, env, transition="COOK", slug="should-not-be-used")
            env["GHOSTTY_PEON_FAKE_LLM_PROMPTS"] = str(prompt_log)
            (dirs["terminal"] / "session-plan-origin").write_text("term-test-1")
            (dirs["debounce"] / "session-plan-origin").write_text("123\n🌀 plan-billing-retry-rules")
            (dirs["debounce"] / "session-plan-origin.origin").write_text(
                '<skill name="plan-quick" location="/tmp/plan-quick/SKILL.md">\n'
                "<user-request>Plan billing retry rules.</user-request>\n"
                "<skill-instructions>Verbose plan-quick instructions that should not reach transition judgment.</skill-instructions>\n"
                "</skill>"
            )

            import sys
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "hooks"))
            import workflow_state
            from unittest.mock import patch
            with patch.dict(os.environ, env, clear=True):
                workflow_state.create_workstream(
                    session_id="session-plan-origin",
                    terminal_id="term-test-1",
                    state="plan",
                    slug="billing-retry-rules",
                )

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-plan-origin",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": "Looks good, implement it.",
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-plan-origin").read_text().splitlines()[1], "🌀 cook-billing-retry-rules")
            records = [json.loads(line) for line in prompt_log.read_text().splitlines()]
            transition_prompt = next(record["prompt"] for record in records if record["tag"] == "workflow-transition")
            self.assertIn("<title_origin>Plan billing retry rules.</title_origin>", transition_prompt)
            self.assertNotIn("Verbose plan-quick instructions", transition_prompt)
            self.assertNotIn("<skill", transition_prompt)

    def test_plan_quick_from_active_check_ignores_stale_transcript_artifact(self):
        with hook_test_env() as (root, env, dirs):
            calls = install_fake_llm(root, env, transition="NONE", slug="should-not-be-used")
            session_file = root / "session-check-to-plan.jsonl"
            session_file.write_text(
                json.dumps(
                    {
                        "type": "tool_result",
                        "content": [
                            {
                                "type": "text",
                                "text": "Unrelated code fixture mentions `etc/prd/source-based-session-footprint.md`.",
                            }
                        ],
                    }
                )
                + "\n"
            )
            (dirs["terminal"] / "session-check-to-plan").write_text("term-test-1")
            (dirs["debounce"] / "session-check-to-plan").write_text("123\n🌿 check-investigate-question-tool-forwarding")

            import sys
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "hooks"))
            import workflow_state
            from unittest.mock import patch
            with patch.dict(os.environ, env, clear=True):
                active = workflow_state.create_workstream(
                    session_id="session-check-to-plan",
                    terminal_id="term-test-1",
                    state="check",
                    slug="investigate-question-tool-forwarding",
                )
                stale = workflow_state.create_workstream(
                    state="plan",
                    slug="source-based-session-footprint",
                    artifacts=("etc/prd/source-based-session-footprint.md",),
                )

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-check-to-plan",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": (
                        '<skill name="plan-quick" location="/tmp/plan-quick/SKILL.md">\n'
                        "<user-request>Turn that sanity check into an implementation plan.</user-request>\n"
                        "<skill-instructions>Validate agreed changes against the codebase.</skill-instructions>\n"
                        "</skill>"
                    ),
                    "transcript_path": str(session_file),
                    "session_file": str(session_file),
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual(
                (dirs["debounce"] / "session-check-to-plan").read_text().splitlines()[1],
                "🌀 plan-investigate-question-tool-forwarding",
            )
            self.assertEqual(call_tags(calls), [])
            with patch.dict(os.environ, env, clear=True):
                resolved = workflow_state.resolve_active(session_id="session-check-to-plan")
                self.assertEqual(resolved.id, active.id)
                self.assertEqual(resolved.slug, "investigate-question-tool-forwarding")
                self.assertEqual(workflow_state.resolve_by_artifact(("etc/prd/source-based-session-footprint.md",)).id, stale.id)
            self.assertIn("workflow -> 🌀 renamed ('plan-investigate-question-tool-forwarding')", read_log(root))

    def test_plan_skill_uses_recent_transcript_prd_over_placeholder_templates(self):
        with hook_test_env() as (root, env, dirs):
            calls = install_fake_llm(root, env, transition="NONE", slug="should-not-be-used")
            session_file = root / "session-plan.jsonl"
            session_file.write_text(
                json.dumps(
                    {
                        "type": "message",
                        "message": {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "PRD created:\n\n`etc/prd/source-based-session-footprint.md`",
                                }
                            ],
                        },
                    }
                )
                + "\n"
            )
            (dirs["terminal"] / "session-plan-prd").write_text("term-test-1")
            (dirs["debounce"] / "session-plan-prd").write_text("123\n🌀 prep-sanity-check-min-201")

            import sys
            sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "hooks"))
            import workflow_state
            from unittest.mock import patch
            with patch.dict(os.environ, env, clear=True):
                workflow_state.create_workstream(
                    session_id="session-plan-prd",
                    terminal_id="term-test-1",
                    state="prep",
                    slug="sanity-check-min-201",
                )

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-plan-prd",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": (
                        '<skill name="plan" location="/tmp/plan/SKILL.md">\n'
                        '## Context\n'
                        '> **Read first:** `etc/prd/<slug>.md` contains requirements.\n'
                        'Plans are saved to `~/.pi/plans/<project-folder>/<slug>.md`.\n'
                        '</skill>'
                    ),
                    "transcript_path": str(session_file),
                    "session_file": str(session_file),
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-plan-prd").read_text().splitlines()[1], "🌀 plan-source-based-session-footprint")
            self.assertEqual(call_tags(calls), [])
            self.assertIn("workflow -> 🌀 renamed ('plan-source-based-session-footprint')", read_log(root))

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
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-ordinary").read_text().splitlines()[1], "🌀 ordinary-pi-title")
            self.assertEqual(call_tags(calls), ["workflow-transition", "tabtitle"])

    def test_explicit_workflow_signal_without_slug_does_not_fall_through_to_ordinary_title(self):
        with hook_test_env() as (root, env, dirs):
            calls = install_fake_llm(root, env, transition="NONE", slug="")
            (dirs["terminal"] / "session-plan-noslug").write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-plan-noslug",
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": '<skill name="plan" location="/tmp/skill-plan">Plan this work</skill>',
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertFalse((dirs["debounce"] / "session-plan-noslug").exists())
            self.assertEqual(call_tags(calls), ["tabtitle"])
            self.assertIn("workflow -> handled without title", read_log(root))

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
                    "selected_skills": ["cook"],
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-review").read_text().splitlines()[1], "🌀 review-review-linear-skill-changes")
            self.assertIn("workflow -> 🌀 renamed ('review-review-linear-skill-changes')", read_log(root))

    def test_cook_skill_uses_python_branch_fallback_without_payload_branch_name(self):
        with hook_test_env() as (root, env, dirs):
            project = root / "project"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subprocess.run(["git", "checkout", "-q", "-b", "feature/canonical-workflow-titles"], cwd=project, check=True)
            calls = install_fake_llm(root, env, transition="NONE", slug="should-not-be-used")
            (dirs["terminal"] / "session-cook-branch").write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": "session-cook-branch",
                    "cwd": str(project),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": '<skill name="cook" location="/tmp/cook/SKILL.md">Implement the branch</skill>',
                },
                env,
            )

            assert_hook_ok(self, result)
            self.assertEqual((dirs["debounce"] / "session-cook-branch").read_text().splitlines()[1], "🌀 cook-canonical-workflow-titles")
            self.assertEqual(call_tags(calls), [])

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
