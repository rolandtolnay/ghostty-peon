#!/usr/bin/env node
/**
 * ghostty-peon installer
 *
 * Installs Ghostty tab title/status/sound hooks for Claude Code, Pi, or both.
 *
 * Usage:
 *   node install.js                         # Interactive install in a TTY
 *   node install.js --target claude --yes   # Scriptable Claude install
 *   node install.js --target pi --yes       # Scriptable Pi install
 *   node install.js --uninstall             # Interactive uninstall in a TTY
 */

const fs = require("fs");
const path = require("path");
const os = require("os");
const readline = require("readline/promises");

// ── Config ──────────────────────────────────────────────────────────────────

const TOOLKIT_NAME = "ghostty-peon";
const MANIFEST_VERSION = "2.0.0";
const TARGETS = new Set(["claude", "pi", "all"]);
const SOUND_CLASSES = new Set(["orc", "human", "nightelf", "undead", "random", "none", "skip"]);

const CLAUDE_DIR = path.join(os.homedir(), ".claude");
const SETTINGS_PATH = path.join(CLAUDE_DIR, "settings.json");
const MANIFEST_DIR = path.join(os.homedir(), `.${TOOLKIT_NAME}`);
const MANIFEST_PATH = path.join(MANIFEST_DIR, ".manifest.json");
const REPO_ROOT = fs.realpathSync(__dirname);

const PI_AGENT_DIR = process.env.PI_CODING_AGENT_DIR || path.join(os.homedir(), ".pi", "agent");
const PI_EXTENSION_DIR = path.join(PI_AGENT_DIR, "extensions", TOOLKIT_NAME);
const PI_EXTENSION_INDEX = path.join(PI_EXTENSION_DIR, "index.ts");
const PI_REPO_LINK = path.join(PI_EXTENSION_DIR, "repo");
const PI_EXTENSION_SOURCE_DIR = path.join(REPO_ROOT, "pi-extension");
const PI_EXTENSION_SOURCE = path.join(PI_EXTENSION_SOURCE_DIR, "index.ts");
const PI_EXTENSION_MARKER = "Managed by ghostty-peon install.js";

const OLD_HOOKS_PATH = path.join(os.homedir(), ".claude", "hooks", "ghostty");
const OLD_HOOKS_TILDE = "~/.claude/hooks/ghostty";

