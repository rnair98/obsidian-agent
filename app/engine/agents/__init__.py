"""Co-located agent definitions.

Each module in this package owns a single ``AgentSpec`` bundling the
output schema, default system prompt, tool list, and any per-agent
LLM overrides for a single agent. This is the source of truth — the
node modules in ``app/engine/nodes/`` consume specs but do not redefine
schema or prompt fragments.
"""
