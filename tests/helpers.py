import json
import os
import pathlib
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from unittest.mock import patch

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
HOOKS_DIR = REPO_ROOT / "hooks"


@contextmanager
def hook_test_env(namespace="pi", fake_term_id="term-test-1"):
    """Create isolated hook state dirs and fake macOS command binaries."""
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        fake_bin = root / "bin"
        fake_bin.mkdir()

        osascript = fake_bin / "osascript"
        osascript.write_text(
            "#!/bin/sh\n"
            "case \"$*\" in\n"
            "  *'return id of t'*) printf '%s\\n' \"${GHOSTTY_PEON_FAKE_TERM_ID:-term-test-1}\" ; exit 0 ;;\n"
            "esac\n"
            "exit 0\n"
        )
        osascript.chmod(0o755)

        afplay = fake_bin / "afplay"
        afplay.write_text("#!/bin/sh\nexit 0\n")
        afplay.chmod(0o755)

        dirs = {
            "debounce": root / "debounce",
            "handoff": root / "handoff",
            "terminal": root / "terminal",
            "units": root / "units",
            "session_index": root / "session-index",
            "sound_last": root / "sound-last",
            "weights": root / "weights",
            "workflows": root / "workflows",
        }
        for directory in dirs.values():
            directory.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(
            {
                "GHOSTTY_PEON_NAMESPACE": namespace,
                "GHOSTTY_PEON_FAKE_TERM_ID": fake_term_id,
                "GHOSTTY_PEON_LOG_FILE": str(root / "hook.log"),
                "GHOSTTY_PEON_LOG_DATE_FILE": str(root / "hook.lastdate"),
                "GHOSTTY_PEON_LOG_PREV_FILE": str(root / "hook.prev.log"),
                "GHOSTTY_PEON_DEBOUNCE_DIR": str(dirs["debounce"]),
                "GHOSTTY_PEON_PLAN_HANDOFF_DIR": str(dirs["handoff"]),
                "GHOSTTY_PEON_TERMINAL_ID_DIR": str(dirs["terminal"]),
                "GHOSTTY_PEON_UNIT_ASSIGN_DIR": str(dirs["units"]),
                "GHOSTTY_PEON_SESSION_INDEX_DIR": str(dirs["session_index"]),
                "GHOSTTY_PEON_SOUND_LAST_DIR": str(dirs["sound_last"]),
                "GHOSTTY_PEON_WEIGHT_STATE_DIR": str(dirs["weights"]),
                "GHOSTTY_PEON_WEIGHT_STATE_FILE": str(dirs["weights"] / "weights.json"),
                "GHOSTTY_PEON_WORKFLOW_STATE_FILE": str(dirs["workflows"] / "workflows.json"),
                "PEON_SOUND_CLASS": "none",
                "PATH": f"{fake_bin}{os.pathsep}{env.get('PATH', '')}",
            }
        )
        yield root, env, dirs


def run_hook(script_name, payload, env, timeout=10):
    return subprocess.run(
        [sys.executable, str(HOOKS_DIR / script_name)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=REPO_ROOT,
        env=env,
        timeout=timeout,
    )


def assert_hook_ok(testcase, result):
    testcase.assertEqual(
        result.returncode,
        0,
        msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
    )


def seed_workflow_session(dirs, env, session_id, terminal_id, state, slug, emoji="🌿"):
    """Seed matching terminal, debounce, and workflow state for a canonical Pi title."""
    canonical_title = f"{state}-{slug}"
    visible_title = f"{emoji} {canonical_title}"
    (dirs["terminal"] / session_id).write_text(terminal_id)
    (dirs["debounce"] / session_id).write_text(f"123\n{visible_title}\n")

    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    import workflow_state

    with patch.dict(os.environ, env, clear=True):
        workflow_state.create_workstream(
            session_id=session_id,
            terminal_id=terminal_id,
            state=state,
            slug=slug,
            title=canonical_title,
        )
    return visible_title


def read_log(root):
    path = pathlib.Path(root) / "hook.log"
    return path.read_text() if path.exists() else ""
