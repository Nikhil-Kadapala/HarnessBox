import type { SessionCard, SessionStats } from "./types";

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

export async function transitionSession(
  sessionId: string,
  targetState: string,
): Promise<SessionCard> {
  const data = await fetchJSON<Record<string, unknown>>(
    `/v1/workspaces/${sessionId}/transition`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_state: targetState }),
    },
  );
  return transformSessionCard(data);
}

export async function fetchSessionStats(sessionId: string): Promise<SessionStats> {
  try {
    return await fetchJSON<SessionStats>(`/v1/workspaces/${sessionId}/stats`);
  } catch {
    return { insertions: 0, deletions: 0, commit_count: 0 };
  }
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

export async function createPR(
  sessionId: string,
  title: string,
  body: string = "",
): Promise<SessionCard> {
  const data = await fetchJSON<Record<string, unknown>>(
    `/v1/workspaces/${sessionId}/pr`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title, body }),
    },
  );
  return transformSessionCard(data);
}

export async function refreshPRStatus(sessionId: string): Promise<SessionCard> {
  try {
    const data = await fetchJSON<Record<string, unknown>>(
      `/v1/workspaces/${sessionId}/pr/refresh`,
      { method: "POST" },
    );
    return transformSessionCard(data);
  } catch {
    return transformSessionCard({});
  }
}

export async function renameSession(sessionId: string, name: string): Promise<void> {
  await fetchJSON(`/v1/workspaces/${sessionId}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
}

function transformSessionCard(session: Record<string, unknown>): SessionCard {
  const workspaceName = (session.workspace_name as string) || undefined;
  return {
    id: session.session_id as string,
    title: workspaceName || (session.session_id as string)?.slice(0, 8) || "",
    status: session.status as string,
    harness: session.harness as string,
    repository: extractRepoName(workspaceName),
    branch: (session.branch as string) || undefined,
    baseBranch: (session.base_branch as string) || undefined,
    createdAt: session.created_at as string,
    updatedAt: session.created_at as string,
    workspaceName,
    prUrl: (session.pr_url as string) || undefined,
    prNumber: (session.pr_number as number) || undefined,
    ciStatus: (session.ci_status as string) || undefined,
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
