import { Codex } from "@openai/codex-sdk";
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

async function codexFix(prompt: string) {
	const codex = new Codex();
	const thread = codex.startThread({
		model: "gpt-5.1-codex-mini",
	});
	const { events } = await thread.runStreamed(prompt);

	for await (const ev of events) {
		// Stream agent text
		if (ev.type === "item.completed" && ev.item.type === "agent_message") {
			process.stdout.write(`${ev.item.text}\n`);
		}
		if (ev.type === "turn.failed") {
			process.stderr.write(`Turn failed: ${ev.error.message}\n`);
		}
	}
	process.stdout.write("\n");
}

async function main() {
	const maxIter = Number(process.env.CODEX_MAX_ITER ?? "3");
	const allFiles = process.env.ALL_FILES === "1";

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

		// Call Codex to fix based on raw output (you can add structured parsing later).
		console.log("\n=== Codex SDK run ===");
		await codexFix(buildPrompt(res.out));
	}

	console.error("❌ Max iterations reached; still failing.");
	process.exit(1);
}

main().catch((e) => {
	console.error(e?.stack ?? String(e));
	process.exit(1);
});
