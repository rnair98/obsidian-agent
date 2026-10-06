# Feynman audit: what to borrow, what to change

Reviewed 2026-09-27. Recommendation: build an evidence-preserving research system
whose outputs improve a vault over time. Do not define success as matching
Feynman's command catalog, agent count, or artifact count.

## Scope and evidence

- Feynman local snapshot: `fe3fd94943df8c5b519fed14c8485215b206aba8`, package
  version `0.5.8`. This is not a claim about later upstream versions.
- Obsidian-agent baseline: `460b106634f35ecc6479adff98e51ab9a894f3dc`, plus
  the current uncommitted architecture and roadmap documents. Current code is
  authoritative, as requested; proposals below are not shipped capabilities.
- Inspected workflow/system/agent prompts, Pi launch/settings/package wiring,
  selected scholarly/alphaXiv/Hugging Face tools, telemetry, evaluation code,
  committed evaluation reports, relevant tests, and release history.
- Graph discovery and coverage checks succeeded this turn. The two inspected
  TypeScript test files were excluded by fast indexing and read directly.
  Coverage is best-effort, not a whole-repository correctness proof.
- Ran five offline characterization checks against actual source definitions
  with synthetic inputs and mocked metadata/network responses. No paid model
  runs, provider calls, installs, or full application test suites were run.
  Pi and bundled package internals were not installed/independently audited.
- Historical measurements below are committed Feynman reports, not reruns.
  Release notes are maintainer reports, not independently reproduced history.

Reproduce the five checks from the obsidian-agent root (Node 24.21.0 used):

```sh
git clone https://github.com/Companion-Inc/feynman.git
git -C feynman checkout fe3fd94943df8c5b519fed14c8485215b206aba8
node docs/research/feynman-audit-checks.mjs
```

The script refuses any other revision. It loads code from that checkout
in-process, so run it only against the pinned, trusted snapshot.

The script accepts an alternative Feynman checkout path. It intentionally
characterizes weaknesses in the reviewed snapshot; if upstream fixes one,
its assertion should fail and this audit should be revised. It does not test
whether a particular LLM will produce the bad example.

## What Feynman gets right

Feynman is a thin research-oriented layer over an existing agent runtime. It
reuses Pi instead of owning every terminal, model, and session primitive.
It offers useful literature-specific retrieval, explicit uncertainty rules,
file-based handoffs, dataset/code grounding, and an adversarial review role.
Its tools expose provenance and several have bounded responses, request
timeouts, and explicit rate-limit/fallback behavior. It also ships a small
research-quality evaluation corpus and records failed runs.

These are worth retaining as principles. The gap is between a good instruction
and an enforced, measurable research contract. More agents, citations, or files
do not automatically close that gap.

Sources: [runtime](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/src/pi/runtime.ts),
[research tools](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools.ts),
[science adapters](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools/science-databases.ts),
[eval documentation](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/README.md).

## Findings and architectural consequences

### F1 — Identifier correctness is not claim support

**Confirmed by code and offline probes.** `scoreCitations()` resolves identifiers
and accepts title-token overlap or the first author's surname. It does not
compare a claim with a source passage. Changing “two plus two is four” to
“two plus two is five” with the same mocked bibliography yields identical
perfect identifier/title scores. A wrong title with the expected surname also
passes. `keyRecall()` measures whether expected papers are mentioned, not whether
the answer uses them correctly.

The verifier prompt does demand semantic support; the issue is that these
metrics cannot tell whether the instruction was followed. The release phrase
“same research quality” exceeds what these metrics alone establish.

**Consequence:** evaluate identifier identity, citation support, citation
completeness, answer correctness, and usefulness separately. Store the exact
passage and locator behind decisive claims. Human-calibrated semantic judgments
can assess support but must remain fallible, with an uncertain outcome.

