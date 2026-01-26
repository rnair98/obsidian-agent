#!/bin/bash

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get current working directory
CWD=$(pwd)

echo -e "${BLUE}=== Agent Plugins Setup Script ===${NC}"
echo ""

# Step 1: Shallow clone the repository to a temp directory
TMP_DIR=$(mktemp -d)
REPO_URL="https://github.com/cercova-studios/terminal-agent-plugins.git"

echo -e "${YELLOW}[1/7] Cloning terminal-agent-plugins repository...${NC}"
git clone --depth 1 "$REPO_URL" "$TMP_DIR" 2>/dev/null || {
    echo -e "${RED}Error: Failed to clone repository${NC}"
    rm -rf "$TMP_DIR"
    exit 1
}
echo -e "${GREEN}✓ Repository cloned to temporary directory${NC}"

# Step 2: Create .agents directory structure if it doesn't exist
echo -e "${YELLOW}[2/7] Setting up .agents directory structure...${NC}"
AGENTS_DIR="$CWD/.agents"

if [ ! -d "$AGENTS_DIR" ]; then
    mkdir -p "$AGENTS_DIR"
    echo -e "${GREEN}✓ Created .agents directory${NC}"
else
    echo -e "${BLUE}• .agents directory already exists${NC}"
fi

# Create subdirectories and files
mkdir -p "$AGENTS_DIR/hooks"
mkdir -p "$AGENTS_DIR/commands"
mkdir -p "$AGENTS_DIR/skills"

# Copy AGENTS.md from the cloned repo's root directory
if [ -f "$TMP_DIR/AGENTS.md" ]; then
    cp "$TMP_DIR/AGENTS.md" "$CWD/AGENTS.md"
    echo -e "${GREEN}✓ Copied AGENTS.md from repository${NC}"
else
    echo -e "${YELLOW}Warning: AGENTS.md not found in repository root${NC}"
    if [ ! -f "$CWD/AGENTS.md" ]; then
        touch "$CWD/AGENTS.md"
        echo "# Agents Configuration" > "$CWD/AGENTS.md"
        echo "" >> "$CWD/AGENTS.md"
        echo "This file contains shared agent configurations." >> "$CWD/AGENTS.md"
    fi
fi

if [ ! -f "$AGENTS_DIR/.mcp.json" ]; then
    echo "{}" > "$AGENTS_DIR/.mcp.json"
fi

echo -e "${GREEN}✓ Directory structure ready${NC}"

# Step 3: Copy files from the cloned repo
echo -e "${YELLOW}[3/7] Copying plugin files...${NC}"
PLUGIN_DIR="$TMP_DIR/plugins/10x-swe"

if [ -d "$PLUGIN_DIR" ]; then
    # Copy agents => .agents/commands
    if [ -d "$PLUGIN_DIR/agents" ]; then
        cp -r "$PLUGIN_DIR/agents/"* "$AGENTS_DIR/commands/" 2>/dev/null || true
        echo -e "${GREEN}✓ Copied agents to commands${NC}"
    fi

    # Copy skills => .agents/skills
    if [ -d "$PLUGIN_DIR/skills" ]; then
        cp -r "$PLUGIN_DIR/skills/"* "$AGENTS_DIR/skills/" 2>/dev/null || true
        echo -e "${GREEN}✓ Copied skills${NC}"
    fi

    # Copy hooks => .agents/hooks
    if [ -d "$PLUGIN_DIR/hooks" ]; then
        cp -r "$PLUGIN_DIR/hooks/"* "$AGENTS_DIR/hooks/" 2>/dev/null || true
        echo -e "${GREEN}✓ Copied hooks${NC}"
    fi

    # Copy .mcp.json
    if [ -f "$PLUGIN_DIR/.mcp.json" ]; then
        cp "$PLUGIN_DIR/.mcp.json" "$AGENTS_DIR/.mcp.json"
        echo -e "${GREEN}✓ Copied .mcp.json${NC}"
    fi
else
    echo -e "${RED}Warning: Plugin directory not found at $PLUGIN_DIR${NC}"
fi

