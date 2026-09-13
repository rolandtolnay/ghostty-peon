// Managed by ghostty-peon install.js. Source: pi-extension/index.ts
import type { ExtensionAPI, ExtensionContext, ToolCallEvent, ToolResultEvent } from "@earendil-works/pi-coding-agent";
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
	beforeAgentStartPayload,
	compactTokenCount,
	extractAssistantText,
	hookSessionId,
	isQuestionToolName,
	mapSessionStartReason,
	permissionHookEventName,
	sessionId,
	type PermissionEvent,
} from "./event-mapping.js";

const PERMISSION_CHANNEL = "ghostty-peon:permission";
const pendingTabtitleBySession = new Map<string, Promise<HookResult>>();
const pendingToolResultBySession = new Map<string, Promise<HookResult>>();

function handlePermissionEvent(data: unknown) {
	const event = data as PermissionEvent;
	if (!event || !event.sessionId || !event.cwd || !isInteractiveGhosttyTerminal()) return;

	const hookEventName = permissionHookEventName(event.phase);
	if (!hookEventName) return;
	const id = hookSessionId(event.sessionId);

	void runHook(
		"tab-attention-hook.py",
		{
			hook_event_name: hookEventName,
			tool_name: event.toolName || "unknown",
			session_id: id,
			cwd: event.cwd,
		},
		event.cwd,
		id,
		{ timeoutMs: FAST_HOOK_TIMEOUT_MS },
	);
}

export default function (pi: ExtensionAPI) {
	pi.events.on(PERMISSION_CHANNEL, handlePermissionEvent);

	// Wait owners publish snapshots; Ghostty never infers waits from tool names or timers.
	const waits = new Map<string, { sessionId: string; state: string; dirty: boolean }>();
	let currentCtx: ExtensionContext | undefined;
	let closed = false;
	let statusUpdate = Promise.resolve();
	const hasBackgroundWait = (ctx: ExtensionContext) => [...waits.values()].some(
		(wait) => wait.sessionId === ctx.sessionManager.getSessionId() && wait.state === "waiting",
	);
	const queueStatus = (update: () => Promise<void>) => {
		statusUpdate = statusUpdate.then(async () => {
			if (!closed) await update();
		}).catch((error) => runnerLog(undefined, `wait status error: ${String(error)}`));
		return statusUpdate;
	};
	const handleWaitEvent = (data: unknown) => {
		const event = data as { source?: string; sessionId?: string; cwd?: string; state?: string } | null;
		if (!event || !["subagent_wait", "schedule_wakeup"].includes(event.source ?? "")
			|| !["waiting", "resuming", "idle"].includes(event.state ?? "")
			|| typeof event.sessionId !== "string" || typeof event.cwd !== "string" || closed) return;
		const ctx = currentCtx;
		if (ctx && event.sessionId !== ctx.sessionManager.getSessionId()) return;
		const previous = waits.get(event.source!);
		// Keep an unapplied transition through startup, even if the owner restores and
		// clears an overdue wait before our session_start handler can capture the tab.
		const dirty = event.state !== "idle" || Boolean(previous?.sessionId === event.sessionId
			&& (previous.state !== "idle" || previous.dirty));
		const snapshot = { sessionId: event.sessionId, state: event.state!, dirty };
		waits.set(event.source!, snapshot);
		if (!ctx || !isInteractiveGhostty(ctx) || !dirty) return;
		snapshot.dirty = false;
		void queueStatus(async () => {
			const working = hasBackgroundWait(ctx) || event.state === "resuming" || !ctx.isIdle();
			const id = sessionId(ctx);
			await runHook("tab-attention-hook.py", {
				...basePayload(ctx, id),
				hook_event_name: working ? "BackgroundWait" : "BackgroundIdle",
			}, ctx.cwd, id, { timeoutMs: FAST_HOOK_TIMEOUT_MS });
		});
	};
	const unsubscribeWait = pi.events.on("ghostty-peon:wait", handleWaitEvent);
	const queryWaits = (ctx: ExtensionContext) => {
		pi.events.emit("ghostty-peon:wait-query", { sessionId: ctx.sessionManager.getSessionId() });
	};

	pi.on("session_start", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		const id = sessionId(ctx);
		currentCtx = ctx;
		const source = mapSessionStartReason(event.reason);
		runnerLog(id, `event session_start reason=${event.reason} source=${source ?? "skip"} instance=${process.pid} file=${ctx.sessionManager.getSessionFile() ?? ""} prev=${event.previousSessionFile ?? ""}`);
		if (!source) {
			queryWaits(ctx);
			return undefined;
		}
		await runHook(
			"session-sound-hook.py",
			{ ...basePayload(ctx, id), source, pi_reason: event.reason, previous_session_file: event.previousSessionFile ?? "" },
			ctx.cwd,
			id,
			{ timeoutMs: SESSION_HOOK_TIMEOUT_MS },
		);
		queryWaits(ctx);
		return undefined;
	});

	pi.on("session_tree", (_event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return;
		currentCtx = ctx;
		queryWaits(ctx);
	});

	pi.on("session_shutdown", async (event, ctx) => {
		closed = true;
		unsubscribeWait();
		waits.clear();
		currentCtx = undefined;
		await statusUpdate;
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
			beforeAgentStartPayload(event, ctx, id),
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
		const pending = runHook(
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
		pendingToolResultBySession.set(id, pending);
		try {
			await pending;
		} finally {
			if (pendingToolResultBySession.get(id) === pending) pendingToolResultBySession.delete(id);
		}

		return undefined;
	});

	pi.on("agent_end", async (event, ctx) => {
		if (!isInteractiveGhostty(ctx)) return undefined;
		const id = sessionId(ctx);
		const pendingTabtitle = pendingTabtitleBySession.get(id);
		if (pendingTabtitle) await waitBriefly(pendingTabtitle, TABTITLE_BARRIER_MS);
		const pendingToolResult = pendingToolResultBySession.get(id);
		if (pendingToolResult) await waitBriefly(pendingToolResult, FAST_HOOK_TIMEOUT_MS);
		const followupTabtitle = pendingTabtitleBySession.get(id);
		if (followupTabtitle && followupTabtitle !== pendingTabtitle) await waitBriefly(followupTabtitle, TABTITLE_BARRIER_MS);

		await queueStatus(async () => {
			await runHook(
				"tab-stop-question-hook.py",
				{
					...basePayload(ctx, id),
					hook_event_name: "Stop",
					stop_hook_active: false,
					last_assistant_message: extractAssistantText(event),
					background_wait: hasBackgroundWait(ctx),
				},
				ctx.cwd,
				id,
				{ timeoutMs: HOOK_TIMEOUT_MS },
			);
		});
		return undefined;
	});
}