function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`;
}

const HOOKS = [
  {
    event: "PreToolUse",
    matcher: "AskUserQuestion",
    script: "tab-attention-hook.py",
    timeout: 5,
    async: true,
  },
  {
    event: "UserPromptSubmit",
    script: "tabtitle-hook.py",
    timeout: 30,
    async: true,
  },
  {
    event: "PermissionRequest",
    script: "tab-attention-hook.py",
    timeout: 5,
    async: true,
  },
  {
    event: "PostToolUse",
    script: "tab-attention-hook.py",
    timeout: 5,
    async: true,
  },
  {
    event: "Stop",
    script: "tab-stop-question-hook.py",
    timeout: 20,
    async: true,
  },
  {
    event: "SessionStart",
    script: "session-sound-hook.py",
    timeout: 5,
    async: true,
  },
  {
    event: "SessionEnd",
    script: "session-end-hook.py",
    timeout: 1,
    async: false,
  },
].map((hook) => ({
  ...hook,
  command: `python3 ${shellQuote(path.join(REPO_ROOT, "hooks", hook.script))}`,
}));

// ── Helpers ─────────────────────────────────────────────────────────────────

function ensureDir(dir) {
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
}

function readJson(file, fallback = {}) {
  if (!fs.existsSync(file)) return fallback;
  return JSON.parse(fs.readFileSync(file, "utf-8"));
}

function writeJson(file, data) {
  ensureDir(path.dirname(file));
  fs.writeFileSync(file, JSON.stringify(data, null, 2) + "\n");
}

function readSettings() {
  return readJson(SETTINGS_PATH, {});
}

function writeSettings(settings) {
  writeJson(SETTINGS_PATH, settings);
}

function readManifest() {
  try {
    return readJson(MANIFEST_PATH, null);
  } catch {
    return null;
  }
}

function writeManifest(manifest) {
  ensureDir(MANIFEST_DIR);
  writeJson(MANIFEST_PATH, {
    ...manifest,
    version: MANIFEST_VERSION,
    installedAt: new Date().toISOString(),
    repoRoot: REPO_ROOT,
    targets: manifest.targets || {},
  });
}

function removeManifestIfEmpty(manifest) {
  if (manifest?.targets && Object.keys(manifest.targets).length > 0) {
    writeManifest(manifest);
    return;
  }

  if (fs.existsSync(MANIFEST_PATH)) {
    fs.unlinkSync(MANIFEST_PATH);
    console.log(`  [ok]   Removed manifest`);
  }
  if (fs.existsSync(MANIFEST_DIR)) {
    try {
      fs.rmdirSync(MANIFEST_DIR);
    } catch {}
  }
}

function parseArgs(argv) {
  const result = {
    uninstall: false,
    target: undefined,
    help: false,
    force: false,
    yes: false,
    soundClass: undefined,
  };

  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--help" || arg === "-h") result.help = true;
    else if (arg === "--uninstall") result.uninstall = true;
    else if (arg === "--force") result.force = true;
    else if (arg === "--yes" || arg === "-y") result.yes = true;
    else if (arg === "--claude") result.target = "claude";
    else if (arg === "--pi") result.target = "pi";
    else if (arg === "--all") result.target = "all";
    else if (arg === "--target") result.target = argv[++i];
    else if (arg.startsWith("--target=")) result.target = arg.slice("--target=".length);
    else if (arg === "--sound-class") result.soundClass = argv[++i];
    else if (arg.startsWith("--sound-class=")) result.soundClass = arg.slice("--sound-class=".length);
    else throw new Error(`Unknown argument: ${arg}`);
  }

  if (result.target) {
    result.target = result.target.toLowerCase();
    if (!TARGETS.has(result.target)) throw new Error(`Invalid target: ${result.target}. Use claude, pi, or all.`);
  }

  if (result.soundClass) {
    result.soundClass = result.soundClass.toLowerCase();
    if (!SOUND_CLASSES.has(result.soundClass)) {
      throw new Error(`Invalid sound class: ${result.soundClass}. Use orc, human, nightelf, undead, random, none, or skip.`);
    }
  }

  return result;
}

function expandTargets(target) {
  if (target === "all") return ["claude", "pi"];
  return [target];
}

function installedTargetFromManifest(manifest) {
  const targets = manifest?.targets ? Object.keys(manifest.targets).filter((target) => target === "claude" || target === "pi") : [];
  if (targets.includes("claude") && targets.includes("pi")) return "all";
  if (targets.includes("claude")) return "claude";
  if (targets.includes("pi")) return "pi";
  return undefined;
}

function isTty() {
  return Boolean(process.stdin.isTTY && process.stdout.isTTY);
}

function normalizeChoice(answer, defaultValue, choices) {
  const value = answer.trim().toLowerCase() || defaultValue;
  return choices[value] || choices[Object.keys(choices).find((key) => choices[key] === value)] || value;
}

async function withReadline(callback) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  try {
    return await callback(rl);
  } finally {
    rl.close();
  }
}

async function promptForInstallTarget(manifest) {
  const manifestDefault = installedTargetFromManifest(manifest);
  const defaultTarget = manifestDefault || "all";
  return withReadline(async (rl) => {
    console.log(`\nInstall ${TOOLKIT_NAME} for:`);
    console.log(`  1) Claude Code`);
    console.log(`  2) Pi`);
    console.log(`  3) Both`);
    const answer = await rl.question(`Target [${defaultTarget}]: `);
    const target = normalizeChoice(answer, defaultTarget, {
      "1": "claude",
      claude: "claude",
      "claude code": "claude",
      "2": "pi",
      pi: "pi",
      "3": "all",
      both: "all",
      all: "all",
    });
    if (!TARGETS.has(target)) throw new Error(`Invalid target: ${target}`);
    return target;
  });
}

async function promptForUninstallTarget(manifest) {
  const defaultTarget = installedTargetFromManifest(manifest) || "all";
  return withReadline(async (rl) => {
    console.log(`\nUninstall ${TOOLKIT_NAME} from:`);
    console.log(`  1) Claude Code`);
    console.log(`  2) Pi`);
    console.log(`  3) Both`);
    const answer = await rl.question(`Target [${defaultTarget}]: `);
    const target = normalizeChoice(answer, defaultTarget, {
      "1": "claude",
      claude: "claude",
      "claude code": "claude",
      "2": "pi",
      pi: "pi",
      "3": "all",
      both: "all",
      all: "all",
    });
    if (!TARGETS.has(target)) throw new Error(`Invalid target: ${target}`);
    return target;
  });
}

async function promptForSoundClass() {
  return withReadline(async (rl) => {
    console.log(`\nOptional default sound class for this project:`);
    console.log(`  skip, random, orc, human, nightelf, undead, none`);
    const answer = await rl.question(`Sound class [skip]: `);
    const soundClass = (answer.trim().toLowerCase() || "skip");
    if (!SOUND_CLASSES.has(soundClass)) throw new Error(`Invalid sound class: ${soundClass}`);
    return soundClass;
  });
}

async function confirmSummary({ uninstall, targets, soundClass, yes }) {
  if (yes) return true;
  if (!isTty()) return true;
  return withReadline(async (rl) => {
    console.log(`\nSummary:`);
    console.log(`  Action: ${uninstall ? "uninstall" : "install"}`);
    console.log(`  Targets: ${targets.join(", ")}`);
    if (!uninstall && soundClass && soundClass !== "skip") console.log(`  Sound class: ${soundClass}`);
    const answer = await rl.question(`Proceed? [y/N]: `);
    return ["y", "yes"].includes(answer.trim().toLowerCase());
  });
}

async function resolveTarget(args, manifest) {
  if (args.target) return args.target;

  const envDefault = process.env.GHOSTTY_PEON_DEFAULT_TARGET?.toLowerCase();
  if (envDefault) {
    if (!TARGETS.has(envDefault)) throw new Error(`Invalid GHOSTTY_PEON_DEFAULT_TARGET: ${envDefault}`);
    return envDefault;
  }

  if (!isTty()) {
    throw new Error(`Non-interactive ${args.uninstall ? "uninstall" : "install"} requires --target claude|pi|all`);
  }

  return args.uninstall ? promptForUninstallTarget(manifest) : promptForInstallTarget(manifest);
}

function hasManagedMarker(file) {
  if (!fs.existsSync(file)) return false;
  try {
    return fs.readFileSync(file, "utf8").includes(PI_EXTENSION_MARKER);
  } catch {
    return false;
  }
}

function commandReferencesRepo(command, repoRoot = REPO_ROOT) {
  if (!command) return false;
  return command.includes(repoRoot) || command.includes(shellQuote(repoRoot));
}

function isOurHook(entry, repoRoot = REPO_ROOT) {
  return entry.hooks?.some((h) => commandReferencesRepo(h.command, repoRoot));
}

function isOldGhosttyHook(entry) {
  return entry.hooks?.some(
    (h) => h.command?.includes(OLD_HOOKS_PATH) || h.command?.includes(OLD_HOOKS_TILDE)
  );
}

function updateManifestTarget(target, data) {
  const manifest = readManifest() || {};
  const targets = manifest.targets || {};
  targets[target] = data;
  writeManifest({ ...manifest, repoRoot: REPO_ROOT, targets });
}

function removeManifestTarget(target) {
  const manifest = readManifest();
  if (!manifest) return;
  const targets = manifest.targets || {};
  delete targets[target];
  removeManifestIfEmpty({ ...manifest, targets });
}

// ── Local sound settings ────────────────────────────────────────────────────

function settingsPathForTarget(target) {
  if (target === "claude") return path.join(process.cwd(), ".claude", "settings.local.json");
  if (target === "pi") return path.join(process.cwd(), ".pi", "settings.local.json");
  throw new Error(`Unsupported settings target: ${target}`);
}

function writeLocalSoundClass(targets, soundClass) {
  if (!soundClass || soundClass === "skip") return;
  for (const target of targets) {
    const file = settingsPathForTarget(target);
    const data = readJson(file, {});
    if (!data.env || typeof data.env !== "object" || Array.isArray(data.env)) data.env = {};
    data.env.PEON_SOUND_CLASS = soundClass;
    writeJson(file, data);
    console.log(`  [ok]   Set ${target} sound class in ${path.relative(process.cwd(), file) || file}`);
  }
}

// ── Claude install/uninstall ────────────────────────────────────────────────

function installClaude() {
  console.log(`\nInstalling ${TOOLKIT_NAME} for Claude Code from ${REPO_ROOT}\n`);

  const settings = readSettings();
  if (!settings.hooks) settings.hooks = {};

  let hooksChanged = false;

  for (const event of Object.keys(settings.hooks)) {
    if (!Array.isArray(settings.hooks[event])) continue;
    const before = settings.hooks[event].length;
    settings.hooks[event] = settings.hooks[event].filter(
      (entry) => !isOldGhosttyHook(entry) && !isOurHook(entry)
    );
    const removed = before - settings.hooks[event].length;
    if (removed > 0) {
      console.log(`  [ok]   Removed existing ${TOOLKIT_NAME} hook(s): ${event}`);
      hooksChanged = true;
    }
    if (settings.hooks[event].length === 0) delete settings.hooks[event];
  }

  for (const hookDef of HOOKS) {
    const { event, command, timeout } = hookDef;
    if (!settings.hooks[event]) settings.hooks[event] = [];

    const hookEntry = { type: "command", command, timeout };
    if (hookDef.async) hookEntry.async = true;

    const entry = { hooks: [hookEntry] };
    if (hookDef.matcher) entry.matcher = hookDef.matcher;

    settings.hooks[event].push(entry);
    console.log(`  [ok]   Registered hook: ${event}${hookDef.matcher ? ` [${hookDef.matcher}]` : ""}`);
    hooksChanged = true;
  }

  if (hooksChanged) writeSettings(settings);

  updateManifestTarget("claude", {
    settingsPath: SETTINGS_PATH,
    hookEvents: HOOKS.map((h) => h.event),
  });

  console.log(`\n  Manifest updated at ${MANIFEST_PATH}`);
}

function uninstallClaude(manifest) {
  console.log(`\nUninstalling ${TOOLKIT_NAME} from Claude Code\n`);

  const repoRoot = manifest?.repoRoot || REPO_ROOT;

  if (fs.existsSync(SETTINGS_PATH)) {
    const settings = readSettings();
    let changed = false;

    if (settings.hooks) {
      for (const { event } of HOOKS) {
        if (!settings.hooks[event]) continue;

        const before = settings.hooks[event].length;
        settings.hooks[event] = settings.hooks[event].filter((entry) => !isOurHook(entry, repoRoot));
        const after = settings.hooks[event].length;

        if (after < before) {
          console.log(`  [ok]   Removed hook: ${event}`);
          changed = true;
        } else {
          console.log(`  [skip] Hook not found: ${event}`);
        }

        if (settings.hooks[event].length === 0) delete settings.hooks[event];
      }

      if (Object.keys(settings.hooks).length === 0) delete settings.hooks;
    }

    if (changed) writeSettings(settings);
  }

  removeManifestTarget("claude");
}

// ── Pi install/uninstall ────────────────────────────────────────────────────

function piExtensionSourceFiles() {
  if (!fs.existsSync(PI_EXTENSION_SOURCE_DIR)) {
    throw new Error(`Missing Pi extension source directory: ${PI_EXTENSION_SOURCE_DIR}`);
  }
  return fs.readdirSync(PI_EXTENSION_SOURCE_DIR)
    .filter((name) => name.endsWith(".ts"))
    .sort();
}

function managedPiExtensionSource(name) {
  let source = fs.readFileSync(path.join(PI_EXTENSION_SOURCE_DIR, name), "utf8");
  if (!source.includes(PI_EXTENSION_MARKER)) {
    source = `// ${PI_EXTENSION_MARKER}. Source: pi-extension/${name}\n${source}`;
  }
  return source;
}

