import type {
  CredentialProbe,
  CreateSessionRequest,
  DetectedWorkspace,
  GuardInfo,
  HarnessInfo,
  ProviderInfo,
  SessionResponse,
  WorkspaceNameResponse,
} from "@/types";

const BASE = "/api";

async function fetchJSON<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`${res.status}: ${text || res.statusText}`);
  }
  const data = await res.json();
  return data as T;
}

export async function fetchCredentials(): Promise<CredentialProbe[]> {
  const data = await fetchJSON<{ probes: CredentialProbe[] } | CredentialProbe[]>("/v1/credentials/status");
  // Handle both wrapped response {probes: [...]} and direct array
  if (Array.isArray(data)) {
    return data;
  }
  if (data && typeof data === "object" && "probes" in data) {
    return data.probes;
  }
  console.warn("Unexpected credentials response format:", data);
  return [];
}

export async function fetchHarnesses(): Promise<HarnessInfo[]> {
  return fetchJSON<HarnessInfo[]>("/v1/harnesses");
}

export async function fetchProviders(): Promise<ProviderInfo[]> {
  return fetchJSON<ProviderInfo[]>("/v1/providers");
}

export async function fetchGuards(): Promise<GuardInfo[]> {
  return fetchJSON<GuardInfo[]>("/v1/guards");
}

export async function createSession(config: CreateSessionRequest, signal?: AbortSignal): Promise<SessionResponse> {
  return fetchJSON<SessionResponse>("/v1/workspaces", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
    signal,
  });
}

export async function listSessions(): Promise<SessionResponse[]> {
  return fetchJSON<SessionResponse[]>("/v1/workspaces");
}

export async function destroySession(id: string): Promise<void> {
  const res = await fetch(`${BASE}/v1/workspaces/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 404) {
    throw new Error(`Failed to destroy session: ${res.status}`);
  }
}

export async function sendPermission(
  sessionId: string,
  requestId: string,
  behavior: "allow" | "deny",
): Promise<void> {
  await fetchJSON(`/v1/workspaces/${sessionId}/permission`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request_id: requestId, behavior }),
  });
}

export async function fetchWorkspaceName(): Promise<string> {
  const data = await fetchJSON<WorkspaceNameResponse>("/v1/workspace/name");
  return data.name;
}

export async function detectWorkspace(path: string): Promise<DetectedWorkspace> {
  return fetchJSON<DetectedWorkspace>(`/v1/workspace/detect?path=${encodeURIComponent(path)}`);
}

export interface GitHubProfile {
  login: string;
  name: string | null;
  email: string | null;
  avatar_url: string;
}

export async function fetchGitHubProfile(): Promise<GitHubProfile> {
  return fetchJSON<GitHubProfile>("/v1/account/github");
}

export async function pauseSession(sessionId: string): Promise<SessionResponse> {
  return fetchJSON<SessionResponse>(
    `/v1/workspaces/${sessionId}/pause`,
    { method: "POST" },
  );
}

export async function resumeSession(sessionId: string): Promise<SessionResponse> {
  return fetchJSON<SessionResponse>(
    `/v1/workspaces/${sessionId}/resume`,
    { method: "POST" },
  );
}

export async function stopSession(sessionId: string): Promise<void> {
  await fetchJSON(`/v1/workspaces/${sessionId}/stop`, { method: "POST" });
}
