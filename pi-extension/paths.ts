// Managed by ghostty-peon install.js. Source: pi-extension/paths.ts
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

export const EXT_DIR = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = resolveRepoRoot();
export const HOOKS_DIR = join(REPO_ROOT, "hooks");
export const PI_LOG_FILE = "/tmp/pi-tab-hooks.log";

export const REQUIRED_HOOKS = [
	"session-sound-hook.py",
	"session-end-hook.py",
	"tabtitle-hook.py",
	"tab-attention-hook.py",
	"tab-stop-question-hook.py",
] as const;

export type HookScript = (typeof REQUIRED_HOOKS)[number];

function resolveRepoRoot() {
	const installedRepo = join(EXT_DIR, "repo");
	if (existsSync(join(installedRepo, "hooks"))) return installedRepo;

	// Development fallback for running this file directly from the repository.
	const repoParent = dirname(EXT_DIR);
	if (existsSync(join(repoParent, "hooks"))) return repoParent;

	return installedRepo;
}