# Step 4: Cleanup the temp directory
echo -e "${YELLOW}[4/7] Cleaning up temporary files...${NC}"
rm -rf "$TMP_DIR"
echo -e "${GREEN}✓ Temporary files cleaned up${NC}"

# Step 5: Ask user which agents they want to work with
echo ""
echo -e "${YELLOW}[5/7] Select which agents you'd like to work with:${NC}"
echo ""
echo "Available agents:"
echo "  1) Claude (Anthropic)"
echo "  2) Cursor"
echo "  3) Codex (OpenAI)"
echo "  4) Droid (Factory)"
echo "  5) Opencode"
echo "  6) Copilot (GitHub)"
echo "  7) Gemini (Google)"
echo ""
echo -e "${BLUE}Enter the numbers of agents you want (comma-separated, e.g., 1,2,3):${NC}"
read -r SELECTION

# Parse selection into array
IFS=',' read -ra SELECTED <<< "$SELECTION"

# Map numbers to agent names and directories
declare -A AGENT_DIRS
AGENT_DIRS[1]=".claude"
AGENT_DIRS[2]=".cursor"
AGENT_DIRS[3]=".codex"
AGENT_DIRS[4]=".factory"
AGENT_DIRS[5]=".opencode"
AGENT_DIRS[6]=".github"
AGENT_DIRS[7]=".gemini"

declare -A AGENT_NAMES
AGENT_NAMES[1]="Claude"
AGENT_NAMES[2]="Cursor"
AGENT_NAMES[3]="Codex"
AGENT_NAMES[4]="Droid"
AGENT_NAMES[5]="Opencode"
AGENT_NAMES[6]="Copilot"
AGENT_NAMES[7]="Gemini"

# Track if Claude was selected
CLAUDE_SELECTED=false

# Step 6: Create directories for selected agents
echo ""
echo -e "${YELLOW}[6/7] Setting up selected agents...${NC}"

