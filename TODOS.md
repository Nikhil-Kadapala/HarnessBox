# TODOs

Deferred items from v0.2.0 planning. These are post-adoption features that should be informed by real usage data from the EventHandler system.

## Runtime Tool Installation — User-selectable developer tools

**What:** Let users choose which tools to install at sandbox startup from a curated list of common developer tools and runtimes.

**Why:** E2B base images have git, python3, node, npm, uv pre-installed, but are missing bun, gh, tree, rg, fd. Rather than pre-baking templates (complex, rigid), let users select what they need on a per-session basis.

**Timing data (from instrumentation):**
- E2B base has: git, python3, node, npm, uv (no installation needed)
- Missing: bun, gh, tree, rg, fd
- Current setup time: 3.2s (no tool installation happening)
- Tool installation would add ~15-25s for missing tools if needed

**Design:**
- UI: Multi-select dropdown in session creation flow (web app, CLI flag `--install-tools bun,gh,tree`)
- API: Add `install_tools: list[str]` to `CreateSessionRequest`
- Server: Map tool names to install commands, run via `provider.run_command()` during setup
- Timing: Run tool installs in Phase 2 (after sandbox creation, before git clone)

**Tool catalog:**
```python
INSTALLABLE_TOOLS = {
    # Already in E2B base (no-op, but show in UI as "pre-installed")
    "git": None,
    "python3": None,
    "node": None,
    "npm": None,
    "uv": None,
    
    # Available for installation
    "bun": "curl -fsSL https://bun.sh/install | bash",
    "gh": "curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | sudo dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && echo \"deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main\" | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null && sudo apt update && sudo apt install gh -y",
    "tree": "apt-get update && apt-get install -y tree",
    "ripgrep": "apt-get update && apt-get install -y ripgrep",
    "fd": "apt-get update && apt-get install -y fd-find && ln -s $(which fdfind) /usr/local/bin/fd",
    "jq": "apt-get update && apt-get install -y jq",
    "vim": "apt-get update && apt-get install -y vim",
    "tmux": "apt-get update && apt-get install -y tmux",
    "docker": "curl -fsSL https://get.docker.com | sh",
}
```

**Implementation:**
1. Add `install_tools: list[str] | None = None` to `CreateSessionRequest` in `server.py`
2. Create `sdk/src/harnessbox/_utils/tools.py` with `INSTALLABLE_TOOLS` registry and `install_tool()` function
3. Add Phase 2.5 in `Sandbox.setup()`: loop through `install_tools`, run install commands, log timing
4. Update web app: add multi-select tool picker in session creation form
5. Update CLI: add `--install-tools` flag (comma-separated)

**Tradeoffs:**
- Pro: Flexible, no template complexity, user chooses what they need
- Pro: Easy to extend (just add to registry)
- Con: Adds ~15-25s to setup if many tools selected
- Con: Install failures are runtime errors (vs template build-time errors)

**Future optimization:** If most users select the same 3-5 tools, revisit templates.

**Depends on:** Timing instrumentation (completed), user feedback on which tools are most needed.

## Sandbox Snapshots — Preserve state on kill/archive for later restoration

**What:** When a user kills or archives a session, save a snapshot of the sandbox state (filesystem, installed tools, git state) so they can restore it later instead of starting from scratch.

**Why:** Currently, if a sandbox times out or is killed, the session becomes unusable and throws exceptions. Users lose all progress (installed tools, modified files, git changes). Snapshots allow users to "pause and resume" work across sessions.

**Error scenario (current behavior):**
```
User sends prompt → Sandbox timed out (502 Bad Gateway) →
  "The sandbox was not found" exception →
    SSE stream crashes with unhandled ExceptionGroup →
      User sees 500 error, session is dead
```

**Design:**
- **Snapshot creation**: When user calls `/v1/sessions/{id}/kill` or `/v1/sessions/{id}/archive`, run:
  1. Commit current workspace changes (if `GitWorkspace` with `commit_on_exit`)
  2. Create E2B snapshot via `sandbox.snapshot()` (returns snapshot_id)
  3. Store snapshot metadata in session manager: `SnapshotInfo(snapshot_id, created_at, tools_installed, git_sha)`
- **Snapshot restoration**: When creating a new session with `restore_from: session_id`:
  1. Look up snapshot_id from archived session
  2. Create new E2B sandbox from snapshot: `AsyncSandbox.create(snapshot=snapshot_id)`
  3. Resume agent process with `--resume {conversation_id}`
- **Snapshot expiry**: E2B snapshots expire after 7 days (platform limit). Show warning to user if snapshot is >6 days old.

**Implementation:**
1. Add `snapshot_id: str | None` to `SessionInfo` in `session.py`
2. Add `/v1/sessions/{id}/archive` endpoint in `server.py` (like `/kill` but saves snapshot first)
3. Update `Sandbox.kill()` to accept `save_snapshot: bool = False` parameter
4. Add `Sandbox.create_snapshot() -> str` method that wraps `provider.snapshot()`
5. Add `restore_from: str | None` to `CreateSessionRequest` (session_id to restore from)
6. Update `SessionManager.create()` to check for `restore_from`, load snapshot_id, pass to provider
7. Add snapshot metadata to `GET /v1/sessions` response

**Tradeoffs:**
- Pro: Users can pause work and resume later without losing progress
- Pro: Graceful handling of timeout/kill scenarios
- Con: E2B snapshots expire after 7 days (platform limitation)
- Con: Snapshots count against E2B storage quota

**Depends on:** Graceful error handling for killed sandboxes (see plan below).

