import unittest

import sys
from helpers import HOOKS_DIR

sys.path.insert(0, str(HOOKS_DIR))
import workflow_model


class WorkflowModelTests(unittest.TestCase):
    def test_deterministic_skill_signal_selects_workflow_state(self):
        cases = [
            ("prep", "prep"),
            ("to-prd", "prep"),
            ("plan", "plan"),
            ("plan-quick", "plan"),
            ("cook-plan", "cook"),
            ("cook", "cook"),
            ("review", "review"),
            ("review-hard", "review"),
            ("triage-pr-comments", "review"),
        ]

        for skill, expected_state in cases:
            with self.subTest(skill=skill):
                decision = workflow_model.decide(
                    workflow_model.WorkflowContext(
                        selected_skills=(skill,),
                        inherited_slug="canonical-workflow-titles",
                    )
                )

                self.assertEqual(decision.state, expected_state)
                self.assertEqual(decision.slug, "canonical-workflow-titles")
                self.assertEqual(decision.action, "set")

    def test_prd_artifact_slug_wins_when_prd_and_plan_are_referenced(self):
        decision = workflow_model.decide(
            workflow_model.WorkflowContext(
                selected_skills=("plan",),
                prompt=(
                    "Use etc/prd/canonical-pi-workflow-titles.md and "
                    "the plan at ~/.pi/plans/ghostty-peon/canonical-pi-workflow-titles-plan.md"
                ),
                inherited_slug="older-generated-slug",
            )
        )

        self.assertEqual(decision.state, "plan")
        self.assertEqual(decision.slug, "canonical-pi-workflow-titles")
        self.assertEqual(decision.canonical_title, "plan-canonical-pi-workflow-titles")

    def test_cook_keeps_inherited_slug_before_branch_fallback(self):
        decision = workflow_model.decide(
            workflow_model.WorkflowContext(
                selected_skills=("cook",),
                inherited_slug="canonical-workflow-titles",
                branch_name="feature/branch-slug-should-not-win",
            )
        )

        self.assertEqual(decision.state, "cook")
        self.assertEqual(decision.slug, "canonical-workflow-titles")

    def test_cook_uses_non_generic_branch_when_no_stronger_slug_exists(self):
        decision = workflow_model.decide(
            workflow_model.WorkflowContext(
                selected_skills=("cook",),
                branch_name="feature/canonical-workflow-titles",
            )
        )

        self.assertEqual(decision.state, "cook")
        self.assertEqual(decision.slug, "canonical-workflow-titles")

    def test_first_turn_check_judgment_enters_check_and_requests_existing_slug_flow(self):
        decision = workflow_model.decide(
            workflow_model.WorkflowContext(
                transition="check",
                prompt="Can you sanity check MIN-180?",
            )
        )

        self.assertEqual(decision.state, "check")
        self.assertTrue(decision.needs_slug)

    def test_canonical_followup_without_transition_keeps_current_title_stable(self):
        decision = workflow_model.decide(
            workflow_model.WorkflowContext(
                current_state="check",
                active_binding=True,
                inherited_slug="canonical-workflow-titles",
                prompt="Thanks, one more thought",
            )
        )

        self.assertEqual(decision.action, "keep")
        self.assertEqual(decision.canonical_title, "check-canonical-workflow-titles")

    def test_judged_transitions_move_only_to_allowed_next_state(self):
        check_to_prep = workflow_model.decide(
            workflow_model.WorkflowContext(
                current_state="check",
                active_binding=True,
                inherited_slug="canonical-workflow-titles",
                transition="prep",
            )
        )
        plan_to_cook = workflow_model.decide(
            workflow_model.WorkflowContext(
                current_state="plan",
                active_binding=True,
                inherited_slug="canonical-workflow-titles",
                transition="cook",
            )
        )

        self.assertEqual(check_to_prep.canonical_title, "prep-canonical-workflow-titles")
        self.assertEqual(plan_to_cook.canonical_title, "cook-canonical-workflow-titles")


if __name__ == "__main__":
    unittest.main()