for NUM in "${SELECTED[@]}"; do
    NUM=$(echo "$NUM" | tr -d ' ') # Remove whitespace

    if [ -n "${AGENT_DIRS[$NUM]}" ]; then
        AGENT_DIR="$CWD/${AGENT_DIRS[$NUM]}"
        AGENT_NAME="${AGENT_NAMES[$NUM]}"

        # Create directory if it doesn't exist
        if [ ! -d "$AGENT_DIR" ]; then
            mkdir -p "$AGENT_DIR"
            echo -e "${GREEN}✓ Created ${AGENT_DIRS[$NUM]} directory${NC}"
        else
            echo -e "${BLUE}• ${AGENT_DIRS[$NUM]} already exists${NC}"
        fi

        # Handle Claude specifically
        if [ "$NUM" -eq 1 ]; then
            CLAUDE_SELECTED=true
            # Create/update settings.json for Claude
            SETTINGS_FILE="$AGENT_DIR/settings.json"

            if [ -f "$SETTINGS_FILE" ]; then
                # File exists - merge the enabledPlugins
                if command -v jq &> /dev/null; then
                    # Use jq if available
                    TMP_SETTINGS=$(mktemp)
                    jq '.enabledPlugins = (.enabledPlugins // {}) + {
                        "code-review@claude-plugins-official": true,
                        "context7@claude-plugins-official": true,
                        "frontend-design@claude-plugins-official": true,
                        "pr-review-toolkit@claude-plugins-official": true,
                        "playwright@claude-plugins-official": false,
                        "explanatory-output-style@claude-plugins-official": true,
                        "code-simplifier@claude-plugins-official": true,
                        "10x-swe@terminal-agent-plugins": true
                    }' "$SETTINGS_FILE" > "$TMP_SETTINGS" && mv "$TMP_SETTINGS" "$SETTINGS_FILE"
                else
                    # Without jq, overwrite the file
                    cat > "$SETTINGS_FILE" << 'EOF'
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
EOF
                fi
            else
                # Create new settings.json
                cat > "$SETTINGS_FILE" << 'EOF'
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
EOF
            fi
            echo -e "${GREEN}✓ Updated Claude settings.json with plugins${NC}"
        else
            # Create symlinks for other agents
            case "$NUM" in
                2) # Cursor
                    ln -sfn "$AGENTS_DIR/commands" "$AGENT_DIR/commands" 2>/dev/null || true
                    ln -sfn "$AGENTS_DIR/skills" "$AGENT_DIR/skills" 2>/dev/null || true
                    echo -e "${GREEN}✓ Created symlinks for Cursor${NC}"
                    ;;
                3) # Codex
                    ln -sfn "$AGENTS_DIR/commands" "$AGENT_DIR/prompts" 2>/dev/null || true
                    ln -sfn "$AGENTS_DIR/skills" "$AGENT_DIR/skills" 2>/dev/null || true
                    echo -e "${GREEN}✓ Created symlinks for Codex${NC}"
                    ;;
                4) # Droid/Factory
                    ln -sfn "$AGENTS_DIR/commands" "$AGENT_DIR/commands" 2>/dev/null || true
                    ln -sfn "$AGENTS_DIR/hooks" "$AGENT_DIR/hooks" 2>/dev/null || true
                    ln -sfn "$AGENTS_DIR/skills" "$AGENT_DIR/skills" 2>/dev/null || true
                    echo -e "${GREEN}✓ Created symlinks for Droid${NC}"
                    ;;
                5) # Opencode
                    ln -sfn "$AGENTS_DIR/commands" "$AGENT_DIR/commands" 2>/dev/null || true
                    ln -sfn "$AGENTS_DIR/skills" "$AGENT_DIR/skills" 2>/dev/null || true
                    echo -e "${GREEN}✓ Created symlinks for Opencode${NC}"
                    ;;
                6) # Copilot/GitHub
                    ln -sfn "$AGENTS_DIR/commands" "$AGENT_DIR/agents" 2>/dev/null || true
                    ln -sfn "$AGENTS_DIR/skills" "$AGENT_DIR/skills" 2>/dev/null || true
                    echo -e "${GREEN}✓ Created symlinks for Copilot${NC}"
                    ;;
                7) # Gemini
                    ln -sfn "$AGENTS_DIR/commands" "$AGENT_DIR/commands" 2>/dev/null || true
                    ln -sfn "$AGENTS_DIR/skills" "$AGENT_DIR/skills" 2>/dev/null || true
                    echo -e "${GREEN}✓ Created symlinks for Gemini${NC}"
                    ;;
            esac
        fi
    else
        echo -e "${RED}Invalid selection: $NUM${NC}"
    fi
done

# Step 7: Update .gitignore with agent directories (excluding .agents)
echo ""
echo -e "${YELLOW}[7/7] Updating .gitignore with agent directories...${NC}"

GITIGNORE_FILE="$CWD/.gitignore"

# Create .gitignore if it doesn't exist
if [ ! -f "$GITIGNORE_FILE" ]; then
    touch "$GITIGNORE_FILE"
fi

# Add header comment if not already present
if ! grep -q "# Agent directories" "$GITIGNORE_FILE" 2>/dev/null; then
    echo "" >> "$GITIGNORE_FILE"
    echo "# Agent directories (auto-generated by setup-agents.sh)" >> "$GITIGNORE_FILE"
fi

# Add each hidden directory (except .agents) to .gitignore if not already present
for DIR in ".claude" ".cursor" ".codex" ".factory" ".opencode" ".gemini"; do
    if ! grep -q "^${DIR}$" "$GITIGNORE_FILE" 2>/dev/null && ! grep -q "^${DIR}/$" "$GITIGNORE_FILE" 2>/dev/null; then
        echo "${DIR}/" >> "$GITIGNORE_FILE"
    fi
done

echo -e "${GREEN}✓ Updated .gitignore with agent directories${NC}"

echo ""
echo -e "${GREEN}=== Setup Complete! ===${NC}"
echo ""
echo "Your agent plugins have been configured in:"
echo "  • .agents/ (shared configuration)"
for NUM in "${SELECTED[@]}"; do
    NUM=$(echo "$NUM" | tr -d ' ')
    if [ -n "${AGENT_DIRS[$NUM]}" ]; then
        echo "  • ${AGENT_DIRS[$NUM]}/"
    fi
done
echo ""
echo -e "${BLUE}Happy coding! 🚀${NC}"
