import os
import unittest
from unittest.mock import patch

import sys
from helpers import HOOKS_DIR, hook_test_env

sys.path.insert(0, str(HOOKS_DIR))
import workflow_state


class WorkflowStateTests(unittest.TestCase):
    def test_active_bindings_keep_same_project_branch_workstreams_distinct(self):
        with hook_test_env() as (_root, env, _dirs):
            with patch.dict(os.environ, env, clear=True):
                alpha = workflow_state.create_workstream(
                    session_id="session-alpha",
                    terminal_id="term-alpha",
                    state="plan",
                    slug="alpha-workstream",
                    cwd="/repo",
                    branch="feature/shared",
                )
                beta = workflow_state.create_workstream(
                    session_id="session-beta",
                    terminal_id="term-beta",
                    state="plan",
                    slug="beta-workstream",
                    cwd="/repo",
                    branch="feature/shared",
                )

                self.assertNotEqual(alpha.id, beta.id)
                self.assertEqual(workflow_state.resolve_active(session_id="session-alpha").slug, "alpha-workstream")
                self.assertEqual(workflow_state.resolve_active(session_id="session-beta").slug, "beta-workstream")
                self.assertEqual(workflow_state.resolve_active(terminal_id="term-alpha").slug, "alpha-workstream")
                self.assertEqual(workflow_state.resolve_active(terminal_id="term-beta").slug, "beta-workstream")

    def test_artifact_reference_can_attach_a_new_session_to_existing_workstream(self):
        artifact = "/repo/etc/prd/canonical-pi-workflow-titles.md"
        with hook_test_env() as (_root, env, _dirs):
            with patch.dict(os.environ, env, clear=True):
                original = workflow_state.create_workstream(
                    session_id="session-plan",
                    terminal_id="term-plan",
                    state="plan",
                    slug="canonical-pi-workflow-titles",
                    artifacts=(artifact,),
                )
                workflow_state.deactivate(session_id="session-plan", terminal_id="term-plan")

                resolved = workflow_state.resolve_by_artifact((artifact,))
                self.assertEqual(resolved.id, original.id)

                attached = workflow_state.replace_active_workstream(
                    original.id,
                    session_id="session-cook",
                    terminal_id="term-cook",
                    state="cook",
                    slug="canonical-pi-workflow-titles",
                    artifacts=(artifact,),
                )

                self.assertEqual(attached.id, original.id)
                self.assertEqual(workflow_state.resolve_active(session_id="session-cook").state, "cook")

    def test_explicit_artifact_can_replace_current_active_workstream(self):
        artifact = "/repo/etc/prd/shared-artifact.md"
        with hook_test_env() as (_root, env, _dirs):
            with patch.dict(os.environ, env, clear=True):
                active = workflow_state.create_workstream(
                    session_id="current-session",
                    terminal_id="current-term",
                    state="plan",
                    slug="active-workstream",
                )
                artifact_bound = workflow_state.create_workstream(
                    session_id="old-session",
                    terminal_id="old-term",
                    state="plan",
                    slug="shared-artifact",
                    artifacts=(artifact,),
                )
                workflow_state.deactivate(session_id="old-session", terminal_id="old-term")

                self.assertEqual(workflow_state.resolve_active(session_id="current-session").id, active.id)
                self.assertEqual(workflow_state.resolve_by_artifact((artifact,)).id, artifact_bound.id)

                replaced = workflow_state.replace_active_workstream(
                    artifact_bound.id,
                    session_id="current-session",
                    terminal_id="current-term",
                    state="cook",
                    slug="shared-artifact",
                    artifacts=(artifact,),
                )

                self.assertEqual(replaced.id, artifact_bound.id)
                self.assertEqual(workflow_state.resolve_active(session_id="current-session").id, artifact_bound.id)
                self.assertEqual(workflow_state.resolve_active(session_id="current-session").state, "cook")
                self.assertEqual(workflow_state.resolve_active(terminal_id="current-term").id, artifact_bound.id)

    def test_create_replacing_active_workstream_preserves_old_workstream_but_moves_active_binding(self):
        with hook_test_env() as (_root, env, _dirs):
            with patch.dict(os.environ, env, clear=True):
                original = workflow_state.create_workstream(
                    session_id="session-current",
                    terminal_id="term-current",
                    state="plan",
                    slug="old-plan",
                )

                replacement = workflow_state.create_replacing_active_workstream(
                    session_id="session-current",
                    terminal_id="term-current",
                    state="prep",
                    slug="new-prd",
                )

                self.assertNotEqual(replacement.id, original.id)
                self.assertEqual(workflow_state.resolve_active(session_id="session-current").id, replacement.id)
                self.assertEqual(workflow_state.resolve_active(terminal_id="term-current").id, replacement.id)

    def test_deactivated_workstream_does_not_restore_for_ordinary_future_prompt(self):
        with hook_test_env() as (_root, env, _dirs):
            with patch.dict(os.environ, env, clear=True):
                workflow_state.create_workstream(
                    session_id="stale-session",
                    terminal_id="stale-term",
                    state="check",
                    slug="canonical-workflow-titles",
                    cwd="/repo",
                    branch="feature/shared",
                )
                workflow_state.deactivate(session_id="stale-session", terminal_id="stale-term")

                self.assertIsNone(workflow_state.resolve_active(session_id="new-session"))
                self.assertIsNone(workflow_state.resolve_active(terminal_id="new-term"))

    def test_replacement_start_transfers_active_binding_to_new_session(self):
        with hook_test_env() as (_root, env, _dirs):
            with patch.dict(os.environ, env, clear=True):
                original = workflow_state.create_workstream(
                    session_id="old-session",
                    terminal_id="term-shared",
                    state="plan",
                    slug="canonical-workflow-titles",
                )

                transferred = workflow_state.transfer_binding(
                    old_session_id="old-session",
                    new_session_id="new-session",
                    terminal_id="term-shared",
                )

                self.assertEqual(transferred.id, original.id)
                self.assertIsNone(workflow_state.resolve_active(session_id="old-session"))
                self.assertEqual(workflow_state.resolve_active(session_id="new-session").slug, "canonical-workflow-titles")

    def test_unwritable_state_file_degrades_without_crashing_explicit_facade(self):
        with hook_test_env() as (root, env, _dirs):
            blocker = root / "not-a-directory"
            blocker.write_text("file blocks directory creation")
            env["GHOSTTY_PEON_WORKFLOW_STATE_FILE"] = str(blocker / "workflows.json")
            with patch.dict(os.environ, env, clear=True):
                workstream = workflow_state.create_workstream(
                    session_id="session-unwritable",
                    terminal_id="term-unwritable",
                    state="plan",
                    slug="canonical-workflow-titles",
                )
                workflow_state.deactivate(session_id="session-unwritable", terminal_id="term-unwritable")
                transferred = workflow_state.transfer_binding(
                    old_session_id="session-unwritable",
                    new_session_id="new-session",
                    terminal_id="term-unwritable",
                )

                self.assertEqual(workstream.slug, "canonical-workflow-titles")
                self.assertIsNone(transferred)


if __name__ == "__main__":
    unittest.main()
