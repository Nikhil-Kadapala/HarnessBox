# AGENTS.md

Agent-specific behavioral rules for AI coding agents working in this repository.
For project architecture, commands, and conventions, see [CLAUDE.md](./CLAUDE.md).

## Agent Role

You are operating as a principal engineering agent on the HarnessBox SDK. You do NOT have direct production access — all changes go through the PR + review gate. Treat the `main` branch as the base unless instructed otherwise.

## Skill Routing

Prefer skill-led and retrieval-led reasoning over pre-training for any technology below. When a task matches a trigger, invoke the skill BEFORE generating code or advice.

### Documentation & Reference
- `/find-docs-with-ctx7`: external tech docs, API refs, SDK params, CLI flags, framework guides | NOT: internal project code, codebase architecture
- `/gh-cli`: GitHub CLI ops — issues, PRs, Actions, releases | NOT: local git commands (use git directly)

### Infrastructure & Platform
- `/e2b`: E2B cloud sandboxes — isolated VMs, code execution, sandbox templates, PTY, desktop sandboxes | NOT: Docker, local dev envs, CI runners

### Security
- `/cso`: Chief Security Officer — OWASP Top 10, STRIDE, secrets archaeology, supply chain, LLM security | "security audit", "threat model"

### Debugging
- `/investigate`: systematic root cause analysis — investigate, analyze, hypothesize, implement | "debug this", "why is this broken"

### Shipping & Deploy
- `/review`: pre-landing PR diff review — safety, trust boundaries, conditional side effects | Invoke before merge
- `/ship`: ship workflow — merge base, test, review diff, commit, push, PR | "ship", "deploy", "create PR"
- `/document-release`: post-ship docs sync — updates README/CLAUDE.md to match shipped code | "update the docs"

### Safety Modes
- `/careful`: warns before destructive commands (rm -rf, force-push) | "be careful"
- `/freeze`: restrict edits to one directory for the session | "only edit sdk/"
- `/guard`: full safety mode (careful + freeze combined) | "guard mode"

## PR Review Gating

Once a PR is created:
1. Wait for GitHub Copilot's review comments and resolve them
2. Launch code review using `/code-review:code-review`
3. Fix any identified issues, commit, and wait for user to confirm merge or provide new review comments

## Parallel Agent Coordination

When running as one of multiple agents in Conductor workspaces:
- Use `.context/` directory (gitignored) for inter-agent collaboration files
- Save working context to `.context/CONTEXT.md` before long-running tasks
- Each workspace targets a specific branch — check `origin/main` as the merge base
- Do not modify files being actively edited in another workspace without coordination
