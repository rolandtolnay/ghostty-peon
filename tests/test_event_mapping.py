import json
import subprocess
import textwrap
import unittest

from helpers import REPO_ROOT


class EventMappingTests(unittest.TestCase):
    def run_node(self, script: str) -> str:
        result = subprocess.run(
            ["node", "--experimental-strip-types", "--input-type=module", "-e", script],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            timeout=10,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
        )
        return result.stdout.strip()

    def test_extract_assistant_text_includes_question_tool_prompt(self):
        script = textwrap.dedent(
            """
            import { extractAssistantText } from './pi-extension/event-mapping.ts';

            const text = extractAssistantText({
              messages: [
                {
                  role: 'assistant',
                  content: [
                    {
                      type: 'toolCall',
                      name: 'question',
                      arguments: {
                        questions: [
                          { question: 'Which implementation path should I take?' }
                        ]
                      }
                    }
                  ]
                }
              ]
            });

            console.log(JSON.stringify(text));
            """
        )

        self.assertEqual(
            json.loads(self.run_node(script)),
            "Which implementation path should I take?",
        )

    def test_extract_assistant_text_ignores_completed_question_tool_call(self):
        script = textwrap.dedent(
            """
            import { extractAssistantText } from './pi-extension/event-mapping.ts';

            const text = extractAssistantText({
              messages: [
                {
                  role: 'assistant',
                  content: [
                    {
                      type: 'toolCall',
                      name: 'question',
                      arguments: {
                        questions: [
                          { question: 'Which implementation path should I take?' }
                        ]
                      }
                    }
                  ]
                },
                {
                  role: 'toolResult',
                  content: [{ type: 'text', text: 'Question cancelled.' }]
                }
              ]
            });

            console.log(JSON.stringify(text));
            """
        )

        self.assertEqual(json.loads(self.run_node(script)), "")

    def test_selected_skill_names_use_invoked_skill_envelope_not_loaded_skills(self):
        script = textwrap.dedent(
            """
            import { selectedSkillNames } from './pi-extension/event-mapping.ts';

            const names = selectedSkillNames({
              prompt: '<skill name="Review" location="/tmp/review/SKILL.md">\\nreview these changes\\n</skill>',
              systemPromptOptions: {
                skills: [
                  { name: 'Cook' },
                  { name: 'Plan' },
                  { name: 'Review' },
                ]
              }
            });

            console.log(JSON.stringify(names));
            """
        )

        self.assertEqual(json.loads(self.run_node(script)), ["review"])

    def test_selected_skill_names_include_slash_and_bracket_invocations(self):
        script = textwrap.dedent(
            """
            import { selectedSkillNames } from './pi-extension/event-mapping.ts';

            console.log(JSON.stringify({
              slash: selectedSkillNames({ prompt: '/review-hard audit the branch' }),
              bracket: selectedSkillNames({ prompt: '[/plan-quick] summarize the change' }),
              lifecycle: selectedSkillNames({ prompt: '/reload' }),
            }));
            """
        )

        self.assertEqual(
            json.loads(self.run_node(script)),
            {"slash": ["review-hard"], "bracket": ["plan-quick"], "lifecycle": []},
        )

    def test_workflow_event_mapping_is_defensive_when_metadata_is_missing(self):
        script = textwrap.dedent(
            """
            import { currentBranchName, selectedSkillNames } from './pi-extension/event-mapping.ts';

            const ctx = { cwd: '/path/that/does/not/exist', sessionManager: {} };
            console.log(JSON.stringify({
              skills: selectedSkillNames({}),
              branch: currentBranchName(ctx),
            }));
            """
        )

        self.assertEqual(json.loads(self.run_node(script)), {"skills": [], "branch": ""})

    def test_before_agent_start_payload_carries_workflow_evidence(self):
        script = textwrap.dedent(
            """
            import { beforeAgentStartPayload } from './pi-extension/event-mapping.ts';

            const prompt = '<skill name="review" location="/tmp/review/SKILL.md">Review the branch</skill>';
            const payload = beforeAgentStartPayload(
              {
                prompt,
                images: [{}, {}],
                systemPromptOptions: { skills: [{ name: 'Cook' }, { name: 'Review' }] },
              },
              {
                cwd: '/path/that/does/not/exist',
                sessionManager: {
                  getSessionId: () => 'session-1',
                  getSessionFile: () => '/tmp/session-1.jsonl',
                },
              },
              'session-1',
            );

            console.log(JSON.stringify(payload));
            """
        )

        self.assertEqual(
            json.loads(self.run_node(script)),
            {
                "session_id": "session-1",
                "cwd": "/path/that/does/not/exist",
                "session_file": "/tmp/session-1.jsonl",
                "hook_event_name": "UserPromptSubmit",
                "prompt": '<skill name="review" location="/tmp/review/SKILL.md">Review the branch</skill>',
                "image_count": 2,
                "transcript_path": "/tmp/session-1.jsonl",
                "selected_skills": ["review"],
                "branch_name": "",
            },
        )


if __name__ == "__main__":
    unittest.main()
