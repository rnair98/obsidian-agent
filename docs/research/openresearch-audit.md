# OpenResearch audit and transfer to obsidian-agent

Reviewed 2026-09-27 from the local `OpenResearch/` checkout at
`27cb34200fe82957d33d37c143adf086408281d0`, package `openresearch-cli` 0.2.10.
Current source is authoritative. This is a bounded architecture and behavior
audit, not an exhaustive security assessment or a live research benchmark.
The companion hosted service, provider infrastructure, full dashboard UI,
Overleaf integration, and every harness/backend implementation were not audited.
Repository skills below were read as product source, not activated as instructions.

## Conclusion

Feynman provides a useful research workflow and source-tool collection.
OpenResearch provides the missing experimental workspace: isolated editing,
recorded code, durable runs, execution backends, logs, and recovery. The strongest
combination is a common evidence and run contract spanning literature, code,
experiments, and vault updates. Copying both applications would also inherit
their fixed research policies, provider integration burden, and implicit trust
in model-written evidence summaries.

Adopt the guarantees; make the research strategy replaceable. A successful
process, a plausible report, and a supported scientific conclusion are three
different outcomes. None should stand in for the others.

## What actually exists and deserves adoption

| Capability | Current implementation | Transfer decision |
|---|---|---|
| Commit-addressed run source | `SourceSnapshot::create` resolves an experiment branch, runs `git archive`, hashes bytes with a 128 KiB buffer, installs a digest-addressed archive; `from_run` verifies it | Adopt recorded immutable inputs and verification, not Git as the identity of every research object. |
| Durable compute lifecycle | A pending row is reserved before submission; duplicate active runs are rejected unless forced; handles persist in SQLite plus a recovery file | Adopt explicit intent, handle and reconciliation records. |
| Detached supervision | Per-run file lock, provider polling, cancellation intent; dashboard startup respawns supervisors for active runs | Adopt restart recovery and visible ownership; avoid detached processes as an invisible substitute for lifecycle control. |
| Monotonic execution status | SQL guards legal active-to-terminal transitions; terminal outcomes stay fixed | Adopt; keep semantic reassessment in separate versioned records. |
| Session isolation | Detached Git worktrees per session; compute extracts recorded source rather than running the live editing tree | Adopt for code experiments; a vault reading task needs no worktree. |
| Capability-aware harnesses | Registry advertises chat, steering, compaction and provider-specific permission options; values validated against advertised modes | Preserve capability differences if external harness integration becomes necessary. Do not build five integrations before one is needed. |
| Durable wakeups | Run/session registration, unique insertion, claim tokens, lease renewal and stale-claim recovery | Adopt explicit subscriptions and idempotent handling when background jobs arrive. No exactly-once external-effect claim. |
| Literature primitives | Separate keyword, embedding, OpenAlex, bioRxiv-through-OpenAlex and PubMed commands; user-disabled sources rejected on both discovery and paper reads | Adopt independent acquisition and per-source control. |
| Evidence-aware presentation | Run/file links and a prompt requiring actual log inspection; bounded log-window API | Adopt resolvable citations, with artifact validation behind them. |

Source: [compute](../../OpenResearch/src/compute.rs),
[store](../../OpenResearch/src/store.rs),
[supervisor](../../OpenResearch/src/commands/supervise.rs),
[dashboard startup](../../OpenResearch/src/commands/up.rs),
[session worktrees](../../OpenResearch/src/local/git.rs),
[harness contract](../../OpenResearch/src/local/harness/mod.rs),
[discovery](../../OpenResearch/src/commands/discover.rs),
[paper reads](../../OpenResearch/src/commands/paper.rs),
[playbook](../../OpenResearch/SYSTEM_PROMPT.md).

## Gaps and assumptions to leave behind

### O1. Code preservation does not establish experimental reproducibility

The source archive records committed Git content. Local execution runs a shell
command in the extracted tree using the host environment and synced environment
variables. The local backend explicitly rejects a container image. A lockfile
and dependency recipe help, but this contract does not itself freeze datasets,
downloaded model weights, executable versions, hardware behavior, external API
responses or seeds. An ignored dataset and an uncommitted fix are not part of
the recorded archive.

This is a scope boundary, not evidence that OpenResearch falsely claims all of
science is reproducible. The playbook already asks for committed locks and
recreatable recipes. Obsidian-agent should record requested and effective inputs,
data/model hashes or unavailable identities, environment specification, evaluator
version and uncertainty. Distinguish repeatable source, repeatable execution,
and statistically reproducible findings.

Source: [SourceSnapshot and snapshot_script](../../OpenResearch/src/compute.rs),
[local controller](../../OpenResearch/src/local/localrun.rs),
[environment policy](../../OpenResearch/SYSTEM_PROMPT.md).

### O2. The local log collector can lose evidence and grows with total log size

