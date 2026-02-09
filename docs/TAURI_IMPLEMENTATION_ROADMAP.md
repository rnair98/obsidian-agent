# Tauri Migration: Detailed Implementation Roadmap

## Overview
This document provides a step-by-step implementation guide for migrating Codex from Electron to Tauri + Svelte, optimized for Linux-first development with cross-platform support.

---

## Phase 1: Environment Setup (Week 1, Days 1-2)

### 1.1 Prerequisites
```bash
# System requirements
- Rust 1.70+ (install via rustup)
- Node.js 18+ (for frontend build)
- Tauri CLI
- Platform SDKs (Linux: libgtk-3-dev, libwebkit2gtk-4.1-dev)

# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Install Tauri CLI
cargo install tauri-cli
```

### 1.2 Project Structure
```
codex-tauri/
├── src-tauri/              # Rust backend
│   ├── src/
│   │   ├── main.rs        # Entry point
│   │   ├── agent.rs       # Agent management
│   │   ├── executor.rs    # Agent execution
│   │   ├── db.rs          # Database layer
│   │   └── ipc.rs         # IPC commands
│   ├── Cargo.toml
│   └── tauri.conf.json
├── src/                    # Svelte frontend
│   ├── routes/
│   │   ├── +page.svelte   # Main page
│   │   └── +layout.svelte # Layout
│   ├── components/
│   │   ├── AgentList.svelte
│   │   ├── AgentEditor.svelte
│   │   ├── CodeEditor.svelte
│   │   └── OutputPane.svelte
│   ├── lib/
│   │   ├── stores.ts      # Svelte stores
│   │   └── api.ts         # Tauri command wrappers
│   ├── app.html
│   └── app.css
├── package.json
├── svelte.config.js
├── vite.config.js
└── Cargo.toml (workspace root)
```

### 1.3 Create Tauri Project
```bash
# Create new Tauri project with SvelteKit
npm create tauri-app -- --project-name codex-tauri --package-manager npm --ui svelte

cd codex-tauri
npm install
```

---

## Phase 2: Backend Implementation (Weeks 2-3)

### 2.1 Core Rust Modules

#### `src-tauri/src/main.rs`
```rust
#![cfg_attr(
    all(not(debug_assertions), target_os = "windows"),
    windows_subsystem = "windows"
)]

mod agent;
mod db;
mod executor;
mod ipc;

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .setup(|app| {
            // Initialize database
            db::init(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            ipc::list_agents,
            ipc::load_agent,
            ipc::save_agent,
            ipc::delete_agent,
            ipc::execute_agent,
            ipc::get_execution_logs,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
```

#### `src-tauri/src/agent.rs`
```rust
use serde::{Deserialize, Serialize};
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent {
    pub id: String,
    pub name: String,
    pub description: String,
    pub system_prompt: String,
    pub tools: Vec<String>,
    pub parameters: HashMap<String, serde_json::Value>,
    pub created_at: String,
    pub updated_at: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AgentExecution {
    pub id: String,
    pub agent_id: String,
    pub status: ExecutionStatus,
    pub output: String,
    pub error: Option<String>,
    pub started_at: String,
    pub completed_at: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ExecutionStatus {
    #[serde(rename = "pending")]
    Pending,
    #[serde(rename = "running")]
    Running,
    #[serde(rename = "success")]
    Success,
    #[serde(rename = "error")]
    Error,
    #[serde(rename = "cancelled")]
    Cancelled,
}
```

#### `src-tauri/src/db.rs`
```rust
use sqlx::sqlite::{SqlitePool, SqlitePoolOptions};
use tauri::AppHandle;
use std::sync::Mutex;

pub struct DbState {
    pub pool: SqlitePool,
}

pub async fn init(app: &AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    let db_path = app.path_resolver()
        .app_data_dir()
        .ok_or("Failed to resolve app data dir")?
        .join("codex.db");

    std::fs::create_dir_all(db_path.parent().unwrap())?;

    let database_url = format!("sqlite:{}", db_path.display());
    
    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect(&database_url)
        .await?;

    // Run migrations
    sqlx::migrate!()
        .run(&pool)
        .await?;

    app.manage(Mutex::new(DbState { pool }));
    Ok(())
}

pub async fn get_agent(pool: &sqlx::SqlitePool, agent_id: &str) 
    -> Result<Agent, sqlx::Error> 
{
    sqlx::query_as::<_, Agent>(
        "SELECT id, name, description, system_prompt, tools, parameters, 
                created_at, updated_at FROM agents WHERE id = ?"
    )
    .bind(agent_id)
    .fetch_one(pool)
    .await
}
```

