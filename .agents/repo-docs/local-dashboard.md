---
type: Repo Doc
title: Local Dashboard Dogfood
description: Internal walkthrough — start harnessbox serve + the web dashboard, then create → chat → pause → resume.
tags: [web, server, workspace, sandbox, cli]
status: stable
generated: { by: agent/cursor, at: 2026-07-27T20:04:00Z }
---

# Local Dashboard Dogfood

**Internal only** — not part of the public OKF bundle under `docs/`. Use this to exercise the React dashboard against a real local `harnessbox serve` backend. The web app proxies `/api` to `http://localhost:8000`, so both processes must be running.

## Prerequisites

- Python 3.12+, [uv](https://docs.astral.sh/uv/), and [Bun](https://bun.sh/)
- An E2B API key (real sandboxes; without it create will fail)
- A harness API key for the agent you pick (Claude Code → `ANTHROPIC_API_KEY`)

From the monorepo root:

```bash
# SDK + server + E2B provider (editable install)
cd packages/sdk
uv sync --extra e2b

# Web deps
cd ../../apps/web
bun install
```

Export keys in the shell that will run the server. For this local dogfood flow, the server copies the explicitly allowlisted provider and harness keys into new workspaces when the UI omits them. User-provided workspace values take priority. Git authentication uses the credential helper and is not copied into the workspace environment:

```bash
export E2B_API_KEY=...
export ANTHROPIC_API_KEY=...   # or OPENAI_API_KEY for Codex
```

You can also paste keys in the dashboard **Settings** page or the New Workspace sheet; host env is enough for most dogfood runs.

## 1. Start the backend

In one terminal:

```bash
cd packages/sdk
uv run harnessbox serve --port 8000
```

You should see something like:

```text
Starting HarnessBox server on 0.0.0.0:8000
Storage: sqlite
Database: ~/.harnessbox/sessions.db
```

Useful variants:

```bash
uv run harnessbox serve --port 8000 --storage memory   # ephemeral; no SQLite
uv run harnessbox serve --port 8000 --db /tmp/hb.db      # custom SQLite path
```

Sanity check (another terminal):

```bash
curl -s http://localhost:8000/v1/providers | head
curl -s http://localhost:8000/v1/credentials/status | head
```

Leave this process running.

## 2. Start the frontend

In a second terminal:

```bash
cd apps/web
bun run dev
```

Vite prints a local URL (usually `http://localhost:5173`). Open it in the browser.

How the proxy works (`apps/web/vite.config.ts`): browser calls `/api/v1/...` → Vite strips `/api` → `http://localhost:8000/v1/...`. If the board fails to load sessions, the server is almost always down or on a different port.

### Frontend unit tests (optional)

Automated UI tests do not need the server:

```bash
cd apps/web
bun run test    # Vitest
bun run lint
bunx tsc --noEmit
```

Use that for component/regression checks. Use the steps below for end-to-end dogfood against real sandboxes.

## 3. Simple dogfood workflow

Goal: **create Project → create Workspace → chat → pause → resume → stop**.

### Create a Project, then a Workspace

1. In the sidebar, click **+** beside Projects and create a Project from a remote Git URL or a local repository. Local selection reads Git metadata in the browser and records the remote; it does not copy the local working tree to the server.
2. Click **+** beside the new Project to create a Workspace. Project creation alone does not provision a cloud runtime.
3. Choose the runtime provider and harness (for example, `e2b` and `claude-code`) and configure credentials/permissions as needed.
4. Click **Create Workspace**.

The UI navigates to `/session/<id>` while the server provisions the selected cloud runtime (time varies by provider). Watch the creating state; on failure, check the server terminal for provider or credential errors.

### Chat

1. When the runtime is **Running**, send a short prompt, e.g. `Reply with exactly: pong`.
2. Confirm streamed events appear in the feed (assistant text / tool calls).
3. Optional: send a second turn to confirm the conversation continues in the same workspace.

### Pause

1. Go back to the **board** (`/`) or use the session controls.
2. **Pause** the workspace.
3. Confirm status moves to **paused** (board column / sidebar badge). Idle auto-pause can also happen after the configured idle minutes; explicit pause is clearer for dogfood.

### Resume

1. **Resume** the same workspace.
2. Confirm status returns to **active**.
3. Send another short prompt. The agent should continue (resume may take a few seconds while the sandbox wakes).

### Stop / destroy

1. **Stop** (or destroy from the sidebar) when finished so you are not billed for an idle live sandbox.
2. Confirm it disappears from the active list (or moves to a terminal column, depending on UI state).

## Troubleshooting

| Symptom | Likely cause |
|--------|----------------|
| Board empty / network errors | Server not on `:8000`, or Vite not proxying |
| Create fails immediately | Missing `E2B_API_KEY` in server env / Settings |
| Sandbox up, agent silent / auth errors | Missing harness key (`ANTHROPIC_API_KEY`, etc.) |
| Resume fails | The server may have a newer runtime state than the page; refresh the page and check the server terminal/provider credentials |
| Port already in use | `uv run harnessbox serve --port 8001` and point Vite proxy at that port, or free `8000` |

## Related

- [Developer Commands](commands.md) — shorter command cheat sheet
- Public user guides (SDK install / quickstart): [`docs/getting-started/`](../../docs/getting-started/)
- [Streaming Events](../../docs/sandboxes/streaming.md) — what the event feed shows
