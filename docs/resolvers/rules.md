# Resolver: Safety & Development Rules

This resolver contains the project's core safety guardrails, development constraints, validation workflows, and checklists. Read this file before making modifications to the codebase or declaring tasks complete.

## Auto Compaction
Follow this when the context window is filled over 50%.
Carefully watch for meaningful conversation boundaries and tool call boundaries to identify checkpoints where it is most beneficial and safe to compact without losing critical information.
Do not wait until compaction gets auto-triggered midway through implementation.
Save context with `/context-save` so you can refer back after compaction with `/context-restore`.

## Intent before Implementation
Make sure to ask enough questions to clearly capture the user's intent before creating plans for new features, upgrades, or revamps. Probe the user to clearly state their intent and make outcomes explicit so implementation results in maximum success.

## Tool Invocation Priority
When executing tasks, follow this tool selection hierarchy:
1. **Read before write**: Always read existing files/code before modifying
2. **Search before create**: Search codebase for existing patterns before adding new ones
3. **Lint/type-check after every change**: Run `ruff check` + `mypy` in `packages/sdk/` before declaring done
4. **Test before PR**: Run relevant `pytest` scope minimally before opening a PR

## Parallel Subagent Guidelines
Spawn parallel subagents when:
- Multiple independent test files need to be written for the same feature
- Code review + documentation update can proceed simultaneously
- Independent module changes have no shared file writes

Do NOT parallelize when:
- Tasks have sequential data dependencies (e.g., define protocol → then implement provider)
- One task's output is another's input
- Shared file writes would create merge conflicts

## When to Stop and Clarify (Mandatory)
ALWAYS pause and ask before proceeding if:
- The task involves changes to the **`SandboxProvider` protocol** or `Workspace` protocol
- The task touches **security policy** or credential guard definitions
- The task requires **new runtime dependencies** (SDK must stay zero-dep at runtime)
- The task changes the **server API contract** (`/v1/sessions/*` endpoints)
- You are unsure which module owns a given responsibility
- A feature spans 3+ modules without a clear seam

## Do Not List
- Never add runtime dependencies to the SDK — provider SDKs are optional extras only
- Never modify `SandboxProvider` protocol without user confirmation
- Never hardcode sandbox credentials or API keys
- Never use broad `git add` commands (`git add .`, `git add -A`) — always stage specific files
- Never include internal tracking references (Notion URLs, project links) in PR descriptions or commit messages

## Development Workflow
When working on fresh issues or tasks:
- Create a GitHub Issue first if appropriate before starting work
- For new features or major refactors, create a new branch. For small fixes, stay on the current working branch
- After implementation and testing (including CI), commit and create a PR
- Run the full CI check (`ruff check . && mypy . && pytest tests/ -v`) before declaring done

## Task Completion Checklist
Before marking any task done, confirm:
- [ ] All new code has passing lint (`ruff check .`) and types (`mypy .`)
- [ ] New logic has at least one corresponding pytest
- [ ] Tests pass (`pytest tests/ -v`)
- [ ] PR description includes: what changed, why, and how to test it
- [ ] No secrets, debug prints, or leftover `TODO`s in committed code
- [ ] GitHub Issue is linked to the PR when applicable
