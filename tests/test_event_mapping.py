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

    def test_before_agent_start_payload_keeps_workflow_interpretation_out_of_adapter(self):
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
            },
        )


if __name__ == "__main__":
    unittest.main()
