# ghostty-peon

Warcraft III-themed notifications for AI coding sessions in Ghostty.

`ghostty-peon` keeps your terminal tabs recognizable while agents work: it renames tabs to short task titles, shows status emojis, and plays Warcraft III unit voice lines when sessions start, tasks change, or your input is needed.

It supports both [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and [Pi](https://github.com/mariozechner/pi). Install it for one runtime or both from the same checkout.

## What it does

- Renames Ghostty tabs to concise task slugs like `fix-auth-token` or `refactor-cache-layer`.
- Shows status emojis in the tab title so you can see whether an agent is working, ready, blocked, or waiting for input.
- Assigns each session a distinct Warcraft III unit voice so concurrent tabs are easy to tell apart by sound.
- Plays focus-aware attention sounds only when useful; the visual emoji still updates even when sound is skipped.
- Works per project, with optional sound class preferences for Claude Code, Pi, or both.

## Supported runtimes

| Runtime | Support |
|---|---|
| Claude Code | Full support via Claude Code hooks |
| Pi | Full tab title, sound, question, and ready support via a Pi extension |

One caveat: the 🔥 permission/blocked emoji is native in Claude Code. In Pi, 🔥 requires an optional compatible permission/security extension that emits `ghostty-peon:permission` events. Without that integration, Pi still supports all other features.

## Features

### Tab titles

Tabs auto-rename to a short action slug using a local LLM. Titles update when you shift to a different task and stay stable during follow-up messages on the same topic.

### Status emojis

| Emoji | Meaning | When |
|-------|---------|------|
| 🌀 | Working | The agent is processing |
| ⭐ | Question | The agent asked you something |
| 🔥 | Blocked | A permission prompt is waiting |
| 🌿 | Ready | The agent finished and no input is needed |

### Sound effects

Three events trigger Warcraft III voice lines:

| Event | Sound Type | Example |
|-------|-----------|---------|
| Session start | "Ready" | *"Ready to work!"* |
| Tab title change | "Yes" / acknowledge | *"Work, work."* |
| Input needed | "What" / question | *"Something need doing?"* |

Sounds are focus-aware: the input-needed sound only plays when you're looking at a different tab. The emoji still appears regardless.

## Sound classes

Four classes with 7 units each. Sessions are assigned a unique unit per project so concurrent tabs have distinct voices.

| Class | Units |
|-------|-------|
| Orc | Peon, Grunt, Headhunter, Witch Doctor, Tauren, Shadow Hunter, Shaman |
| Human | Peasant, Footman, Knight, Rifleman, Sorceress, Gryphon Rider, Priest |
| Night Elf | Archer, Huntress, Warden, Druid of the Claw, Druid of the Talon, Demon Hunter, Dryad |
| Undead | Acolyte, Crypt Fiend, Necromancer, Ghoul, Abomination, Dreadlord, Banshee |

## Requirements

- macOS
- [Ghostty](https://ghostty.org/) terminal
- Claude Code and/or Pi
- [Ollama](https://ollama.com/) with the default local model: `qwen3.5:4b`
- `python3` (system Python; no pip dependencies)
- Node.js (installer only)

## Installation

```bash
git clone https://github.com/rolandtolnay/ghostty-peon.git
cd ghostty-peon

ollama pull qwen3.5:4b
node install.js
```

`node install.js` starts an interactive installer where you can choose:

1. Claude Code
2. Pi
3. Both

For non-interactive installs, pass an explicit target:

```bash
node install.js --target claude --yes
node install.js --target pi --yes
node install.js --target all --yes
```

After installing for Pi, run `/reload` in Pi or restart Pi.

### What gets installed

- Claude Code target: hook registrations in `~/.claude/settings.json`.
- Pi target: a managed extension in `~/.pi/agent/extensions/ghostty-peon/` with a `repo` symlink back to this checkout.
- Both targets: a shared manifest at `~/.ghostty-peon/.manifest.json`.

Sound files and source files stay in this repository checkout.

## Choosing sound classes

Source the helper function once:

```bash
source /path/to/ghostty-peon/peon-class.sh
```

Then use it in any project directory:

```bash
peon-class orc                         # Claude Code setting for this project
peon-class --target pi undead          # Pi setting for this project
peon-class --target both random        # Both runtimes
peon-class --target all none           # Disable sounds for both runtimes
peon-class                             # Show Claude Code setting
peon-class --target both               # Show both settings
```

Settings are project-local:

- Claude Code: `.claude/settings.local.json`
- Pi: `.pi/settings.local.json`

## Configuration

### Changing the LLM model

The default model is `qwen3.5:4b` via local Ollama. To use a different model, edit the `MODEL` constant in `client.py`:

```python
MODEL = "qwen3.5:4b"  # Change to any Ollama model
```

For a non-Ollama backend, replace the `llm()` function body in `client.py`. The hooks only depend on the signature: `llm(prompt, system=, temperature=, max_tokens=, num_ctx=, tag=, timeout=) -> str`.

### Custom sounds

Sounds are organized as `sounds/{class}/{unit}/{event}/*.caf`. To add custom sound packs:

1. Create a new class directory under `sounds/`.
2. Add unit subdirectories with `session.start/`, `task.acknowledge/`, and `input.required/` folders.
3. Place audio files in each event folder (CAF, WAV, or any format `afplay` supports).
4. Add the class name to `VALID_CLASSES` and `UNITS` in `hooks/sound_utils.py`.

### Volume

Sound playback volume is set in `hooks/sound_utils.py`:

```python
PLAYBACK_VOLUME = "0.07"  # 0.0 to 1.0
```

## Uninstall

```bash
node install.js --uninstall                    # interactive in a TTY
node install.js --uninstall --target claude --yes
node install.js --uninstall --target pi --yes
node install.js --uninstall --target all --yes
```

Uninstall removes managed hook/extension registrations for the selected target. Sound files and the repository itself are not removed.

## Debugging

See [docs/debugging.md](docs/debugging.md) for log format, architecture details, and troubleshooting common issues.

Log files:

- Claude Code: `/tmp/claude-tab-hooks.log`
- Pi: `/tmp/pi-tab-hooks.log`

## Attribution

Sound effects are from Warcraft III: Reign of Chaos by Blizzard Entertainment. They are included in this repository for personal, non-commercial use as notification sounds. All audio content is property of Blizzard Entertainment. These files will be removed upon request from the rights holder.

## License

MIT (code). See [LICENSE](LICENSE).