Sources: [scorer](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/run.mjs) (`scoreCitations`, `keyRecall`),
[verifier](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/.feynman/agents/verifier.md),
[0.5.3 release](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/RELEASES.md).
External corroboration: the [ALCE paper](https://arxiv.org/abs/2305.14627v2)
separates correctness and citation quality in evaluation. Only its abstract
was inspected here; no ALCE numeric result is used as a product target.

### F2 — Completion is spread across prompts, files, and telemetry

**Confirmed by code/probe; historical failure reported upstream.** The evaluator's
`findFinal()` accepts even empty Markdown and provenance files and chooses the
largest matching artifact. It does not parse verification state. Telemetry's
`stopStatus()` classifies non-error/non-aborted stops as completed;
`output_written` separately accepts any recently modified file under outputs or
papers, including intermediate artifacts. These are activity indicators, not
research acceptance criteria.

The pre-wait 0.5.3 report records a run ending while the reviewer still ran;
the final provenance file was missing. Later prompts instruct the parent to
wait. This is a historical fixed symptom, not evidence the same failure always
occurs in 0.5.8. The Feynman-owned launch path still delegates execution to Pi;
this audit does not claim Pi lacks all lifecycle controls.

**Consequence:** a run manifest and deterministic finalizer own completion.
`complete`, `partial`, `failed`, and `cancelled` must be separate terminal states.
A partial deliverable is useful but cannot masquerade as verified completion.
When workers are eventually introduced, the supervisor must join/cancel them
and collect artifact receipts; a prompt reminder is insufficient.

Sources: [scorer](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/run.mjs),
[telemetry](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools/telemetry.ts),
[launch](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/src/pi/launch.ts),
[pre-wait report](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/results/2026-09-24-lit-0.5.3-pre-wait-ferrylane-openai_gpt-5.6-terra.md).

### F3 — Some evidence rules create false certainty or selection bias

**Confirmed prompt content; impact is a testable hypothesis.** The researcher
says “If a search returns zero results, the thing does not exist” and requires
at least five evidence entries. It also excludes evidence without a URL.
A failed retrieval is not proof of nonexistence; a five-source quota can pad
narrow answers; URL-only evidence excludes valid local/private artifacts.
The reviewer defaults to AI/ML-paper concerns even when `/lit` covers other
research domains.

**Consequence:** record searched scope and unknowns, allow fewer stronger
sources, and accept vault/file/commit locators. Use question-specific evidence
requirements. Absence claims need a stated search boundary and uncertainty.
Paper-review rubrics should be optional task criteria, not universal gates.

Sources: [researcher](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/.feynman/agents/researcher.md),
[reviewer](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/.feynman/agents/reviewer.md),
[literature workflow](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/prompts/lit.md).

### F4 — Retrieval policy favors seminal-paper recall by default

**Confirmed code; generalized quality impact unmeasured.** Semantic Scholar
search defaults to citation-count ordering. Anonymous relevance-search 429s
can fall back to that ordering, with the change disclosed in the returned note.
The fixed corpus rewards known key-paper recall. This is useful for foundational
surveys, but does not establish suitability for recent results, negative findings,
minority positions, or implementation questions. Two indexes confirming one
paper's identity also do not constitute two independent studies.

**Consequence:** explicit task intent should control relevance/recency/foundation
tradeoffs. Preserve the actual query, filters, ordering, fallback, and retrieval
time. Group preprint/venue/mirror records as one evidence family. Test recent,
contradictory, negative, and unanswerable cases; do not add a universal ranking
model before measuring these failures.

Sources: [science adapters](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools/science-databases.ts)
(`searchSemanticScholar`), [questions](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/questions.jsonl).

### F5 — Post-hoc citation editing can hide how a conclusion was reached

**Confirmed workflow structure; failure risk inferred.** Deep research drafts,
then adds citations, then reviews. The verifier merges numeric source IDs and
may delete unsupported claims. That can improve the deliverable, but its prose
output is not a structured history of which claim changed, which evidence was
rejected, or which question became unanswered. Counting accepted/rejected URLs
in a sidecar is weaker than retaining those relationships.

**Consequence:** attach evidence references while gathering; synthesize from
those records; keep revision/assessment records when a conclusion changes.
Distinguish identity, accessibility, support, contradiction, and uncertainty.
Unavailable content should remain recorded as unavailable, not silently become
false or disappear from the research history.

Sources: [deep research](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/prompts/deepresearch.md),
[verifier](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/.feynman/agents/verifier.md).

### F6 — Fixed workflow ceremony is not adaptive research

**Confirmed prompts; cost/quality advantage of alternatives needs evaluation.**
`/deepresearch` imposes a plan approval turn, while `/lit` continues automatically.
Direct deep research has a minimum of three queries; literature review always
specifies verifier and reviewer stages. The autoresearch prompt continues until
interruption or its iteration limit. These are understandable recipes, but
question difficulty, evidence sufficiency, and marginal information gain are
not equivalent to a fixed number of queries, roles, or iterations.

**Consequence:** keep bounded execution in code while allowing the agent to
choose research actions. Default to a single researcher and evidence assessment;
escalate to independent critique or parallel tasks only when uncertainty or
measured benefit justifies it. Ask for clarification when the goal is ambiguous,
and approval for consequential actions—not for routine authorized reading.
Keep an explicit `budget_exhausted` outcome; do not dress it up as sufficient
coverage. A learned stopping rule is later work, after calibration.

Sources: [deep research](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/prompts/deepresearch.md),
[literature](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/prompts/lit.md),
[autoresearch](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/prompts/autoresearch.md).

### F7 — Compact tool output does not imply bounded runtime memory

**Confirmed code.** Hugging Face file reading calls `response.text()` before
truncating to `maxChars`, and has no explicit request timeout in this path.
File-extension exclusions are helpful but a very large `.txt` can still be
fully downloaded/materialized. `repoFiles()` slices a fetched array; the API
response and model-visible response are different resource boundaries.
By contrast, the general science adapter has a 25-second request timeout.

**Consequence:** enforce transferred-byte, decoded-byte, item, and deadline
limits before materializing large inputs; persist bounded extracts and return
references. Preserve truncation and continuation metadata. Do not read a whole
paper/corpus into memory merely to return a small excerpt.

Source: [Hugging Face adapter](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools/huggingface.ts)
(`fetchJson`, `repoFiles`, `readRepoFile`),
[science adapter](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools/science-databases.ts).

### F8 — Extraction and service failures can masquerade as evidence gaps

**Confirmed by two offline probes.** Section extraction treats an unpunctuated
prose line such as “Accuracy improved” as a heading; a requested results section
can consequently be reported missing. DOI scoring treats mocked Crossref and
DOI-handle HTTP 503 responses as `resolves: false` rather than unknown. These
are distinct failure classes: parse uncertainty and provider unavailability.

**Consequence:** typed acquisition outcomes must separate not-found, access
blocked, timeout/rate limit, parse failure, and successfully inspected evidence.
A section parser should preserve source offsets and expose ambiguity instead of
quietly implying that the paper lacks a section. Pin paper/code versions and
record extraction method; alphaXiv's AI report is derived material, not raw paper
text (the tool already exposes a `fullText` option).

Sources: [section parser](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools/alpha-sections.ts),
[alpha tools](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools/alpha.ts),
[DOI scorer](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/run.mjs). Existing
[section tests](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/tests/alpha-sections.test.ts) cover simple headings,
not the reproduced unpunctuated-prose case.

### F9 — Report artifacts are not a durable knowledge-update model

**Confirmed contract boundary, not a claim that Feynman has no memory.** Feynman
has sessions, annotations, a lab notebook convention, and optional memory packages.
Its workflow artifacts are topic-slug based. That convention does not guarantee
uniqueness across repeated/concurrent runs of the same topic. The inspected
workflow contracts do not specify evidence-driven reconciliation of existing
Obsidian notes, source invalidation, or preservation of manual edits.

**Consequence:** obsidian-agent's differentiator should be incremental knowledge
maintenance: retrieve relevant existing notes, propose create/update/link/no-op,
retain provenance, and detect changed evidence. Use a run ID for isolation and
content hashes for conflict detection. The model proposes changes; one controlled
writer applies them. This needs local integration tests, not a new graph database.

Sources: [artifact conventions](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/AGENTS.md),
[optional memory packages](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/src/pi/packages.ts),
[alpha annotations](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools/alpha.ts).

### F10 — Telemetry does not automatically provide safe or complete evaluation

**Confirmed code; no real disclosure tested.** Error telemetry preserves arbitrary
error text after replacing the home path and truncating it. That is not content
or secret redaction. Workflow status and output-write activity also do not prove
quality. Committed eval reports show `$0` when model pricing is unavailable;
that means unknown cost, not free research.

**Consequence:** keep operational events and private research evidence separate.
Allowlist exported telemetry fields; do not export raw errors by default. Keep
local diagnostics useful. Report unknown cost explicitly and retain token/cache
breakdowns. Phoenix can remain an optional observer rather than a correctness
dependency; observability must not become another production data store to keep
consistent with research state.

Sources: [telemetry](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/extensions/research-tools/telemetry.ts)
(`errorText`, `finishRun`), [eval usage](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/run.mjs),
[eval docs](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/README.md).

### F11 — Published runs demonstrate progress, not superiority

**Historical evidence only.** The final 0.5.3 Terra report records 4/4 completed
questions, 44 resolving/title-matched citations, and 578–652 seconds per question.
It records 13,353,797 aggregate tokens across sessions and `$0` cost. These are
provider/runtime-reported totals, including repeated/cache accounting—not unique
source-text volume and not a dollar estimate. The pre-wait run completed 3/4.

Useful evidence, but a tiny visible subset, changing live retrieval, no paired
repeated trials reported there, and no claim-support score cannot establish a
broad research-quality win. The suite has 12 questions; the four-question report
is not a result for all 12. Refusals/timeouts must remain failures in the original
cohort even if a later report deliberately runs a smaller subset.

**Consequence:** compare against the current obsidian-agent pipeline and a simple
single-agent baseline on equal budgets. Separate frozen-evidence experiments,
frozen-corpus search experiments, and live canaries. Publish per-case failures,
uncertainty, and operational outcomes, not just successful-run averages.

Sources: [final report](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/results/2026-09-24-lit-0.5.3-ferrylane-openai_gpt-5.6-terra.md),
[pre-wait report](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/results/2026-09-24-lit-0.5.3-pre-wait-ferrylane-openai_gpt-5.6-terra.md),
[scorer](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/evals/run.mjs).

### F12 — Its history already argues against copying the whole product

**Maintainer-reported history, corroborated selectively by present wiring.**
Release 0.4.0 removed a science workbench, many specialist integrations, scheduling
workflows depending on an absent tool, and a ranking path that missed key papers.
0.5.0 returned to stock Pi. 0.5.3 removed duplicated/obsolete prompt instructions;
0.5.4 removed a session-search preset with the wrong storage path and a command
collision. Current runtime wiring indeed loads stock Pi and bundled packages.

**Consequence:** adopt evaluated capabilities rather than a catalog. Keep existing
LangGraph, typed schemas, filesystem ports, and virtual execution boundaries.
No terminal clone, scheduler, GPU fleet, generic plugin platform, or extra
production model-call runtime is required for the initial research product.
Do not describe removed features as current bugs.

Sources: [release history](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/RELEASES.md) §§0.4.0–0.5.4,
[current launch](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/src/pi/launch.ts),
[current package loading](https://github.com/Companion-Inc/feynman/blob/fe3fd94943df8c5b519fed14c8485215b206aba8/src/pi/runtime.ts).

## Obsidian-agent must fix its own baseline first

The current code has useful boundaries but is not already the better system:

| Current gap | Evidence | Consequence |
|---|---|---|
| Reports/CSV share filenames; note IDs only deconflict within a run | [persist](../../app/engine/nodes/persist.py) | Repeated/concurrent research can overwrite earlier artifacts. |
| Response projection checks existence, not current-run ownership | [executor](../../app/engine/executor.py) | Old artifacts can be reported by a standalone workflow. |
| Memories store source counts but omit structured source records; their report path is reused | [memory store](../../app/engine/artifacts/memory.py) | A later run can reuse conclusions after their original grounding is lost. |
| Prior memories are described as privileged context and selected by a bounded filename manifest | [executor](../../app/engine/executor.py) | Stale/irrelevant generated knowledge can bias new research. |
| Sources and notes lack structured evidence locators/status | [schemas](../../app/engine/schema.py), [Zettelkasten](../../app/engine/agents/zettelkasten.py) | Fluent unsupported findings can become durable notes. |
| Static graph has no evidence-assessment stage | [graph](../../app/engine/graphs/research.py) | Report generation goes straight to note extraction. |
| Old tool results are cleared; persistence happens after synthesis | [middleware](../../app/engine/nodes/builders/middleware.py), [persist](../../app/engine/nodes/persist.py) | The policy must retain cited evidence before context compaction. |
| Profile summary cache keys only on note count | [profiler](../../app/engine/nodes/vault_profiler.py) | Edited conventions can leave a stale qualitative profile. |
| A run ID is generated but request has no resume contract | [executor](../../app/engine/executor.py), [request](../../app/engine/schema.py) | A checkpointer alone does not provide user-visible resumability. |

These are source-derived risks, not newly reproduced end-to-end application
failures. The roadmap gives them failure-injection acceptance tests.

## Strategy: evidence first, adaptive actions, controlled publication

Keep one modular application and one authoritative writer. The agent chooses
which bounded research action to take; deterministic code controls permissions,
budgets, durable records, terminal status, and publication. Use typed source,
evidence, and assessment records only where a consumer needs them. Markdown
reports and notes are readable projections of those records, not the sole record.

The initial target is technical research that can answer a question with cited
support, retain uncertainty, and safely improve an existing vault. Foundational
surveys, current technical comparisons, and paper/code audits are evaluation
lanes over shared primitives. They are not three mandatory orchestration stacks.

Without an engineering-cost limit, this remains the preferred architecture:
full evidence lineage, recoverable publication, selective verification, calibrated
evaluation, and incremental knowledge maintenance. Broader domains, more sources,
more independent reviewers, larger corpora, and policy optimization frequency are
quality dials. Evidence integrity, manual-edit protection, explicit failure states,
and runtime bounds are not quality dials.

What engineering cannot guarantee: complete discovery on the open web, truth from
citation agreement, independent evidence from mirrored sources, or identical future
LLM/web outputs. What engineering can guarantee: which bytes were inspected,
which version was used, what checks ran, what remained unknown, what was written,
and whether configured execution limits were enforced.

Use streaming/bounded reads and disk-backed evidence; hydrate only relevant
passages into model context. Measure peak RSS and total source/context bytes.
Keep heavyweight semantic optimization and eventual training offline. Existing
Python/LangGraph is retained; no rewrite is justified without resource measurements.

The implementation sequence and measurable release gates belong in
[ROADMAP.md](../../ROADMAP.md). The [OpenResearch audit](openresearch-audit.md)
extends the design to controlled experiment execution. A better result must beat baselines on evidence
quality, safe knowledge reuse, and resource use—not merely produce more output.
