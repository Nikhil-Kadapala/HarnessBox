# TODOs

Deferred items from v0.2.0 planning. These are post-adoption features that should be informed by real usage data from the EventHandler system.

## Rename Sandbox -> HarnessBox + setup() -> create()

**What:** Rename the `Sandbox` class to `HarnessBox` and its `setup()` method to `create()`. The target public API:

```python
from harnessbox import HarnessBox

hb = HarnessBox(provider="e2b", harness="claude-code", provider_api_key="...", setup_script="./setup.sh", secrets="./secrets.json")
hb_id = hb.create()
```

**Why:** `HarnessBox` is the product name and maps directly to what users are creating. `create()` is what they mentally do -- provision a sandbox, inject config, run setup. The current `Sandbox.setup()` naming is an internal implementation detail that leaked into the API.

**Scope:**
- Rename class `Sandbox` -> `HarnessBox` across all modules (sandbox.py, server.py, session.py, workspace_manager.py, __init__.py, all tests)
- Rename method `setup()` -> `create()`, return `sandbox_id`
- Add `secrets` parameter (path to secrets.json with standardized format)
- Keep `Sandbox` as a deprecated alias for one release cycle
- Update all docstrings, README, CLAUDE.md references

**Depends on:** Issue #3 pipeline refactor (completed, PR #10). Do this as the immediate follow-up PR.

## Subagent Visibility — Parallel Execution UI

**What:** When the agent spawns subagents (via the `Agent` tool), the frontend should render dedicated subagent cards showing status, description, and results — with side-by-side layout for parallel subagents.

**Why:** Subagent calls can take 30s–5min. Without dedicated UI, users see an opaque tool call spinner with no context about what's happening or why it's taking long. The SDK now emits `ITEM_COMPLETED` for Agent tool calls with enriched metadata (`subagent_type`, `description`, `prompt`), and `tool_result` events carry the subagent's output. The frontend needs to render this as something better than a generic collapsible tool call.

**Design:**
- When `ITEM_STARTED` fires with `tool_kind="agent"`, render a **SubagentCard** (spinner + "Spawning: {description}")
- When `ITEM_DELTA` arrives with `tool_kind="agent"`, accumulate the input JSON to show subagent metadata as it streams in
- When `ITEM_COMPLETED` fires with `tool_kind="agent"` and `metadata.description`, update the card to show the subagent type + description prominently
- When the corresponding `tool_result` arrives (matched via `call_id`), render the result inside the card and mark it complete
- **Parallel detection:** If the grouping layer sees multiple `ITEM_STARTED` events with `tool_kind="agent"` that share the same parent message (same sequence range before a turn-end), render them in a side-by-side grid layout
- The correlation key is `item_id` on the tool_use start → `call_id` on the tool_result

**Streaming subagent output (future):**
- Claude Code doesn't yet stream subagent internals to the parent (`stream_to_parent` is a feature request: github.com/anthropics/claude-code/issues/33199)
- When/if it ships, subagent messages will carry `parent_tool_use_id` — use this to render indented/nested events inside the SubagentCard
- For now, subagent internals are opaque; we show input (prompt) and output (result) only

**Depends on:** `ToolKind.AGENT` classification (shipped), subagent metadata enrichment on `ITEM_COMPLETED` (shipped), event grouping by `item_id` (shipped).

## AskUserQuestion — Interactive Form Rendering