#### `src-tauri/src/executor.rs`
```rust
use std::process::{Command, Stdio};
use std::io::{BufRead, BufReader};
use tokio::sync::mpsc;

pub async fn execute_agent(
    agent_id: String,
    command: String,
    args: Vec<String>,
    tx: mpsc::UnboundedSender<String>,
) -> Result<String, String> {
    let mut child = Command::new(&command)
        .args(&args)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| e.to_string())?;

    let stdout = child.stdout.take().ok_or("Failed to capture stdout")?;
    let reader = BufReader::new(stdout);

    for line in reader.lines() {
        if let Ok(line) = line {
            let _ = tx.send(line);
        }
    }

    let status = child.wait().map_err(|e| e.to_string())?;
    
    if status.success() {
        Ok("Execution completed successfully".to_string())
    } else {
        Err(format!("Execution failed with code: {}", status.code().unwrap_or(-1)))
    }
}
```

#### `src-tauri/src/ipc.rs`
```rust
use tauri::State;
use crate::agent::{Agent, AgentExecution};
use crate::db::DbState;

#[tauri::command]
pub async fn list_agents(db: State<'_, DbState>) -> Result<Vec<Agent>, String> {
    sqlx::query_as::<_, Agent>(
        "SELECT * FROM agents ORDER BY created_at DESC"
    )
    .fetch_all(&db.pool)
    .await
    .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn load_agent(
    agent_id: String,
    db: State<'_, DbState>,
) -> Result<Agent, String> {
    crate::db::get_agent(&db.pool, &agent_id)
        .await
        .map_err(|e| e.to_string())
}

#[tauri::command]
pub async fn save_agent(
    agent: Agent,
    db: State<'_, DbState>,
) -> Result<String, String> {
    sqlx::query(
        "INSERT OR REPLACE INTO agents 
         (id, name, description, system_prompt, tools, parameters, created_at, updated_at)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
    )
    .bind(&agent.id)
    .bind(&agent.name)
    .bind(&agent.description)
    .bind(&agent.system_prompt)
    .bind(serde_json::to_string(&agent.tools).unwrap())
    .bind(serde_json::to_string(&agent.parameters).unwrap())
    .bind(&agent.created_at)
    .bind(&agent.updated_at)
    .execute(&db.pool)
    .await
    .map_err(|e| e.to_string())?;

    Ok(agent.id)
}

#[tauri::command]
pub async fn execute_agent(
    agent_id: String,
    command: String,
    args: Vec<String>,
    app: tauri::AppHandle,
) -> Result<String, String> {
    let (tx, mut rx) = tokio::sync::mpsc::unbounded_channel();

    let app_handle = app.clone();
    tokio::spawn(async move {
        while let Some(line) = rx.recv().await {
            let _ = app_handle.emit_all("agent_output", line);
        }
    });

    crate::executor::execute_agent(agent_id, command, args, tx).await
}
```

### 2.2 Dependencies in Cargo.toml
```toml
[package]
name = "codex-tauri"
version = "0.1.0"
edition = "2021"

[dependencies]
tauri = { version = "1.5", features = ["shell-open", "api-all"] }
serde_json = { version = "1.0" }
serde = { version = "1.0", features = ["derive"] }
tokio = { version = "1", features = ["full"] }
sqlx = { version = "0.7", features = ["runtime-tokio-native-tls", "sqlite"] }
uuid = { version = "1.0", features = ["v4", "serde"] }
chrono = { version = "0.4", features = ["serde"] }

[dev-dependencies]
tauri-build = "1.5"
```

---

## Phase 3: Frontend Implementation (Weeks 4-5)

### 3.1 SvelteKit Setup

#### `svelte.config.js`
```javascript
import adapter from '@sveltejs/adapter-static';

export default {
    kit: {
        adapter: adapter({
            pages: 'build',
            assets: 'build',
            fallback: 'index.html',
            precompress: false,
            strict: true,
        }),
    },
};
```

#### `vite.config.js`
```javascript
import { defineConfig } from 'vite';
import { svelte } from 'vite-plugin-svelte';

export default defineConfig({
    plugins: [svelte()],
    build: {
        minify: 'terser',
        outDir: '../src-tauri/tauri-builds',
    },
});
```

