// --- Event types (from SDK streaming.py UniversalEvent.to_dict()) ---

export interface UniversalEvent {
  type: string;
  timestamp: string;
  message: {
    event_id: string;
    sequence: number;
    session_id: string;
    item_id?: string;
    item_kind?: string;
    item_status?: string;
    content?: ContentPart[];
    delta?: string;
    tool_kind?: string;
    cost_usd?: number;
    duration_ms?: number;
    error_message?: string;
    metadata?: Record<string, unknown>;
  };
}

export interface ContentPart {
  type: string;
  text?: string;
  tool_name?: string;
  tool_input?: string;
  call_id?: string;
  file_path?: string;
  file_action?: string;
}

export interface ContextCategory {
  key: string;
  label: string;
  tokens: number;
}

export interface SessionContextStats {
  tokensUsed: number;
  contextWindow: number;
  percentUsed: number;
  model?: string;
  categories: ContextCategory[];
}

export interface ModelCostBreakdown {
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface CostBreakdown {
  total_cost_usd: number;
  turn_count: number;
  per_model: Record<string, ModelCostBreakdown>;
}

export interface CacheStats {
  cacheReadTokens: number;
  cacheCreationTokens: number;
  inputTokens: number;
  outputTokens: number;
}

// --- Discovery types (from server endpoints) ---

export interface HarnessInfo {
  name: string;
  cli_command: string;
  supports_persistent: boolean;
  default_template: string | null;
  workspace_root: string;
}

export interface ProviderInfo {
  name: string;
}

export interface GuardInfo {
  name: string;
  bash_deny_count: number;
  read_deny_count: number;
}

export interface CredentialProbe {
  name: string;
  available: boolean;
}

export interface WorkspaceNameResponse {
  name: string;
}

export interface DetectedWorkspace {
  remote: string;
  default_branch: string;
  name: string;
}

// --- Workspace creation ---

export interface SecurityPolicyConfig {
  denied_tools?: string[];
  deny_network?: boolean;
  credential_guards?: boolean | string[];
}

export interface GitCredentials {
  type?: string;
  token?: string;
  /** Accepted but unused until SSH clone auth is wired. */
  ssh_key?: string;
}

/** @deprecated Use GitCredentials */
export type GitCredentialsParams = GitCredentials;

export interface GitSourceParams {
  repo_url: string;
  branch?: string;
  credentials?: GitCredentials;
  clone_depth?: number;
  clone_dir_name?: string;
}

export interface FileSystemParams {
  source: string;
  mount_path?: string;
}

/** @deprecated Use FileSystemParams */
export type MountSourceParams = FileSystemParams;

/** @deprecated Prefer git/file_system on CreateWorkspaceRequestParams */
export interface WorkspaceConfig {
  remote: string;
  branch?: string;
  auth_token?: string;
  clone_depth?: number;
  commit_on_exit?: boolean;
  clone_dir_name?: string;
}

export interface CreateWorkspaceRequestParams {
  provider: string;
  env_vars: Record<string, string>;
  skip_permissions: boolean;
  sandbox_timeout?: number;
  session_timeout?: number;
  template?: string;
  git?: GitSourceParams;
  file_system?: FileSystemParams;
  /** @deprecated legacy create body — ignored by server for identity */
  session_id?: string;
  workspace_id?: string;
  project_id?: string;
  model?: string;
  security_policy?: SecurityPolicyConfig;
  workspace?: WorkspaceConfig;
}

/** @deprecated Use CreateWorkspaceRequestParams */
export type CreateSessionRequest = CreateWorkspaceRequestParams;

export interface PromptBody {
  prompt: string;
  harness: string;
  conversation_id?: string;
}

export interface CreateWorkspaceResponseParams {
  workspace_id: string;
  state: string;
  created_at: string;
  harness: string;
  project_id?: string;
  workspace_name?: string;
  branch?: string;
  base_branch?: string;
  remote?: string;
  file_system_path?: string;
  total_cost_usd?: number;
  error_message?: string;
  /** @deprecated legacy fields — prefer workspace_id / state / file_system_path */
  session_id?: string;
  runtime_state?: string;
  mount_path?: string;
}

/** @deprecated Use CreateWorkspaceResponseParams */
export type SessionResponse = CreateWorkspaceResponseParams;

export function workspaceIdOf(s: CreateWorkspaceResponseParams): string {
  return s.workspace_id || s.session_id || "";
}

export function workspaceStateOf(s: CreateWorkspaceResponseParams): string {
  return s.state || s.runtime_state || "";
}

export interface SessionCard {
  id: string;
  title: string;
  status: string;
  harness: string;
  repository?: string;
  branch?: string;
  baseBranch?: string;
  createdAt: string;
  updatedAt: string;
  workspaceName?: string;
  totalCostUsd?: number;
  latestMessage?: string;
}

// --- Multi-session state ---

export type SessionStatus =
  | "backlog"
  | "creating"
  | "starting"
  | "active"
  | "streaming"
  | "paused"
  | "in_review"
  | "ending"
  | "merged"
  | "failed"
  | "archived"
  | "ended"
  | "error"
  | "dead"
  | "dying";

export interface SessionEntry {
  id: string;
  harness: string;
  status: SessionStatus;
  runtimeState: string;
  createdAt: string;
  events: UniversalEvent[];
  error: string | null;
  workspaceName?: string;
  branch?: string;
  baseBranch?: string;
  remote?: string;
}
