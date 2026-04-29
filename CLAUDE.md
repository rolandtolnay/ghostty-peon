# ghostty-peon

Warcraft III-themed tab title and sound hooks for Claude Code/Pi + Ghostty terminal.

## File Layout

- `hooks/` — Python hook scripts shared by Claude Code hooks and the Pi extension
- `sounds/` — CAF audio files organized as `{class}/{unit}/{event}/`
- `client.py` — Standalone Ollama HTTP client (pure stdlib, no pip deps)
- `pi-extension/` — TypeScript Pi extension wrapper around the shared Python hooks
- `install.js` — Multi-runtime installer: `--target claude|pi|all`, writes manifest
- `peon-class.sh` — Bash function for switching sound classes per project/runtime

## Key Paths

- Runtime state: `~/.ghostty-peon/` (`weights.json`, `pi-weights.json`, `.manifest.json`)
- Claude logs/state: `/tmp/claude-tab-hooks.log`, `/tmp/claude-tabtitle/`, `/tmp/claude-sound-units/`, `/tmp/claude-tabterminal/`
- Pi logs/state: `/tmp/pi-tab-hooks.log`, `/tmp/pi-tabtitle/`, `/tmp/pi-sound-units/`, `/tmp/pi-tabterminal/`
- Pi extension install path: `~/.pi/agent/extensions/ghostty-peon/`

## Core Module

`hooks/sound_utils.py` is the shared module — emoji config, sound playback, tab targeting, unit assignment, and logging all live here. Most changes start in this file.

## Testing

Manual verification: install the target (`node install.js --target claude|pi --yes`), start a Claude Code or Pi session in Ghostty, and check:
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
