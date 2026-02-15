#!/usr/bin/env bash
#
# setup-agents.sh — Bootstrap AI agent plugin directories
#
# Clones a pinned version of terminal-agent-plugins and wires up
# per-agent directories (.claude, .cursor, etc.) via symlinks.
#
# Usage:
#   ./setup-agents.sh              # interactive mode
#   ./setup-agents.sh 1,2,6        # non-interactive (Claude, Cursor, Copilot)
#   ./setup-agents.sh --list       # show available agents
#   PLUGIN_VERSION=v2.0 ./setup-agents.sh 1  # pin a specific version
#
# Safe to re-run. Uses rsync --update so local customizations are preserved.

set -euo pipefail

# ── Configuration ────────────────────────────────────────────────────────────

PLUGIN_VERSION="${PLUGIN_VERSION:-main}"
REPO_URL="https://github.com/cercova-studios/terminal-agent-plugins.git"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENTS_DIR="$PROJECT_ROOT/.agents"

# ── Agent Registry ───────────────────────────────────────────────────────────
# Format: number|name|dotdir
# Add new agents here — the rest of the script adapts automatically.

AGENT_REGISTRY=(
    "1|Claude|.claude"
    "2|Cursor|.cursor"
    "3|Codex|.codex"
    "4|Droid|.factory"
    "5|Opencode|.opencode"
    "6|Copilot|.github"
    "7|Gemini|.gemini"
)

# ── Colors ───────────────────────────────────────────────────────────────────

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ── Logging ──────────────────────────────────────────────────────────────────

log_info()    { echo -e "${BLUE}  • $1${NC}"; }
log_success() { echo -e "${GREEN}  ✓ $1${NC}"; }
log_warn()    { echo -e "${YELLOW}  ⚠ $1${NC}"; }
log_error()   { echo -e "${RED}  ✗ $1${NC}" >&2; }
log_step()    { echo -e "\n${YELLOW}[$1] $2${NC}"; }

die() { log_error "$1"; exit 1; }

# ── Cleanup Trap ─────────────────────────────────────────────────────────────

TMP_DIR=""
cleanup() {
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT INT TERM

# ── Registry Helpers ─────────────────────────────────────────────────────────

registry_get() {
    local num="$1" field="$2"
    for entry in "${AGENT_REGISTRY[@]}"; do
        IFS='|' read -r id name dir <<< "$entry"
        if [[ "$id" == "$num" ]]; then
            case "$field" in
                name) echo "$name" ;;
                dir)  echo "$dir"  ;;
            esac
            return 0
        fi
    done
    return 1
}

registry_valid() {
    local num="$1"
    for entry in "${AGENT_REGISTRY[@]}"; do
        IFS='|' read -r id _ _ <<< "$entry"
        [[ "$id" == "$num" ]] && return 0
    done
    return 1
}

show_agents() {
    echo "Available agents:"
    for entry in "${AGENT_REGISTRY[@]}"; do
        IFS='|' read -r id name dir <<< "$entry"
        echo "  $id) $name ($dir/)"
    done
}

# ── Agent Setup Functions ────────────────────────────────────────────────────

setup_claude() {
    local target_dir="$1"
    local settings_file="$target_dir/settings.json"

    local plugin_config='{
        "code-review@claude-plugins-official": true,
        "explanatory-output-style@claude-plugins-official": true,
        "10x-swe@terminal-agent-plugins": true
    }'

    if command -v jq &>/dev/null; then
        if [[ -f "$settings_file" ]]; then
            local tmp_json
            tmp_json=$(mktemp)
            jq --argjson p "$plugin_config" \
                '.enabledPlugins = (.enabledPlugins // {}) + $p' \
                "$settings_file" > "$tmp_json" && mv "$tmp_json" "$settings_file"
            log_success "Merged plugins into existing settings.json"
        else
            jq -n --argjson p "$plugin_config" '{enabledPlugins: $p}' > "$settings_file"
            log_success "Created settings.json with plugins"
        fi
    else
        log_warn "jq not found — cannot safely merge settings.json"
        if [[ ! -f "$settings_file" ]]; then
            cat > "$settings_file" <<-EJSON
			{
			    "enabledPlugins": {
			        "code-review@claude-plugins-official": true,
			        "explanatory-output-style@claude-plugins-official": true,
			        "10x-swe@terminal-agent-plugins": true
			    }
			}
			EJSON
            log_success "Created settings.json (no jq — fresh write only)"
        else
            log_warn "settings.json exists but jq unavailable — skipping merge"
        fi
    fi
}

