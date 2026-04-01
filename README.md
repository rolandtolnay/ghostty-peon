# ghostty-peon

Warcraft III-themed hooks for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) that auto-rename [Ghostty](https://ghostty.org/) terminal tabs, show status emojis, and play unit voice lines on key events.

Each Claude Code session gets assigned a unique Warcraft III unit (Peon, Knight, Dryad, etc.) so you can identify tabs by their voice. Tab titles update automatically based on what you're working on, and emojis indicate when Claude needs your attention.

## Features

### Tab Titles

Tabs auto-rename to a short action slug (e.g., `fix-auth-token`, `refactor-cache-layer`) using a local LLM. Titles update when you shift to a different task and stay stable during follow-up messages on the same topic.

### Status Emojis

| Emoji | Meaning | When |
|-------|---------|------|
| 🌀 | Working | Claude is processing |
| ⭐ | Question | Claude asked you something |
| 🔥 | Blocked | Permission prompt waiting |
| 🌿 | Ready | Claude finished, no input needed |

### Sound Effects

Three events trigger Warcraft III voice lines:

| Event | Sound Type | Example |
|-------|-----------|---------|
| Session start | "Ready" | *"Ready to work!"* |
| Tab title change | "Yes" / acknowledge | *"Work, work."* |
| Input needed | "What" / question | *"Something need doing?"* |

Sounds are **focus-aware** — the "input needed" sound only plays when you're looking at a different tab. The emoji still appears regardless.

## Sound Classes

Four classes with 7 units each. Sessions are assigned a unique unit per project so concurrent tabs have distinct voices.

| Class | Units |
|-------|-------|
| Orc | Peon, Grunt, Headhunter, Witch Doctor, Tauren, Shadow Hunter, Shaman |
| Human | Peasant, Footman, Knight, Rifleman, Sorceress, Gryphon Rider, Priest |
| Night Elf | Archer, Huntress, Warden, Druid of the Claw, Druid of the Talon, Demon Hunter, Dryad |
| Undead | Acolyte, Crypt Fiend, Necromancer, Ghoul, Abomination, Dreadlord, Banshee |

## Requirements

- [Ghostty](https://ghostty.org/) terminal (macOS)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
- [Ollama](https://ollama.com/) with a local model (default: `qwen3.5:4b`)
- macOS (uses `afplay` for sound, `osascript` for tab control)
- python3 (system — no pip dependencies)
- Node.js (installer only)

## Installation

```bash
git clone https://github.com/rolandtolnay/ghostty-peon.git
cd ghostty-peon

# Pull the local LLM model
ollama pull qwen3.5:4b

# Register hooks in Claude Code
node install.js
```

The installer registers all hooks in `~/.claude/settings.json` and writes a manifest to `~/.ghostty-peon/`.

### Shell function (optional)

To switch sound classes per project, source the helper function:

```bash
# Add to ~/.bashrc or ~/.zshrc
source /path/to/ghostty-peon/peon-class.sh
```

Then use it in any project directory:

```bash
peon-class orc       # Use Orc sounds for this project
peon-class human     # Use Human sounds
peon-class nightelf  # Use Night Elf sounds
peon-class undead    # Use Undead sounds
peon-class random    # Random class per session (default)
peon-class none      # Disable sounds
peon-class           # Show current setting
```

The setting is stored in `.claude/settings.local.json` (per-project, gitignored by Claude Code).

## Configuration

### Changing the LLM model

The default model is `qwen3.5:4b` via local Ollama. To use a different model, edit the `MODEL` constant in `client.py`:

```python
MODEL = "qwen3.5:4b"  # Change to any Ollama model
```

For a non-Ollama backend, replace the `llm()` function body in `client.py`. The hooks only depend on the signature: `llm(prompt, system=, temperature=, max_tokens=, num_ctx=, tag=, timeout=) -> str`.

### Custom sounds

Sounds are organized as `sounds/{class}/{unit}/{event}/*.caf`. To add custom sound packs:

1. Create a new class directory under `sounds/`
2. Add unit subdirectories with `session.start/`, `task.acknowledge/`, and `input.required/` folders
3. Place audio files in each event folder (CAF, WAV, or any format `afplay` supports)
4. Add the class name to `VALID_CLASSES` and `UNITS` in `hooks/sound_utils.py`

### Volume

Sound playback volume is set in `hooks/sound_utils.py`:

```python
PLAYBACK_VOLUME = "0.07"  # 0.0 to 1.0
```

## Uninstall

```bash
node install.js --uninstall
```

This removes all hook registrations from `~/.claude/settings.json` and deletes the manifest. Sound files and the repository itself are not removed.

## Debugging

See [docs/debugging.md](docs/debugging.md) for log format, architecture details, and troubleshooting common issues.

Logs are written to `/tmp/claude-tab-hooks.log` with per-session IDs for filtering.

## Attribution

Sound effects are from Warcraft III: Reign of Chaos by Blizzard Entertainment. They are included in this repository for personal, non-commercial use as notification sounds. All audio content is property of Blizzard Entertainment. These files will be removed upon request from the rights holder.

## License

MIT (code). See [LICENSE](LICENSE).
