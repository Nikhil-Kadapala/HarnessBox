import type { SessionCard, SessionStats } from "./types"

const API_BASE = "/api"

export async function fetchSessions(): Promise<SessionCard[]> {
  const response = await fetch(`${API_BASE}/v1/sessions`)
  if (!response.ok) {
    throw new Error(`Failed to fetch sessions: ${response.statusText}`)
  }
  const data = await response.json()
  return data.map((session: Record<string, unknown>) => transformSessionCard(session))
}

export async function transitionSession(
  sessionId: string,
  targetState: string,
): Promise<SessionCard> {
  const response = await fetch(`${API_BASE}/v1/sessions/${sessionId}/transition`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_state: targetState }),
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Failed to transition session: ${response.statusText}`)
  }
  const data = await response.json()
  return transformSessionCard(data)
}

export async function fetchSessionStats(sessionId: string): Promise<SessionStats> {
  const response = await fetch(`${API_BASE}/v1/sessions/${sessionId}/stats`)
  if (!response.ok) {
    return { insertions: 0, deletions: 0, commit_count: 0 }
  }
  return response.json()
}

export async function pauseSession(sessionId: string): Promise<SessionCard> {
  const response = await fetch(`${API_BASE}/v1/sessions/${sessionId}/pause`, { method: "POST" })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || "Failed to pause session")
  }
  return transformSessionCard(await response.json())
}

export async function resumeSession(sessionId: string): Promise<SessionCard> {
  const response = await fetch(`${API_BASE}/v1/sessions/${sessionId}/resume`, { method: "POST" })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || "Failed to resume session")
  }
  return transformSessionCard(await response.json())
}

export async function stopSession(sessionId: string): Promise<void> {
  const response = await fetch(`${API_BASE}/v1/sessions/${sessionId}/stop`, { method: "POST" })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || "Failed to stop session")
  }
}

export async function createPR(
  sessionId: string,
  title: string,
  body: string = "",
): Promise<SessionCard> {
  const response = await fetch(`${API_BASE}/v1/sessions/${sessionId}/pr`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, body }),
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || "Failed to create PR")
  }
  return transformSessionCard(await response.json())
}

export async function refreshPRStatus(sessionId: string): Promise<SessionCard> {
  const response = await fetch(`${API_BASE}/v1/sessions/${sessionId}/pr/refresh`, {
    method: "POST",
  })
  if (!response.ok) {
    return transformSessionCard({})
  }
  return transformSessionCard(await response.json())
}

export async function renameSession(sessionId: string, name: string): Promise<void> {
  const response = await fetch(`${API_BASE}/v1/sessions/${sessionId}/rename`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || "Failed to rename session")
  }
}

function transformSessionCard(session: Record<string, unknown>): SessionCard {
  const workspaceName = (session.workspace_name as string) || undefined
  return {
    id: session.session_id as string,
    title: workspaceName || (session.session_id as string).slice(0, 8),
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
  }
}

function extractRepoName(workspaceName?: string): string | undefined {
  if (!workspaceName) return undefined
  const parts = workspaceName.split("-")
  if (parts.length >= 2) {
    return `${parts[0]}/${parts[1]}`
  }
  return workspaceName
}