create_agent_symlinks() {
    local num="$1" target_dir="$2"
    local name
    name=$(registry_get "$num" "name")

    # Default: commands + skills
    local cmd_target="commands"

    case "$num" in
        3) cmd_target="prompts" ;;  # Codex uses prompts/
        6) cmd_target="agents"  ;;  # Copilot uses agents/
    esac

    ln -sfn "$AGENTS_DIR/commands" "$target_dir/$cmd_target"
    ln -sfn "$AGENTS_DIR/skills"   "$target_dir/skills"

    # Droid gets hooks too
    [[ "$num" -eq 4 ]] && ln -sfn "$AGENTS_DIR/hooks" "$target_dir/hooks"

    log_success "Linked $name ($cmd_target/, skills/)"
}

# ── Safe File Sync ───────────────────────────────────────────────────────────

sync_plugin_dir() {
    local src="$1" dest="$2" label="$3"

    if [[ ! -d "$src" ]]; then
        return
    fi

    if command -v rsync &>/dev/null; then
        rsync -a --update "$src/" "$dest/"
    else
        cp -rn "$src/"* "$dest/" 2>/dev/null || true
    fi
    log_success "Synced $label"
}

# ── Gitignore ────────────────────────────────────────────────────────────────

update_gitignore() {
    local gitignore="$PROJECT_ROOT/.gitignore"
    touch "$gitignore"

    if ! grep -q "# Agent directories" "$gitignore" 2>/dev/null; then
        echo "" >> "$gitignore"
        echo "# Agent directories (auto-generated by setup-agents.sh)" >> "$gitignore"
    fi

    for entry in "${AGENT_REGISTRY[@]}"; do
        IFS='|' read -r _ _ dir <<< "$entry"

        # Never gitignore .github — it's used for Actions, issue templates, etc.
        [[ "$dir" == ".github" ]] && continue

        if ! grep -qE "^\\${dir}/?$" "$gitignore" 2>/dev/null; then
            echo "${dir}/" >> "$gitignore"
        fi
    done

    log_success "Updated .gitignore"
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo -e "${BLUE}=== Agent Plugins Setup ===${NC}"
    echo -e "  repo: $REPO_URL"
    echo -e "  version: $PLUGIN_VERSION"

    # Handle --list / --help
    if [[ "${1:-}" == "--list" ]]; then
        show_agents
        exit 0
    fi
    if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
        echo "Usage: $0 [OPTIONS] [agent_numbers]"
        echo ""
        echo "Options:"
        echo "  --list    Show available agents"
        echo "  --help    Show this help"
        echo ""
        echo "Environment:"
        echo "  PLUGIN_VERSION  Git ref to checkout (default: main)"
        echo ""
        show_agents
        exit 0
    fi

    # ── Step 1: Collect selection BEFORE doing network I/O ────────────────

    log_step "1/6" "Agent selection"

    local selection=""
    if [[ $# -gt 0 ]]; then
        selection="$1"
        log_info "Using CLI selection: $selection"
    else
        show_agents
        echo ""
        echo -en "  ${BLUE}Select agents (comma-separated, e.g. 1,2,6):${NC} "
        read -r selection
    fi

    # Validate all selections before proceeding
    IFS=',' read -ra SELECTED <<< "${selection// /}"

    if [[ ${#SELECTED[@]} -eq 0 ]]; then
        die "No agents selected"
    fi

    for num in "${SELECTED[@]}"; do
        if ! registry_valid "$num"; then
            die "Invalid agent number: $num"
        fi
    done

    local selected_names=()
    for num in "${SELECTED[@]}"; do
        selected_names+=("$(registry_get "$num" "name")")
    done
    log_success "Selected: ${selected_names[*]}"

    # ── Step 2: Clone repository ──────────────────────────────────────────

    log_step "2/6" "Cloning plugins (ref: $PLUGIN_VERSION)"
    TMP_DIR=$(mktemp -d)
    git clone --depth 1 --branch "$PLUGIN_VERSION" "$REPO_URL" "$TMP_DIR" &>/dev/null \
        || die "Failed to clone repository at ref '$PLUGIN_VERSION'"
    log_success "Repository cloned"

    # ── Step 3: Core directory structure ──────────────────────────────────

    log_step "3/6" "Setting up .agents/ structure"
    mkdir -p "$AGENTS_DIR"/{rules,hooks,commands,skills}

    # AGENTS.md
    if [[ -f "$TMP_DIR/AGENTS.md" ]]; then
        cp "$TMP_DIR/AGENTS.md" "$PROJECT_ROOT/AGENTS.md"
        log_success "Copied AGENTS.md"
    elif [[ ! -f "$PROJECT_ROOT/AGENTS.md" ]]; then
        printf "# Agents Configuration\n\nShared agent configurations.\n" > "$PROJECT_ROOT/AGENTS.md"
        log_success "Created default AGENTS.md"
    fi

    [[ ! -f "$AGENTS_DIR/.mcp.json" ]] && echo "{}" > "$AGENTS_DIR/.mcp.json"

    # ── Step 4: Sync plugin files ─────────────────────────────────────────

    log_step "4/6" "Syncing plugin files"
    local plugin_src="$TMP_DIR/plugins/10x-swe"

    if [[ -d "$plugin_src" ]]; then
        sync_plugin_dir "$plugin_src/rules"  "$AGENTS_DIR/rules"    "rules"
        sync_plugin_dir "$plugin_src/agents" "$AGENTS_DIR/commands" "commands"
        sync_plugin_dir "$plugin_src/skills" "$AGENTS_DIR/skills"   "skills"
        sync_plugin_dir "$plugin_src/hooks"  "$AGENTS_DIR/hooks"    "hooks"

        if [[ -f "$plugin_src/.mcp.json" ]]; then
            cp "$plugin_src/.mcp.json" "$AGENTS_DIR/.mcp.json"
            log_success "Synced .mcp.json"
        fi
    else
        log_warn "Plugin directory not found at plugins/10x-swe"
    fi

    # Legacy .agent symlink
    mkdir -p "$PROJECT_ROOT/.agent"
    ln -sfn "$AGENTS_DIR/rules" "$PROJECT_ROOT/.agent/rules"

    # ── Step 5: Configure each selected agent ─────────────────────────────

    log_step "5/6" "Configuring agents"

    for num in "${SELECTED[@]}"; do
        local dir_name agent_dir
        dir_name=$(registry_get "$num" "dir")
        agent_dir="$PROJECT_ROOT/$dir_name"
        mkdir -p "$agent_dir"

        if [[ "$num" -eq 1 ]]; then
            setup_claude "$agent_dir"
        else
            create_agent_symlinks "$num" "$agent_dir"
        fi
    done

    # ── Step 6: Update .gitignore ─────────────────────────────────────────

    log_step "6/6" "Updating .gitignore"
    update_gitignore

    # ── Summary ───────────────────────────────────────────────────────────

    echo ""
    echo -e "${GREEN}=== Setup Complete ===${NC}"
    echo "  Shared config: .agents/"
    for num in "${SELECTED[@]}"; do
        echo "  $(registry_get "$num" "name"): $(registry_get "$num" "dir")/"
    done
    echo ""
}

main "$@"
