import type { SessionCard } from "./types";

const API_BASE = "/api";

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init);
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(detail || `Request failed: ${res.statusText}`);
  }
  return res.json();
}

export async function fetchSessions(): Promise<SessionCard[]> {
  const data = await fetchJSON<Record<string, unknown>[]>("/v1/workspaces");
  return data.map(transformSessionCard);
}

export async function pauseSession(sessionId: string): Promise<SessionCard> {
  const data = await fetchJSON<Record<string, unknown>>(
    `/v1/workspaces/${sessionId}/pause`,
    { method: "POST" },
  );
  return transformSessionCard(data);
}

export async function resumeSession(sessionId: string): Promise<SessionCard> {
  const data = await fetchJSON<Record<string, unknown>>(
    `/v1/workspaces/${sessionId}/resume`,
    { method: "POST" },
  );
  return transformSessionCard(data);
}

export async function stopSession(sessionId: string): Promise<void> {
  await fetchJSON(`/v1/workspaces/${sessionId}/stop`, { method: "POST" });
}

function transformSessionCard(session: Record<string, unknown>): SessionCard {
  const workspaceName = (session.workspace_name as string) || undefined;
  const id = (session.workspace_id as string) || (session.session_id as string) || "";
  const state = (session.state as string) || (session.runtime_state as string) || "";
  return {
    id,
    title: workspaceName || id.slice(0, 8) || "",
    status: state,
    harness: session.harness as string,
    repository: extractRepoName(workspaceName),
    branch: (session.branch as string) || undefined,
    baseBranch: (session.base_branch as string) || undefined,
    createdAt: session.created_at as string,
    updatedAt: session.created_at as string,
    workspaceName,
    totalCostUsd: (session.total_cost_usd as number) || undefined,
  };
}

function extractRepoName(workspaceName?: string): string | undefined {
  if (!workspaceName) return undefined;
  const parts = workspaceName.split("-");
  if (parts.length >= 2) {
    return `${parts[0]}/${parts[1]}`;
  }
  return workspaceName;
}