function copyPiExtension(force) {
  const sourceFiles = piExtensionSourceFiles();
  if (!sourceFiles.includes("index.ts")) {
    throw new Error(`Missing Pi extension source: ${PI_EXTENSION_SOURCE}`);
  }

  ensureDir(PI_EXTENSION_DIR);

  for (const name of sourceFiles) {
    const dest = path.join(PI_EXTENSION_DIR, name);
    if (fs.existsSync(dest) && !hasManagedMarker(dest) && !force) {
      throw new Error(`Refusing to overwrite non-managed Pi extension file: ${dest}. Re-run with --force to overwrite.`);
    }
  }

  for (const name of sourceFiles) {
    const dest = path.join(PI_EXTENSION_DIR, name);
    fs.writeFileSync(dest, managedPiExtensionSource(name));
    console.log(`  [ok]   Wrote ${dest}`);
  }

  const sourceSet = new Set(sourceFiles);
  for (const name of fs.readdirSync(PI_EXTENSION_DIR)) {
    if (!name.endsWith(".ts") || sourceSet.has(name)) continue;
    const dest = path.join(PI_EXTENSION_DIR, name);
    if (fs.statSync(dest).isFile() && hasManagedMarker(dest)) {
      fs.unlinkSync(dest);
      console.log(`  [ok]   Removed stale Pi extension file ${dest}`);
    }
  }
}

