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

function getGithubToken() {
	return process.env.COPILOT_TOKEN || process.env.GITHUB_TOKEN;
}

async function copilotFix(prompt: string, model: string, cliUrl: string) {
	const githubToken = getGithubToken();
	if (!githubToken) {
		throw new Error(
			"Missing auth token. Set COPILOT_TOKEN or GITHUB_TOKEN and start headless Copilot CLI with COPILOT_GITHUB_TOKEN.",
		);
	}

	const client = new CopilotClient({
		cliUrl,
	});

	let session: Awaited<ReturnType<typeof client.createSession>> | undefined;
	try {
		session = await client.createSession({
			sessionId: `pre-commit-${Date.now()}`,
			model,
			onPermissionRequest: async (req: PermissionRequest) => {
				return { kind: "approved" };
			},
		});
		const response = await session.sendAndWait({ prompt });
		const text = response?.data?.content;
		if (text) {
			process.stdout.write(`${text}\n\n`);
		}
	} finally {
		await session?.disconnect();
	}
}

async function main() {
	const maxIter = Number(process.env.COPILOT_MAX_ITER ?? process.env.CODEX_MAX_ITER ?? "3");
	const allFiles = process.env.ALL_FILES === "1";
	const model = "gpt-5.4-mini";
	const cliUrl = process.env.COPILOT_CLI_URL ?? "localhost:4321";

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

	for (let i = 1; i <= maxIter; i++) {
		console.log(`\n=== pre-commit pass ${i}/${maxIter} ===`);
		const res = await run(pcCmd, { env });
		console.log(res.out);

		if (res.code === 0) {
			console.log("✅ pre-commit clean.");
			process.exit(0);
		}

		console.log("\n=== Copilot SDK run ===");
		try {
			await copilotFix(buildPrompt(res.out), model, cliUrl);
		} catch (error) {
			const message = error instanceof Error ? error.message : String(error);
			const extra = message.includes("ECONNREFUSED")
				? `\nHint: start Copilot CLI in headless mode, e.g. \`copilot --headless --port ${cliUrl.split(":").at(-1) ?? "4321"}\`.`
				: "";
			console.error(`Copilot SDK failed: ${message}${extra}`);
			process.exit(1);
		}
	}

	console.error("❌ Max iterations reached; still failing.");
	process.exit(1);
}

main().catch((e) => {
	console.error(e?.stack ?? String(e));
	process.exit(1);
});
