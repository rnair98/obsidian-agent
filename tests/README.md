# Testing

Read this before adding, editing, or deleting a test. The file map of what the suite protects today is [ARCHITECTURE.md §11](../ARCHITECTURE.md). The invariants worth protecting are [§10](../ARCHITECTURE.md). The door is `just check`, described in [§11.2](../ARCHITECTURE.md).

## Two different failures

Coding agents and probabilistic model output break example-based unit tests for different reasons. Keep the remedies separate.

**Agents satisfy the test they can see.** A localized `assert result == "..."` is a reward. The same change can update the helper and the expected value, mock the unit under test, or cover a private branch no caller reaches. The suite stays green while the workflow regresses. Pete Johnson's argument that `assertEqual` cannot grade an LLM is about the second problem below; the failure mode in this repository is the first one. The check has to name the characteristic up front. The current function body cannot be the spec.

**Model text has no single correct string.** Faithfulness, relevance, and task success are different dimensions, and one sample is not a pass/fail product gate. LangChain's [State of Agent Engineering](https://www.langchain.com/state-of-agent-engineering) survey (18 Nov–2 Dec 2025, 1,340 responses) found 29.5% of teams building agents do not evaluate them, 52.4% run offline evals, and 37.3% run online evals. Among teams with agents in production, the share not evaluating drops to 22.8% and online evals rise to 44.8%. Johnson's "29% / 45% in production" shorthand points at those figures. Score model behavior with the eval fixtures described in `TODOS.md` and `ROADMAP.md`: separate development cases from held-out cases, label dimensions before comparing candidates, and keep upstream checkouts out of this pytest suite.

Deterministic substrate still needs executable checks: parsers, vault IO, auth, path sandbox, command grammars, prompt/schema wiring. Those checks have to describe a characteristic that remains true as agents, workflows, and backends are added.

## What to write

Prefer, in this order:

1. **A proof checked across its multiverse.** [ARCHITECTURE.md §11.1](../ARCHITECTURE.md). Fitness functions and functional tests below are proofs whose axes are "every module of this kind" or "this caller-visible outcome."
2. **Architectural fitness functions.** Neal Ford, Rebecca Parsons, and Patrick Kua define one as an objective integrity assessment of an architectural characteristic (*Building Evolutionary Architectures*). It fails when that characteristic erodes, including when a new module forgets to opt in.
   - **Atomic:** one characteristic in one context. Path escape is rejected. Auth runs before filesystem, network, or provider side effects. Every `AgentName` publishes a schema into its system prompt.
   - **Holistic:** several characteristics in a shared context. A workflow run projects state and writes the files a caller observes, with no provider, network, or Phoenix.
   - **Triggered:** `uv run pytest` on every change. Continual production monitors are for model evals, not for this suite.
   - Protect a §10 invariant or a caller-visible outcome. Do not protect the current shape of a private helper.

3. **Functional tests.** Drive a public seam — HTTP route, shell command, persist node, vault operation — and assert the world afterward: status, files, rejection, or the absence of a side effect. `tests/nodes/test_persist.py`, `tests/api/test_workflows.py`, and `tests/engine/test_vaults.py` are the pattern. Routing tests do not establish graph correctness. The uncovered holistic path is still `vault_profiler → researcher → summarizer → zettelkasten → persist` through the compiled graph with a stub model. When that path is tested, the stub model, the vault contents, and the faults are axes of one proof, not nine examples.

4. **Generated inputs.** Use [Hypothesis](https://hypothesis.readthedocs.io/) when an axis is a large space of values rather than a small named set. Do not add the dependency for a single example. Hypothesis strategies are axes. They still need a `Proof`.

## What to refuse

- An assertion that restates the implementation's current return value.
- A patch or mock of the function under test, or an assertion on its internal call sequence. Mock only a true external boundary, at the lookup site the product uses.
- A branch matrix over toy types the product never constructs. Renderer coverage of `tuple`, bare `Dict`, `Literal`, and `Enum` did not extend to a new agent; `tests/engine/agents/test_schema_prompt.py` checks every shipped `AgentSpec` instead.
- A test whose job is to move a coverage number.
- Weakening, skipping, or narrowing an assertion so the suite goes green.
- `assertEqual` on free-form model prose.
- A browser runner. This service has no UI. End-to-end here means the workflow seam above, in pytest.

## Adding a test

1. Write a `Proof` for the §10 invariant or the caller-visible outcome. If you cannot name the seam, the fault model, and the axes, do not add the test.
2. Check it with `check_always` or `check_sometimes`. A new module of the same kind must be an axis value the existing proof already covers, or the proof is too narrow.
3. Put the test next to the seam it protects. Update [ARCHITECTURE.md §11](../ARCHITECTURE.md) in the same change.
4. Run the focused file, then `just check` when the contract is shared. A failure prints `seed=` and the axis assignment. Replay that seed. Do not delete the world to make it pass.

## Removed

`tests/test_settings.py` asserted `FilesystemConfig().backend_type == IN_PROCESS`. That copied the default into the test. It did not check that every backend type has a factory. `tests/backends/test_factory.py` is the replacement: the configured default must be registered, and a new enum member without a factory fails.