### 3.2 Core Components

#### `src/routes/+page.svelte`
```svelte
<script>
  import { onMount } from 'svelte';
  import AgentList from '../components/AgentList.svelte';
  import AgentEditor from '../components/AgentEditor.svelte';
  import CodeEditor from '../components/CodeEditor.svelte';
  import OutputPane from '../components/OutputPane.svelte';
  
  let selectedAgentId = null;
  let agents = [];
  let output = '';
  let isRunning = false;
  
  onMount(async () => {
    const { invoke } = await import('@tauri-apps/api/tauri');
    agents = await invoke('list_agents');
  });
</script>

<div class="app-container">
  <div class="sidebar">
    <AgentList bind:agents bind:selectedAgentId />
  </div>
  
  <div class="main-pane">
    <div class="editor-pane">
      {#if selectedAgentId}
        <AgentEditor {selectedAgentId} />
        <CodeEditor {selectedAgentId} />
      {/if}
    </div>
    
    <OutputPane bind:output bind:isRunning />
  </div>
</div>

<style>
  .app-container {
    display: flex;
    height: 100vh;
    background: #1e1e1e;
    color: #e0e0e0;
  }
  
  .sidebar {
    width: 300px;
    border-right: 1px solid #333;
    overflow-y: auto;
  }
  
  .main-pane {
    flex: 1;
    display: flex;
    flex-direction: column;
  }
  
  .editor-pane {
    flex: 1;
    display: flex;
    gap: 10px;
    padding: 10px;
  }
</style>
```

#### `src/components/AgentList.svelte`
```svelte
<script>
  import { invoke } from '@tauri-apps/api/tauri';
  
  export let agents = [];
  export let selectedAgentId = null;
  
  async function createAgent() {
    const name = prompt('Agent name:');
    if (!name) return;
    
    const newAgent = {
      id: Date.now().toString(),
      name,
      description: '',
      system_prompt: '',
      tools: [],
      parameters: {},
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    };
    
    await invoke('save_agent', { agent: newAgent });
    agents = await invoke('list_agents');
  }
</script>

<div class="agent-list">
  <h2>Agents</h2>
  <button on:click={createAgent} class="create-btn">+ New Agent</button>
  
  <div class="list">
    {#each agents as agent (agent.id)}
      <div
        class="agent-item"
        class:active={selectedAgentId === agent.id}
        on:click={() => (selectedAgentId = agent.id)}
      >
        <div class="name">{agent.name}</div>
        <div class="desc">{agent.description || '(no description)'}</div>
      </div>
    {/each}
  </div>
</div>

<style>
  .agent-list {
    padding: 15px;
  }
  
  .create-btn {
    width: 100%;
    padding: 10px;
    margin-bottom: 15px;
    background: #0066cc;
    color: white;
    border: none;
    border-radius: 4px;
    cursor: pointer;
  }
  
  .agent-item {
    padding: 10px;
    margin-bottom: 8px;
    background: #2a2a2a;
    border-left: 3px solid transparent;
    cursor: pointer;
    border-radius: 4px;
  }
  
  .agent-item.active {
    border-left-color: #0066cc;
    background: #333;
  }
  
  .name {
    font-weight: 500;
    margin-bottom: 4px;
  }
  
  .desc {
    font-size: 12px;
    color: #999;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
</style>
```

#### `src/components/OutputPane.svelte`
```svelte
<script>
  import { listen } from '@tauri-apps/api/event';
  import { onMount } from 'svelte';
  
  export let output = '';
  export let isRunning = false;
  
  onMount(async () => {
    const unlisten = await listen('agent_output', (event) => {
      output += event.payload + '\n';
      // Auto-scroll
      setTimeout(() => {
        const container = document.querySelector('.output-content');
        if (container) container.scrollTop = container.scrollHeight;
      }, 0);
    });
    
    return unlisten;
  });
  
  function clearOutput() {
    output = '';
  }
</script>

<div class="output-pane">
  <div class="header">
    <h3>Output</h3>
    {#if isRunning}
      <span class="status">⏱️ Running...</span>
    {/if}
    <button on:click={clearOutput} class="clear-btn">Clear</button>
  </div>
  
  <div class="output-content">
    <pre>{output}</pre>
  </div>
</div>

<style>
  .output-pane {
    height: 300px;
    border-top: 1px solid #333;
    display: flex;
    flex-direction: column;
  }
  
  .header {
    padding: 10px;
    border-bottom: 1px solid #333;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }
  
  .output-content {
    flex: 1;
    overflow-y: auto;
    padding: 10px;
    font-family: 'Courier New', monospace;
    font-size: 12px;
  }
  
  pre {
    margin: 0;
    white-space: pre-wrap;
    word-wrap: break-word;
  }
  
  .status {
    color: #ffa500;
    margin-right: 10px;
  }
  
  .clear-btn {
    padding: 4px 8px;
    background: #444;
    color: #e0e0e0;
    border: none;
    border-radius: 3px;
    cursor: pointer;
    font-size: 12px;
  }
</style>
```

