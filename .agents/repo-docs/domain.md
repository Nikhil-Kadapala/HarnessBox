---
type: Repo Doc
title: Domain Docs
description: How agents should consume CONTEXT.md glossary and ADR vocabulary when exploring the codebase.
tags: [glossary, agent]
status: stable
generated: { by: process:okf-migration, at: 2026-07-27T19:33:00Z }
---

# Domain Docs

How engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the project's domain glossary and bounded-context definitions.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in (created lazily if present).

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## File structure

```
/
├── CONTEXT.md
├── AGENTS.md
├── .agents/repo-docs/     # agent deep-dives (this tree)
├── docs/                  # OKF user-facing bundle
│   ├── getting-started/
│   ├── sandboxes/
│   └── openapi.yaml
├── packages/sdk/
└── apps/
```

## Use the glossary's vocabulary

When your output names a domain concept (issue title, refactor proposal, hypothesis, test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0001 (protocol-based providers) — but worth reopening because..._
