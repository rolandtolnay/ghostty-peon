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


if __name__ == "__main__":
    unittest.main()
