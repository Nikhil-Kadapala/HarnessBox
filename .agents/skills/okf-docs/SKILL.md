---
name: okf-docs
description: >-
  Author and migrate HarnessBox documentation in Open Knowledge Format (OKF) v0.2 —
  YAML frontmatter, docs/ OKF bundle, and .agents/repo-docs/ agent deep-dives. Use when
  adding or editing docs under docs/ or .agents/repo-docs/, writing OKF frontmatter,
  creating docs/index.md, migrating resolvers/agents docs, or when the user mentions
  OKF, knowledge bundle, or repo-docs.
---

# OKF Docs (HarnessBox)

Write and maintain docs as OKF v0.2 markdown: YAML frontmatter for queryable fields, markdown body for prose. Spec: [GoogleCloudPlatform/knowledge-catalog/okf/SPEC.md](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md).

## Layout (do not invent alternatives)

```
docs/                         # OKF user-facing bundle
  index.md                    # MAY include okf_version: "0.2"
  getting-started/*.md
  sandboxes/*.md
  openapi.yaml                # leave as YAML; optional thin .md wrapper later
.agents/
  repo-docs/                  # agent deep-dives (outside OKF bundle root)
    index.md
    architecture.md
    commands.md
    conventions.md
    rules.md
    domain.md
    issue-tracker.md
    triage-labels.md
  skills/                     # canonical skills bundle (source of truth)
.cursor/skills -> ../.agents/skills   # Cursor discovery
.claude/skills -> ../.agents/skills   # Claude Code discovery
.codex/skills  -> ../.agents/skills   # Codex discovery
AGENTS.md                     # always-loaded agent guide (not an OKF concept)
CONTEXT.md                    # domain glossary (not an OKF concept)
```

Add new skills only under `.agents/skills/`. The three tool paths are directory symlinks — do not duplicate skill trees there.

- Concept ID = path relative to bundle root without `.md` (for `docs/` files).
- Reserved names: `index.md`, `log.md` — not concept documents.
- Folder `index.md` files: **no** frontmatter (except bundle-root `docs/index.md` may set `okf_version`).
- Cross-links: prefer bundle-absolute `/getting-started/introduction.md` inside `docs/`; use relative links across `.agents/` ↔ `docs/` as needed.
- Never recreate `docs/resolvers/` or `docs/agents/` — those moved to `.agents/repo-docs/`.

## Required frontmatter (house style)

Every concept `.md` file (not folder indexes):

```yaml
---
type: <Guide | Subsystem Doc | Repo Doc | API Spec>
title: <display name>
description: <one sentence>
resource: <optional GitHub blob URL or omit>
tags: [<from controlled list>]
status: stable   # draft | stable | deprecated
generated: { by: <actor>, at: <ISO-8601> }
---
```

- **`type` is the only OKF-required key**; we always also write the recommended + lifecycle fields above.
- **Do not** add `sources`, `verified`, or `stale_after` unless the user asks (deferred).
- **Do not** use v0.1 `timestamp:` — use `generated.at`.
- Actors: `human:<id>`, `process:<name>`, or `agent/<tool>` (e.g. `process:okf-migration`).

### Type vocabulary

| `type` | Where |
|--------|--------|
| `Guide` | `docs/getting-started/` |
| `Subsystem Doc` | `docs/sandboxes/` |
| `Repo Doc` | `.agents/repo-docs/` |
| `API Spec` | thin markdown companion to `openapi.yaml` only if added |

### Tags (controlled list)

`sdk` · `server` · `web` · `cli` · `security` · `streaming` · `lifecycle` · `workspace` · `session` · `sandbox` · `http` · `git` · `agent` · `ci` · `glossary` · `architecture`

Pick 2–5 relevant tags. Do not invent synonyms (`vm` → use `sandbox`).

### `resource`

- Code-backed concepts: GitHub blob URL on `main`, e.g. `https://github.com/Nikhil-Kadapala/HarnessBox/blob/main/packages/sdk/src/harnessbox/streaming.py`
- Pure guides / process docs: omit `resource`

## Workflows

### New user-facing doc under `docs/`

1. Choose directory (`getting-started/` or `sandboxes/`).
2. Create `*.md` with frontmatter + body.
3. Add a bullet to the folder `index.md` and to `docs/index.md`.
4. Link from related guides with relative or `/…` paths.
5. If behavior changed for agents, update the matching `.agents/repo-docs/` file and `AGENTS.md` deep-dive pointer if needed.

### New or updated agent deep-dive under `.agents/repo-docs/`

1. Use `type: Repo Doc` and the same frontmatter shape.
2. Update `.agents/repo-docs/index.md`.
3. Keep `AGENTS.md` Deep-Dive Docs links accurate.
4. Prefer pointing to `AGENTS.md` for exhaustive file indexes; keep architecture deep-dives focused on flows/invariants/extension points.

### Content accuracy (architecture / HTTP)

When editing architecture or API docs:

- Method is `send_message`, not `run_prompt`.
- HTTP is FastAPI `/v1/workspaces/*` — **no** `/v1/sessions/*` tree.
- `RuntimeState` includes `PAUSED` and `ERROR`.
- Do not reintroduce a root `session.py` / `SessionManager` myth.

### Validation checklist

Before finishing:

- [ ] Frontmatter opens and closes with `---` on their own lines
- [ ] `type`, `title`, `description`, `tags`, `status`, `generated` present
- [ ] `tags` use the controlled list
- [ ] Folder indexes updated; no orphan pages
- [ ] No links to `docs/resolvers/` or `docs/agents/`
- [ ] YAML parses (no tabs; spaces only)

## Additional resources

- Field reference and examples: [reference.md](reference.md)
- Live bundle root: [`docs/index.md`](../../docs/index.md)
- Agent deep-dives: [`.agents/repo-docs/`](../../repo-docs/)
