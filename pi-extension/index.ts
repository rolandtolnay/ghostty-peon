// Managed by ghostty-peon install.js. Source: pi-extension/index.ts
import { spawn } from "node:child_process";
import { appendFileSync, existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join, parse } from "node:path";
import { fileURLToPath } from "node:url";
import type {
	AgentEndEvent,
	ExtensionAPI,
	ExtensionContext,
	ToolCallEvent,
	ToolResultEvent,
} from "@mariozechner/pi-coding-agent";

const EXT_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolveRepoRoot();
const HOOKS_DIR = join(REPO_ROOT, "hooks");
const PI_LOG_FILE = "/tmp/pi-tab-hooks.log";
const PERMISSION_CHANNEL = "ghostty-peon:permission";

const HOOK_TIMEOUT_MS = 15_000;
const FAST_HOOK_TIMEOUT_MS = 5_000;
const SESSION_HOOK_TIMEOUT_MS = 8_000;
const TABTITLE_BARRIER_MS = 2_500;

const REQUIRED_HOOKS = [
	"session-sound-hook.py",
	"session-end-hook.py",
	"tabtitle-hook.py",
	"tab-attention-hook.py",
	"tab-stop-question-hook.py",
] as const;

type HookScript = (typeof REQUIRED_HOOKS)[number];
type HookResult = "ok" | "disabled" | "error" | "timeout";

type PermissionEvent = {
	phase?: "start" | "end";
	sessionId?: string;
	cwd?: string;
	toolName?: string;
};

type RunOptions = {
	timeoutMs?: number;
	logStart?: boolean;
};

const pendingTabtitleBySession = new Map<string, Promise<HookResult>>();
let missingRepoLogged = false;

function resolveRepoRoot() {
	const installedRepo = join(EXT_DIR, "repo");
	if (existsSync(join(installedRepo, "hooks"))) return installedRepo;

	// Development fallback for running this file directly from the repository.
	const repoParent = dirname(EXT_DIR);
	if (existsSync(join(repoParent, "hooks"))) return repoParent;

	return installedRepo;
}

function runnerLog(sessionId: string | undefined, message: string) {
	try {
		const now = new Date();
		const time = now.toTimeString().slice(0, 8) + `.${now.getMilliseconds().toString().padStart(3, "0")}`;
		const sid = (sessionId || "").slice(-6) || "??????";
		appendFileSync(PI_LOG_FILE, `${time} [${sid}] runner     | ${message}\n`);
	} catch {
		// Logging must never break pi startup or tool execution.
	}
}

function hooksAvailable(sessionId?: string) {
	if (!existsSync(HOOKS_DIR)) {
		if (!missingRepoLogged) {
			runnerLog(sessionId, `disabled: missing hooks dir ${HOOKS_DIR}`);
			missingRepoLogged = true;
		}
		return false;
	}
	for (const hook of REQUIRED_HOOKS) {
		if (!existsSync(join(HOOKS_DIR, hook))) {
			if (!missingRepoLogged) {
				runnerLog(sessionId, `disabled: missing hook ${join(HOOKS_DIR, hook)}`);
				missingRepoLogged = true;
			}
			return false;
		}
	}
	return true;
}

function isGhosttyEnv() {
	return (
		process.env.TERM_PROGRAM?.toLowerCase() === "ghostty" ||
		Boolean(process.env.GHOSTTY_RESOURCES_DIR || process.env.GHOSTTY_BIN_DIR)
	);
}

function isInteractiveGhostty(ctx: ExtensionContext) {
	return ctx.hasUI && isGhosttyEnv() && Boolean(process.stdin.isTTY && process.stdout.isTTY);
}

function isInteractiveGhosttyEnvOnly() {
	return isGhosttyEnv() && Boolean(process.stdin.isTTY && process.stdout.isTTY);
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

function getPeonSoundClass(cwd: string) {
	const piSettings = findUp(cwd, join(".pi", "settings.local.json"));
	if (piSettings) return readPeonSoundClass(piSettings);

	const claudeSettings = findUp(cwd, join(".claude", "settings.local.json"));
	return claudeSettings ? readPeonSoundClass(claudeSettings) : undefined;
}

function buildHookEnv(cwd: string) {
	const env: NodeJS.ProcessEnv = {
		...process.env,
		GHOSTTY_PEON_NAMESPACE: "pi",
		GHOSTTY_PEON_LOG_FILE: "/tmp/pi-tab-hooks.log",
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

function runHook(
	script: HookScript,
	payload: Record<string, unknown>,
	cwd: string,
	sessionId: string,
	options: RunOptions = {},
): Promise<HookResult> {
	if (!hooksAvailable(sessionId)) return Promise.resolve("disabled");

	const hookPath = join(HOOKS_DIR, script);
	const timeoutMs = options.timeoutMs ?? HOOK_TIMEOUT_MS;
	if (options.logStart !== false) runnerLog(sessionId, `start ${script}`);

	return new Promise((resolve) => {
		let settled = false;
		let stderr = "";

		const finish = (result: HookResult, message?: string) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			if (message) runnerLog(sessionId, message);
			resolve(result);
		};

		const child = spawn("python3", [hookPath], {
			cwd: REPO_ROOT,
			env: buildHookEnv(cwd),
			stdio: ["pipe", "ignore", "pipe"],
		});

		const timer = setTimeout(() => {
			child.kill("SIGTERM");
			finish("timeout", `timeout ${script} after ${timeoutMs}ms`);
		}, timeoutMs);

		child.stderr?.on("data", (chunk) => {
			stderr += chunk.toString();
			if (stderr.length > 4000) stderr = stderr.slice(-4000);
		});

		child.on("error", (error) => {
			finish("error", `error ${script}: ${error.message}`);
		});

		child.on("close", (code, signal) => {
			if (settled) return;
			if (code === 0) {
				finish("ok");
				return;
			}
			const suffix = stderr.trim() ? ` stderr=${JSON.stringify(stderr.trim().slice(-1000))}` : "";
			finish("error", `exit ${script}: code=${code ?? "null"} signal=${signal ?? "null"}${suffix}`);
		});

		try {
			child.stdin?.end(JSON.stringify(payload));
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			finish("error", `stdin ${script}: ${message}`);
		}
	});
}

function sessionId(ctx: ExtensionContext) {
	return ctx.sessionManager.getSessionId() || "unknown";
}

function basePayload(ctx: ExtensionContext) {
	return {
		session_id: sessionId(ctx),
		cwd: ctx.cwd,
	};
}

function waitBriefly<T>(promise: Promise<T>, timeoutMs: number) {
	return Promise.race([
		promise.catch(() => undefined),
		new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), timeoutMs)),
	]);
}

