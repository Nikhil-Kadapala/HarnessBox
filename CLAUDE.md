# For AI Coding Agents

This file guides AI Coding Agents when working on the HarnessBox project.

## What is HarnessBox

HarnessBox is a platform for running AI coding agents in secure sandbox environments. It consists of:

- **`packages/sdk/`** — Python SDK providing sandbox security, workspace, and harness primitives. Zero runtime dependencies — provider SDKs are optional extras.
- **`apps/web/`** — Web application (dashboard)
- **`apps/desktop/`** — Desktop application via Tauri (planned)
- **`apps/api/`** — Cloud API for paid tier (planned, imports SDK)
- **`apps/site/`** — Marketing + documentation site (planned)

## Resolvers (Modular Instructions)

To manage complexity and save context tokens, project instructions are split into specialized resolver files. When performing a task, you MUST first dynamically read (view) the relevant resolver file using your file reading tools.

- **Developer Commands & Workspace Setup** → Read [commands.md](docs/resolvers/commands.md) when building, running, testing, or syncing dependencies.
- **Safety, Guards & Development Rules** → Read [rules.md](docs/resolvers/rules.md) before implementing changes, especially when touching sandbox providers, security guards, or credentials.
- **Architecture & Module Responsibilities** → Read [architecture.md](docs/resolvers/architecture.md) to understand SDK orchestration, module layout, and key design decisions.
- **Coding Conventions, Commits & CI Policies** → Read [conventions.md](docs/resolvers/conventions.md) before formatting code, writing pytests, composing commit messages, or recovering from CI check failures.
- **Issue Tracking, Labels & Domain Docs** → Read [issue-tracker.md](docs/agents/issue-tracker.md), [triage-labels.md](docs/agents/triage-labels.md), and [domain.md](docs/agents/domain.md) when managing GitHub issues or naming domain-specific entities.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
