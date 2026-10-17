# Development archive

The [GitHub wiki](https://github.com/rnair98/obsidian-agent/wiki/Home) owns plans, experiments, research audits and development history. These records do not establish current capabilities. Read [ARCHITECTURE.md](../ARCHITECTURE.md) for current contracts.

- [Roadmap and release gates](https://github.com/rnair98/obsidian-agent/wiki/Roadmap)
- [Implementation tasks and completion checks](https://github.com/rnair98/obsidian-agent/wiki/Implementation-tasks)
- [Code intelligence plan](https://github.com/rnair98/obsidian-agent/wiki/Code-intelligence-plan)
- [Historical code intelligence steps](https://github.com/rnair98/obsidian-agent/wiki/Historical-code-intelligence-steps)
- [Feynman audit](https://github.com/rnair98/obsidian-agent/wiki/Feynman-audit)
- [OpenResearch audit](https://github.com/rnair98/obsidian-agent/wiki/OpenResearch-audit)
- [Development history](https://github.com/rnair98/obsidian-agent/wiki/Development-history)

Keep setup, usage, interfaces, operating contracts, executable checks, schemas and licenses with the code. Keep the active cross-project request ledger in `docs/cross-project/`; historical references there retain their original wording. For its historical `ROADMAP.md` references, use [Platform convergence](https://github.com/rnair98/obsidian-agent/wiki/Roadmap#platform-convergence-swe-term); the ledger records this location correction as a notice.

The wiki is public. Remove credentials, private source content, personal paths and conversation links before publishing. Runnable audit checks remain in `docs/research/`; the audit pages document their pinned inputs and commands.

## Local wiki workflow

Use the persistent `.wiki/` checkout inside this project. It is a separate Git
repository with its own commits and remote. Keep it locally excluded through
the parent repository's `.git/info/exclude` (`/.wiki/`); do not stage it or add a submodule.

From the project root, before editing wiki pages:

1. Run `git -C .wiki status --short`. If it shows changes, coordinate with their
   owner before proceeding; do not discard or overwrite them.
2. When the checkout is clean, run `git -C .wiki pull --ff-only`.
   If the pull fails, resolve the cause before editing; do not reset or force-push.
3. Edit pages in `.wiki/`, review the diff and check for private material.
   Commit explicit paths inside that repository and push only when publication is authorized.

If `.wiki/` is absent, clone it once into the project, then add the local exclusion:

```sh
git clone https://github.com/rnair98/obsidian-agent.wiki.git .wiki
```

Reuse this checkout on later tasks instead of cloning into temporary directories.
