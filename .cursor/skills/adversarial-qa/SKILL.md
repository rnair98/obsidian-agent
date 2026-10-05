---
name: adversarial-qa
description: Adversarially review a batch of obsidian-agent changes from a fresh agent that did not write them. Use after just check, for every batch, before the work is called done.
---

<objective>
The diff's best outcome is getting shorter. You did not write it. The author's reasons are not evidence. List cuts. Do not apply them.
</objective>

<process>
1. Ignore any summary of intent. Read ARCHITECTURE.md §§9, 10, 11.2, and 11.3.
2. List the batch with `git status --short`. Read `git diff HEAD` and the untracked files in that list. Leave `OpenResearch/`, `feynman/`, and `docs/research/` alone unless they are the batch. Trace the flow the diff touches before judging it.
3. Climb the ladder on every added line. Stop at the first rung that holds: it need not exist; it already lives in this repo; the stdlib does it; the platform does it; an installed dependency does it; it can be one line; only then the minimum that works.
4. Report every cut that keeps robustness, the caller-visible outcome, and extensibility. One line, biggest cut first: `<file>:L<line>: <tag> <what to cut>. <replacement>.`
5. A cut that drops correctness, safety, debuggability, operability, or maintainability, or breaks a §10 boundary, is not a finding. If every remaining cut is one of those, stop with `Lean already. Ship.` and name that sacrifice in one line.
6. After the cut list, one line per break: a §10 miss, a sensor or canary the diff should have, a workflow registered as a graph, a LangChain or LangGraph import outside the §9 table, a test that restates the implementation, an experiment record another agent cannot rerun. Tag these `break:`.
</process>

<format>
Tags for cuts:

- `delete:` dead code, unused flexibility, speculative feature. Replacement: nothing.
- `stdlib:` hand-rolled thing the standard library ships. Name the function.
- `native:` dependency or code doing what the platform already does. Name the feature.
- `yagni:` one implementation, one caller, config nobody sets, a wrapper that only delegates.
- `shrink:` same logic, fewer lines. Show the shorter form.

End the cut list with `net: -<N> lines possible.` Nothing to cut: `Lean already. Ship.`

A single proof, fitness sensor, or smoke check is the minimum. Never flag it for deletion. Do not flag correctness, security, or performance here; those are `break:` lines.
</format>

<success_criteria>
The report is lines, not an essay. A negative `net` means the batch is not done. `Lean already. Ship.` is the only stop, and it names the sacrifice. Restating the plan does not close a line.
</success_criteria>
