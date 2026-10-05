# Implementation tasks

Status for [ROADMAP.md](ROADMAP.md). Rationale and exit gates stay there; check a box only in this file. Read [ARCHITECTURE.md](ARCHITECTURE.md) §§5, 9, 10, and 12 before implementing. Audits and planning documents are not delivered features.

A task is one reviewable change. Touch the listed files, and add a module only when that task needs it.

**Open:** T01 → T02 → T03 → T04. After T01, T05, T06, and the T13 cases can proceed beside that chain. T28, the workflow inventory, can be filled at any time. Leave agent frameworks, model libraries, databases, and dashboards unstarted.

## Open

- [ ] **T01 — Exercise the complete graph without live models.**
  **Touch:** `app/engine/graphs/research.py`, `app/engine/nodes/builders/agent.py`, `tests/engine/`, `tests/nodes/`.
  Inject deterministic model results at the model-call boundary. Run profiler → researcher → summarizer → Zettelkasten → persist on a temporary vault, including empty and populated vaults and a failure at each stage.
  **Done when:** the test checks state projection and the files produced, with no provider, network, or Phoenix. Record current behavior, and leave unsafe behavior out of the contract.

- [ ] **T02 — Give every persisted artifact a run owner.** Depends on T01.
  **Touch:** `app/engine/schema.py`, `executor.py`, `nodes/persist.py`, `artifacts/`, `workspace.py`.
  Pass the executor run id through immutable context. Store the report, CSV, draft notes, and a versioned manifest under `outputs/runs/<run_id>/`. Make memory filenames deterministic per run. Leave existing user files intact. Generated notes stay run-owned drafts until T19.
  **Done when:** concurrent same-topic runs use disjoint paths, and persisting one run again does not duplicate notes or memory.

- [ ] **T03 — Return write receipts instead of guessing output paths.** Depends on T02.
  **Touch:** `nodes/persist.py`, `executor.py`, `schema.py`, `tests/engine/test_executor_response.py`.
  Persistence returns receipts with run id, path, kind, and hash. Project the HTTP response from those receipts. Remove existence scans, memory-directory diffs, duplicated filename prediction, and obsolete aliases.
  **Done when:** standalone workflows return no new artifacts when older reports exist, and every returned receipt belongs to this run.

- [ ] **T04 — Make interrupted persistence recoverable.** Depends on T03.
  **Touch:** `app/engine/artifacts/`, `nodes/persist.py`, `backends/`, `tests/nodes/test_persist.py`.
  Stage writes, validate required artifacts, journal applied writes, and publish the completion manifest last. Extend the filesystem port only for this writer. Distinguish complete, partial, and failed.
  **Done when:** a failure between any two writes leaves an honest manifest, and retry neither duplicates memory nor reports a partial run as complete.

- [ ] **T05 — Align prompts with actual tool capabilities.** Depends on T01.
  **Touch:** `app/engine/agents/`, `app/engine/tools/`, `executor.py`, `app/core/resources/agent_config.yaml`, `app/harness/`.
  Resolve the Jina/host-network and prior-memory `ls` contradictions in ARCHITECTURE.md §12. Enforce allowed operations in runtime policy. Reject tool requirements a provider cannot offer. Keep the shell virtual.
  **Done when:** advertised prompt examples run, and a denied operation fails when model or source text requests it.

- [ ] **T06 — Remove ambiguous automatic agent re-execution.** Depends on T01.
  **Touch:** `app/engine/nodes/builders/agent.py` and its tests.
  Replace the stream-with-no-final-result fallback with explicit failure or recovery. Distinguish a rejected request from uncertain completion.
  **Done when:** a fake stream that performs an action and then fails does not execute that action again.

- [ ] **T13 — Land the reviewed cases.** Start after T01. Paired scores wait under Next.
  **Touch:** evaluation fixtures beside `tests/`. Use `docs/research/` audit checks, and keep either upstream checkout out of the regression suite.
  Cover factual, comparative, recent, contested, unanswerable, private-source, stale-memory, and repeated-vault questions, plus the eight audit counterexamples. Separate development from held-out cases. Define semantic labels before comparing candidates.
  **Done when:** the cases and labels exist, and integrity failures score apart from semantic support.