**What:** When the agent emits an `input.requested` event (from Claude's built-in `AskUserQuestion` tool), the frontend should render an interactive form with the structured question data — radio buttons for single-select, checkboxes for multi-select, option descriptions, and a submit button.

**Why:** Currently the SDK emits the `INPUT_REQUESTED` event with the full questions payload in metadata (`questions[].header`, `questions[].question`, `questions[].options[].label/description`, `questions[].multiSelect`). The user's response must flow back via `POST /v1/sessions/{id}/permission` with `request_id` + the answers dict. Without a proper form UI, the agent hangs waiting for input.

**Design:**
- New component: `InputRequestCard` (renders alongside `PermissionCard` in the event feed)
- Each question renders as: header badge + question text + option list (radio or checkbox based on `multiSelect`)
- Submit button calls the existing permission endpoint with `behavior: "allow"` and `updated_input: { questions, answers }` 
- The `answers` dict maps `question_text → selected_option_label` (or comma-separated for multi-select)
- After submission, card transitions to "answered" state showing the selected option(s)
- If the session ends or errors before the user answers, card shows "expired" state

**Agent SDK reference:** The response format expected by Claude Code is:
```json
{
  "type": "control_response",
  "request_id": "<from the event>",
  "response": {
    "subtype": "success",
    "response": {
      "behavior": "allow",
      "updatedInput": {
        "questions": [...original questions...],
        "answers": {"Which database?": "PostgreSQL"}
      }
    }
  }
}
```

**Depends on:** `input.requested` event type (shipped), permission response endpoint (shipped), event-card rendering pipeline (shipped).


## Session Board — Lifecycle Actions Per Column

**What:** Each kanban column should have distinct card actions beyond the current "Review" and "Archive" buttons.

**Why:** Users need to control session lifecycle directly from the board without switching to a terminal view.

**Actions by column:**
- **In Progress** → `Pause`, `View Logs`, `Stop`
- **In Review** → `Open PR`, `View Diff`, `Re-run`, `Discard`
- **Merged** → `Delete Branch`, `View PR`, `Clone as new session`
- **Archived** → `Restore`, `Delete Permanently`

"Clone as new session" on merged cards lets users iterate on shipped features without starting from scratch.

**Depends on:** Kanban board (shipped), backend pause/stop endpoints, PR integration.

## Session Board — Backlog as Creation Queue

**What:** Make Backlog a first-class creation surface where users queue task descriptions that agents pick up when compute is available.

**Why:** Turns the board into an async work queue rather than just a status tracker. Users describe what they want done, sessions spawn when sandbox capacity is free.

**Design:**
- New `BacklogItem` model: `{ description, harness, repo, branch, priority, created_at }`
- `POST /v1/backlog` to create items, `GET /v1/backlog` to list
- Scheduler picks items off the queue and calls `create_session()` when capacity allows
- Items move from Backlog → In Progress automatically on spawn

**Depends on:** Kanban board (shipped), capacity management, session creation flow.

## Session Board — CI Status Integration

**What:** Show CI pass/fail status inline on session cards via GitHub webhook integration.

**Why:** Users need to know if agent code passes CI without leaving the board.

**Design:** GitHub webhook listener that receives `check_suite` and `check_run` events, maps them to sessions via branch name, stores status on `SessionInfo`.

**Depends on:** PR integration, webhook infrastructure.

## Session Board — Auto-Archive on Merge

**What:** Automatically move sessions to Archived when their PR is merged, via GitHub webhook.

**Why:** Eliminates manual cleanup. Once a PR merges, the session's work is done.

**Design:** GitHub `pull_request.closed` webhook with `merged=true` triggers `transition_session(id, "archived")`. Branch deletion optional (configurable).

**Depends on:** PR integration, webhook infrastructure, CI status integration.

## Session Board — Stale Session Warning

**What:** Sessions in "In Progress" for >24h without a commit get a warning badge.

**Why:** Prompts users to check if an agent is stuck or idle.

**Design:** Track `last_commit_at` on `SessionInfo`. Periodic check (or on board load) compares against threshold. Show ⚠️ badge on stale cards.

**Depends on:** Commit tracking (diff stat/commit count work), board refresh.

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

## Multi-Agent Collaboration — Agent-to-agent invocation and shared state

**What:** Enable multiple coding agents (claude-code, codex) to collaborate within a single sandbox session via subprocess invocation.

**Why:** Users want to leverage agent-specific strengths (e.g., "Claude, ask Codex to review what you just wrote"). Conductor already provides manual agent switching via new conversations + summary transfer, which handles user-initiated switches. This feature focuses on agent-to-agent collaboration.

**Design:**

**Pattern 1: Agent as subprocess (recommended, implement first)**
- One agent invokes another as a subprocess: `await provider.run_command("codex review src/sandbox.py")`
- Output streams back as text, incorporated into primary agent's response
- No complex context management, no routing logic
- Already works today (both CLIs exist in sandbox)

**Pattern 2: Agent-specific tools (future enhancement)**
```python
@tool
async def consult_codex(task: str, files: list[str]) -> str:
    """Ask Codex for a second opinion or specialized task."""
    result = await provider.run_command(f"codex {task} {' '.join(files)}")
    return result.stdout

@tool
async def consult_claude(task: str, files: list[str]) -> str:
    """Ask Claude Code for implementation or debugging help."""
    result = await provider.run_command(f"claude {task} {' '.join(files)}")
    return result.stdout
```

**Pattern 3: Multiple PersistentProcess instances (future, if needed)**
- Track multiple agents simultaneously: `self._agents: dict[str, PersistentProcess]`
- Active agent routing: `self._active_agent` determines which receives prompts
- Explicit handoffs: `handoff(from_agent, to_agent, instruction)` transfers context
- Shared state: all agents operate on same filesystem, git repo, conversation history

**Implementation:**
1. Document the subprocess invocation pattern (CLAUDE.md, README)
2. Add example: "Claude calls Codex for code review" walkthrough
3. (Future) Add `@tool` wrappers for common agent invocations
4. (Future) Multi-PersistentProcess if subprocess pattern proves insufficient

**Tradeoffs:**
- Pro: Subprocess pattern is simple, works today, no new code needed
- Pro: Shared filesystem state (git repo, files) already works
- Pro: Clean separation: user switches via Conductor UI, agents invoke via subprocess
- Con: Subprocess invocation is text-only (no structured output from invoked agent)
- Con: No built-in context transfer (invoked agent starts cold)
- Con: Multi-PersistentProcess adds complexity (context window bloat, routing logic)

**Non-goals:**
- In-conversation agent switching (Conductor handles this via new conversation + summary)
- Automatic agent routing based on prompt content (users/agents choose explicitly)
- Complex orchestration (keep it simple: one primary agent, subprocess for consultation)

**Depends on:** User feedback on whether subprocess pattern is sufficient, or if true multi-agent concurrency is needed.

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

## Documentation Site — Hosted API reference via Mintlify/Fern

**What:** Build a documentation site (API reference, quickstart, guides) as part of the marketing/landing page using Mintlify or Fern.

**Why:** Hosted docs are a trust signal for OSS adopters. Auto-generated API references from docstrings make the SDK discoverable beyond the README.

**Design notes:**
- Unified marketing + docs site (one deploy, one brand)
- Mintlify/Fern handle versioning, search, and mobile out of the box
- SDK already has comprehensive docstrings on all public APIs (enforced by CI via ruff D rules)
- Input: Google-style docstrings in `src/harnessbox/` + README examples

**Tradeoffs:**
- Pro: Better design quality and DX than self-hosted MkDocs
- Pro: Auto-generated API reference from existing docstrings
- Con: Vendor dependency (Mintlify/Fern are SaaS, free tiers for OSS exist)
- Con: Requires content structure decisions (domain, navigation, branding)

**Depends on:** Docstring enforcement (shipped, ruff D rules in CI), marketing site design decisions.

## Bandit Security Scan — Tune skip list and scope

**What:** Revisit the bandit configuration to reduce the skip list and scope the scan appropriately rather than blanket-suppressing findings.

**Why:** The current bandit config skips B101, B110, B311, B404, B603, B607, B608 — effectively disabling most of what bandit checks. This was done pragmatically to unblock CI, but it means bandit provides almost no value in its current state. The codebase legitimately uses `subprocess` (git/gh CLI detection), `try/except/pass` (graceful credential probing), and `random.choice` (workspace names, not crypto). These aren't bugs, but the blanket skips also hide real issues.

**Design:**
- Option A: Scope bandit to only `src/harnessbox/security/` where strict scanning matters, remove skip list
- Option B: Use per-file `# nosec` annotations on legitimate uses, keep global skip list minimal
- Option C: Replace bandit with a lighter tool (e.g., `ruff` security rules via `S` prefix) that integrates with existing lint

**Depends on:** Codebase stabilization — do this once the module boundaries stop shifting.

## Secret Management — Encrypted secrets with sealed token injection

**What:** Inject API keys, tokens, and credentials into sandboxes without the real values ever entering the VM. Secrets are encrypted at rest, sealed into opaque tokens at boot, and only revealed by a host-side proxy on outbound HTTPS requests.

**Why:** Currently, HarnessBox injects secrets as plaintext env vars via `SandboxManifest.env_vars`. The credential guards in `security/guards.py` block the agent from reading them (deny `env`, `printenv`, `cat /proc/*/environ`) but a determined attacker or buggy tool could still exfiltrate them. The correct model ensures real values never enter the VM at all.

**Reference:** OpenComputer's secrets implementation (https://docs.opencomputer.dev/sandboxes/secrets) — their architecture uses a MITM proxy that intercepts outbound HTTPS, replacing sealed tokens with real secrets only for allowlisted hosts.

**Architecture (three layers):**

1. **Secret Store (persistence)** — secrets encrypted with AES-256-GCM in a backing store (Postgres, SQLite, or encrypted local vault). Values never returned by the API. CRUD via SDK and CLI.

2. **Sealed Tokens (sandbox injection)** — at boot, real secrets are replaced with opaque `hbx_sealed_<hash>` tokens injected as env vars. `echo $API_KEY` prints a sealed token, not the real value.

3. **MITM Proxy (enforcement)** — host-side HTTPS proxy intercepts outbound requests. When it sees a sealed token in a request header/body, it substitutes the real secret — but only if the destination host is on the egress allowlist.

**Key features:**
- **Per-secret host restrictions** — individual secrets locked to specific domains (e.g., `ANTHROPIC_API_KEY` only works for `api.anthropic.com`)
- **Egress allowlists** — store-level control over which domains can receive any secret
- **Layering with snapshots** — fork a pre-built env and attach different credentials per worker; on collision, fork's store wins; egress lists are unioned
- **Values never returned** — API only returns secret names and metadata

**Implementation approach (Hybrid — phased):**

Phase 1: SDK model + storage
- Define `SecretStore`, `SecretEntry` dataclasses
- Implement CRUD operations (create store, set/list/delete secrets)
- Encrypted storage backend (AES-256-GCM, key via config)
- Generate sealed tokens (`hbx_sealed_<hash>`)

Phase 2: Manifest integration
- Modify `build_manifest()` to accept a `SecretStore` and inject sealed tokens (not real values) into `env_vars`
- Add `egress_allowlist` to `SecurityPolicy`
- Update `Sandbox.setup()` to handle secret stores

Phase 3: Provider proxy support
- For E2B: investigate `HTTPS_PROXY` env var pointing to sidecar, or native secret support
- Add `supports_secret_proxy()` and `configure_secret_proxy()` to `SandboxProvider` protocol
- For providers without proxy support, fall back to enhanced file-based injection with guards

Phase 4: CLI + Web UI
- `oc secrets create <store-name> --egress api.anthropic.com`
- `oc secrets set <store-name> ANTHROPIC_API_KEY <value> --allowed-hosts api.anthropic.com`
- `oc secrets list <store-name>`
- Web UI: secret store management in settings panel, store selector in session creation

**Data model sketch:**
```python
@dataclass(frozen=True)
class SecretEntry:
    name: str  # env var name in sandbox
    sealed_token: str  # opaque token injected into VM
    allowed_hosts: tuple[str, ...] = ()  # per-secret host restrictions

@dataclass
class SecretStore:
    id: str
    name: str  # unique per org/user
    egress_allowlist: tuple[str, ...] = ()  # store-level egress control
    entries: dict[str, SecretEntry] = field(default_factory=dict)

class SandboxProvider(Protocol):
    # ... existing methods ...
    async def supports_secret_proxy(self) -> bool: ...
    async def configure_secret_proxy(self, store: SecretStore, encryption_key: bytes) -> None: ...
```

**Security properties:**
| Property | Detail |
|----------|--------|
| Encryption at rest | AES-256-GCM, key via `HARNESSBOX_SECRET_ENCRYPTION_KEY` |
| Never in VM memory | Env vars contain opaque `hbx_sealed_*` tokens |
| Host-side only | Real values exist only in the proxy process on the worker host |
| Egress control | Allowlists restrict which domains receive secrets |
| Per-secret scoping | Individual secrets locked to specific hosts |
| Values never returned | API only returns secret names and metadata |

**Architectural decision: Co-locate proxy in existing FastAPI server**

The SDK already runs a FastAPI server (`server.py`) for SSE streaming and session management. Rather than spinning up a separate proxy gateway, reuse it with a `/v1/proxy/{session_id}` endpoint. The server already has `SessionManager` context (knows which session owns which secrets), so token substitution is a natural extension.

Traffic flow:
```
Sandbox env: HTTPS_PROXY=https://<server-url>/v1/proxy/{session_id}

Sandbox curl → HTTPS_PROXY → /v1/proxy/{session_id}/{destination} →
  server checks sealed tokens in headers/body →
  substitutes real values →
  validates destination against egress allowlist →
  forwards to actual API →
  returns response to sandbox
```

This is an explicit forward proxy (sandbox is configured to use it via `HTTPS_PROXY`), not MITM — no TLS interception, no custom CA cert injection needed.

Endpoint sketch:
```python
@app.api_route("/v1/proxy/{session_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def proxy_request(session_id: str, path: str, request: Request):
    # 1. Validate session exists and has a secret store
    # 2. Check destination host against egress allowlist
    # 3. Read request body, replace hbx_sealed_* tokens with real values
    # 4. Forward to actual destination
    # 5. Return response (optionally scan response for leaked secrets)
```

During `sandbox.setup()`, inject proxy config:
```python
env_vars["HTTPS_PROXY"] = f"{server_base_url}/v1/proxy/{session_id}"
env_vars["HTTP_PROXY"] = env_vars["HTTPS_PROXY"]
env_vars["NO_PROXY"] = "localhost,127.0.0.1"
```

| | Co-located (reuse server) | Separate proxy |
|---|---|---|
| Ops complexity | Single process, single deploy | Extra process to manage per sandbox |
| Session context | Already has it (SessionManager) | Needs shared state or IPC |
| Network | Sandbox must reach server (may need tunnel for local dev) | Runs on host alongside sandbox (always reachable) |
| Blast radius | Proxy load affects SSE streaming & API | Isolated failure domain |
| Latency | Extra hop if server is remote from sandbox | Minimal if co-located with VM |

Decision: co-locate for Phase 1. The proxy endpoint is lightweight (header/body scan + httpx forward). If proxy load becomes a problem later, split out — but that's an optimization, not a day-one concern.

Network reachability consideration:
- Server deployed as a service (cloud, publicly routable) → works immediately
- Running locally → E2B sandboxes are remote VMs, can't reach `localhost:8000`. Requires a tunnel (Cloudflare Tunnel, ngrok) or a relay. Document this as a local dev requirement.

**Open questions:**
1. Where do secrets live at rest? Local encrypted file (simple, good for single-user) vs Postgres (multi-tenant) vs managed service (Vault, GCP Secret Manager)?
2. Do we need per-secret host restrictions on day one? Or is store-level egress allowlist sufficient initially?
3. Multi-tenancy — do different sessions/users get isolated stores, or shared per-org?
4. E2B-specific: can we configure network egress rules or proxy settings on their microVMs?
5. Local dev: should we bundle a tunnel solution (e.g., `bore` or Cloudflare Tunnel) or just document the requirement?

**Tradeoffs:**
- Pro: Real zero-knowledge security — secrets cannot be exfiltrated even by a compromised agent
- Pro: Clean SDK interface regardless of provider capability (graceful degradation)
- Pro: Egress allowlists provide defense-in-depth beyond credential guards
- Pro: No separate proxy process — reuses existing server infrastructure and session context
- Pro: Explicit forward proxy avoids TLS interception complexity (no custom CA certs)
- Con: Provider-dependent security guarantees if proxy isn't available
- Con: Adds latency to outbound HTTPS requests (proxy hop through server)
- Con: Local dev requires tunnel for sandbox → server reachability

**Depends on:** E2B provider capabilities (network policy, proxy support), user feedback on threat model priorities.

## Frontend Test Infrastructure — vitest + React Testing Library

**What:** Set up vitest with React Testing Library in `apps/web/` and write tests for session creation, event streaming, and component rendering.

**Why:** Zero test coverage in the web app. Every new feature adds untested surface area. The optimistic creation flow has 11 untested code paths (reducer actions, background POST, SSE subscription, abort on destroy, component rendering). MSW (already in node_modules) can mock the SSE/fetch layer.

**Design:**
- Install vitest + @testing-library/react + jsdom
- Add `"test": "vitest"` script to package.json
- Create `apps/web/vitest.config.ts` extending the existing Vite config
- Priority test files:
  - `src/hooks/use-session-manager.test.ts` — reducer actions, optimistic creation, error handling
  - `src/components/session/session-view.test.tsx` — conditional rendering by status
  - `src/lib/sse.test.ts` — stream parsing, reconnection, abort behavior

**Tradeoffs:**
- Pro: Catches regressions automatically, enables confident refactoring
- Pro: MSW already installed — SSE/fetch mocking is straightforward
- Pro: Vitest integrates natively with Vite (zero config for transforms/aliases)
- Con: Setup overhead (~30 min), requires learning MSW SSE mocking patterns
- Con: Adds CI time (likely <10s for unit tests)

**Depends on:** Nothing. Can be done independently at any time.

## Server-Side Async Workspace Creation (202 Pattern)

**What:** Refactor backend to register workspace immediately (return 202 with session_id), then provision sandbox in a background task. Stream real provisioning events via the existing SSE events endpoint.

**Why:** The current `POST /v1/workspaces` blocks for 3-10+ seconds during `sandbox.setup()` (E2B provisioning, git clone, setup script). Client-side optimism is a workaround. The correct architecture lets the server drive the lifecycle with real progress events ("Creating sandbox...", "Cloning repo...", "Running setup...").

**Design:**
- `POST /v1/workspaces` creates a `WorkspaceInstance` immediately with `status: "starting"`, registers it in the manager, returns 202
- Provisioning runs in a background `asyncio.Task`
- `sandbox.setup()` emits lifecycle events during each phase (not just `session.started` at the end)
- `GET /v1/workspaces/{id}/events` works immediately after POST (workspace is registered)
- On setup completion: status transitions to `"active"`, `session.started` emitted
- On setup failure: status transitions to `"failed"`, error event emitted

**Implementation sketch:**
1. Split `workspace_manager.create_workspace` into `register_workspace` (sync, returns immediately) + `provision_workspace` (async background task)
2. Add intermediate lifecycle events to `sandbox.setup()`: `setup.phase` events with metadata like `{phase: "sandbox_create"}`, `{phase: "git_clone"}`, `{phase: "setup_script"}`
3. Update frontend: remove client-side optimistic dispatch, use real server events to drive progress UI
4. Update `SessionCreatingView` to show real phase names from events

**Tradeoffs:**
- Pro: Real progress streaming, honest UX, cleaner API contract
- Pro: Enables real-time setup monitoring for long-running provisions (>10s)
- Pro: Eliminates all client-side race conditions (destroy-during-create, stale closure, resurrection guard)
- Con: Significant refactor of workspace_manager.py, sandbox.py, and server.py
- Con: Must handle "workspace exists but isn't ready" state in all endpoints (prompt, events, etc.)
- Con: Changes API contract from 200 to 202 (may affect other consumers)

**Depends on:** Nothing blocks starting this. Should be informed by real usage patterns (how long do setups actually take? do users need intermediate progress for 3-5s waits, or only for >10s?). The client-side optimistic creation (current plan) ships first as the immediate UX fix.

## Data Structure Optimizations — Scale-Ready Internals

**What:** Replace O(N) linear scans with indexed lookups in three hot paths that will become bottlenecks at multi-tenant scale.

**Why:** Current data structures are correct for single-digit sessions but degrade linearly as workspace/session count grows. These are cheap wins — straightforward index additions, no architectural changes.

### 1. Workspace pool lookup — secondary index for (remote, branch)

**Location:** `workspace_manager.py` — `find_by_repo_branch()` (line ~459), `get_or_create_workspace()` (line ~490)

**Problem:** Both methods do O(N) scans over all workspaces to find a match by `(remote, branch)`. Called on every session creation (pool hit check) and resume.

**Fix:** Add `_repo_branch_index: dict[tuple[str, str], str]` mapping `(remote, branch) → workspace_id`. Update on create/destroy/transition. Lookups become O(1).

```python
# On create:
self._repo_branch_index[(info.remote, info.branch)] = workspace_id

# On lookup:
def find_by_repo_branch(self, remote: str, branch: str) -> WorkspaceInstance | None:
    wid = self._repo_branch_index.get((remote, branch))
    return self._workspaces.get(wid) if wid else None
```

### 2. Event replay — bisect on monotonic sequence

**Location:** `events.py` — `replay(after_sequence)` (line ~127)

**Problem:** SSE reconnect triggers `[e for e in self._ring if e.sequence > after_sequence]` — scans all 1024 slots. Called on every client reconnect (tab switch, network hiccup, mobile wake).

**Fix:** Since the ring buffer is a deque with monotonically increasing sequences, use `bisect` to find the start index in O(log N), then slice from there.

```python
import bisect

def replay(self, after_sequence: int) -> list[UniversalEvent]:
    sequences = [e.sequence for e in self._ring]
    start = bisect.bisect_right(sequences, after_sequence)
    return list(itertools.islice(self._ring, start, len(self._ring)))
```

### 3. Auto-pause idle detection — heap-based expiry

**Location:** `workspace_manager.py` — `_run_auto_pause()` background task (line ~632)

**Problem:** Scans all workspaces every 60 seconds, parses ISO timestamps for each, checks if idle exceeds threshold. At 100 workspaces this is still trivially fast, but it's wasteful design.

**Fix:** Maintain a `heapq` sorted by `last_active + timeout` (next expiry time). The background task sleeps until the nearest expiry, pops expired workspaces in O(log N), and re-heaps on activity.

```python
import heapq

# _expiry_heap: list[tuple[float, str]]  # (expiry_timestamp, workspace_id)

async def _run_auto_pause(self) -> None:
    while True:
        if not self._expiry_heap:
            await asyncio.sleep(60)
            continue
        next_expiry, wid = self._expiry_heap[0]
        sleep_for = max(0, next_expiry - time.time())
        await asyncio.sleep(sleep_for)
        # Pop and pause all expired
        while self._expiry_heap and self._expiry_heap[0][0] <= time.time():
            _, expired_wid = heapq.heappop(self._expiry_heap)
            await self._pause_workspace(expired_wid)
```

### Priority

Implement in this order based on call frequency:
1. **Event replay bisect** — highest call frequency (every SSE reconnect)
2. **Workspace pool index** — called on every session create/resume
3. **Heap-based auto-pause** — lowest priority (background task, 60s cadence)

**Depends on:** Nothing. Can be done independently at any time. Best done when we have >10 concurrent workspaces in testing to validate the improvement.

## Auth Gateway — Per-User Process Isolation for Paid Tier

**What:** A lightweight gateway service that authenticates users (JWT/API key) and routes requests to per-user HarnessBox instances. Each user gets their own process with their own SQLite database. Multi-tenancy is handled by architecture (process isolation) not code (user_id filtering + RLS).

**Why:** The alternative (shared-DB multi-tenancy with Supabase + RLS + user_id plumbing through every SDK method) adds complexity to the SDK core, risks cross-tenant data leaks from missed WHERE clauses, and requires dual migration systems. Per-user isolation keeps the SDK single-tenant (simpler, more secure) and pushes auth to the infrastructure layer where it belongs.

**Architecture:**
```
Internet → Auth Gateway (validates JWT/API key, routes by user)
               │
               ├── user-A → harnessbox serve (port 8001, ~/.harnessbox-A/sessions.db)
               ├── user-B → harnessbox serve (port 8002, ~/.harnessbox-B/sessions.db)
               └── user-C → harnessbox serve (port 8003, ~/.harnessbox-C/sessions.db)
```

**Gateway responsibilities:**
- JWT validation (Supabase Auth or any OIDC provider)
- API key validation (hash-based lookup against a users table)
- Request routing: authenticated user → their HarnessBox instance
- Process lifecycle: spawn on first request, idle-pause after timeout, resume on next request
- Billing hooks: meter API calls and sandbox minutes per user

**Implementation options:**
- Cloudflare Workers / Durable Objects (serverless, auto-scaling)
- Caddy reverse proxy + systemd per-user services (simple, self-hosted)
- Kubernetes with per-user pods (enterprise scale)
- Simple Python supervisor (MVP: asyncio process manager)

**Trigger:** Build this when the first paying user materializes. Until then, `harnessbox serve` with SQLite is the complete product for OSS and single-user paid.

**Depends on:** Phase A (SQLite defaults + CLI) must ship first so `harnessbox serve` works standalone.

## WorkspaceManager.prompt() Refactor — Extract Responsibilities

**What:** The `prompt()` method in `workspace_manager.py` has accumulated too many responsibilities: conversation state management, SANDBOX_DEAD error transitions, event streaming, and status polling. Extract into focused sub-methods before it grows further.

**Why:** Adding any new per-turn logic (cost queries, context tracking, session analytics) to this method makes it harder to test, harder to reason about, and harder to modify one concern without touching others. Currently ~60 lines but growing.

**Design:**
- Extract `_handle_conversation_state(workspace_id, prompt)` — manages conversation lookup/creation and last_active updates
- Extract `_handle_stream_error(workspace_id, error)` — SANDBOX_DEAD detection, state transitions, error event emission
- `prompt()` becomes: validate state → handle conversation → delegate to sandbox.send_message → handle errors

**Depends on:** Nothing. Can be done independently. Best done before adding more per-turn logic.

## Cost Tracking — Per-Turn Breakdown

**What:** Store cost data per turn (not just per-session aggregate). Track which prompts were expensive vs cheap.

**Why:** Enables cost optimization at the prompt level. Users can see "turn 3 cost $2.50 because it used Opus, turn 4 cost $0.05 because it used Haiku" and adjust their prompting strategy or model selection.

**Pros:**
- Granular cost visibility — users see which specific prompts are expensive
- Enables A/B testing of prompts ("did my system prompt change increase costs?")
- Better debugging — cost spikes correlate with specific prompts/tools

**Cons:**
- Requires storing turn history (list of TurnCost entries with timestamp, prompt_preview, cost)
- Larger memory footprint per session (100 turns × ~100 bytes per turn = ~10KB)
- More complex CostMetrics dataclass (need List[TurnCost], not just aggregates)

**Context:** Currently, CostMetrics only stores per-session aggregates (total_cost_usd, per_model breakdown). To add per-turn tracking, extend CostMetrics with a `turns: list[TurnCost]` field where `TurnCost = {turn_number: int, timestamp: str, total_cost: float, per_model: dict}`. Update `_poll_session_status()` to append a new TurnCost entry on each poll.

**Depends on:** Cost tracking implementation (per-session aggregates).

## Cost Tracking — Persistence and Export

**What:** Persist cost metrics to database or file (e.g., SQLite, CSV export) so costs survive beyond Sandbox instance lifespan. Include session metadata (session_id, start/end time, total cost, per-model breakdown).

**Why:** Dashboard kanban needs historical cost data to show "session X cost $5.23" for archived sessions. Currently, costs disappear when the Sandbox instance is garbage-collected.

**Pros:**
- Historical cost tracking — dashboard shows costs for all sessions, not just active ones
- Budget reports — users can query "how much did I spend this week?"
- Cost attribution — link costs to specific repos, branches, or users

**Cons:**
- Requires database schema or file format design
- Adds I/O overhead (write cost data on each turn)
- Storage management (pruning old cost records, avoiding unbounded growth)

**Context:** Currently, CostMetrics lives in `sandbox._cost_metrics` (in-memory only). To persist, write cost data to `_storage` backend (already exists for event replay) or add a new `CostStorage` backend. The `SessionManager` in `session.py` can serialize cost_metrics when a session ends and load it on restore.

**Depends on:** Cost tracking implementation (per-session aggregates), storage backend design.
