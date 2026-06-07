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

const SKILL_ENVELOPE_RE = /<skill\b[^>]*\bname=["']([^"']+)["'][^>]*>/gi;
const BRACKET_COMMAND_RE = /^\s*\[\/([\w:_-]+)\](?:\s+([^\n]*))?\s*$/gm;
const SLASH_COMMAND_RE = /^\s*\/([\w:_-]+)(?:\s+([^\n]*))?\s*$/gm;
const LIFECYCLE_COMMANDS = new Set([
	"clear",
	"exit",
	"compact",
	"resume",
	"new",
	"fork",
	"clone",
	"tree",
	"init",
	"login",
	"logout",
	"status",
	"config",
	"help",
	"model",
	"settings",
	"session",
	"copy",
	"export",
	"share",
	"reload",
	"hotkeys",
	"changelog",
	"quit",
]);

export function selectedSkillNames(event: { prompt?: unknown; systemPromptOptions?: unknown }): string[] {
	const prompt = typeof event.prompt === "string" ? event.prompt : "";
	return invokedSkillNames(prompt);
}

function invokedSkillNames(prompt: string): string[] {
	const names: string[] = [];
	const seen = new Set<string>();
	const add = (raw: string) => {
		const name = normalizeSkillName(raw);
		if (!name || seen.has(name) || LIFECYCLE_COMMANDS.has(name)) return;
		seen.add(name);
		names.push(name);
	};

	for (const match of prompt.matchAll(SKILL_ENVELOPE_RE)) add(match[1]);
	for (const match of prompt.matchAll(BRACKET_COMMAND_RE)) add(match[1]);
	for (const match of prompt.matchAll(SLASH_COMMAND_RE)) add(match[1]);
	return names;
}

function normalizeSkillName(name: string): string {
	let normalized = name.trim().replace(/^\/+/, "").toLowerCase();
	if (normalized.startsWith("skill:")) normalized = normalized.slice("skill:".length);
	return normalized.trim();
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