## Next — close M0 and M1

- [ ] **T07 — Enforce one budget across the run.** Depends on T04 and T06.
  **Touch:** `executor.py`, `schema.py`, `nodes/builders/`, `app/harness/session.py`, `app/core/settings.py`.
  Count calls, actions, tokens, bytes, wall time, and concurrency, including retries, child work, provider-hosted tools, and MCP. Reject limits a provider cannot enforce. Report gaps and bounded overshoot.
  **Done when:** a tiny limit stops the next dispatch, cancels in-flight work where supported, and leaves a partial result with that stop reason.

- [ ] **T08 — Record status, then add validated resume.** Depends on T07.
  **Touch:** `executor.py`, `schema.py`, `app/api/v1/workflows.py`.
  Land status first. Running, complete, partial, failed, and cancelled come from recorded checks and reuse T04's persistence outcome. Assessment state arrives with T14. Ephemeral checkpoints report that restart resume is unavailable.
  **Done when:** status is in, and the resume follow-up validates vault identity, contract versions, and receipts before continuing. Concurrent resume is rejected. Completed work is not published again. Cancellation records intent and the observed outcome, including an external job whose termination is unconfirmed. Document the API contract before adding routes.

- [ ] **T09 — Record local diagnostics and resource measurements.** Depends on T04 and T07.
  **Touch:** `executor.py`, `nodes/builders/`, `app/core/logger.py`, `app/main.py`.
  Record actions, results, errors, versions, latency, token and cache use, transferred and context bytes, and peak RSS. Unknown price stays unavailable. Keep private evidence out of allowlisted telemetry. State how retention affects replay.
  **Done when:** a synthetic failure is diagnosable from the run id, a telemetry failure leaves the result unchanged, and exported logs omit private content and secrets.

- [ ] **Close T13 — Paired baseline.** Depends on the T13 cases and T09.
  Run the current pipeline and a single-agent baseline on the reviewed cases under equal budgets.
  **Done when:** paired per-case results show failures, disagreement, and uncertainty. With T01 and the T13 cases, this is the M0 exit.

## Later

Expand a block after its entry condition. Held-out quality gates stay in the roadmap.

### M2 — Evidence

Entry: T04, T05, and T07.

- [ ] **T10 — Persist evidence before clearing tool messages.** Depends on T04 and T05. Record identity, family/version, time, hash, locator, extraction method, and a content reference. Keep large bodies on disk. Mark summaries as derived. Label excerpts when the original bytes were never stored.
- [ ] **T11 — Bound acquisition and separate failure from absence.** Depends on T10 and T07. Stream under byte, deadline, and item limits. Record not-found, denied, unavailable, rate-limited, timeout, parse failure, and truncation separately. Treat source and memory text as data, and remove privileged-memory prompt wording.
- [ ] **T12 — Reuse source identities.** Depends on T11. Group DOI, arXiv, and mirror versions by family while keeping exact versions and code commits. An academic connector waits for a coverage trial and stays off the default path.

### M3 — Supported answers

Entry: T10 and the T13 cases. Compare policies only against the closed T13 baseline.

- [ ] **T14 — Cite evidence records from synthesis.** Depends on T10 and T13. Make decisive claims and required questions explicit, with supporting and contradicting ids in the structured output. Assess support before note extraction. Bibliography metadata alone cannot pass a false claim. A missing locator fails. Semantic judgments stay signals.
- [ ] **T15 — Add bounded repair and honest uncertainty.** Depends on T14 and T07. Start semantic rejection in shadow mode. A disputed decisive claim gets bounded gathering or stays uncertain. Recheck question coverage after a removal. Finish without waiting for a model to say PASS.
- [ ] **T16 — Choose the next action from a question ledger.** Depends on T15 and T13. Track required questions, leads, evidence, and remaining budget. Choose search, read, compare, or stop. Literature review and paper/code audit are criteria on this path, using existing repository snapshots. The M3 exit gate decides whether this policy replaces the simpler one.