## Graceful Error Handling for Killed/Timed-Out Sandboxes

**Problem:** When a sandbox times out or is killed, subsequent operations throw unhandled exceptions that crash the SSE stream and show 500 errors to users.

**Current error flow:**
1. User sends prompt via `/v1/sessions/{id}/prompt`
2. Sandbox is dead (timed out, killed, or destroyed)
3. `send_stdin()` raises `TimeoutException: The sandbox was not found`
4. Retry logic attempts `--resume`, but sandbox is still gone (502 Bad Gateway)
5. `start_persistent()` raises another `TimeoutException`
6. Exception bubbles up through SSE stream → `ExceptionGroup` in ASGI → 500 error

**Solution: Catch sandbox-not-found errors and return structured error events**

### Phase 1: Detect sandbox death in run_prompt_events()

Update `sandbox.py::run_prompt_events()`:

```python
async def run_prompt_events(self, prompt: str) -> AsyncIterator[dict[str, Any]]:
    """Stream agent output events. Yields structured error if sandbox is dead."""
    try:
        # Existing logic: ensure agent ready, send prompt, stream output
        ...
    except (TimeoutException, ConnectException) as e:
        if "sandbox was not found" in str(e).lower() or "502" in str(e):
            # Sandbox is dead, yield structured error event
            yield {
                "type": "error",
                "error": {
                    "code": "SANDBOX_DEAD",
                    "message": "Sandbox has timed out or been destroyed. Create a new session or restore from snapshot.",
                    "details": str(e),
                    "recoverable": False,
                }
            }
            # Transition session state to FAILED
            self._state = SessionState.FAILED
            return
        raise  # Re-raise non-sandbox errors
```

### Phase 2: Handle in SessionManager.prompt()

Update `session.py::SessionManager.prompt()`:

```python
async def prompt(self, session_id: str, prompt: str) -> AsyncIterator[dict[str, Any]]:
    """Stream prompt response. Marks session as FAILED if sandbox is dead."""
    async with self._locks[session_id]:
        info = self._sessions.get(session_id)
        if not info:
            raise KeyError(f"Session {session_id} not found")
        
        async for event in info.sandbox.run_prompt_events(prompt):
            if event.get("type") == "error" and event["error"]["code"] == "SANDBOX_DEAD":
                # Mark session as failed, stop streaming
                info.state = SessionState.FAILED
                yield event
                return
            yield event
```

### Phase 3: Update web UI to show recovery options

When the web app receives an error event with `code: "SANDBOX_DEAD"`:

```typescript
if (event.type === "error" && event.error.code === "SANDBOX_DEAD") {
  // Show user-friendly error with actions
  showError({
    title: "Session Ended",
    message: "Your sandbox has timed out or been terminated.",
    actions: [
      { label: "Create New Session", onClick: () => createNewSession() },
      { label: "View Logs", onClick: () => showLogs() },
      // Future: { label: "Restore from Snapshot", onClick: () => restore() }
    ]
  });
}
```

### Phase 4: Prevent new prompts to dead sessions

Add session state check in `POST /v1/sessions/{id}/prompt`:

```python
@app.post("/v1/sessions/{id}/prompt")
async def prompt_session(id: str, req: PromptRequest):
    info = mgr._sessions.get(id)
    if not info:
        raise HTTPException(404, "Session not found")
    
    if info.state in (SessionState.FAILED, SessionState.MERGED):
        raise HTTPException(
            409,
            detail={
                "error": "Session is not active",
                "state": info.state.value,
                "message": "This session has ended. Create a new session to continue."
            }
        )
    
    return EventSourceResponse(event_generator())
```

### Implementation checklist:

- [ ] Add `TimeoutException`, `ConnectException` to imports in `sandbox.py`
- [ ] Wrap `run_prompt_events()` with try/except for sandbox-not-found errors
- [ ] Yield structured error event with `code: "SANDBOX_DEAD"`
- [ ] Transition session state to FAILED when sandbox dies
- [ ] Add state check in `POST /v1/sessions/{id}/prompt` endpoint
- [ ] Update web UI to handle `SANDBOX_DEAD` error events gracefully
- [ ] Add integration test: create session, kill sandbox externally, send prompt, verify error event

**Timeline:** Implement Phase 1-4 immediately (graceful errors). Snapshot feature follows after.

## PolicyEngine — Identity-aware security rules

**What:** Add a PolicyEngine with identity-aware rule evaluation (RBAC/ABAC), replacing the flat deny-list approach.

**Why:** Currently every sandbox gets the same security rules regardless of who's running it. Enterprise multi-tenant platforms need role-scoped access (e.g., "contractors can read /workspace/src but not /workspace/.env").

**Design notes:** The EventHandler audit data from v0.2.0 should inform which rule primitives are needed. The engine should compose with SecurityPolicy (backward-compat bridge via `PolicyEngine.from_security_policy()`). guard_bash.py stays as defense-in-depth.

**Depends on:** v0.2.0 event system (shipped), real adoption data.

## ContentGuard — I/O content scanning

**What:** Content scanning system with pluggable detectors for secrets/PII in agent input and output.

**Why:** Agent output could contain AWS keys, private keys, connection strings that leak to logs or downstream consumers.

**Design notes:** Should use a `ContentDetector` Protocol for pluggable detectors (regex built-in, Presidio NER optional). Unclear policy question: block? redact? log-only? Defer decision until real usage patterns emerge. User feedback during v0.2.0 review: "leave content filtering to users to decide."

**Depends on:** v0.2.0 event system (shipped), user feedback on whether built-in scanning is wanted.
