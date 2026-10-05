---
peer: ../swe-term
peer-ledger: docs/cross-project/obsidian-agent.md
prefix: OA
peer-prefix: ST
---
# Cross-project ledger: obsidian-agent <-> swe-term

Append-only. Only this repo's agents edit this file. Protocol: skill `cross-project-requests`.
Entry headings: request or notice `### <prefix>-NNN · <status> · <date>`; response to the peer `### Re <peer-prefix>-NNN · <status> · <date>`.

### OA-001 · open · 2026-10-04
Title: Host-hosted tools and a Python client over the wire protocol
Need: Register tools when opening a session, receive call-backs from the loop, from a Python host (no second process).
Context: Roadmap gate C1; first agent-facing tool is ObsidianVaultOperations.
Evidence: ROADMAP.md 'Platform convergence' item 4; ARCHITECTURE.md §12 'Obsidian-semantic operations'
Workaround: None. Tools stay LangChain @tool functions on LangGraph.
Blocks: C1

### OA-002 · open · 2026-10-04
Title: Typed final output from a caller-supplied JSON Schema
Need: Session returns a result validated against a JSON Schema the host supplies; providers declare support; violations are failures.
Context: Replaces ProviderStrategy for summarizer and Zettelkasten steps.
Evidence: app/engine/nodes/builders/agent.py:213
Workaround: ProviderStrategy via langchain; parse_structured fallback.
Blocks: C2

### OA-003 · open · 2026-10-04
Title: Effect observation levels for host-hosted and provider-hosted tools
Need: Record effects as observed, attested or unobservable; let a strict profile deny unobservable ones.
Context: Provider-hosted web_search and code_interpreter cannot be observed by any harness.
Evidence: app/engine/tools/__init__.py:4 (OPENAI_TOOLS); ../swe-term/ARCHITECTURE.md §12 item 8
Workaround: Prompt-only routing, which is not a permission boundary (ARCHITECTURE.md §2 item 5).
Blocks: C2
