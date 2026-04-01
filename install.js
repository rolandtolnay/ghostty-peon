#!/usr/bin/env node
/**
 * ghostty-peon installer
 *
 * Registers hooks in ~/.claude/settings.json so Claude Code plays
 * Warcraft III sounds and auto-renames Ghostty tabs.
 *
 * Usage:
 *   node install.js              # Install
 *   node install.js --uninstall  # Remove everything
 */

const fs = require("fs");
const path = require("path");
const os = require("os");

// ── Config ──────────────────────────────────────────────────────────────────

const TOOLKIT_NAME = "ghostty-peon";
const CLAUDE_DIR = path.join(os.homedir(), ".claude");
const SETTINGS_PATH = path.join(CLAUDE_DIR, "settings.json");
const MANIFEST_DIR = path.join(os.homedir(), `.${TOOLKIT_NAME}`);
const MANIFEST_PATH = path.join(MANIFEST_DIR, ".manifest.json");
const REPO_ROOT = fs.realpathSync(__dirname);

const OLD_HOOKS_PATH = path.join(os.homedir(), ".claude", "hooks", "ghostty");

const HOOKS = [
  {
    event: "PreToolUse",
    matcher: "AskUserQuestion",
    command: `python3 ${path.join(REPO_ROOT, "hooks", "tab-attention-hook.py")}`,
    timeout: 5,
    async: true,
  },
  {
    event: "UserPromptSubmit",
    command: `python3 ${path.join(REPO_ROOT, "hooks", "tabtitle-hook.py")}`,
    timeout: 30,
    async: true,
  },
  {
    event: "PermissionRequest",
    command: `python3 ${path.join(REPO_ROOT, "hooks", "tab-attention-hook.py")}`,
    timeout: 5,
    async: true,
  },
  {
    event: "PostToolUse",
    command: `python3 ${path.join(REPO_ROOT, "hooks", "tab-attention-hook.py")}`,
    timeout: 5,
    async: true,
  },
  {
    event: "Stop",
    command: `python3 ${path.join(REPO_ROOT, "hooks", "tab-stop-question-hook.py")}`,
    timeout: 20,
    async: true,
  },
  {
    event: "SessionStart",
    command: `python3 ${path.join(REPO_ROOT, "hooks", "session-sound-hook.py")}`,
    timeout: 5,
    async: true,
  },
  {
    event: "SessionEnd",
    command: `python3 ${path.join(REPO_ROOT, "hooks", "session-end-hook.py")}`,
    timeout: 1,
    async: false,
  },
];

// ── Helpers ─────────────────────────────────────────────────────────────────

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function readSettings() {
  if (!fs.existsSync(SETTINGS_PATH)) return {};
  return JSON.parse(fs.readFileSync(SETTINGS_PATH, "utf-8"));
}

function writeSettings(settings) {
  ensureDir(CLAUDE_DIR);
  fs.writeFileSync(SETTINGS_PATH, JSON.stringify(settings, null, 2) + "\n");
}

/** Check if a hook entry's command references this repo. */
function isOurHook(entry) {
  return entry.hooks?.some((h) => h.command?.includes(REPO_ROOT));
}

/** Check if a hook entry references the old ~/.claude/hooks/ghostty/ path. */
function isOldGhosttyHook(entry) {
  return entry.hooks?.some((h) => h.command?.includes(OLD_HOOKS_PATH));
}

// ── Install ─────────────────────────────────────────────────────────────────

