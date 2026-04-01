# Debugging Guide

Architecture details, log format, and troubleshooting for ghostty-peon hooks.

---

## Architecture Overview

```
settings.json hooks config
    │
    ├─ PreToolUse
    │    └─ AskUserQuestion ─► tab-attention-hook.py ──► add ⭐ + input.required sound
    │
    ├─ UserPromptSubmit ──────► tabtitle-hook.py ──► Ollama slug ──► set title + task.acknowledge sound
    │
    ├─ PermissionRequest ────► tab-attention-hook.py ──► add 🔥 + input.required sound (skips AskUserQuestion)
    │
    ├─ PostToolUse
    │    └─ AskUserQuestion ──► tab-attention-hook.py ──► clear emoji → restore 🌀
    │
    ├─ Stop ──────────────────► tab-stop-question-hook.py ──► Ollama question check ──► add ⭐ or 🌿
    │
    ├─ SessionStart
    │    ├─ startup ──────────► session-sound-hook.py ──► assign_unit() + session.start sound
    │    ├─ clear ────────────► session-sound-hook.py ──► delete debounce + re-assign unit
    │    └─ resume ───────────► session-sound-hook.py ──► assign_unit() if no existing assignment
    │
    └─ SessionEnd ────────────► session-end-hook.py ──► release_unit() + reset title
```

## File Map

| File | Purpose |
|------|---------|
| `hooks/sound_utils.py` | Shared module: `set_tab_title()`, `capture_terminal_id()`, `play_sound()`, `assign_unit()`, `release_unit()`, `log()` |
| `hooks/tabtitle-hook.py` | UserPromptSubmit: sets 🌀 working emoji, generates slug via Ollama, plays task.acknowledge |
| `hooks/tab-attention-hook.py` | PreToolUse/PermissionRequest: sets attention emoji; PostToolUse clears it |
| `hooks/tab-stop-question-hook.py` | Stop: heuristic question detection via Ollama, sets ⭐ or 🌿 |
| `hooks/session-sound-hook.py` | SessionStart: assigns unit + plays session.start on startup; re-assigns on clear |
| `hooks/session-end-hook.py` | SessionEnd: releases unit assignment, resets tab title to folder name |
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

All hooks log every code path — including skips, failures, and no-ops. Every exit from every hook produces at least one log line explaining why. If a hook fires and there is **no log line at all**, it means the hook runner itself failed (timeout, crash) before the script executed.

### Log Format

```
HH:MM:SS.mmm [sid] hook       | message
```

- `HH:MM:SS.mmm` — wall-clock timestamp with millisecond precision
- `[sid]` — last 6 characters of the full session ID (stable within a session, unique across concurrent sessions)
- `hook` — left-padded to 10 chars. Values: `session`, `tabtitle`, `attention`, `stop-q`, `plan-accept`, `sound`
- `message` — free-form, always starts with one of: an action (`startup ->`, `set ->`, `cleared attention ->`), a skip reason (`skip: ...`), a delegation (`calling llm`, `llm ->`), or a failure (`set_tab_title failed`, `llm error`)

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
- `skip: cooldown (Xs elapsed, 90s required)` — still within the cooldown window
- `llm returned None` — Ollama timed out (10s timeout) or returned an invalid slug
- `llm error: ...` — Ollama not running or model not available
- `set_tab_title failed` — Ghostty AppleScript failed (window not focused, Ghostty not running)
- `target: SKIPPED (no term_id, refusing unsafe fallback)` — terminal UUID was lost

**Attention emoji not appearing:**
Look for `attention` lines and `stop-q` lines:
- `skip: stop_hook_active` — the Stop hook was triggered inside another Stop hook (loop prevention)
- `skip: no '?' in last 500 chars` — pre-filter blocked LLM call
- `llm -> False (model answered 'NO')` — Ollama classified the response as not requiring user action
- `llm -> False (llm error: ...)` — Ollama call failed
- `skip: ⭐ already showing` — emoji was already set, deduplication fired
- No `stop-q` lines at all — the hook itself didn't fire; check `settings.json` Stop entry

**Wrong emoji (🔥 instead of ⭐ for AskUserQuestion):**
Look for `attention` lines:
- Should see `PreToolUse:AskUserQuestion` log line first, then `skip: AskUserQuestion handled by PreToolUse` for the PermissionRequest
- If `PreToolUse` line is missing, the `PreToolUse[AskUserQuestion]` hook entry may be missing from `settings.json`

**Sound not playing:**
Look for `sound` lines in the log:
- `skip session.start: class=none` — sounds disabled via `peon-class none`
- `skip ...: dir missing (class/unit/event)` — sound files not found
- `skip ...: invalid class=...` — invalid PEON_SOUND_CLASS value

Check your sound class setting:
```sh
peon-class          # shows current setting
```

**Unit assignment issues:**
Check the assignment files:
```sh
ls -la /tmp/claude-sound-units/*/         # all project assignments
ls -la /tmp/claude-sound-session/         # session index
cat /tmp/claude-sound-units/*/<session_id>  # shows class\nunit for a session
```