### M4 — Vault updates

Entry: T15. Retrieval also needs T10 and T05.

- [ ] **T17 — Retrieve relevant existing notes.** Depends on T10 and T05. Use `ObsidianVaultOperations` with lexical matches, links, and identities, inside a measured read budget. Treat old generated memories as dated, unverified leads.
- [ ] **T18 — Propose create, update, link, or no-op.** Depends on T15 and T17. Include the expected prior hash, evidence, and justification. Validate rendered frontmatter, links, and claim support. A repeat run may no-op. Keep contradictions.
- [ ] **T19 — Publish through one conflict-aware writer.** Depends on T18 and T04. Use conditional writes, per-vault coordination, and an explicit automatic-versus-review policy. Journal hashes and return receipts. Undo only an unchanged agent edit. Document the backend's actual compare-and-swap limits.
- [ ] **T20 — Refresh stale knowledge and profiles.** Depends on T19 and T10. Invalidate a profile when relevant content changes even if the note count does not. A corrected source becomes an update proposal. Preserve historical research and manual edits.

### M6 — One CPU experiment

Entry: T08, T11, and T15. Publishing the note also needs T19.

- [ ] **T21 — Specify one reproducible CPU experiment.** Record the hypothesis, comparison, immutable code and data, locks, command, evaluator, metrics, split, seeds, and limits. Exclude credentials. A source hash alone is not the reproducibility claim.
- [ ] **T22 — Run it through one authorized local runner.** Depends on T21. Keep this capability separate from Monty. Provide submit, status, logs, cancel, and result, with durable launch intent and process-tree termination. Cover restart, a lost handle, an ambiguous launch, and an ignored TERM. A retry must not duplicate a job. Leave `orx` and `feynman` uncalled.
- [ ] **T23 — Keep experiment evidence complete.** Depends on T22 and T14. Read logs with a byte bound, finalize evidence independent of process exit, and compare evaluator, configuration, and split before ranking results. Reject a zero exit that lacks the declared metric. The cited vault note is T19.
- [ ] **T24 — Add one remote backend for a selected workload.** Depends on T23. Pass the same lifecycle tests, with spending limits and cleanup visible. Local runs need no hosted account.

### Unscheduled

- [ ] **T25 — Build a policy-evaluation harness.** Entry: T09, T13, T14, and a decision to optimize. Replay fixed evidence for synthesis and notes. Use a frozen corpus for retrieval trials. Keep live canaries separate, and leave the hidden set out of training.
- [ ] **T26 — Run one bounded trial.** Depends on T25. Pick BAML, Jev, or DSPy/GEPA from a measured gap. Add independent reviewers or parallel researchers only when that gap calls for them, under the shared budget and with no worker writes to the vault. Adopt it with a rollback path, or remove the trial.
- **T27 — Distillation** stays in the roadmap research section. It blocks nothing here.
- [ ] **T28 — Name retained workflows and data.** Fill this at any time. For each workflow in the roadmap M7 matrix, record required or waived, the acceptance scenario, and the data to preserve.
- [ ] **T29 — Import retained research.** Depends on T28 and the stores those workflows need. Import read-only. Preserve original identities, hashes, provenance, and Git history, including uncommitted work. Back up live SQLite consistently, exclude credentials, and restore to a temporary location before changing originals.
- [ ] **T30 — Prove the old CLIs are unnecessary, then remove them on request.** Depends on T29 and every milestone T28 retained. Compare representative tasks, run where `feynman` and `orx` are absent, and test restore from backup. Uninstall only after that passes and the user asks. Stop or transfer active jobs first. Leave research data and shared runtimes in place.

## Completion rules

- Preserve unrelated work. Check the working tree before editing shared files.
- Update schemas, prompts, callers, tests, and ARCHITECTURE.md together. Remove stale aliases. Preserve legacy user data in place.
- Run the focused tests, then `uv run pytest` and `just typecheck` when the contract warrants it. Record the commands and any environment failure.
- State the observable result, the failure behavior, and the rollback. Checking a box does not install anything, start a remote job, migrate data, deploy, or uninstall.
