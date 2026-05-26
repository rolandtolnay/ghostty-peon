# Debugging Guide

Architecture details, log format, and troubleshooting for ghostty-peon hooks.

---

## Architecture Overview

```
Claude settings.json hooks or Pi extension events
    │
    ├─ PreToolUse / Pi tool_call:question
    │    └─ AskUserQuestion/question ─► tab-attention-hook.py ──► add ⭐ + input.required sound
    │
    ├─ UserPromptSubmit / Pi before_agent_start ─► tabtitle-hook.py ──► Ollama slug ──► set title + task.acknowledge sound
    │
    ├─ PermissionRequest / ghostty-peon:permission ─► tab-attention-hook.py ──► add 🔥 + input.required sound
    │
    ├─ PostToolUse / Pi tool_result ─► tab-attention-hook.py ──► clear emoji → restore 🌀
    │
    ├─ Stop / Pi agent_end ──────────► tab-stop-question-hook.py ──► Ollama question check ──► add ⭐ or 🌿
    │
    ├─ SessionStart / Pi session_start
    │    ├─ startup/new/fork ────────► session-sound-hook.py ──► capture/claim terminal + assign unit + session.start sound
    │    ├─ resume ─────────────────► session-sound-hook.py ──► capture/claim terminal + restore title + assign unit if needed
    │    ├─ compact ────────────────► session-sound-hook.py ──► keep existing terminal + restore title
    │    └─ clear ──────────────────► session-sound-hook.py ──► delete debounce + re-assign unit
    │
    └─ SessionEnd / Pi session_shutdown ─► session-end-hook.py ──► reset/preserve/handoff title state + release unit/terminal
```

## File Map

| File | Purpose |
|------|---------|
| `hooks/sound_utils.py` | Compatibility facade plus shared sound playback, unit assignment, emoji helpers, and logging |
| `hooks/runtime_config.py` | Runtime namespace/env/path configuration for Claude and Pi |
| `hooks/title_state.py` | Debounce/title/origin state file parsing and writing |
| `hooks/title_handoff.py` | Terminal-scoped title handoff JSON for plan/fork replacement flows |
| `hooks/ghostty_tab.py` | Ghostty terminal capture, ownership, safe title targeting, stale terminal cleanup, focus checks |
| `hooks/lifecycle_policy.py` | Pure lifecycle decisions for Pi/Claude replacement, reset, and cleanup behavior |
| `hooks/tabtitle-hook.py` | UserPromptSubmit: sets 🌀 working emoji, generates slug via Ollama, plays task.acknowledge |
| `hooks/tab-attention-hook.py` | PreToolUse/PermissionRequest: sets attention emoji; PostToolUse clears it |
| `hooks/tab-stop-question-hook.py` | Stop: heuristic question detection via Ollama, sets ⭐ or 🌿 |
| `hooks/session-sound-hook.py` | SessionStart: captures/claims terminal, restores handoff/title state, assigns unit, plays session.start where applicable |
| `hooks/session-end-hook.py` | SessionEnd: reset/preserve title state, writes handoff for plan/fork, releases unit + terminal id |
| `pi-extension/index.ts` | Pi extension entrypoint and event wiring |
| `pi-extension/event-mapping.ts` | Pi-to-Claude-like payload mapping helpers |
| `pi-extension/ghostty-env.ts` | Pi Ghostty detection and hook subprocess environment construction |
| `pi-extension/hook-runner.ts` | Python hook subprocess runner, timeout handling, runner logging |
| `pi-extension/paths.ts` | Pi extension path resolution and required hook list |
| `client.py` | Standalone Ollama HTTP client (pure stdlib, no pip deps) |

---

## Emoji Reference

| Emoji | Constant | Meaning |
|-------|----------|---------|
| 🌀 | `EMOJI_WORKING` | Claude is processing |
| ⭐ | `EMOJI_QUESTION` | Question / input needed |
| 🔥 | `EMOJI_BLOCKED` | Permission prompt waiting |
| 🌿 | `EMOJI_READY` | Done, no input needed |

---

## Session Unit Assignment

### How it works

Each terminal session is assigned a unique Warcraft III unit within its project using weighted rotation. All 4 classes have 7 units each. When `PEON_SOUND_CLASS` is `random`, both class and unit are selected via weighted rotation for balanced distribution.

### Tmp file locations

```
/tmp/claude-sound-units/{project_key}/{session_id}   # contents: {class}\n{unit}
/tmp/claude-sound-session/{session_id}                # contents: {project_key}
/tmp/claude-tabterminal/{session_id}                  # contents: Ghostty terminal UUID
```

