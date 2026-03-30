import { CopilotClient, type PermissionRequest } from "@github/copilot-sdk";
import { mkdirSync } from "node:fs";
import { resolve } from "node:path";

type RunResult = { code: number; out: string };

async function run(
	cmd: string[],
	opts?: { cwd?: string; env?: Record<string, string> },
): Promise<RunResult> {
	const p = Bun.spawn(cmd, {
		cwd: opts?.cwd,
		stdout: "pipe",
		stderr: "pipe",
		env: opts?.env ?? (process.env as Record<string, string>),
	});
	const out = await new Response(p.stdout).text();
	const err = await new Response(p.stderr).text();
	const code = await p.exited;
	return { code, out: out + err };
}

function buildPrompt(preCommitOutput: string) {
	return [
		"Do not run pre-commit, git, or any commands that create lock files. I will validate locally. Only edit files.",
		"You are operating inside a git repository. Fix the pre-commit failures in the working tree.",
		"",
		"Hard constraints:",
		"- Make minimal, surgical edits. Preserve behavior.",
		"- Do not add dependencies.",
		"- Prefer formatting-only changes when possible.",
		"- Only modify files implicated by the failures unless absolutely necessary.",
		"- After changes, `pre-commit run` must pass for the same scope used here.",
		"",
		"Raw pre-commit output:",
		preCommitOutput,
		"",
		"Apply the required edits in-place. Then briefly summarize what you changed.",
	].join("\n");
}

async function copilotFix(prompt: string, model: string) {
	const client = new CopilotClient({});

	let session: Awaited<ReturnType<typeof client.createSession>> | undefined;
	try {
		session = await client.createSession({
			sessionId: `pre-commit-${Date.now()}`,
			model,
			onPermissionRequest: async (req: PermissionRequest) => {
				if (req.kind === "write" || req.kind === "read") {
					return { kind: "approved" };
				}
				console.warn(`Denied permission request: ${req.kind}`);
				return { kind: "denied-interactively-by-user" };
			},
		});
		const response = await session.sendAndWait({ prompt });
		const text = response?.data?.content;
		if (!text) {
			throw new Error("Copilot returned no actionable response.");
		}
		process.stdout.write(`${text}\n\n`);
	} finally {
		await session?.disconnect();
	}
}

async function main() {
	const maxIter = Number(process.env.COPILOT_MAX_ITER ?? process.env.CODEX_MAX_ITER ?? "3");
	const allFiles = process.env.ALL_FILES === "1";
	const model = "gpt-5.4-mini";

	const repoRoot = process.cwd();
	const precommitHome = resolve(repoRoot, ".cache", "pre-commit");
	mkdirSync(precommitHome, { recursive: true });

	const env = {
		...process.env,
		PRE_COMMIT_HOME: precommitHome,
		XDG_CACHE_HOME: resolve(repoRoot, ".cache"),
	};

	const pcCmd = allFiles
		? ["pre-commit", "run", "--all-files"]
		: ["pre-commit", "run"]; // staged-only by default

	let prevFailCount: number | null = null;

	for (let i = 1; i <= maxIter; i++) {
		console.log(`\n=== pre-commit pass ${i}/${maxIter} ===`);
		const res = await run(pcCmd, { env });
		console.log(res.out);

		if (res.code === 0) {
			console.log("✅ pre-commit clean.");
			process.exit(0);
		}

		const failCount = (res.out.match(/^Failed$/gm) ?? []).length;
		if (prevFailCount !== null && failCount >= prevFailCount) {
			console.error("⚠️  Failures not decreasing after fix; aborting.");
			process.exit(1);
		}
		prevFailCount = failCount;

		// Check if pre-commit already auto-fixed files (e.g., ruff --fix)
		const autoFixed = await run(["git", "diff", "--name-only"], { env });
		if (autoFixed.out.trim()) {
			console.log("Pre-commit auto-fixed files; re-staging and retrying...");
			await run(["git", "add", "-u"], { env });
			continue;
		}

		// No auto-fixes — ask Copilot to fix the remaining issues
		console.log("\n=== Copilot SDK run ===");
		try {
			await copilotFix(buildPrompt(res.out), model);
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			console.error(`Copilot SDK failed: ${message}`);
			process.exit(1);
		}

		const diff = await run(["git", "diff", "--name-only"], { env });
		if (!diff.out.trim()) {
			console.error("⚠️  Copilot made no file changes; aborting.");
			process.exit(1);
		}
		await run(["git", "add", "-u"], { env });
	}

	console.error("❌ Max iterations reached; still failing.");
	process.exit(1);
}

main().catch((e) => {
	console.error(e?.stack ?? String(e));
	process.exit(1);
});