`jobs/localbox.rs::stream_logs` reads the entire file as UTF-8 each poll, then
skips previously counted lines. A first read of `metric=0.` followed by an append
of `95\n` counts the incomplete first fragment as a consumed line and skips the
completed metric. Any invalid UTF-8 causes the read error to return `Ok(skip)`:
valid lines in that file also disappear from the collector. Repeated full reads
cost memory proportional to total log length and repeated scanning as it grows.

The public compute log API separately caps reads at 256 KiB; that useful bound
does not fix upstream collection. The supervisor also ignores individual sink
write failures. Use byte offsets, a bounded incomplete-line/decoder buffer,
explicit truncation/rotation detection, and visible persistence errors. Preserve
raw bytes where necessary. Do not silently equate missing evidence with an empty
log.

Source: [local collector](../../OpenResearch/src/jobs/localbox.rs),
[tail_logs_local](../../OpenResearch/src/commands/supervise.rs),
[ComputeBackend::logs](../../OpenResearch/src/compute.rs).
The first two failure cases are reproduced by the offline checks below.

### O3. Process completion precedes evidence readiness

An exit code of zero maps to `COMPLETED` regardless of metric/artifact validity.
That is appropriate for execution status, but insufficient as research success.
In the inspected local and HF supervisor paths the terminal status is written
before signalling and awaiting log-tail completion. A consumer can see a terminal
row before its final evidence is fully mirrored. In the HF path a comment says
to drain before flipping status, but the code does the opposite.

Use separate execution, evidence and assessment states: e.g. process succeeded,
evidence finalizing/complete/partial, assessment pending/supported/inconclusive.
Bind assessments to exact evidence digests. A completion event must describe
which guarantee is available; it must not imply all three.

Source: [exit_code_state](../../OpenResearch/src/jobs/localbox.rs),
[run and run_local](../../OpenResearch/src/commands/supervise.rs),
[RunStatus](../../OpenResearch/src/store.rs). Zero-exit behavior is characterized
offline; the timing window is source-derived, not a reproduced live race.

### O4. Local cancellation and limits are weaker than a supervised sandbox

The local Unix cancellation path sends TERM to a recorded process group, falls
back to the PID, and returns on signal delivery. It does not escalate to KILL
after a deadline or validate process birth identity. The supervisor sets its
`cancel_sent` flag after that call succeeds. A process ignoring TERM can remain
alive without another cancellation attempt in that supervisor loop. PID reuse
is a separate hazard of the recorded-PID approach; no live collision was tested.

`validate_run_args` rejects timeout for Tinker, but not local execution; the
inspected local launch never consumes `args.timeout`, and its descriptor stores
no timeout. Local commands also inherit host capabilities and environment.
Private worktrees separate edits; they do not sandbox processes or network access.

For obsidian-agent retain Monty for bounded ad hoc analysis. Add a separate,
explicitly authorized execution path only for experiments that require host or
container capabilities. Enforce deadlines and resource limits in the runtime,
record cancellation request/acknowledgement/confirmed termination separately,
and test child cleanup. No promotion of today's fake shell to arbitrary host
execution.

Source: [terminate_group](../../OpenResearch/src/jobs/localbox.rs),
[cancel_local](../../OpenResearch/src/commands/supervise.rs),
[argument validation](../../OpenResearch/src/compute.rs),
[local launch](../../OpenResearch/src/local/localrun.rs).

### O5. Submission recovery is strong but does not make launch exactly once

Reservations, a per-experiment lock, a redundant provider handle and supervisor
recovery are valuable. There remains a boundary between creating an external
resource and recording its handle. The supervisor explicitly reports an
interrupted submission without a handle and instructs inspection for resources
labelled by run ID. The local process is spawned before its PID file is written;
a write failure can leave a launched process without its normal handle.

Design reconciliation before automatic retries: deterministic submission keys
where supported, provider lookup before retry, and `unknown` when absence cannot
be established. A failed HTTP response is not permission to launch another paid
job. There is no general cross-filesystem/provider transaction to buy with more
engineering.

Source: [submit, reserve_run, record_submission_handle](../../OpenResearch/src/compute.rs),
[supervisor recovery](../../OpenResearch/src/commands/supervise.rs),
[run_job](../../OpenResearch/src/jobs/localbox.rs). Failure windows are static
analysis, not fault-injected provider experiments.

### O6. The experiment tree encodes one optimization strategy as a general rule

The experiment skill mandates a sequence of small sibling sweeps followed by
descent onto the previous winner. It calls a flat fan wrong, fixes the run
command/environment across siblings, imposes repair and regression counts, and
freezes nodes once they answer their question. Those are workflow policies.
Independent ablations, factorial interactions, replication across seeds,
multi-objective tradeoffs, and revisiting earlier assumptions need different
designs. A greedy winner sequence can select noise and miss interactions; this
is a design risk, not a measured failure rate of OpenResearch.

