// Managed by ghostty-peon install.js. Source: pi-extension/event-mapping.ts
import type { AgentEndEvent, ExtensionContext, ToolResultEvent } from "@earendil-works/pi-coding-agent";

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

export function beforeAgentStartPayload(event: { prompt?: string; images?: unknown }, ctx: ExtensionContext, id = sessionId(ctx)) {
	const imageCount = Array.isArray(event.images) ? event.images.length : 0;
	const sessionFile = ctx.sessionManager.getSessionFile() || "";
	return {
		...basePayload(ctx, id),
		hook_event_name: "UserPromptSubmit",
		prompt: typeof event.prompt === "string" ? event.prompt : "",
		image_count: imageCount,
		transcript_path: sessionFile,
	};
}

export function questionWorkflowTransitionPayload(
	event: Pick<ToolResultEvent, "toolName" | "details">,
	ctx: ExtensionContext,
	id = sessionId(ctx),
) {
	if (!isQuestionToolName(event.toolName)) return undefined;
	const prompt = questionWorkflowTransitionPrompt(event.details);
	if (!prompt) return undefined;
	const sessionFile = ctx.sessionManager.getSessionFile() || "";
	return {
		...basePayload(ctx, id),
		hook_event_name: "QuestionToolResult",
		prompt,
		transcript_path: sessionFile,
		workflow_transition_only: "plan-to-cook",
	};
}

export function questionWorkflowTransitionPrompt(details: unknown): string | undefined {
	const record = asRecord(details);
	if (!record || record.result !== "submitted") return undefined;
	const selections = Array.isArray(record.selections) ? record.selections : [];
	const questions = Array.isArray(record.questions) ? record.questions : [];
	const lines = ["User answered questions:"];

	for (const [index, rawSelection] of selections.entries()) {
		const selection = asRecord(rawSelection);
		if (!selection) continue;
		const answer = cleanText(selection.answer);
		if (!answer) continue;

		const question = cleanText(selection.question) || questionTextAt(questions, index);
		if (question) lines.push(`- Question: ${question}`);
		else lines.push("- Question: (unknown)");
		lines.push(`  Answer: ${answer}`);

		const selectedLabels = Array.isArray(selection.selectedOptions)
			? selection.selectedOptions.map(cleanText).filter(Boolean)
			: [];
		for (const label of selectedLabels) {
			const description = optionDescriptionFor(questions, index, label);
			lines.push(description ? `  Selected option: ${label} — ${description}` : `  Selected option: ${label}`);
		}

		const customText = cleanText(selection.customText);
		if (customText && customText !== answer) lines.push(`  Free-form answer: ${customText}`);
	}

	return lines.length > 1 ? lines.join("\n") : undefined;
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

function asRecord(value: unknown): Record<string, unknown> | undefined {
	return value && typeof value === "object" ? value as Record<string, unknown> : undefined;
}

function cleanText(value: unknown): string {
	return typeof value === "string" ? value.replace(/\s+/g, " ").trim() : "";
}

function questionTextAt(questions: unknown[], index: number): string {
	return cleanText(asRecord(questions[index])?.question);
}

function optionDescriptionFor(questions: unknown[], questionIndex: number, label: string): string {
	const question = asRecord(questions[questionIndex]);
	const options = Array.isArray(question?.options) ? question.options : [];
	for (const rawOption of options) {
		const option = asRecord(rawOption);
		if (!option || cleanText(option.label) !== label) continue;
		return cleanText(option.description);
	}
	return "";
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
