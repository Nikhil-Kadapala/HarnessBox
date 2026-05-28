import type { SessionCard, SessionResponse } from "@/types";

export function extractRepoName(workspaceName?: string): string | undefined {
  if (!workspaceName) return undefined;
  const parts = workspaceName.split("-");
  if (parts.length >= 2) {
    return `${parts[0]}/${parts[1]}`;
  }
  return workspaceName;
}

export function transformSessionResponseToCard(session: SessionResponse): SessionCard {
  return {
    id: session.session_id,
    title: session.workspace_name || session.session_id.slice(0, 8),
    status: session.workflow_state,
    harness: session.harness,
    repository: extractRepoName(session.workspace_name),
    branch: session.branch,
    baseBranch: session.base_branch,
    createdAt: session.created_at,
    updatedAt: session.created_at,
    workspaceName: session.workspace_name,
    prUrl: session.pr_url,
    prNumber: session.pr_number,
    ciStatus: session.ci_status,
    totalCostUsd: session.total_cost_usd,
  };
}

export function searchSessions(sessions: SessionCard[], query: string): SessionCard[] {
  const q = query.trim().toLowerCase();
  if (!q) return sessions;
  return sessions.filter((s) =>
    [s.title, s.status, s.repository, s.branch, s.harness, s.workspaceName, s.latestMessage]
      .filter(Boolean)
      .some((v) => v?.toLowerCase().includes(q)),
  );
}

export function formatStatusLabel(value: string): string {
  const n = value.trim().toLowerCase();
  if (!n || n === "unknown") return "No status";
  return value
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (l) => l.toUpperCase());
}

export function formatRelativeTime(value: string | undefined): string {
  if (!value) return "No activity";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "No activity";

  const diffMs = Date.now() - date.getTime();
  const minutes = Math.max(1, Math.floor(diffMs / 60_000));
  if (minutes < 60) return `${minutes}m ago`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;

  return `${Math.floor(hours / 24)}d ago`;
}
