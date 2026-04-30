/**
 * Session Board Types
 *
 * These types power the kanban-style session board UI, adapted from
 * Cursor's Agent Kanban pattern. Maps HarnessBox sessions to visual
 * cards with status, repo, artifacts, and metadata.
 */

export type GroupBy = "status" | "repository" | "createdAt"

export type SidebarFilter = "all" | "recentlyActive" | "paused" | "failed"

export interface SessionCard {
  id: string
  title: string
  status: string
  harness: string
  repository?: string
  repositoryUrl?: string
  branch?: string
  createdBy?: string
  createdAt: string
  updatedAt?: string
  latestMessage?: string
  workspaceName?: string
  artifacts: ArtifactPreview[]
}

export interface ArtifactPreview {
  path: string
  name: string
  size?: number
  contentType?: string
  mediaUrl?: string
  previewKind: "image" | "video" | "file"
}

export interface SessionListResponse {
  sessions: SessionCard[]
}

export interface CreateSessionInput {
  harness: string
  prompt: string
  repository?: string
  branch?: string
  env_vars?: Record<string, string>
  skip_permissions?: boolean
}

export interface CreateSessionResponse {
  session: SessionCard
}
