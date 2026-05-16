// Managed by ghostty-peon install.js. Source: pi-extension/index.ts
import type { ExtensionAPI, ToolCallEvent, ToolResultEvent } from "@earendil-works/pi-coding-agent";
import { isInteractiveGhostty, isInteractiveGhosttyTerminal } from "./ghostty-env.js";
import {
	FAST_HOOK_TIMEOUT_MS,
	HOOK_TIMEOUT_MS,
	SESSION_HOOK_TIMEOUT_MS,
	TABTITLE_BARRIER_MS,
	runHook,
	runnerLog,
	waitBriefly,
	type HookResult,
} from "./hook-runner.js";
import {
	basePayload,
	compactTokenCount,
	extractAssistantText,
	isQuestionToolName,
	mapSessionStartReason,
	permissionHookEventName,
	sessionId,
	type PermissionEvent,
} from "./event-mapping.js";

const PERMISSION_CHANNEL = "ghostty-peon:permission";
const pendingTabtitleBySession = new Map<string, Promise<HookResult>>();

function handlePermissionEvent(data: unknown) {
	const event = data as PermissionEvent;
	if (!event || !event.sessionId || !event.cwd || !isInteractiveGhosttyTerminal()) return;

	const hookEventName = permissionHookEventName(event.phase);
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
		const id = sessionId(ctx);
		const source = mapSessionStartReason(event.reason);
		runnerLog(id, `event session_start reason=${event.reason} source=${source ?? "skip"} file=${ctx.sessionManager.getSessionFile() ?? ""} prev=${event.previousSessionFile ?? ""}`);
		if (!source) return undefined;
		await runHook(
			"session-sound-hook.py",
			{ ...basePayload(ctx, id), source, pi_reason: event.reason, previous_session_file: event.previousSessionFile ?? "" },
			ctx.cwd,
			id,
			{ timeoutMs: SESSION_HOOK_TIMEOUT_MS },
		);
		return undefined;
	});

	pi.on("session_shutdown", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		const id = sessionId(ctx);
		runnerLog(id, `event session_shutdown reason=${event.reason} target=${event.targetSessionFile ?? ""}`);
		if (event.reason === "reload") return undefined;
		await runHook(
			"session-end-hook.py",
			{ ...basePayload(ctx, id), shutdown_reason: event.reason, target_session_file: event.targetSessionFile ?? "" },
			ctx.cwd,
			id,
			{ timeoutMs: SESSION_HOOK_TIMEOUT_MS },
		);
		return undefined;
	});

	pi.on("session_before_fork", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		runnerLog(sessionId(ctx), `event session_before_fork entry=${event.entryId} position=${event.position}`);
		return undefined;
	});

	pi.on("session_before_compact", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		runnerLog(sessionId(ctx), `event session_before_compact tokens=${compactTokenCount(event) ?? "unknown"}`);
		return undefined;
	});

	pi.on("session_compact", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		const id = sessionId(ctx);
		runnerLog(id, `event session_compact fromExtension=${Boolean(event.fromExtension)}`);
		await runHook(
			"session-sound-hook.py",
			{ ...basePayload(ctx, id), source: "compact", pi_reason: "compact" },
			ctx.cwd,
			id,
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
				...basePayload(ctx, id),
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
		if (!isInteractiveGhostty(ctx) || !isQuestionToolName(event.toolName)) return undefined;
		const id = sessionId(ctx);
		await runHook(
			"tab-attention-hook.py",
			{
				...basePayload(ctx, id),
				hook_event_name: "PreToolUse",
				tool_name: event.toolName,
			},
			ctx.cwd,
			id,
			{ timeoutMs: FAST_HOOK_TIMEOUT_MS },
		);
		return undefined;
	});

	pi.on("tool_result", async (event: ToolResultEvent, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		const id = sessionId(ctx);
		void runHook(
			"tab-attention-hook.py",
			{
				...basePayload(ctx, id),
				hook_event_name: "PostToolUse",
				tool_name: event.toolName,
			},
			ctx.cwd,
			id,
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
				...basePayload(ctx, id),
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
