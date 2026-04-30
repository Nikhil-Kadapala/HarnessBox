/**
 * Session API Client
 *
 * Fetches session data from the HarnessBox backend for the session board.
 */

import type { SessionCard } from "./types"

const API_BASE = "http://localhost:8080"

export async function fetchSessions(): Promise<SessionCard[]> {
  const response = await fetch(`${API_BASE}/v1/sessions`)
  if (!response.ok) {
    throw new Error(`Failed to fetch sessions: ${response.statusText}`)
  }
  const data = await response.json()

  // Transform server response to SessionCard format
  return data.map((session: any) => transformSessionCard(session))
}

function transformSessionCard(session: any): SessionCard {
  return {
    id: session.session_id,
    title: session.workspace_name || session.session_id.slice(0, 8),
    status: session.status,
    harness: session.harness,
    repository: extractRepoName(session.workspace_name),
    createdAt: session.created_at,
    updatedAt: session.created_at, // TODO: track last activity
    workspaceName: session.workspace_name,
    artifacts: [], // TODO: artifact support
  }
}

function extractRepoName(workspaceName?: string): string | undefined {
  if (!workspaceName) return undefined
  // workspace_name format: "owner-repo" or just a city name
  // If it contains a dash and looks like a repo, extract it
  const parts = workspaceName.split("-")
  if (parts.length >= 2) {
    return `${parts[0]}/${parts[1]}`
  }
  return workspaceName
}
