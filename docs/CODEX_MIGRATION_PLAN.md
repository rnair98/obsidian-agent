# Codex: Electron → Cross-Platform Migration Plan

## Executive Summary

Current Codex (macOS) is built with **Electron + Vue.js**, using an app.asar archive. The app bundles:
- **Frontend**: Vue.js + Vite (transpiled to `/webview` directory)
- **Backend**: Node.js main process with native SQLite bindings
- **Native modules**: electron-liquid-glass (macOS glass morphism UI)
- **Architecture**: Multi-process (GPU, Plugin, Renderer helper processes)

**Goal**: Migrate to a performant, cross-platform (Linux/macOS/Windows) application while preserving UI aesthetics and functionality.

---

## Current Architecture

### Application Structure
```
Codex.app (Electron)
├── Frameworks/
│   ├── Electron Framework
│   ├── Codex Helper (GPU).app
│   ├── Codex Helper (Plugin).app
│   ├── Codex Helper (Renderer).app
│   └── Codex Helper.app
├── Resources/
│   ├── app.asar
│   │   ├── package.json
│   │   ├── webview/          (Vue.js frontend)
│   │   ├── .vite/build/      (Vite bundled assets)
│   │   ├── skills/           (Agent definitions)
│   │   └── node_modules/     (Dependencies)
│   └── codex-dmg-background.png
└── [Electron binary]
```

### Key Dependencies
- **Electron**: Desktop shell, IPC, native APIs
- **Vue.js**: UI framework
- **Vite**: Build tool
- **better-sqlite3**: Local data persistence
- **electron-liquid-glass**: macOS-specific glass effect UI
- **Sparkle**: macOS auto-update framework
- **Squirrel.Windows**: Windows installer (unused on macOS)

### UI Stack
- Vue.js components
- CSS (likely Tailwind or similar)
- HTML template (`webview/index.html`)

---

## Analysis: Why Migrate?

### Problems with Electron
1. **Bundle Size**: ~150-200MB for a lightweight agent manager
2. **Memory Footprint**: Chromium engine overhead (200-400MB base RAM)
3. **Startup Time**: 3-5 seconds typical for Electron apps
4. **Platform Lock-in**: Requires macOS build infrastructure for macOS builds
5. **Dependencies**: Heavy dependency tree, security surface area
6. **Distribution**: DMG format (macOS-only); need separate installers per platform

### Performance Targets for Migration
- **Bundle Size**: <50MB (AppImage), <30MB (binary)
- **RAM Usage**: <100MB at rest
- **Startup Time**: <1 second
- **CPU Usage**: Minimal idle, efficient during agent execution

---

## Migration Approaches

### Option 1: Tauri + SvelteKit (Recommended)
**Tech Stack**: Rust + Svelte + SvelteKit

**Pros**:
- ✅ ~50-80MB AppImage/MSI (vs 200MB Electron)
- ✅ ~50-80MB RAM footprint (vs 300-400MB Electron)
- ✅ Native OS integration (file dialogs, system APIs)
- ✅ Smaller dependency surface
- ✅ Can reuse Vue/Svelte knowledge easily (similar templating)
- ✅ Strong TypeScript support
- ✅ Built-in Tauri plugins for native features

**Cons**:
- ⚠️ Need to rewrite frontend: Vue → Svelte (moderate effort, ~20-30% codebase)
- ⚠️ Rust backend required (learning curve for Node.js team)
- ⚠️ Smaller ecosystem vs Electron

**Migration Path**:
1. Extract Vue components from app.asar
2. Port components to Svelte (structure is similar)
3. Rewrite backend in Rust using Tauri framework
4. Use Tauri's file/IPC APIs for agent orchestration

**Estimated Effort**: 4-6 weeks (with experienced team)

---

### Option 2: Next.js + Electron (Quick Win)
**Tech Stack**: Node.js + Next.js + Electron (optimized)

**Pros**:
- ✅ Minimal rewrite (Next.js is mostly compatible with Vue structure)
- ✅ Keep Node.js backend
- ✅ Faster initial deployment
- ✅ Leverage existing build infrastructure

**Cons**:
- ❌ Still 150-200MB (only marginal improvement)
- ❌ Still 250-350MB RAM (Chromium overhead remains)
- ❌ Doesn't solve the core Electron problem

