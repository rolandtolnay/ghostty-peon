import importlib.util
import os
import pathlib
import socket
import unittest
from unittest.mock import patch

import sys
from helpers import HOOKS_DIR, REPO_ROOT

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

    def test_local_llm_eval_production_contract_stays_in_sync_when_available(self):
        local_llm_repo = pathlib.Path(os.environ.get("LOCAL_LLM_REPO", REPO_ROOT.parent / "local-llm"))
        contract_path = local_llm_repo / "prompts" / "workflow-transition-ab" / "production.py"
        if not contract_path.exists():
            self.skipTest("local-llm workflow-transition eval contract not available")

        spec = importlib.util.spec_from_file_location("workflow_transition_eval_production", contract_path)
        contract = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(contract)

        self.assertEqual(workflow_judgment._ALLOWED, contract.ALLOWED)
        self.assertEqual(workflow_judgment._PROMPTS, contract.PROMPTS)

        context = workflow_judgment.JudgmentContext(
            kind="plan-to-cook",
            prompt="Looks good, implement it.",
            current_state="plan",
            current_title="plan-billing-retry-rules",
            origin_message="/plan-quick Build a plan for billing retry rules.",
            recent_messages=("Plan looks ready.", "Tests should cover retry states."),
        )
        case = {
            "current_state": context.current_state,
            "current_title": context.current_title,
            "origin_message": context.origin_message,
            "recent_messages": context.recent_messages,
            "current_message": context.prompt,
        }
        self.assertEqual(workflow_judgment._user_message(context), contract.build_user_message(case))

        for raw in ["COOK", " cook ", "NONE", "uncertain", "PREP", ""]:
            with self.subTest(raw=raw):
                self.assertEqual(
                    workflow_judgment.parse_transition(raw, "cook"),
                    contract.parse_transition(raw, "cook"),
                )


if __name__ == "__main__":
    unittest.main()