**Clearing the log:**
```sh
> /tmp/claude-tab-hooks.log   # truncate
rm /tmp/claude-tab-hooks.log  # delete (recreated automatically on next hook fire)
```

### Inspecting the Debounce File

The debounce file is the shared state between all hooks for a given session:

```sh
cat /tmp/claude-tabtitle/<session_id>
# line 1: unix timestamp of last rename
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

---

## Hook Implementation Details

### `tabtitle-hook.py` (UserPromptSubmit)

The most complex hook. Flow:

1. **Recursion guard**: Check `_CLAUDE_HOOK_NESTED` env var, exit if set
2. **Read debounce file**: Get current title
3. **Set working emoji**: Replace any attention emoji with 🌀
4. **Debounce check**: Skip if within 90s cooldown or message is short (<40 chars). First message always triggers.
5. **Generate slug**: Call local Ollama model via `client.py` (10s timeout)
6. **Set title + sound**: If new slug generated, set title with 🌀 and play `task.acknowledge`. Write debounce file.

The slug prompt asks the model to output a 2-5 word hyphenated slug or `KEEP` if the current title still fits. Validation rejects anything with spaces, special characters, error markers, or over 40 chars.

### `tab-attention-hook.py` (attention emoji + clear)

Registered on three events via separate entries in `settings.json`:
- `PreToolUse[AskUserQuestion]` → ⭐
- `PermissionRequest` → 🔥 (skips AskUserQuestion since PreToolUse handles it)
- `PostToolUse` → clears emoji, restores 🌀

### `tab-stop-question-hook.py` (Stop)

Tier 2 heuristic for detecting when Claude stops with a question.

1. Pre-filter: skip if no `?` in the last 500 chars (~80% of stops filtered out cheaply)
2. Check debounce file — skip if ⭐ emoji already showing
3. Call Ollama to classify whether the text is asking for user input (YES/NO)
4. If YES: set ⭐ + play `input.required`. If NO: set 🌿 (ready, no sound).

### `session-sound-hook.py` (SessionStart)

Handles three `source` values:
- `startup`: captures terminal UUID, assigns unit via `assign_unit()`, plays `session.start`
- `clear`: deletes debounce file, re-captures UUID, re-assigns unit
- `resume`: captures UUID, assigns unit only if no existing assignment

### `session-end-hook.py` (SessionEnd)

1. Checks debounce file for `planpending` flag — if set, preserves title instead of resetting
2. Otherwise resets tab title to folder name
3. Cleans up debounce + origin files
4. Releases unit assignment and terminal UUID

### Plan Acceptance

`PostToolUse:ExitPlanMode` never fires in Claude Code, so plan acceptance is handled via the `planpending` flag in the debounce file. When `PermissionRequest:ExitPlanMode` fires, the flag is written. `session-end-hook.py` reads this flag and preserves the current title instead of resetting to the folder name.

### Recursion Guard: `_CLAUDE_HOOK_NESTED`

Hooks that fire inside nested `claude` subprocesses would cause recursive execution. All hook scripts check `_CLAUDE_HOOK_NESTED` at the top and exit immediately if set. The env var propagates from parent processes to all hooks they fire.

### Sound Deduplication

Sounds are tightly coupled to state changes:
- `task.acknowledge`: Only when a new slug is generated (not on KEEP)
- `input.required`: Only when the emoji state actually changes (existing emoji = skip)
- `session.start`: Only on startup/clear (not on resume with existing assignment)

**AskUserQuestion deduplication**: `AskUserQuestion` fires both `PreToolUse` and `PermissionRequest`. The `PermissionRequest` handler checks `tool_name` and skips `AskUserQuestion`, so only `PreToolUse` handles it (with ⭐, not 🔥).

### Sound Playback

`play_sound(event, session_id)` flow:
1. Look up stored assignment via session index (O(1))
2. Fall back to `PEON_SOUND_CLASS` env var + random unit if no assignment
3. Find sound files in `sounds/{class}/{unit}/{event}/`
4. No-repeat: exclude last-played file for this category
5. Pick random file from remaining candidates
6. Fire `afplay` via `subprocess.Popen()` — non-blocking, fire-and-forget
7. All failures silently caught

### settings.json Hook Registration

| Hook Script | Event | Matcher | Timeout | Async |
|-------------|-------|---------|---------|-------|
| `tab-attention-hook.py` | `PreToolUse` | `AskUserQuestion` | 5s | yes |
| `tabtitle-hook.py` | `UserPromptSubmit` | (none) | 30s | yes |
| `tab-attention-hook.py` | `PermissionRequest` | (none) | 5s | yes |
| `tab-attention-hook.py` | `PostToolUse` | (none) | 5s | yes |
| `tab-stop-question-hook.py` | `Stop` | (none) | 20s | yes |
| `session-sound-hook.py` | `SessionStart` | (none) | 5s | yes |
| `session-end-hook.py` | `SessionEnd` | (none) | 1s | no |

All hooks except `session-end-hook.py` run async to avoid blocking the Claude Code UI.