function extractAssistantText(event: AgentEndEvent) {
	for (let i = event.messages.length - 1; i >= 0; i--) {
		const message = event.messages[i] as { role?: string; content?: unknown };
		if (message.role !== "assistant") continue;
		return contentToText(message.content).trim();
	}
	return "";
}

function contentToText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	const parts: string[] = [];
	for (const block of content) {
		if (!block || typeof block !== "object") continue;
		const record = block as Record<string, unknown>;
		if (record.type === "text" && typeof record.text === "string") parts.push(record.text);
	}
	return parts.join("\n");
}

function mapSessionStartReason(reason: string) {
	if (reason === "reload") return undefined;
	if (reason === "resume") return "resume";
	return "startup";
}

function handlePermissionEvent(data: unknown) {
	const event = data as PermissionEvent;
	if (!event || !event.sessionId || !event.cwd || !isInteractiveGhosttyEnvOnly()) return;

	const hookEventName = event.phase === "start" ? "PermissionRequest" : event.phase === "end" ? "PostToolUse" : undefined;
	if (!hookEventName) return;

	void runHook(
		"tab-attention-hook.py",
		{
			hook_event_name: hookEventName,
			tool_name: event.toolName || "unknown",
			session_id: event.sessionId,
			cwd: event.cwd,
		},
		event.cwd,
		event.sessionId,
		{ timeoutMs: FAST_HOOK_TIMEOUT_MS },
	);
}

export default function (pi: ExtensionAPI) {
	pi.events.on(PERMISSION_CHANNEL, handlePermissionEvent);

	pi.on("session_start", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		const source = mapSessionStartReason(event.reason);
		if (!source) return undefined;
		await runHook(
			"session-sound-hook.py",
			{ ...basePayload(ctx), source },
			ctx.cwd,
			sessionId(ctx),
			{ timeoutMs: SESSION_HOOK_TIMEOUT_MS },
		);
		return undefined;
	});

	pi.on("session_shutdown", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx) || event.reason === "reload") return undefined;
		await runHook(
			"session-end-hook.py",
			basePayload(ctx),
			ctx.cwd,
			sessionId(ctx),
			{ timeoutMs: SESSION_HOOK_TIMEOUT_MS },
		);
		return undefined;
	});

	pi.on("before_agent_start", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		const id = sessionId(ctx);
		const pending = runHook(
			"tabtitle-hook.py",
			{
				...basePayload(ctx),
				hook_event_name: "UserPromptSubmit",
				prompt: event.prompt,
				transcript_path: ctx.sessionManager.getSessionFile() || "",
			},
			ctx.cwd,
			id,
			{ timeoutMs: HOOK_TIMEOUT_MS },
		);
		pendingTabtitleBySession.set(id, pending);
		void pending.finally(() => {
			if (pendingTabtitleBySession.get(id) === pending) pendingTabtitleBySession.delete(id);
		});
		return undefined;
	});

	pi.on("tool_call", async (event: ToolCallEvent, ctx) => {
		if (!isInteractiveGhostty(ctx) || event.toolName !== "AskUserQuestion") return undefined;
		await runHook(
			"tab-attention-hook.py",
			{
				...basePayload(ctx),
				hook_event_name: "PreToolUse",
				tool_name: "AskUserQuestion",
			},
			ctx.cwd,
			sessionId(ctx),
			{ timeoutMs: FAST_HOOK_TIMEOUT_MS },
		);
		return undefined;
	});

	pi.on("tool_result", async (event: ToolResultEvent, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		void runHook(
			"tab-attention-hook.py",
			{
				...basePayload(ctx),
				hook_event_name: "PostToolUse",
				tool_name: event.toolName,
			},
			ctx.cwd,
			sessionId(ctx),
			{ timeoutMs: FAST_HOOK_TIMEOUT_MS },
		);
		return undefined;
	});

	pi.on("agent_end", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		const id = sessionId(ctx);
		const pending = pendingTabtitleBySession.get(id);
		if (pending) await waitBriefly(pending, TABTITLE_BARRIER_MS);

		await runHook(
			"tab-stop-question-hook.py",
			{
				...basePayload(ctx),
				hook_event_name: "Stop",
				stop_hook_active: false,
				last_assistant_message: extractAssistantText(event),
			},
			ctx.cwd,
			id,
			{ timeoutMs: HOOK_TIMEOUT_MS },
		);
		return undefined;
	});
}
