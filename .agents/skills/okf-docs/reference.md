# OKF Docs — Reference

Canonical house style for HarnessBox. Upstream: OKF SPEC v0.2.

## Frontmatter families (what we use vs defer)

| Family | Keys | HarnessBox policy |
|--------|------|-------------------|
| Required (OKF) | `type` | Always |
| Recommended (OKF) | `title`, `description`, `resource`, `tags` | Always (omit `resource` when N/A) |
| Trust | `generated`, `verified` | Always `generated`; defer `verified` |
| Provenance | `sources[]` | Defer |
| Lifecycle | `status`, `stale_after` | Always `status`; defer `stale_after` |
| Bundle | `okf_version` | Only on `docs/index.md` → `"0.2"` |

## Example: Guide

```yaml
---
type: Guide
title: Quickstart
description: Create a sandbox session and stream a first prompt in minutes.
tags: [sdk, sandbox, workspace]
status: stable
generated: { by: human:nikhilk, at: 2026-07-27T19:33:00Z }
---
```

## Example: Subsystem Doc with resource

```yaml
---
type: Subsystem Doc
title: Streaming Events
description: UniversalEvent stream parsing from agent NDJSON output.
resource: https://github.com/Nikhil-Kadapala/HarnessBox/blob/main/packages/sdk/src/harnessbox/streaming.py
tags: [streaming, sdk, http]
status: stable
generated: { by: process:okf-migration, at: 2026-07-27T19:33:00Z }
---
```

## Example: Repo Doc

```yaml
---
type: Repo Doc
title: Safety & Development Rules
description: Stop-and-clarify triggers, do-not list, and completion checklist for agents.
tags: [security, sdk, agent, ci]
status: stable
generated: { by: process:okf-migration, at: 2026-07-27T19:33:00Z }
---
```

## Example: bundle-root index

```yaml
---
okf_version: "0.2"
---

# HarnessBox docs
...
```

## Index body convention

```markdown
# Section heading

* [Title](relative-or-path.md) - short description
```

## Actor strings

| Form | Meaning | Example |
|------|---------|---------|
| `human:<id>` | Person | `human:nikhilk` |
| `process:<name>` | Automation / migration | `process:okf-migration` |
| `agent/<tool>` | Agent or tool | `reference_agent/gemini-2.5-pro` |

Trust tiers (if `verified` is ever added): no `verified` → unverified; non-`human:` only → machine-confirmed; any `human:` → human-reviewed.

## Status values

| Value | Meaning |
|-------|---------|
| `draft` | Incomplete / under rewrite |
| `stable` | Ready (default if omitted by OKF; we still write it) |
| `deprecated` | Kept for links/history |

## Path migration map (historical)

| Old path | New path |
|----------|----------|
| `docs/resolvers/*.md` | `.agents/repo-docs/*.md` |
| `docs/agents/*.md` | `.agents/repo-docs/*.md` |
| "resolver" in AGENTS prose | "repo-docs" / `.agents/repo-docs/` |

## Tool discovery symlinks

Canonical skills live in `.agents/skills/`. These relative directory symlinks expose the same tree to each agent host:

| Path | Target |
|------|--------|
| `.cursor/skills` | `../.agents/skills` |
| `.claude/skills` | `../.agents/skills` |
| `.codex/skills` | `../.agents/skills` |

Add skills only under `.agents/skills/`. Do not copy skill trees into the tool directories.

## Out of scope for this skill

- Rewriting `AGENTS.md` / `CONTEXT.md` as OKF concepts (always-loaded; stay outside the bundle)
- Attested Computation concepts (`type: Attested Computation`)
- Publishing to Google Knowledge Catalog / BigQuery enrichment agent
