// Managed by ghostty-peon install.js. Source: pi-extension/event-mapping.ts
import { execFileSync } from "node:child_process";
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

export function selectedSkillNames(event: { systemPromptOptions?: unknown }): string[] {
	const options = event.systemPromptOptions;
	if (!options || typeof options !== "object") return [];
	const skills = (options as { skills?: unknown }).skills;
	if (!Array.isArray(skills)) return [];

	const names: string[] = [];
	const seen = new Set<string>();
	for (const skill of skills) {
		const raw = skillName(skill);
		const name = normalizeSkillName(raw);
		if (!name || seen.has(name)) continue;
		seen.add(name);
		names.push(name);
	}
	return names;
}

function skillName(skill: unknown): string {
	if (typeof skill === "string") return skill;
	if (!skill || typeof skill !== "object") return "";
	const value = (skill as { name?: unknown }).name;
	return typeof value === "string" ? value : "";
}

function normalizeSkillName(name: string): string {
	return name.trim().replace(/^\/+/, "").toLowerCase();
}

export function currentBranchName(ctx: ExtensionContext): string {
	try {
		const cwd = (ctx as { cwd?: unknown }).cwd;
		if (typeof cwd !== "string" || !cwd) return "";
		const branch = execFileSync("git", ["rev-parse", "--abbrev-ref", "HEAD"], {
			cwd,
			encoding: "utf8",
			stdio: ["ignore", "pipe", "ignore"],
			timeout: 1000,
		}).trim();
		return branch && branch !== "HEAD" ? branch : "";
	} catch {
		return "";
	}
}

export function beforeAgentStartPayload(
	event: { prompt?: string; images?: unknown; systemPromptOptions?: unknown },
	ctx: ExtensionContext,
	id = sessionId(ctx),
) {
	const imageCount = Array.isArray(event.images) ? event.images.length : 0;
	const sessionFile = ctx.sessionManager.getSessionFile() || "";
	return {
		...basePayload(ctx, id),
		hook_event_name: "UserPromptSubmit",
		prompt: typeof event.prompt === "string" ? event.prompt : "",
		image_count: imageCount,
		transcript_path: sessionFile,
		selected_skills: selectedSkillNames(event),
		branch_name: currentBranchName(ctx),
	};
}

export function extractAssistantText(event: AgentEndEvent) {
	const lastToolResultIndex = lastMessageIndex(event.messages, "toolResult");
	const startIndex = lastToolResultIndex >= 0 ? lastToolResultIndex + 1 : 0;

	for (let i = event.messages.length - 1; i >= startIndex; i--) {
		const message = event.messages[i] as { role?: string; content?: unknown };
		if (message.role !== "assistant") continue;
		return contentToText(message.content).trim();
	}
	return "";
}

function lastMessageIndex(messages: unknown[], role: string) {
	for (let i = messages.length - 1; i >= 0; i--) {
		const message = messages[i] as { role?: string } | undefined;
		if (message?.role === role) return i;
	}
	return -1;
}

function contentToText(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	const parts: string[] = [];
	for (const block of content) {
		if (!block || typeof block !== "object") continue;
		const record = block as Record<string, unknown>;
		if (record.type === "text" && typeof record.text === "string") parts.push(record.text);
		const questionText = questionToolCallText(record);
		if (questionText) parts.push(questionText);
	}
	return parts.join("\n");
}

function questionToolCallText(record: Record<string, unknown>): string {
	if (record.type !== "toolCall" || typeof record.name !== "string" || !isQuestionToolName(record.name)) return "";
	const args = record.arguments;
	if (!args || typeof args !== "object") return "";

	const argRecord = args as Record<string, unknown>;
	const parts: string[] = [];
	if (typeof argRecord.question === "string") parts.push(argRecord.question);
	if (Array.isArray(argRecord.questions)) {
		for (const item of argRecord.questions) {
			if (!item || typeof item !== "object") continue;
			const question = (item as Record<string, unknown>).question;
			if (typeof question === "string") parts.push(question);
		}
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