- `project_key` = `sha256(cwd)[:12]` — short, filesystem-safe
- Session index enables O(1) lookup in `play_sound()` (no need to scan all projects)
- Stale files (>12 hours) are cleaned on each `assign_unit()` call
- Weighted rotation state persisted at `~/.ghostty-peon/weights.json`

### Lifecycle

1. **SessionStart:startup** → `capture_terminal_id()` + `assign_unit(session_id, cwd)` picks a unit, writes assignment + index files
2. **play_sound(event, session_id)** → reads index → reads assignment → uses stored class/unit
3. **SessionEnd** → `release_unit(session_id, cwd)` deletes assignment + index files, `release_terminal_id()` deletes UUID
4. **/clear** → SessionEnd fires (releasing old), then SessionStart fires (re-assigning, possibly different unit)

---

## Debugging

### Log File

Location: `/tmp/claude-tab-hooks.log` (today's log). Previous day's log archived at `/tmp/claude-tab-hooks.prev.log`. Rotates once per day at the first log write after midnight.

Most non-early-exit paths log skips, failures, and no-ops with the reason. A total absence of log lines usually means the hook runner did not execute the script, but there are intentional pre-log exits such as `_CLAUDE_HOOK_NESTED=1` and `_CLAUDE_NO_SOUND=1`.

Use `/tmp/pi-tab-hooks.log` for Pi sessions. The two runtimes have separate logs and `/tmp` state namespaces; do not debug a Pi symptom from Claude logs or vice versa.

### Log Format

```
HH:MM:SS.mmm [sid] hook       | message
```

- `HH:MM:SS.mmm` — wall-clock timestamp with millisecond precision
- `[sid]` — last 6 characters of the full session ID (stable within a session, unique across concurrent sessions)
- `hook` — left-padded to 10 chars. Values: `session`, `tabtitle`, `attention`, `stop-q`, `plan-accept`, `sound`
- `message` — free-form, always starts with one of: an action (`startup ->`, `set ->`, `cleared attention ->`), a skip reason (`skip: ...`), a delegation (`calling llm`, `llm ->`), or a failure (`set_tab_title failed`, `llm error`)

### Fast Triage Checklist

Start with the runtime-specific log and state before reading hook code:

```sh
# Claude Code
tail -200 /tmp/claude-tab-hooks.log
ls -lt /tmp/claude-tabtitle /tmp/claude-tabterminal /tmp/claude-sound-session 2>/dev/null

# Pi
tail -200 /tmp/pi-tab-hooks.log
ls -lt /tmp/pi-tabtitle /tmp/pi-tabterminal /tmp/pi-sound-session 2>/dev/null
```

Then identify the `[sid]` suffix and build a one-session trace:

```sh
grep '\[abc123\]' /tmp/claude-tab-hooks.log
grep '\[abc123\]' /tmp/pi-tab-hooks.log
```

Check these high-signal patterns before broader exploration:

```sh
# Subagent/nested-session suppression
grep "skip: subagent" /tmp/claude-tab-hooks.log
grep "nested hook guard exported" /tmp/claude-tab-hooks.log
grep "subagent detected" /tmp/claude-tab-hooks.log

# Unsafe tab targeting avoided
grep "target: SKIPPED (no term_id" /tmp/claude-tab-hooks.log /tmp/pi-tab-hooks.log

# Pi replacement handoff correctness
grep -E "replacement handoff written|restored replacement terminal_id|restored replacement title|captured terminal_id" /tmp/pi-tab-hooks.log

# Question/ready status path
grep -E "agent_end|stop-q|llm ->|skip: no '\?'|skip 🌿: no established title" /tmp/pi-tab-hooks.log /tmp/claude-tab-hooks.log

# Sound-producing paths
grep -E "sound +\| session.start|sound +\| task.acknowledge|sound +\| input.required" /tmp/claude-tab-hooks.log /tmp/pi-tab-hooks.log
```

### Filtering by Session

The `[sid]` tag is the primary filter key. To debug a specific session:

1. **Find the session ID suffix.** Look for its `session | startup ->` line, or `ls -lt /tmp/claude-tabtitle/` to find recent session IDs (the last 6 chars of the filename = the `[sid]`).
2. **Filter:** `grep '\[abc123\]' /tmp/claude-tab-hooks.log` gives the complete chronological trace for that session across all hooks.
3. **Every user message** produces a `tabtitle | prompt=Nchars` line. Count these to verify no messages were dropped.
4. **Every Claude stop** produces either a `stop-q | fired` line or `stop-q | skip: stop_hook_active`. If neither appears, the Stop hook didn't fire.

Multiple sessions interleave in the log but are fully separable by `[sid]`. Date separators (`=== YYYY-MM-DD ===`) mark day boundaries.

### Example: Full Session Trace

```
22:45:01.100 [a1b2c3] session   | startup -> captured terminal_id='...'
22:45:01.150 [a1b2c3] session   | startup -> assigned unit='peon'
22:45:01.200 [a1b2c3] tabtitle  | prompt=42chars
22:45:01.201 [a1b2c3] tabtitle  | skip 🌀: no established title yet
22:45:01.202 [a1b2c3] tabtitle  | calling llm (current='', origin=0chars, recent=0msgs)
22:45:03.500 [a1b2c3] tabtitle  | llm returned 'fix-auth-token'
22:45:03.700 [a1b2c3] tabtitle  | -> 🌀 renamed ('fix-auth-token')
22:45:06.000 [a1b2c3] stop-q    | fired (msg_len=450)
22:45:06.001 [a1b2c3] stop-q    | calling llm (tail='...Which approach do you prefer?')
22:45:08.200 [a1b2c3] stop-q    | llm -> True (model answered 'YES')
22:45:08.400 [a1b2c3] stop-q    | -> ⭐ question ('fix-auth-token')
22:45:10.100 [a1b2c3] attention | PreToolUse:AskUserQuestion title='⭐ fix-auth-token'
22:45:10.101 [a1b2c3] attention | skip: ⭐ already showing
22:45:15.000 [a1b2c3] tabtitle  | prompt=15chars
22:45:15.001 [a1b2c3] tabtitle  | -> 🌀 working ('fix-auth-token')
22:45:15.002 [a1b2c3] tabtitle  | skip: prompt too short (15 < 40 chars)
22:50:00.100 [a1b2c3] session   | end -> title reset to 'my-project'
22:50:00.200 [a1b2c3] session   | end -> cleaned up debounce, unit + terminal_id released
```

### Diagnosing Common Issues

**Tab title not renaming:**
Look for `tabtitle` lines. The log will show exactly why:
- `skip: prompt too short (N < 40 chars)` — message was too short
- `skip: cooldown (Xs elapsed, 90s required)` — still within the cooldown window (cooldown only resets on actual renames, not on same-slug or KEEP results)
- `llm returned None` — Ollama timed out (10s timeout) or returned an invalid slug
- `llm error: ...` — Ollama not running or model not available
- `set_tab_title failed` — Ghostty AppleScript failed (stale/missing terminal, Ghostty not running, or AppleScript error)
- `target: SKIPPED (no term_id, refusing unsafe fallback)` — terminal UUID was lost

**Attention emoji not appearing:**
Look for `attention` lines and `stop-q` lines:
- `skip: stop_hook_active` — the Stop hook was triggered inside another Stop hook (loop prevention)
- `skip: no '?' in last 500 chars` — pre-filter blocked LLM call
- `llm -> False (model answered 'NO')` — Ollama classified the response as not requiring user action
- `llm -> False (llm error: ...)` — Ollama call failed
- `skip: ⭐ already showing` — emoji was already set, deduplication fired
- No `stop-q` lines at all — the hook itself didn't fire; check `settings.json` Stop entry

**Wrong emoji (🔥 instead of ⭐ for AskUserQuestion/question):**
Look for `attention` lines:
- Claude Code should log `PreToolUse:AskUserQuestion`; Pi should log `PreToolUse:question`
- PermissionRequest for either question tool should log `skip: ... handled by PreToolUse`
- If `PreToolUse` is missing, the question-tool hook/extension mapping may be missing

**Sound not playing or playing less often than expected:**
Look for `sound` lines in the log:
- `skip session.start: class=none` — sounds disabled via `peon-class none`
- `skip ...: dir missing (class/unit/event)` — sound files not found
- `skip ...: invalid class=...` — invalid PEON_SOUND_CLASS value
- fewer `task.acknowledge` sounds can be expected when tab titles rename less often; `task.acknowledge` only plays on actual new slug generation, not on `KEEP`, same-slug, short prompt, cooldown skip, or invalid slug

Check your sound class setting:
```sh
peon-class          # shows current setting
```

If title/sound behavior depends on the LLM, inspect the detailed local-LLM-compatible call log:

```sh
ls -lh ~/.local/share/local-llm/calls-*.jsonl
local-llm ./logview --tag tabtitle --last 1h
local-llm ./logview --tag stop-question --last 1h
```

Validated caveats from prior debugging:
- Ollama can be healthy while Ghostty Peon lacks detailed call logs if `client.py` logging is broken; check for the current month file.
- `ollama serve` plus one `ollama runner` for the warm model is normal. Extra old model runners can waste RAM; `ollama ps` shows loaded models, and `ollama stop gemma4:e4b`/`ollama stop gemma4:e2b` unloads a model.
- Current hooks use `gemma4:e2b`; previous investigations did not require stop-question prompt retuning for this model.

**Unit assignment issues:**
Check the assignment files:
```sh
ls -la /tmp/claude-sound-units/*/         # all project assignments
ls -la /tmp/claude-sound-session/         # session index
cat /tmp/claude-sound-units/*/<session_id>  # shows class\nunit for a session
```

**Subagents emit sounds or change the focused tab:**
There are three validated subagent/nested-session paths; check all before assuming a stale install:

1. Claude in-process subagent hook payloads include `agent_id` and may use `hook_event_name=SubagentStart/SubagentStop`; these should log `skip: subagent` and exit before terminal capture, title mutation, unit assignment, sounds, or cleanup.
2. Bash-launched nested `claude` subprocesses may not include `agent_id`; parent `SessionStart` should write `export _CLAUDE_HOOK_NESTED=1` to `CLAUDE_ENV_FILE`, visible as `nested hook guard exported via CLAUDE_ENV_FILE`.
3. Older Claude Agent/Task-style subagents created separate sessions on the same Ghostty terminal; terminal ownership detection logs `subagent detected (terminal owned by ...)` and releases the subagent terminal id before sounds/unit assignment.

Suspicious pattern when suppression fails:

```text
[child] session  | startup -> assigned unit='...'
[child] sound    | session.start -> ...
[child] tabtitle | prompt=...chars
[child] sound    | task.acknowledge -> ...
```

Useful checks:

```sh
grep "skip: subagent" /tmp/claude-tab-hooks.log
grep "nested hook guard exported" /tmp/claude-tab-hooks.log
grep "subagent detected" /tmp/claude-tab-hooks.log
grep -E "startup -> assigned unit|sound +\| session.start|task.acknowledge" /tmp/claude-tab-hooks.log
```

Known gotchas:
- `agent_type` alone is not a subagent signal; a main `claude --agent <name>` style session must not be skipped just because it has an agent type.
- Terminal ownership inference can false-positive for legitimate multiple sessions sharing one Ghostty terminal/split pane. Prefer explicit `agent_id`, lifecycle event, `_CLAUDE_HOOK_NESTED`, or Pi `PI_SUBAGENT_CHILD` when available.
- A hook with `_CLAUDE_HOOK_NESTED=1` exits before normal logging, so no log line from the child process can be expected.

**Pi replacement starts restore the wrong tab or stale status:**
Known failure modes and expected fixes are all at the lifecycle handoff seam:

- If a Pi `new`/`fork`/`resume` replacement captures the currently focused tab instead of the outgoing tab, look for missing target-session handoff. The bad repro was `term-focused-other != term-outgoing` in `tests/test_session_sound_pi.py`.
- Expected log sequence: outgoing shutdown writes `replacement handoff written`, then replacement start logs `restored replacement terminal_id=...`. If replacement start logs only `captured terminal_id=...`, it fell back to focus capture.
- Pi `new` and `resume` should preserve the outgoing visible title/status (`🌿`, `⭐`, `🔥`, or `🌀`). Pi `fork` and plan continuation intentionally hand off `🌀 <clean-title>` because work continues.
- A prior bug rebuilt every replacement handoff as `🌀 <clean-title>`, which made idle `🌿 investigate-filesystem-footer` sessions look active after `reason=new`.

Useful checks:

```sh
grep -E "event session_shutdown reason=|replacement handoff written|restored replacement terminal_id|restored replacement title|captured terminal_id" /tmp/pi-tab-hooks.log
```

**Stop-question / ⭐ vs 🌿 status is wrong:**
The stop hook is intentionally heuristic:

- It checks only the last 500 chars of `last_assistant_message` for `?` before calling Ollama. A real question earlier than the last 500 chars can be missed.
- If Pi `agent_end` has `msg_len=0`, the event mapping did not provide extractable assistant text; current hooks treat this as ready (`🌿`) because `agent_end` still means the turn finished. Later tool results recover `🌿` back to `🌀` if work unexpectedly continues.
- If there is no established debounce title, `stop-q` logs `skip 🌿: no established title` rather than creating a title from nothing.
- Pi structured `question`/`AskUserQuestion` tool-call blocks must be projected to user-facing text in `pi-extension/event-mapping.ts`; otherwise `tab-stop-question-hook.py` can miss questions represented outside plain text.

Useful checks:

```sh
grep -E "agent_end|stop-q|msg_len=0|skip: no '\?'|llm ->|skip 🌿: no established title" /tmp/pi-tab-hooks.log /tmp/claude-tab-hooks.log
```

**Claude plan acceptance loses emoji/status:**
Plan acceptance crosses a Claude session boundary. The safe behavior is not merely preserving the raw title:

- `PermissionRequest:ExitPlanMode` can temporarily show `🔥` and mark `planpending`.
- `SessionEnd` with `planpending` should convert to `🌀 <clean-title>`, set the visible tab, and write a terminal-scoped handoff.
- The next `SessionStart:clear/startup` should consume that handoff, seed the new session debounce file, and set `🌀 <clean-title>` so later PostToolUse/Stop/attention hooks have state.

If an active post-plan tab has no emoji, check for `planpending`, handoff writes/consumes, and whether the new session has a debounce file.

**Clearing logs/state:**
```sh
> /tmp/claude-tab-hooks.log   # truncate
rm /tmp/claude-tab-hooks.log  # delete (recreated automatically on next hook fire)

# Clear Claude hook state when reproducing from scratch
rm -rf /tmp/claude-tabtitle /tmp/claude-tabterminal /tmp/claude-plan-handoff /tmp/claude-sound-units /tmp/claude-sound-session /tmp/claude-sound-last
```

### Inspecting the Debounce File

The debounce file is the shared state between all hooks for a given session:

```sh
cat /tmp/claude-tabtitle/<session_id>
# line 1: unix timestamp of last actual rename (cooldown reference)
# line 2: current title (may include emoji prefix)
# line 3: (optional) plan state flag
```

Find your session ID in the log (the 6-char `[sid]` suffix is the tail of the full ID):

```sh
ls -lt /tmp/claude-tabtitle/   # most recent file = current session
```

### Tab Targeting

Each session's Ghostty terminal UUID is captured at `SessionStart` and persisted to `/tmp/claude-tabterminal/{session_id}`. All hooks use this UUID to target the correct tab via `perform action "set_tab_title:..." on (first terminal whose id is "UUID")`, which works regardless of which tab or window is focused.

If no UUID is available for a session, `set_tab_title()` refuses to operate (logs `SKIPPED: no term_id, refusing unsafe fallback`) to prevent accidentally renaming the wrong tab.

### Validation Commands and Gotchas

Tests use `tests/helpers.py` as a top-level import, so direct module runs need `PYTHONPATH=tests`:

```sh
PYTHONPATH=tests python3 -m unittest tests.test_session_sound_pi tests.test_session_end_pi
PYTHONPATH=tests python3 -m unittest tests.test_claude_subagent_guard
python3 -m unittest discover -s tests
python3 -m py_compile hooks/*.py
git diff --check
```

Known gotchas from prior sessions:
- `python3 -m unittest` from the repo root discovers 0 tests; use `discover -s tests`.
- `python3 -m unittest tests.test_session_sound_pi` fails without `PYTHONPATH=tests` because tests import `helpers` as top-level.
- Raw `tsc`/Node import checks may fail because this repo does not install local TypeScript/Node type dependencies; prefer the existing installer/extension smoke path or `./scripts/check.sh` when present.
- Do not rely on CI-style Ghostty/Ollama/sound integration tests here. The reliable loop is hook-level contract tests plus manual Ghostty smoke verification when needed.

---

## Hook Implementation Details

### `tabtitle-hook.py` (UserPromptSubmit)

The most complex hook. Flow:

1. **Recursion guard**: Check `_CLAUDE_HOOK_NESTED` env var, exit if set
2. **Read debounce file**: Get current title
3. **Set working emoji**: Replace any attention emoji with 🌀
4. **Debounce check**: Skip if within 90s cooldown or message is short (<40 chars). First message always triggers.
5. **Generate slug**: Call local Ollama model via `client.py` (10s timeout)
6. **Set title + sound**: If new slug generated, set title with 🌀, play `task.acknowledge`, and reset cooldown timestamp. If slug matches current title or LLM returns KEEP, the cooldown timestamp is preserved — so subsequent messages can be evaluated sooner.

The slug prompt asks the model to output a 2-5 word hyphenated slug or `KEEP` if the current title still fits. Validation rejects anything with spaces, special characters, error markers, or over 40 chars.

### `tab-attention-hook.py` (attention emoji + clear)

Registered on three events via separate entries in `settings.json` / Pi extension events:
- `PreToolUse[AskUserQuestion]` or Pi `tool_call:question` → ⭐
- `PermissionRequest` → 🔥 (skips question tools since PreToolUse handles them)
- `PostToolUse` → clears emoji, restores 🌀

### `tab-stop-question-hook.py` (Stop)

Tier 2 heuristic for detecting when Claude stops with a question.

1. Pre-filter: skip if no `?` in the last 500 chars (~80% of stops filtered out cheaply)
2. Check debounce file — skip if ⭐ emoji already showing
3. Call Ollama to classify whether the text is asking for user input (YES/NO)
4. If YES: set ⭐ + play `input.required`. If NO: set 🌿 (ready, no sound).

### `session-sound-hook.py` (SessionStart)

Handles Pi-first lifecycle `source` values:
- `startup` / `new` / `fork`: captures terminal UUID, claims terminal ownership, assigns unit via `assign_unit()`, plays `session.start`; `new` restores the outgoing visible title/status when a replacement handoff exists
- `resume`: captures terminal UUID, restores the replacement or persisted title if present, assigns unit only if no existing assignment
- `compact`: keeps the persisted terminal UUID when present and restores the persisted title after compaction; captures only if the session has no terminal UUID
- `clear`: legacy Claude-style clear support; deletes debounce file, re-captures UUID, re-assigns unit

In the Pi namespace, explicit replacement flows (`new`, `fork`, `resume`, `compact`) may replace a stale terminal owner. Plain `startup` keeps the nested-session/subagent protection behavior so a nested Pi process does not steal the parent tab title.

### `session-end-hook.py` (SessionEnd)

Claude behavior:
1. Checks debounce file for `planpending` flag — if set, preserves the title as 🌀 working and writes a terminal-scoped handoff
2. Otherwise resets tab title to folder name
3. Cleans up debounce + origin files
4. Releases unit assignment and terminal UUID

Pi behavior:
1. Keeps debounce + origin files only for replacement flows (`new`, `fork`, `resume`) so active session switches can restore titles
2. On `/new`, `/fork`, and `/resume`, writes a target-session replacement handoff with the outgoing terminal UUID so the replacement session does not depend on whichever Ghostty tab is focused
3. On `/new` and `/resume`, preserves the outgoing visible title/status (for example `🌿 <title>`); `/fork` and plan continuation hand off `🌀 <title>` because they continue active work
4. On `/fork`, also writes a terminal-scoped title handoff so the replacement session inherits the visible title immediately
5. On `/new`, `/fork`, and `/resume`, avoids resetting the tab to the folder name during replacement
6. On normal `quit`, resets the tab title to the folder name and cleans debounce/origin state so the tab no longer appears active
7. Releases unit assignment and terminal UUID for the outgoing process

### Plan Acceptance

`PostToolUse:ExitPlanMode` never fires in Claude Code, so plan acceptance is handled via the `planpending` flag in the debounce file. When `PermissionRequest:ExitPlanMode` fires, the flag is written. `session-end-hook.py` reads this flag, converts the title back to 🌀 working, and writes a short-lived handoff keyed by the Ghostty terminal UUID. The next `SessionStart:clear/startup` consumes that handoff and seeds the new session's debounce file so post-plan tool hooks keep working with the same title.

### Recursion Guard: `_CLAUDE_HOOK_NESTED`

Hooks that fire inside nested `claude` subprocesses would cause recursive execution. All hook scripts check `_CLAUDE_HOOK_NESTED` at the top and exit immediately if set. During Claude `SessionStart`, `session-sound-hook.py` appends `export _CLAUDE_HOOK_NESTED=1` to `CLAUDE_ENV_FILE` so later Bash-launched child `claude` processes inherit the marker before their own hooks fire.

### Claude Subagent Guard

Claude Code includes `agent_id` on hook payloads that fire inside a subagent, and uses `SubagentStart` / `SubagentStop` for dedicated subagent lifecycle events. Ghostty Peon skips those payloads before any sound, terminal capture, title mutation, or cleanup because subagent hooks share the visible parent terminal/session state.

### Sound Deduplication

Sounds are tightly coupled to state changes:
- `task.acknowledge`: Only when a new slug is generated (not on KEEP)
- `input.required`: Only when the emoji state actually changes (existing emoji = skip)
- `session.start`: On Claude startup/clear and Pi startup/new/fork when a unit is assigned (not on resume with existing assignment or compact)

**Question-tool deduplication**: `AskUserQuestion` (Claude Code) / `question` (Pi) can fire both `PreToolUse` and `PermissionRequest`. The `PermissionRequest` handler checks `tool_name` and skips question tools, so only `PreToolUse` handles them (with ⭐, not 🔥).

### Sound Playback

`play_sound(event, session_id)` flow:
1. Look up stored assignment via session index (O(1))
2. Fall back to `PEON_SOUND_CLASS` env var + random unit if no assignment
3. Find sound files in `sounds/{class}/{unit}/{event}/`
4. No-repeat: exclude last-played file for this category
5. Pick random file from remaining candidates
6. Fire `afplay` via `subprocess.Popen()` — non-blocking, fire-and-forget
7. All failures silently caught

### Verifying Claude Install

Claude Code reads hook registrations from `~/.claude/settings.json`. When a fix appears not to take effect, verify the configured commands point at this checkout rather than an old copied path:

```sh
python3 - <<'PY'
import json, pathlib
settings = json.loads(pathlib.Path.home().joinpath('.claude/settings.json').read_text())
for event, entries in settings.get('hooks', {}).items():
    for entry in entries:
        for hook in entry.get('hooks', []):
            cmd = hook.get('command', '')
            if 'ghostty-peon' in cmd:
                print(event, entry.get('matcher', ''), cmd)
PY
```

Expected script paths should reference this repository's `hooks/` files. If they point elsewhere, reinstall:

```sh
node install.js --target claude --yes
```

After hook changes:
- Python hook file changes are picked up on the next hook invocation if Claude settings point at this checkout.
- Changes that depend on `SessionStart` environment propagation, especially `_CLAUDE_HOOK_NESTED` via `CLAUDE_ENV_FILE`, require relaunching Claude Code from a fresh parent session.
- Existing stale visible titles may need a new prompt/session event or manual state cleanup; code changes do not retroactively repair old `/tmp` state.

### Claude `settings.json` Hook Registration

| Hook Script | Event | Matcher | Timeout | Async |
|-------------|-------|---------|---------|-------|
| `tab-attention-hook.py` | `PreToolUse` | `AskUserQuestion` / Pi `question` | 5s | yes |
| `tabtitle-hook.py` | `UserPromptSubmit` | (none) | 30s | yes |
| `tab-attention-hook.py` | `PermissionRequest` | (none) | 5s | yes |
| `tab-attention-hook.py` | `PostToolUse` | (none) | 5s | yes |
| `tab-stop-question-hook.py` | `Stop` | (none) | 20s | yes |
| `session-sound-hook.py` | `SessionStart` | (none) | 5s | yes |
| `session-end-hook.py` | `SessionEnd` | (none) | 1s | no |

All hooks except `session-end-hook.py` run async to avoid blocking the Claude Code UI.

---

## Pi Runtime Support

`ghostty-peon` can also be installed as a Pi extension by this repository's installer:

```sh
node install.js --target pi --yes
```

The installer writes a small managed TypeScript shim and symlinks the changing source directories:

```text
~/.pi/agent/extensions/ghostty-peon/
  index.ts   # managed shim: exports default from ./src/index.js
  src -> /path/to/ghostty-peon/pi-extension
  repo -> /path/to/ghostty-peon
```

`src` means changes under `pi-extension/` are picked up after `/reload` without reinstalling. `repo` means Python hook changes under `hooks/` are picked up by the next hook invocation. Reinstall is only needed when the managed shim/install layout changes. After installing or uninstalling the Pi target, run `/reload` in Pi or restart Pi.

### Pi Event Mapping

Pi does not use Claude Code's `settings.json` hook system. The Pi extension maps Pi events to the same Python scripts used by Claude Code:

| Pi event / integration | Python script | Notes |
|---|---|---|
| `session_start` | `session-sound-hook.py` | startup => `source: "startup"`; new => `source: "new"`; fork => `source: "fork"`; resume => `source: "resume"`; reload skipped |
| `session_shutdown` | `session-end-hook.py` | skipped on reload |
| `before_agent_start` | `tabtitle-hook.py` | uses Claude-like `UserPromptSubmit` payload |
| `tool_call` `question` | `tab-attention-hook.py` | uses Claude-like `PreToolUse` payload |
| `tool_result` | `tab-attention-hook.py` | uses Claude-like `PostToolUse` payload |
| `agent_end` | `tab-stop-question-hook.py` | uses Claude-like `Stop` payload |
| `session_before_fork` | runner log only | records fork intent before replacement |
| `session_before_compact` | runner log only | records compaction intent and token count when available |
| `session_compact` | `session-sound-hook.py` | preserves the session terminal id and restores existing title after compaction; captures only if missing |
| `ghostty-peon:permission` | `tab-attention-hook.py` | optional event bus integration for 🔥 |

The extension runs only in interactive Ghostty sessions so non-interactive Pi runs do not play sounds or attempt AppleScript tab changes.

### Pi Logs and State

Pi uses a separate runtime namespace from Claude Code:

```text
/tmp/pi-tab-hooks.log
/tmp/pi-tab-hooks.prev.log
/tmp/pi-tab-hooks.lastdate
/tmp/pi-tabtitle/
/tmp/pi-tabterminal/
/tmp/pi-plan-handoff/
/tmp/pi-sound-units/
/tmp/pi-sound-session/
/tmp/pi-sound-last/
~/.ghostty-peon/pi-weights.json
```

Pi runner log lines include lifecycle metadata such as `event session_start reason=...`, `event session_shutdown reason=...`, `event session_before_fork`, and `event session_compact`. Use these with the session suffix to distinguish normal startup, trust/new-session flows, fork replacement, resume, and compaction. For replacement flows, look for `replacement handoff written` on shutdown followed by `restored replacement terminal_id=...` on the new session; if the start falls back to `captured terminal_id=...`, there was no usable target-session handoff.

Pi subagent children should not run Ghostty Peon hooks at all. The extension-level interactive check rejects `PI_SUBAGENT_CHILD=1` before event paths run, even if a future subagent process has a TTY.

Claude Code continues to use `/tmp/claude-*` paths and `~/.ghostty-peon/weights.json`.

### Pi Sound Class Lookup

For Pi sessions, the extension resolves `PEON_SOUND_CLASS` as follows:

1. Nearest ancestor `.pi/settings.local.json`.
2. Only if no `.pi/settings.local.json` exists, nearest ancestor `.claude/settings.local.json`.
3. Otherwise environment/default behavior.

If a nearest `.pi/settings.local.json` exists but has no `env.PEON_SOUND_CLASS`, that file wins and Claude settings are not used as fallback.

Use the helper to set project-local sound classes:

```sh
peon-class --target pi undead
peon-class --target both random
```

### Pi Permission Emoji Integration

Claude Code has a native `PermissionRequest` hook, so 🔥 works automatically there. Pi does not expose one universal permission event. For 🔥 in Pi, a security/permission extension must emit `ghostty-peon:permission` events:

```ts
pi.events.emit("ghostty-peon:permission", {
  phase: "start",
  sessionId: ctx.sessionManager.getSessionId(),
  cwd: ctx.cwd,
  toolName: event.toolName,
});

try {
  // show permission UI
} finally {
  pi.events.emit("ghostty-peon:permission", {
    phase: "end",
    sessionId: ctx.sessionManager.getSessionId(),
    cwd: ctx.cwd,
    toolName: event.toolName,
  });
}
```

Without this optional integration, Pi still supports session sounds, tab titles, 🌀 working, ⭐ questions, and 🌿 ready.

### Verifying Pi Install

```sh
ls -l ~/.pi/agent/extensions/ghostty-peon
readlink ~/.pi/agent/extensions/ghostty-peon/src
readlink ~/.pi/agent/extensions/ghostty-peon/repo
```

Expected:

- `index.ts` exists, contains `Managed by ghostty-peon install.js`, and exports from `./src/index.js`.
- `src` points to this repository's `pi-extension/` directory.
- `repo` points to this repository checkout.
- `/tmp/pi-tab-hooks.log` receives `runner` and hook log lines after Pi events.

After Pi extension changes:
- Run `/reload` in Pi or restart Pi for TypeScript extension changes under `pi-extension/`.
- Python hook changes are picked up by the next hook subprocess if the installed `repo` symlink points at this checkout.
- Reinstall only when the managed shim/install layout changes, or when symlink verification fails.

To clear Pi logs/state during debugging:

```sh
> /tmp/pi-tab-hooks.log
rm -rf /tmp/pi-tabtitle /tmp/pi-tabterminal /tmp/pi-plan-handoff /tmp/pi-sound-units /tmp/pi-sound-session /tmp/pi-sound-last
```
