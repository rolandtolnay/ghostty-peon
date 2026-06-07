import socket
import unittest
from unittest.mock import patch

import sys
from helpers import HOOKS_DIR

sys.path.insert(0, str(HOOKS_DIR))
import workflow_judgment


class WorkflowJudgmentTests(unittest.TestCase):
    def test_first_turn_check_judgment_accepts_only_constrained_check_output(self):
        with patch.object(workflow_judgment, "call_llm", return_value=" CHECK \n"):
            result = workflow_judgment.judge(
                workflow_judgment.JudgmentContext(
                    kind="ordinary-to-check",
                    prompt="Can you sanity check MIN-180 before I plan it?",
                )
            )

        self.assertEqual(result.transition, "check")

    def test_invalid_uncertain_empty_or_timeout_outputs_are_no_transition(self):
        cases = ["", "maybe", "uncertain", "prep"]
        for raw in cases:
            with self.subTest(raw=raw), patch.object(workflow_judgment, "call_llm", return_value=raw):
                result = workflow_judgment.judge(workflow_judgment.JudgmentContext(kind="ordinary-to-check", prompt="x"))
                self.assertEqual(result.transition, "")

        with patch.object(workflow_judgment, "call_llm", side_effect=socket.timeout("timed out")):
            result = workflow_judgment.judge(workflow_judgment.JudgmentContext(kind="plan-to-cook", prompt="Implement it now"))
            self.assertEqual(result.transition, "")

    def test_state_specific_judgments_only_allow_their_target_transition(self):
        cases = [
            ("check-to-prep", "PREP", "prep"),
            ("plan-to-cook", "COOK", "cook"),
        ]
        for kind, raw, expected in cases:
            with self.subTest(kind=kind), patch.object(workflow_judgment, "call_llm", return_value=raw):
                result = workflow_judgment.judge(workflow_judgment.JudgmentContext(kind=kind, prompt="continue"))
                self.assertEqual(result.transition, expected)


if __name__ == "__main__":
    unittest.main()
