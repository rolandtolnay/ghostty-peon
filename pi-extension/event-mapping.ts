// Managed by ghostty-peon install.js. Source: pi-extension/event-mapping.ts
import type { AgentEndEvent, ExtensionContext } from "@earendil-works/pi-coding-agent";

export type PermissionEvent = {
	phase?: "start" | "end";
	sessionId?: string;
	cwd?: string;
	toolName?: string;
};

export function sessionId(ctx: ExtensionContext) {
	return ctx.sessionManager.getSessionId() || "unknown";
}

export function basePayload(ctx: ExtensionContext, id = sessionId(ctx)) {
	return {
		session_id: id,
		cwd: ctx.cwd,
		session_file: ctx.sessionManager.getSessionFile() || "",
	};
}

export function extractAssistantText(event: AgentEndEvent) {
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

export function mapSessionStartReason(reason: string) {
	if (reason === "reload") return undefined;
	if (reason === "resume" || reason === "new" || reason === "fork") return reason;
	return "startup";
}

export function isQuestionToolName(toolName: string) {
	return toolName === "AskUserQuestion" || toolName === "question";
}

export function permissionHookEventName(phase: PermissionEvent["phase"]) {
	switch (phase) {
		case "start":
			return "PermissionRequest";
		case "end":
			return "PostToolUse";
		default:
			return undefined;
	}
}

export function compactTokenCount(event: unknown) {
	const preparation = (event as { preparation?: { tokensBefore?: unknown } }).preparation;
	return typeof preparation?.tokensBefore === "number" ? preparation.tokensBefore : undefined;
}
