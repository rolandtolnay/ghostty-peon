// Managed by ghostty-peon install.js. Source: pi-extension/ghostty-env.ts
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, parse } from "node:path";
import type { ExtensionContext } from "@earendil-works/pi-coding-agent";
import { PI_LOG_FILE } from "./paths.js";

export function isSubagentChild() {
	return process.env.PI_SUBAGENT_CHILD === "1";
}

export function isGhosttyEnv() {
	return (
		process.env.TERM_PROGRAM?.toLowerCase() === "ghostty" ||
		Boolean(process.env.GHOSTTY_RESOURCES_DIR || process.env.GHOSTTY_BIN_DIR)
	);
}

export function isInteractiveGhosttyTerminal() {
	return !isSubagentChild() && isGhosttyEnv() && Boolean(process.stdin.isTTY && process.stdout.isTTY);
}

export function isInteractiveGhostty(ctx: ExtensionContext) {
	return ctx.hasUI && isInteractiveGhosttyTerminal();
}

export function isInteractiveGhosttyEnvOnly() {
	return isInteractiveGhosttyTerminal();
}

function findUp(startDir: string, relativePath: string) {
	let dir = startDir || process.cwd();
	while (true) {
		const candidate = join(dir, relativePath);
		if (existsSync(candidate)) return candidate;
		const parent = dirname(dir);
		if (parent === dir || dir === parse(dir).root) return undefined;
		dir = parent;
	}
}

function readPeonSoundClass(settingsPath: string) {
	try {
		const data = JSON.parse(readFileSync(settingsPath, "utf8")) as {
			env?: { PEON_SOUND_CLASS?: unknown };
		};
		const value = data.env?.PEON_SOUND_CLASS;
		return typeof value === "string" && value.trim() ? value.trim() : undefined;
	} catch {
		return undefined;
	}
}

export function getPeonSoundClass(cwd: string) {
	const piSettings = findUp(cwd, join(".pi", "settings.local.json"));
	if (piSettings) return readPeonSoundClass(piSettings);

	const claudeSettings = findUp(cwd, join(".claude", "settings.local.json"));
	return claudeSettings ? readPeonSoundClass(claudeSettings) : undefined;
}

export function buildHookEnv(cwd: string) {
	const env: NodeJS.ProcessEnv = {
		...process.env,
		GHOSTTY_PEON_NAMESPACE: "pi",
		GHOSTTY_PEON_LOG_FILE: PI_LOG_FILE,
		GHOSTTY_PEON_LOG_PREV_FILE: "/tmp/pi-tab-hooks.prev.log",
		GHOSTTY_PEON_LOG_DATE_FILE: "/tmp/pi-tab-hooks.lastdate",
		GHOSTTY_PEON_DEBOUNCE_DIR: "/tmp/pi-tabtitle",
		GHOSTTY_PEON_TERMINAL_ID_DIR: "/tmp/pi-tabterminal",
		GHOSTTY_PEON_UNIT_ASSIGN_DIR: "/tmp/pi-sound-units",
		GHOSTTY_PEON_SESSION_INDEX_DIR: "/tmp/pi-sound-session",
		GHOSTTY_PEON_SOUND_LAST_DIR: "/tmp/pi-sound-last",
		GHOSTTY_PEON_WEIGHT_STATE_FILE: join(homedir(), ".ghostty-peon", "pi-weights.json"),
	};

	const soundClass = getPeonSoundClass(cwd);
	if (soundClass) env.PEON_SOUND_CLASS = soundClass;
	return env;
}
