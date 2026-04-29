# TODOs

Deferred items from v0.2.0 planning. These are post-adoption features that should be informed by real usage data from the EventHandler system.

## Template Optimization — Pre-installed tooling per harness type

**What:** Create E2B templates per harness type (e.g., claude-code, aider) with pre-installed tooling (bun, gh, uv, tree, ripgrep, etc.) to reduce session startup time.

**Why:** Currently every sandbox installs tools at runtime. Pre-installing them in a template saves 15-25 seconds per session (for tools not in E2B base image).

**Decision gate:** Measure current tool installation time first. If >10 seconds → templates worth it. If <5 seconds → skip for now.

**Design notes:**
- Template per harness type, NOT per repo/session (repo/branch/auth remain runtime config)
- Version templates (`harnessbox-claude-code-v1`) for safe rollout
- Git clone still happens at runtime (it's session-specific)
- Rebuild strategy: manual trigger or monthly cadence (not on every tool release)
- Template structure: `sdk/src/harnessbox/templates/claude-code.Dockerfile`

**Implementation:**
1. Add timing instrumentation to measure current baseline (see instrumentation plan below)
2. Create Dockerfile template with: git, node, bun, gh, uv, tree, ripgrep, fd
3. Add `harnessbox build-template` CLI command
4. Update `_providers/e2b.py` to accept `template` parameter
5. Pass template from `config/harness.py` based on harness type

**Depends on:** Performance measurement data to validate optimization is worth the complexity.

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