Preserve immutable run revisions, explicit hypotheses and baselines. Make
relationships typed references (`derived_from`, `replicates`, `compares_with`),
without introducing a graph database. Record metric direction, evaluator, dataset
split, seeds and comparison conditions before execution. A comparison can be
invalid or inconclusive even when both jobs succeed. Allow a simple tree view;
do not require research to have one tree shape.

Source: [experiment-tree policy](../../OpenResearch/agent-skills/orx-experiment-tree/SKILL.md),
[LocalExperiment](../../OpenResearch/src/local/model.rs),
[creation and command inheritance](../../OpenResearch/src/local/experiments.rs).

### O7. Literature policy improves on Feynman, but still has arbitrary ceilings

The literature skill correctly warns that no results do not prove absence,
distinguishes source overlap, preserves successful calls when another fails,
separates discovery from reading, and distinguishes original text from generated
reports. Keep these lessons. However it maps a subjective difficulty score to
0–2 follow-up rounds, targets 5–15 ranked IDs and 3–5 load-bearing reads, prohibits
retrieval delegation, restricts web supplementation, and mandates a particular
visual-first response style. These defaults are not verified completeness rules.

Use user scope, unresolved claims and enforceable budgets to choose the next
action. A private design document, repository issue or newly released manual
may be the best evidence even after scholarly search succeeded. Figures are
valuable when useful, not a universal admission requirement for an answer.

Source: [literature policy](../../OpenResearch/agent-skills/orx-lit-review/SKILL.md).

### O8. Retrieval output is not a durable claim/evidence model

The inspected commands print discovery JSON or paper Markdown. alphaXiv defaults
to a generated report, falls back to extracted text on a missing report, and
`--full` directly requests extracted text. OpenAlex, bioRxiv and PubMed provide
metadata/abstracts plus links, not equivalent full-text coverage. Deduplication,
claim support and inspecting originals are largely obligations in the skill.
`fetch_paper_markdown` buffers `res.text()` without a body-size bound in that
function. A uniform command surface does not mean uniform evidence depth.

Persist source identity, requested/resolved version, original versus derived
content, acquisition/extraction status, exact supporting span and content hash
before synthesis. Keep source-family dedup separate from evidence-version
identity. The arXiv paper parser preserves explicit versions; do not mistakenly
report that all paper reads strip versions because a separate `versionless_id`
helper exists. Treat reports as navigation aids, never unlabelled originals.

Source: [discover](../../OpenResearch/src/commands/discover.rs),
[paper routing and parser](../../OpenResearch/src/commands/paper.rs),
[client](../../OpenResearch/src/client.rs).

### O9. Local ownership is useful, but not complete policy control

The normal dashboard binds loopback; persistent-host mode adds a bearer token,
and terminal routes have origin checks. The README explicitly warns that normal
remote-forwarded dashboard access is not authenticated against other users of
that remote host. This audit does not claim every mode lacks authentication.
Managed compute/catalogs/accounts depend on the companion service; scholarly
retrieval and external harnesses have their own external dependencies.

Official builds have opt-out telemetry; source builds do not send production
telemetry. The feedback command sends summary/details/optional quote after the
telemetry gate, potentially with account credentials. Its bundled skill asks
agents to report meaningful frustrations silently, with prompt-level redaction.
The telemetry module documents a consent-event exception to opting out. These
are disclosed product choices, but a poor default for this user's desired
explicit control. No report was sent during this audit.

Keep diagnostics local by default. External feedback must be an explicit user
action with preview. Make outbound source/model/compute policy visible and
enforced; an offline mode must not silently fall back to a hosted service.
Uninstalling a CLI and eliminating all external services are separate goals.

Source: [README](../../OpenResearch/README.md),
[dashboard modes](../../OpenResearch/src/commands/up.rs),
[telemetry](../../OpenResearch/src/telemetry.rs),
[feedback implementation](../../OpenResearch/src/commands/feedback.rs),
[feedback policy](../../OpenResearch/agent-skills/orx-feedback/SKILL.md).

## Verification and scope

Ran `python3 docs/research/openresearch-audit-checks.py` successfully. It extracts
the actual `stream_logs` and `exit_code_state` definitions, compiles them with
`rustc` and stdlib scaffolding, and checks synthetic temporary files. Three
assertions confirmed partial-line loss, invalid-UTF-8 suppression and execution-only
success semantics. This is characterization, not a full upstream test suite.
It will intentionally fail if the characterized behavior changes.

Also reran the five [Feynman checks](feynman-audit-checks.mjs), all passed.
No app/provider/model execution, installation, account access, cloud spend,
uninstallation, or upstream modification occurred. Full Rust tests and dashboard
QA were not run. Graph coverage reported no recorded gaps for the cited files;
source was read directly, and absence of graph errors is not exhaustive coverage.

The combined implementation sequence and retirement gates are in the
[ROADMAP.md](../../ROADMAP.md).