**Not Recommended** unless speed-to-market is critical and you're accepting the size/performance tradeoff.

---

### Option 3: React + Capacitor (Mobile-First)
**Tech Stack**: React + Capacitor + TypeScript

**Pros**:
- ✅ Web-based (works on mobile too)
- ✅ Can package as native app (WebView wrapper)
- ✅ React skills transferable from team

**Cons**:
- ❌ Still WebView-based (performance not great)
- ⚠️ Not ideal for desktop-heavy workflows
- ⚠️ Smaller native ecosystem

**Not Recommended** for this use case.

---

## Recommended Path: Tauri + Svelte

### Phase 1: Analysis & Extraction (1 week)
1. ✅ **Extract app.asar** → understand file structure
2. **Audit Vue components** → categorize by complexity
3. **Document data models** → how agents are structured
4. **Identify native APIs** → what Electron APIs are used
5. **Create component inventory**:
   - [ ] Sidebar/navigation
   - [ ] Agent editor
   - [ ] Code editor pane
   - [ ] Execution output pane
   - [ ] Settings/preferences

### Phase 2: Backend Rewrite (2-3 weeks)
1. **Rewrite main process in Rust** using Tauri
   - Agent lifecycle management (spawn, pause, cancel)
   - File I/O (read agent definitions, logs)
   - IPC communication with frontend
2. **Migrate SQLite integration** → sqlx (Rust async SQLite)
3. **Agent execution orchestration**:
   - Subprocess management (same as current)
   - Output streaming (same pattern, Rust channels)
   - Error handling & recovery

### Phase 3: Frontend Migration (2-3 weeks)
1. **Port Vue → Svelte**:
   - Components are similar (both use templates, reactive state)
   - Store management: Pinia → Svelte stores
   - Props/events → Svelte props/events
2. **Replace electron-liquid-glass**:
   - Use native CSS for glass effect (backdrop-filter)
   - Or simpler: dark theme with subtle gradients
3. **Keep design language**:
   - Same typography, colors, dark theme
   - Same layout structure (sidebar + main + output pane)

### Phase 4: Testing & Optimization (1-2 weeks)
1. Cross-platform testing (Linux, macOS, Windows)
2. Performance profiling & optimization
3. AppImage/MSI/DMG packaging
4. Update checks & distribution strategy

### Phase 5: Deployment (1 week)
1. Build automation (GitHub Actions, etc.)
2. Release process
3. User documentation

---

## Implementation Details

### Backend Architecture (Rust/Tauri)

```rust
// Main Tauri command handler
#[tauri::command]
async fn execute_agent(
    agent_id: String,
    params: AgentParams,
) -> Result<String, String> {
    // 1. Load agent definition from disk or DB
    let agent = load_agent(&agent_id)?;
    
    // 2. Spawn subprocess
    let mut child = spawn_agent_process(&agent, &params)?;
    
    // 3. Stream output to frontend via event
    while let Some(line) = read_output_line(&mut child)? {
        app_handle.emit_all("agent_output", OutputEvent {
            agent_id: agent_id.clone(),
            line,
        })?;
    }
    
    Ok("Agent completed".to_string())
}
```

### Frontend Architecture (Svelte)

```svelte
<script>
  import { onMount } from 'svelte';
  import { invoke } from '@tauri-apps/api/tauri';
  import { listen } from '@tauri-apps/api/event';
  
  let agentOutput = '';
  let isRunning = false;
  
  onMount(async () => {
    const unlisten = await listen('agent_output', (event) => {
      agentOutput += event.payload.line + '\n';
    });
    
    return unlisten;
  });
  
  async function runAgent(agentId) {
    isRunning = true;
    await invoke('execute_agent', { agent_id: agentId });
    isRunning = false;
  }
</script>

<div class="agent-manager">
  <!-- UI here -->
</div>
```

### Data Models

```typescript
// Agent definition (YAML-like in DB or JSON)
interface Agent {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  tools: string[];
  parameters: Record<string, unknown>;
}

// Execution log
interface ExecutionLog {
  agent_id: string;
  started_at: DateTime;
  completed_at?: DateTime;
  status: 'running' | 'success' | 'error' | 'cancelled';
  output: string;
  error?: string;
}
```

