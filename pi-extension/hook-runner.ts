// Managed by ghostty-peon install.js. Source: pi-extension/hook-runner.ts
import { spawn } from "node:child_process";
import { appendFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { buildHookEnv } from "./ghostty-env.js";
import { HOOKS_DIR, PI_LOG_FILE, REPO_ROOT, REQUIRED_HOOKS, type HookScript } from "./paths.js";

export type { HookScript };
export type HookResult = "ok" | "disabled" | "error" | "timeout";

export type RunOptions = {
	timeoutMs?: number;
	logStart?: boolean;
};

export const HOOK_TIMEOUT_MS = 15_000;
export const FAST_HOOK_TIMEOUT_MS = 5_000;
export const SESSION_HOOK_TIMEOUT_MS = 8_000;
export const TABTITLE_BARRIER_MS = 2_500;
const HOOK_KILL_GRACE_MS = 2_000;

let missingRepoLogged = false;

export function runnerLog(sessionId: string | undefined, message: string) {
	try {
		const now = new Date();
		const time = now.toTimeString().slice(0, 8) + `.${now.getMilliseconds().toString().padStart(3, "0")}`;
		const sid = (sessionId || "").slice(-6) || "??????";
		appendFileSync(PI_LOG_FILE, `${time} [${sid}] runner     | ${message}\n`);
	} catch {
		// Logging must never break pi startup or tool execution.
	}
}

function logMissingHookOnce(sessionId: string | undefined, message: string) {
	if (missingRepoLogged) return;
	runnerLog(sessionId, message);
	missingRepoLogged = true;
}

function hooksAvailable(sessionId?: string) {
	if (!existsSync(HOOKS_DIR)) {
		logMissingHookOnce(sessionId, `disabled: missing hooks dir ${HOOKS_DIR}`);
		return false;
	}
	for (const hook of REQUIRED_HOOKS) {
		const hookPath = join(HOOKS_DIR, hook);
		if (!existsSync(hookPath)) {
			logMissingHookOnce(sessionId, `disabled: missing hook ${hookPath}`);
			return false;
		}
	}
	return true;
}

export function runHook(
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
		let childClosed = false;
		let killTimer: ReturnType<typeof setTimeout> | undefined;
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
			killTimer = setTimeout(() => {
				if (!childClosed) child.kill("SIGKILL");
			}, HOOK_KILL_GRACE_MS);
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
			childClosed = true;
			if (killTimer) clearTimeout(killTimer);
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

export async function waitBriefly<T>(promise: Promise<T>, timeoutMs: number) {
	let timer: ReturnType<typeof setTimeout> | undefined;
	try {
		return await Promise.race([
			promise.catch(() => undefined),
			new Promise<undefined>((resolve) => {
				timer = setTimeout(() => resolve(undefined), timeoutMs);
			}),
		]);
	} finally {
		if (timer) clearTimeout(timer);
	}
}