function updateRepoSymlink(force) {
  let stat;
  try {
    stat = fs.lstatSync(PI_REPO_LINK);
  } catch (error) {
    if (!error || error.code !== "ENOENT") throw error;
  }

  if (stat?.isSymbolicLink()) {
    let current = fs.readlinkSync(PI_REPO_LINK);
    try {
      current = fs.realpathSync(PI_REPO_LINK);
    } catch {
      // Dangling symlink; replace it below.
    }
    if (current === REPO_ROOT) {
      console.log(`  [skip] Repo symlink already points to ${REPO_ROOT}`);
      return;
    }
    fs.unlinkSync(PI_REPO_LINK);
    console.log(`  [ok]   Updated repo symlink from ${current} to ${REPO_ROOT}`);
  } else if (stat) {
    if (!force) {
      throw new Error(`Refusing to replace non-symlink path: ${PI_REPO_LINK}. Re-run with --force to replace.`);
    }
    fs.rmSync(PI_REPO_LINK, { recursive: true, force: true });
    console.log(`  [ok]   Removed non-symlink repo path due to --force`);
  }

  fs.symlinkSync(REPO_ROOT, PI_REPO_LINK, "dir");
  console.log(`  [ok]   Linked ${PI_REPO_LINK} -> ${REPO_ROOT}`);
}