### 3.3 Svelte Stores

#### `src/lib/stores.ts`
```typescript
import { writable } from 'svelte/store';

export const agents = writable([]);
export const selectedAgent = writable<string | null>(null);
export const agentOutput = writable('');
export const isExecuting = writable(false);
```

---

## Phase 4: Database Schema

### `migrations/001_initial.sql`
```sql
CREATE TABLE IF NOT EXISTS agents (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    system_prompt TEXT NOT NULL,
    tools TEXT, -- JSON array
    parameters TEXT, -- JSON object
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(name)
);

CREATE TABLE IF NOT EXISTS execution_logs (
    id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL, -- pending, running, success, error, cancelled
    output TEXT,
    error TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
);

CREATE INDEX idx_logs_agent ON execution_logs(agent_id);
CREATE INDEX idx_logs_status ON execution_logs(status);
```

---

## Phase 5: Build & Packaging

### 5.1 Building for Linux

```bash
# Install dependencies (Debian/Ubuntu)
sudo apt-get install -y libgtk-3-dev libwebkit2gtk-4.1-dev

# Build AppImage
npm run tauri build -- --target linux

# Output: src-tauri/target/release/bundle/appimage/Codex-0.1.0.AppImage
```

### 5.2 Building for macOS

```bash
npm run tauri build -- --target macos

# Output: src-tauri/target/release/bundle/macos/Codex.app
# Package as DMG
hdiutil create -volname "Codex" -srcfolder src-tauri/target/release/bundle/macos/Codex.app -ov -format UDZO Codex.dmg
```

### 5.3 Building for Windows

```bash
npm run tauri build -- --target windows

# Output: src-tauri/target/release/bundle/msi/Codex-0.1.0-x64-setup.msi
```

---

## Testing Strategy

### Unit Tests (Rust)
```rust
#[cfg(test)]
mod tests {
    use super::*;
    
    #[test]
    fn test_agent_creation() {
        let agent = Agent {
            id: "test-1".to_string(),
            name: "Test Agent".to_string(),
            // ...
        };
        assert_eq!(agent.id, "test-1");
    }
}
```

### Integration Tests (Frontend)
- Component rendering
- State management
- API communication (mocked)

### E2E Tests
- Full agent lifecycle
- Cross-platform builds
- Performance benchmarks

---

## Performance Benchmarks

| Metric | Electron | Tauri | Target |
|--------|----------|-------|--------|
| Bundle Size | 150-200MB | <50MB | ✅ |
| RAM (idle) | 300-400MB | 80-100MB | ✅ |
| Startup Time | 3-5s | <1s | ✅ |
| First Paint | 2-3s | 0.2-0.5s | ✅ |

---

## Deployment Checklist

- [ ] All unit tests passing
- [ ] Cross-platform builds working
- [ ] Performance benchmarks met
- [ ] Documentation updated
- [ ] User migration guide written
- [ ] Auto-update mechanism implemented
- [ ] Analytics/telemetry setup
- [ ] Error reporting (Sentry integration)
- [ ] Staged rollout plan

---

## Appendix: Quick Reference

### Common Tauri Commands
```bash
npm run tauri dev              # Run dev server
npm run tauri build            # Build for current platform
npm run tauri build -- --help  # See build options
npm run tauri info             # System info
```

### Common Svelte Patterns
```svelte
<!-- Props -->
<script>
  export let name = 'World';
</script>

<!-- Stores -->
import { agentsList } from '$lib/stores';
{#each $agentsList as agent}
  {agent.name}
{/each}

<!-- Async -->
{#await promise}
  Loading...
{:then result}
  {result}
{:catch error}
  Error: {error}
{/await}
```

---

**Version**: 1.0  
**Last Updated**: 2026-02-09
