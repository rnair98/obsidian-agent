create a shell script `.sh` that does the following:
1. shallow clones cercova-studios/terminal-agent-plugins from github to a tmp directory
2. if not already in `cwd`, create the .agents directory and create the following subdirectories/files:
    - hooks (dir)
    - commands (dir)
    - skills (dir)
    - AGENTS.md (file)
    - .mcp.json (file)
3. in the cloned github repo, navigate to `plugins/10x-swe` and copy the following:
    - agents => .agents/commands
    - skills => .agents/skills
    - hooks => .agents/hooks
    - .mcp.json => .mcp.json
4. cleanup the tmp cloned repo
5. Asks the user what agents they'd like to work with from this list: (Claude (Anthropic), Cursor, Codex (OpenAI), Droid (Factory), Opencode, Copilot (GitHub), Gemini (Google))
6. if not already in the current working directory, based on what the user chose, creates the directories:
    ```json
        {
            "Claude": ".claude",
            "Cursor": ".cursor",
            "Codex": ".codex",
            "Droid": ".factory",
            "Opencode": ".opencode",
            "Copilot" : ".github",
            "Gemini" : ".gemini"
        }
    ```
5. if claude was selected, goes into .claude/settings.json in the current working directory and adds the following plugins:
    ```json
        {
            "enabledPlugins": {
                "code-review@claude-plugins-official": true,
                "context7@claude-plugins-official": true,
                "frontend-design@claude-plugins-official": true,
                "pr-review-toolkit@claude-plugins-official": true,
                "playwright@claude-plugins-official": false,
                "explanatory-output-style@claude-plugins-official": true,
                "code-simplifier@claude-plugins-official": true,
                "10x-swe@terminal-agent-plugins": true
            }
        }
    ```
6. for the others, creates nested symlinks for each subdirectory in .agents:
    - .agents/commands <=> .github/agents, .codex/prompts, <insert-agent-dir-name-here>/commands
    - .agents/hooks <=> .factory/hooks
    - .agents/skills <=> .<insert-agent-dir-name-here>/skills

