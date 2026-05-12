export interface SessionCard {
  id: string
  title: string
  status: string
  harness: string
  repository?: string
  repositoryUrl?: string
  branch?: string
  baseBranch?: string
  createdBy?: string
  createdAt: string
  updatedAt?: string
  latestMessage?: string
  workspaceName?: string
  prUrl?: string
  prNumber?: number
  ciStatus?: string
  totalCostUsd?: number
}

export interface SessionStats {
  insertions: number
  deletions: number
  commit_count: number
}

export interface CreateSessionInput {
  harness: string
  prompt: string
  repository?: string
  branch?: string
  env_vars?: Record<string, string>
  skip_permissions?: boolean
}
