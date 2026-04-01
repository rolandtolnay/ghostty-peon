# ghostty-peon

Warcraft III-themed tab title and sound hooks for Claude Code + Ghostty terminal.

## File Layout

- `hooks/` — Python hook scripts registered via Claude Code settings.json
- `sounds/` — CAF audio files organized as `{class}/{unit}/{event}/`
- `client.py` — Standalone Ollama HTTP client (pure stdlib, no pip deps)
- `install.js` — Installer: registers hooks in settings.json, writes manifest
- `peon-class.sh` — Bash function for switching sound classes per project

## Key Paths

- Runtime state: `~/.ghostty-peon/` (weights.json, .manifest.json)
- Logs: `/tmp/claude-tab-hooks.log`
- Debounce: `/tmp/claude-tabtitle/`
- Unit assignments: `/tmp/claude-sound-units/`
- Terminal IDs: `/tmp/claude-tabterminal/`

## Core Module

`hooks/sound_utils.py` is the shared module — emoji config, sound playback, tab targeting, unit assignment, and logging all live here. Most changes start in this file.

## Testing

Manual verification: start a Claude Code session in any project and check:
1. Session start sound plays
2. Tab title renames on first substantive message
3. Attention emojis appear on questions/permissions
4. Tab resets to folder name on session end

See `docs/debugging.md` for log inspection and troubleshooting.

## Dependencies

- python3 (system) — all hooks are pure stdlib
- Ollama with qwen3.5:4b — for slug generation and question classification
- macOS (afplay, osascript) — sound playback and Ghostty tab control
- Ghostty terminal — tab title API via AppleScript
- Node.js — installer only
