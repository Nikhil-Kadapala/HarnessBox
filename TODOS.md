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
