"""Vault-profiler node — qualitative profile of an Obsidian vault.

Runs as the first node in the research workflow so the rendered profile
is part of the LangGraph trace tree (free observability via the
openinference-langchain instrumentor).

Profile flow:

1. Compute deterministic structural stats (``_vault_stats``) — no LLM.
2. Cold vault (no notes) → render a stub profile, skip the LLM.
3. Warm vault with a cached profile whose ``notes_count`` still matches →
   reuse the cached qualitative summary, skip the LLM.
4. Otherwise → invoke the ``vault_profiler`` agent once, persist the
   structured response to ``<vault>/.memories/.vault_profile.json``.

The rendered string is written to ``ResearchState.vault_profile`` so
downstream nodes (currently only zettelkasten) can prepend it to their
own agent input.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections import Counter
from typing import TYPE_CHECKING, Any

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from app.core.logger import logger
from app.engine.agents.vault_profiler import SPEC as VAULT_PROFILER_SPEC
from app.engine.nodes.builders.agent import build_agent_executor_from_spec
from app.engine.schema import ResearchContext, ResearchState

if TYPE_CHECKING:
    from pathlib import Path

    from langgraph.runtime import Runtime

    from app.engine.vaults import VaultLayout

_VAULT_PROFILE_SAMPLE_COUNT = 8
_VAULT_PROFILE_SAMPLE_BYTES = 4_000
_VAULT_PROFILE_CACHE_FILENAME = ".vault_profile.json"
_FRONTMATTER_FENCE = "---"
_WIKILINK_RE = re.compile(r"\[\[[^\]]+\]\]")
_MDLINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\([^)]+\)")
_FRONTMATTER_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):", re.MULTILINE)


def _vault_stats(vault: VaultLayout) -> dict[str, Any]:
    """Compute deterministic structural statistics for a vault.

    Cheap regex/path-walking work; no LLM. Returns a JSON-serializable
    dict that becomes the cache key and feeds the qualitative profiler.
    """
    backend = vault.backend
    try:
        note_paths = [p for p in backend.list_dir(vault.notes_dir) if p.suffix == ".md"]
    except Exception:  # noqa: BLE001
        note_paths = []
    try:
        top_level = [
            p.name
            for p in backend.list_dir(vault.root)
            if backend.is_dir(p) and not p.name.startswith(".")
        ]
    except Exception:  # noqa: BLE001
        top_level = []

    samples: list[tuple[str, str]] = []
    fm_count = 0
    wikilink_total = 0
    mdlink_total = 0
    fm_keys: Counter[str] = Counter()
    slug_flags = {"kebab": 0, "date_prefix": 0, "has_uppercase": 0}
    date_prefix_re = re.compile(r"^\d{4}-\d{2}-\d{2}")
    sample_targets = sorted(note_paths)[:_VAULT_PROFILE_SAMPLE_COUNT]
    for path in sample_targets:
        try:
            content = backend.read_text(path)
        except Exception:  # noqa: BLE001
            continue
        slug = path.stem
        if "-" in slug and slug.islower():
            slug_flags["kebab"] += 1
        if date_prefix_re.match(slug):
            slug_flags["date_prefix"] += 1
        if any(c.isupper() for c in slug):
            slug_flags["has_uppercase"] += 1
        if content.startswith(_FRONTMATTER_FENCE):
            fm_count += 1
            end = content.find(f"\n{_FRONTMATTER_FENCE}", len(_FRONTMATTER_FENCE))
            if end > 0:
                for key in _FRONTMATTER_KEY_RE.findall(content[:end]):
                    fm_keys[key] += 1
        wikilink_total += len(_WIKILINK_RE.findall(content))
        mdlink_total += len(_MDLINK_RE.findall(content))
        samples.append((path.name, content[:_VAULT_PROFILE_SAMPLE_BYTES]))

    return {
        "notes_count": len(note_paths),
        "top_level_folders": sorted(top_level),
        "sample_size": len(samples),
        "frontmatter_ratio": (round(fm_count / len(samples), 2) if samples else 0.0),
        "frontmatter_keys": dict(fm_keys.most_common()),
        "wikilinks_per_note": (
            round(wikilink_total / len(samples), 2) if samples else 0.0
        ),
        "mdlinks_per_note": (round(mdlink_total / len(samples), 2) if samples else 0.0),
        "slug_signals": slug_flags,
        "_samples": samples,  # consumed by the profiler, dropped before caching
    }


def _profile_cache_path(vault: VaultLayout) -> Path:
    return vault.memories_dir / _VAULT_PROFILE_CACHE_FILENAME


def _load_cached_profile(vault: VaultLayout) -> dict[str, Any] | None:
    path = _profile_cache_path(vault)
    try:
        if not vault.backend.exists(path):
            return None
        return json.loads(vault.backend.read_text(path))
    except Exception:  # noqa: BLE001
        return None


def _save_cached_profile(
    vault: VaultLayout, notes_count: int, profile: dict[str, Any]
) -> None:
    try:
        vault.backend.write_text(
            _profile_cache_path(vault),
            json.dumps({"notes_count": notes_count, "profile": profile}, indent=2),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("vault_profile cache write failed: {}", exc)


def _render_vault_profile(profile: dict[str, Any] | None, stats: dict[str, Any]) -> str:
    """Format the profile + stats into the ``<vault_profile>`` block."""
    stats_lines = [
        f"- notes_count: {stats['notes_count']}",
        f"- top_level_folders: {', '.join(stats['top_level_folders']) or '(none)'}",
        f"- frontmatter_ratio: {stats['frontmatter_ratio']}",
        f"- wikilinks_per_note: {stats['wikilinks_per_note']}",
        f"- mdlinks_per_note: {stats['mdlinks_per_note']}",
    ]
    if stats["frontmatter_keys"]:
        top_keys = list(stats["frontmatter_keys"].items())[:6]
        stats_lines.append(
            "- top_frontmatter_keys: " + ", ".join(f"{k}({v})" for k, v in top_keys)
        )

    if profile is None:
        return (
            "<vault_profile>\n"
            "Vault is empty or unanalyzed — no established conventions. "
            "When persisting artifacts, follow project defaults: kebab-case "
            "slugs, YAML frontmatter with `tags`, wikilinks for cross-refs.\n\n"
            + "\n".join(stats_lines)
            + "\n</vault_profile>"
        )

    def _bullets(items: list[str], label: str) -> str:
        if not items:
            return f"{label}: (none observed)"
        return f"{label}:\n" + "\n".join(f"  - {b}" for b in items)

    naming = _bullets(profile.get("naming_conventions", []), "Naming conventions")
    structural = _bullets(
        profile.get("structural_conventions", []), "Structural conventions"
    )
    style = _bullets(profile.get("style_conventions", []), "Style conventions")
    return (
        "<vault_profile>\n"
        f"{profile.get('summary', '').strip()}\n\n"
        f"{naming}\n\n"
        f"{structural}\n\n"
        f"{style}\n\n"
        "Vault stats (deterministic):\n" + "\n".join(stats_lines) + "\n</vault_profile>"
    )


def _build_profiler_user_message(stats: dict[str, Any]) -> str:
    samples = stats["_samples"]
    stats_for_llm = {k: v for k, v in stats.items() if not k.startswith("_")}
    sample_blocks = "\n\n".join(
        f"=== {name} ===\n{content}" for name, content in samples
    )
    return (
        "Profile this Obsidian vault. Stats:\n\n"
        f"```json\n{json.dumps(stats_for_llm, indent=2)}\n```\n\n"
        f"Sampled notes ({len(samples)}):\n\n{sample_blocks}"
    )


async def vault_profiler_node(
    state: ResearchState,
    runtime: Runtime[ResearchContext],
    config: RunnableConfig,
) -> dict[str, str]:
    """Compute ``vault_profile`` and write it to state.

    First node in the research workflow; downstream nodes consume the
    rendered string out of state via their own injection mechanism.
    """
    del state, config  # state.messages not needed; config is supplied by LangGraph
    label = VAULT_PROFILER_SPEC.name.upper()
    llm_kwargs = VAULT_PROFILER_SPEC.llm_kwargs()
    logger.debug(
        "[{}] provider={} model={}",
        label,
        llm_kwargs.get("provider", "openai"),
        llm_kwargs.get("model"),
    )

    vault = runtime.context.vault
    stats = await asyncio.to_thread(_vault_stats, vault)

    if stats["notes_count"] == 0:
        logger.debug("[{}] cold vault (0 notes) — rendering stub", label)
        return {"vault_profile": _render_vault_profile(None, stats)}

    cached = _load_cached_profile(vault)
    if (
        cached
        and isinstance(cached.get("profile"), dict)
        and cached.get("notes_count") == stats["notes_count"]
    ):
        logger.debug("[{}] cache hit ({} notes)", label, stats["notes_count"])
        return {"vault_profile": _render_vault_profile(cached["profile"], stats)}

    logger.info("[{}] computing for {} notes", label, stats["notes_count"])
    try:
        executor = build_agent_executor_from_spec(VAULT_PROFILER_SPEC)
        result = await executor.ainvoke(
            {"messages": [HumanMessage(content=_build_profiler_user_message(stats))]},
            context=runtime.context,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[{}] invocation failed: {}", label, exc)
        return {"vault_profile": _render_vault_profile(None, stats)}

    profile_obj = (
        result.get("structured_response") if isinstance(result, dict) else None
    )
    if profile_obj is None or not hasattr(profile_obj, "model_dump"):
        logger.warning("[{}] no structured_response in profiler result", label)
        return {"vault_profile": _render_vault_profile(None, stats)}

    profile_dict = profile_obj.model_dump()
    _save_cached_profile(vault, stats["notes_count"], profile_dict)
    logger.debug("[{}] profile computed and cached", label)
    return {"vault_profile": _render_vault_profile(profile_dict, stats)}