function installPi(force = false) {
  console.log(`\nInstalling ${TOOLKIT_NAME} for Pi from ${REPO_ROOT}\n`);

  copyPiExtension(force);
  updateRepoSymlink(force);

  updateManifestTarget("pi", {
    extensionDir: PI_EXTENSION_DIR,
    indexPath: PI_EXTENSION_INDEX,
    repoLink: PI_REPO_LINK,
  });

  console.log(`\n  Manifest updated at ${MANIFEST_PATH}`);
  console.log(`  Pi: run /reload or restart Pi to load the extension.`);
}

function removeIfManagedFile(file, label) {
  if (!fs.existsSync(file)) {
    console.log(`  [skip] ${label} not found`);
    return;
  }
  if (!hasManagedMarker(file)) {
    console.log(`  [skip] ${label} is not managed by ${TOOLKIT_NAME}: ${file}`);
    return;
  }
  fs.unlinkSync(file);
  console.log(`  [ok]   Removed ${label}`);
}

function removeManagedPiExtensionModules(extensionDir, indexPath) {
  if (!fs.existsSync(extensionDir)) return;
  for (const name of fs.readdirSync(extensionDir)) {
    if (!name.endsWith(".ts")) continue;
    const file = path.join(extensionDir, name);
    if (file === indexPath) continue;
    if (!fs.statSync(file).isFile() || !hasManagedMarker(file)) continue;
    fs.unlinkSync(file);
    console.log(`  [ok]   Removed Pi extension module ${name}`);
  }
}

function removeRepoSymlink(manifest) {
  const repoLink = manifest?.targets?.pi?.repoLink || PI_REPO_LINK;
  let stat;
  try {
    stat = fs.lstatSync(repoLink);
  } catch (error) {
    if (error && error.code === "ENOENT") {
      console.log(`  [skip] Repo symlink not found`);
      return;
    }
    throw error;
  }

  if (!stat.isSymbolicLink()) {
    console.log(`  [skip] Repo path is not a symlink: ${repoLink}`);
    return;
  }

  let current = fs.readlinkSync(repoLink);
  try {
    current = fs.realpathSync(repoLink);
  } catch {
    // Dangling symlink; allow removal if it is manifest-managed.
  }
  const expected = manifest?.repoRoot || REPO_ROOT;
  if (current !== expected && current !== REPO_ROOT && !manifest?.targets?.pi?.repoLink) {
    console.log(`  [skip] Repo symlink points elsewhere: ${repoLink} -> ${current}`);
    return;
  }

  fs.unlinkSync(repoLink);
  console.log(`  [ok]   Removed repo symlink`);
}

