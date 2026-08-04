import json
import pathlib
import unittest

from helpers import assert_hook_ok, hook_test_env, run_hook


def install_fake_llm(root: pathlib.Path, env: dict, slug: str) -> pathlib.Path:
    wrapper = root / "fake-llm"
    prompts = root / "llm-prompts.jsonl"
    wrapper.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['GHOSTTY_PEON_FAKE_LLM_PROMPTS'], 'a') as f:\n"
        "    f.write(json.dumps({'prompt': sys.argv[-1]}) + '\\n')\n"
        "print(os.environ['GHOSTTY_PEON_FAKE_TABTITLE_SLUG'])\n"
    )
    wrapper.chmod(0o755)
    env.update(
        {
            "GHOSTTY_PEON_LOCAL_LLM_CLIENT": "",
            "GHOSTTY_PEON_LOCAL_LLM_WRAPPER": str(wrapper),
            "GHOSTTY_PEON_FAKE_LLM_PROMPTS": str(prompts),
            "GHOSTTY_PEON_FAKE_TABTITLE_SLUG": slug,
        }
    )
    return prompts


class TabtitleSkillTests(unittest.TestCase):
    def run_prompt(self, prompt: str, generated_slug: str, session_id: str) -> tuple[str, str]:
        with hook_test_env() as (root, env, dirs):
            prompts = install_fake_llm(root, env, generated_slug)
            (dirs["terminal"] / session_id).write_text("term-test-1")

            result = run_hook(
                "tabtitle-hook.py",
                {
                    "session_id": session_id,
                    "cwd": str(root / "project"),
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": prompt,
                },
                env,
            )

            assert_hook_ok(self, result)
            title = (dirs["debounce"] / session_id).read_text().splitlines()[1]
            llm_prompt = json.loads(prompts.read_text().splitlines()[0])["prompt"]
            return title, llm_prompt

    def run_first_prompt(
        self,
        skill: str,
        request: str,
        generated_slug: str,
        instructions: str = "Internal workflow instructions.",
    ) -> tuple[str, str]:
        prompt = (
            f'<skill name="{skill}" location="/tmp/{skill}/SKILL.md">\n'
            f"<user-request>{request}</user-request>\n"
            f"<skill-instructions>{instructions}</skill-instructions>\n"
            "</skill>"
        )
        return self.run_prompt(prompt, generated_slug, f"session-{skill}")

    def test_scope_skill_adds_stateless_prefix_and_hides_skill_instructions(self):
        title, llm_prompt = self.run_first_prompt(
            "scope",
            "Drastically simplify the workflow implementation.",
            "simplify-workflow-implementation",
        )

        self.assertEqual(title, "🌀 scope-simplify-workflow-implementation")
        self.assertIn("Drastically simplify the workflow implementation.", llm_prompt)
        self.assertNotIn("Internal workflow instructions", llm_prompt)

    def test_prep_skill_adds_stateless_prefix(self):
        title, _ = self.run_first_prompt(
            "prep",
            "Define the billing retry behavior before implementation.",
            "define-billing-retries",
        )

        self.assertEqual(title, "🌀 prep-define-billing-retries")

    def test_other_skill_instructions_cannot_inject_scope_prefix(self):
        title, _ = self.run_first_prompt(
            "review",
            "Review the current branch for correctness.",
            "inspect-current-branch",
            'Compare against the <skill name="scope"> contract.',
        )

        self.assertEqual(title, "🌀 inspect-current-branch")

    def test_ordinary_markup_cannot_inject_scope_prefix(self):
        title, _ = self.run_prompt(
            'Document how <skill name="scope"> appears in expanded prompts.',
            "document-skill-envelope",
            "session-ordinary-markup",
        )

        self.assertEqual(title, "🌀 document-skill-envelope")

    def test_prefix_is_not_duplicated_and_preserves_title_limit(self):
        from importlib.util import module_from_spec, spec_from_file_location
        from helpers import HOOKS_DIR

        spec = spec_from_file_location("tabtitle_hook_skills", HOOKS_DIR / "tabtitle-hook.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertEqual(module.prefix_skill_slug("scope-fix-tabs", "scope"), "scope-fix-tabs")
        prefixed = module.prefix_skill_slug("a" * 60, "prep")
        self.assertEqual(len(prefixed), 60)
        self.assertTrue(prefixed.startswith("prep-"))


if __name__ == "__main__":
    unittest.main()