function install() {
  console.log(`\nInstalling ${TOOLKIT_NAME} from ${REPO_ROOT}\n`);

  const settings = readSettings();
  if (!settings.hooks) settings.hooks = {};

  let hooksChanged = false;

  // 1. Remove old hooks from ~/.claude/hooks/ghostty/
  for (const event of Object.keys(settings.hooks)) {
    if (!Array.isArray(settings.hooks[event])) continue;
    const before = settings.hooks[event].length;
    settings.hooks[event] = settings.hooks[event].filter(
      (entry) => !isOldGhosttyHook(entry)
    );
    const after = settings.hooks[event].length;
    if (after < before) {
      console.log(`  [ok]   Removed old hook: ${event} (from ~/.claude/hooks/ghostty/)`);
      hooksChanged = true;
    }
    if (settings.hooks[event].length === 0) {
      delete settings.hooks[event];
    }
  }

  // 2. Register new hooks
  for (const hookDef of HOOKS) {
    const { event, command, timeout } = hookDef;
    if (!settings.hooks[event]) settings.hooks[event] = [];

    const already = settings.hooks[event].some(isOurHook);
    if (already) {
      console.log(`  [skip] Hook already registered: ${event}`);
    } else {
      const hookEntry = { type: "command", command, timeout };
      if (hookDef.async) hookEntry.async = true;

      const entry = { hooks: [hookEntry] };
      if (hookDef.matcher) entry.matcher = hookDef.matcher;

      settings.hooks[event].push(entry);
      console.log(`  [ok]   Registered hook: ${event}${hookDef.matcher ? ` [${hookDef.matcher}]` : ""}`);
      hooksChanged = true;
    }
  }

  if (hooksChanged) writeSettings(settings);

  // 3. Write manifest
  ensureDir(MANIFEST_DIR);
  const manifest = {
    version: "1.0.0",
    installedAt: new Date().toISOString(),
    repoRoot: REPO_ROOT,
    hookEvents: HOOKS.map((h) => h.event),
  };
  fs.writeFileSync(MANIFEST_PATH, JSON.stringify(manifest, null, 2) + "\n");

  console.log(`\n  Manifest written to ${MANIFEST_PATH}`);

  // 4. Check Ollama reachability
  try {
    const http = require("http");
    const req = http.get("http://localhost:11434/", { timeout: 3000 }, (res) => {
      console.log(`  Ollama: reachable (status ${res.statusCode})`);
      printDone();
    });
    req.on("error", () => {
      console.log(`  Ollama: NOT reachable — make sure Ollama is running`);
      printDone();
    });
    req.on("timeout", () => {
      req.destroy();
      console.log(`  Ollama: NOT reachable — make sure Ollama is running`);
      printDone();
    });
  } catch {
    printDone();
  }
}

function printDone() {
  console.log(`\nDone! Next steps:`);
  console.log(`  1. Make sure Ollama is running: ollama pull qwen3.5:4b`);
  console.log(`  2. Source the shell function (optional):`);
  console.log(`     source ${path.join(REPO_ROOT, "peon-class.sh")}`);
  console.log(`  3. Or add to your shell config:`);
  console.log(`     echo 'source ${path.join(REPO_ROOT, "peon-class.sh")}' >> ~/.zshrc`);
  console.log(``);
}

// ── Uninstall ───────────────────────────────────────────────────────────────

function uninstall() {
  console.log(`\nUninstalling ${TOOLKIT_NAME}\n`);

  // Read manifest for repo root (handles case where uninstall runs from different dir)
  let repoRoot = REPO_ROOT;
  if (fs.existsSync(MANIFEST_PATH)) {
    try {
      const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, "utf-8"));
      repoRoot = manifest.repoRoot || REPO_ROOT;
    } catch {}
  }

  // 1. Remove hooks from settings.json
  if (fs.existsSync(SETTINGS_PATH)) {
    const settings = readSettings();
    let changed = false;

    if (settings.hooks) {
      for (const { event } of HOOKS) {
        if (!settings.hooks[event]) continue;

        const before = settings.hooks[event].length;
        settings.hooks[event] = settings.hooks[event].filter(
          (entry) =>
            !entry.hooks?.some((h) => h.command?.includes(repoRoot))
        );
        const after = settings.hooks[event].length;

        if (after < before) {
          console.log(`  [ok]   Removed hook: ${event}`);
          changed = true;
        } else {
          console.log(`  [skip] Hook not found: ${event}`);
        }

        // Clean up empty arrays
        if (settings.hooks[event].length === 0) {
          delete settings.hooks[event];
        }
      }

      // Clean up empty hooks object
      if (Object.keys(settings.hooks).length === 0) {
        delete settings.hooks;
      }
    }

    if (changed) writeSettings(settings);
  }

  // 2. Remove manifest
  if (fs.existsSync(MANIFEST_PATH)) {
    fs.unlinkSync(MANIFEST_PATH);
    console.log(`  [ok]   Removed manifest`);
  }
  if (fs.existsSync(MANIFEST_DIR)) {
    try {
      fs.rmdirSync(MANIFEST_DIR);
    } catch {}
  }

  console.log(`\nDone! ${TOOLKIT_NAME} has been uninstalled.\n`);
}

// ── Main ────────────────────────────────────────────────────────────────────

const args = process.argv.slice(2);

if (args.includes("--help") || args.includes("-h")) {
  console.log(`
Usage: node install.js [options]

Options:
  --uninstall   Remove hooks and manifest
  --help        Show this help
`);
  process.exit(0);
}

if (args.includes("--uninstall")) {
  uninstall();
} else {
  install();
}