function uninstallPi(manifest) {
  console.log(`\nUninstalling ${TOOLKIT_NAME} from Pi\n`);

  const indexPath = manifest?.targets?.pi?.indexPath || PI_EXTENSION_INDEX;
  const extensionDir = manifest?.targets?.pi?.extensionDir || PI_EXTENSION_DIR;

  removeRepoSymlink(manifest);
  removeManagedPiExtensionModules(extensionDir, indexPath);
  removeIfManagedFile(indexPath, "Pi extension index.ts");

  if (fs.existsSync(extensionDir)) {
    try {
      fs.rmdirSync(extensionDir);
      console.log(`  [ok]   Removed empty extension directory`);
    } catch {
      console.log(`  [skip] Extension directory not empty: ${extensionDir}`);
    }
  }

  removeManifestTarget("pi");
  console.log(`  Pi: run /reload or restart Pi to unload the extension.`);
}

// ── Ollama check / output ───────────────────────────────────────────────────

function checkOllamaAndPrintDone(targets) {
  let ollamaDone = false;
  try {
    const http = require("http");
    const req = http.get("http://localhost:11434/", { timeout: 3000 }, (res) => {
      if (!ollamaDone) {
        ollamaDone = true;
        console.log(`  Ollama: reachable (status ${res.statusCode})`);
        printDone(targets);
      }
    });
    req.on("error", () => {
      if (!ollamaDone) {
        ollamaDone = true;
        console.log(`  Ollama: NOT reachable — make sure Ollama is running`);
        printDone(targets);
      }
    });
    req.on("timeout", () => {
      req.destroy();
      if (!ollamaDone) {
        ollamaDone = true;
        console.log(`  Ollama: NOT reachable — make sure Ollama is running`);
        printDone(targets);
      }
    });
  } catch {
    printDone(targets);
  }
}

function printDone(targets) {
  console.log(`\nDone! Next steps:`);
  console.log(`  1. Make sure Ollama is running: ollama pull qwen3.5:4b`);
  if (targets.includes("pi")) console.log(`  2. In Pi, run /reload or restart Pi.`);
  console.log(`  ${targets.includes("pi") ? "3" : "2"}. Source the shell function (optional):`);
  console.log(`     source ${path.join(REPO_ROOT, "peon-class.sh")}`);
  console.log(`  ${targets.includes("pi") ? "4" : "3"}. Or add to your shell config:`);
  console.log(`     echo 'source ${path.join(REPO_ROOT, "peon-class.sh")}' >> ~/.zshrc`);
  console.log(``);
}

function printHelp() {
  console.log(`
Usage: node install.js [options]

Options:
  --target <target>        Install/uninstall target: claude, pi, all
  --claude                Alias for --target claude
  --pi                    Alias for --target pi
  --all                   Alias for --target all
  --uninstall             Remove installed target(s)
  --sound-class <class>   Set project sound class during install: orc, human, nightelf, undead, random, none, skip
  --yes, -y               Skip confirmation prompts
  --force                 Overwrite managed-conflict files where safe
  --help, -h              Show this help

Examples:
  node install.js                         # Interactive install in a TTY
  node install.js --target claude --yes
  node install.js --target pi --yes
  node install.js --target all --yes
  node install.js --uninstall --target pi --yes
`);
}

// ── Main ────────────────────────────────────────────────────────────────────

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return;
  }

  const manifest = readManifest();
  const target = await resolveTarget(args, manifest);
  const targets = expandTargets(target);

  let soundClass = args.soundClass;
  if (!args.uninstall && !soundClass && !args.target && isTty()) {
    soundClass = await promptForSoundClass();
  }

  const confirmed = await confirmSummary({ uninstall: args.uninstall, targets, soundClass, yes: args.yes });
  if (!confirmed) {
    console.log(`Cancelled.`);
    return;
  }

  if (args.uninstall) {
    for (const currentTarget of targets) {
      if (currentTarget === "claude") uninstallClaude(manifest);
      if (currentTarget === "pi") uninstallPi(manifest);
    }
    console.log(`\nDone! ${TOOLKIT_NAME} has been uninstalled for: ${targets.join(", ")}\n`);
    return;
  }

  for (const currentTarget of targets) {
    if (currentTarget === "claude") installClaude();
    if (currentTarget === "pi") installPi(args.force);
  }

  writeLocalSoundClass(targets, soundClass);
  checkOllamaAndPrintDone(targets);
}

main().catch((error) => {
  console.error(`\nError: ${error.message}\n`);
  process.exit(1);
});