---

## Estimated Resource Requirements

| Phase | Duration | Team Size | Notes |
|-------|----------|-----------|-------|
| Analysis | 1 week | 2-3 | Extract app.asar, audit code |
| Backend | 2-3 weeks | 1-2 | Rust/Tauri main process |
| Frontend | 2-3 weeks | 1-2 | Vue → Svelte porting |
| Testing | 1-2 weeks | 1-2 | Cross-platform QA |
| **Total** | **6-9 weeks** | **2-3** | Full team: 3-4.5 FTE |

---

## Build & Distribution

### Linux (AppImage)
```bash
# Tauri builds to AppImage automatically
tauri build --target linux
# Output: Codex-0.1.0.AppImage (~40MB)
```

### macOS (DMG)
```bash
tauri build --target macos
# Output: Codex.dmg with .app bundle
```

### Windows (MSI)
```bash
tauri build --target windows
# Output: Codex-0.1.0-x64-setup.msi (~35MB)
```

---

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Rust team unfamiliarity | Start with simple handlers, pair programming |
| Vue → Svelte porting bugs | Component-by-component testing, regression tests |
| Performance regression | Profiling early, benchmark against Electron baseline |
| Agent execution compatibility | Run existing agents unchanged (same subprocess API) |
| Cross-platform issues | Test matrix (Ubuntu 20.04+, macOS 11+, Windows 10+) |

---

## Success Criteria

- [ ] App launches in <1 second
- [ ] Bundle size <50MB (AppImage)
- [ ] RAM footprint <100MB at idle
- [ ] All agent types execute correctly
- [ ] UI matches or improves on original
- [ ] Cross-platform packaging works (Linux/macOS/Windows)
- [ ] Startup time <50% of Electron version

---

## Decision Points

### Decision 1: Frontend Framework
- **Current**: Vue.js (Electron)
- **Proposed**: Svelte (Tauri)
- **Alternative**: Keep Vue (more work, requires headless browser)
- **Recommendation**: Svelte (best alignment with Tauri, smaller bundle)

### Decision 2: Rust vs Node.js Backend
- **Proposed**: Rust (better performance, smaller binary)
- **Alternative**: Node.js with Tauri (less rewrite, but defeats purpose)
- **Recommendation**: Rust (aligns with performance goals)

### Decision 3: AppImage vs Snap vs Flatpak
- **Proposed**: AppImage (most portable, works offline)
- **Alternatives**: Snap (Ubuntu-centric), Flatpak (more overhead)
- **Recommendation**: AppImage (for maximum compatibility across Linux distros)

---

## Timeline

```
Week 1:   Analysis & Planning
Weeks 2-3:  Backend (Rust/Tauri main process)
Weeks 4-5:  Frontend (Vue → Svelte porting)
Weeks 6-7:  Cross-platform testing & optimization
Week 8:    Release prep & documentation
Week 9:    Launch & post-launch support (if needed)
```

---

## Questions for Stakeholders

1. **Are performance targets firm?** (50MB bundle, <1s startup)
2. **macOS native glass effect required?** (Or acceptable to simplify?)
3. **Backwards compatibility** with existing agent definitions?
4. **Distribution strategy**: App Store vs direct download?
5. **Planned feature additions** during rewrite?
6. **Team Rust expertise** level?

---

## Appendix: Component Inventory

*(To be filled after app.asar extraction)*

### Key Components Identified
- Sidebar: Agent list/selector
- Main editor: Agent configuration
- Code pane: Code editor (Monaco/CodeMirror)
- Output pane: Agent execution logs/output
- Settings: Preferences, themes

### Native APIs Used (likely)
- File system access
- Process spawning (agent execution)
- IPC (main ↔ renderer communication)
- Window/UI management

### Database Tables (likely)
- agents (id, name, system_prompt, tools, parameters)
- execution_logs (agent_id, started_at, output, status)
- skills (skill definitions/code)

---

## References

- **Tauri Docs**: https://tauri.app
- **Svelte Docs**: https://svelte.dev
- **Electron → Tauri Migration**: https://tauri.app/v1/guides/examples/
- **AppImage**: https://appimage.org

---

**Document Version**: 1.0  
**Date**: 2026-02-09  
**Status**: Awaiting Stakeholder Review
