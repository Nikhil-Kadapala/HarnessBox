// --- Event types (from SDK streaming.py) ---

export interface UniversalEvent {
  event_id: string;
  sequence: number;
  timestamp: string;
  session_id: string;
  event_type: string;
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

// --- Session creation ---

export interface SecurityPolicyConfig {
  denied_tools?: string[];
  deny_network?: boolean;
  credential_guards?: boolean | string[];
}

export interface WorkspaceConfig {
  remote: string;
  branch?: string;
  auth_token?: string;
  clone_depth?: number;
  commit_on_exit?: boolean;
  clone_dir_name?: string;
}

export interface CreateSessionRequest {
  session_id?: string;
  provider: string;
  harness: string;
  model?: string;
  env_vars: Record<string, string>;
  skip_permissions: boolean;
  sandbox_timeout?: number;
  session_timeout?: number;
  template?: string;
  security_policy?: SecurityPolicyConfig;
  workspace?: WorkspaceConfig;
}

export interface SessionResponse {
  session_id: string;
  harness: string;
  status: string;
  created_at: string;
  workspace_name?: string;
  branch?: string;
  base_branch?: string;
  remote?: string;
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
  | "error";

export interface SessionEntry {
  id: string;
  harness: string;
  status: SessionStatus;
  createdAt: string;
  events: UniversalEvent[];
  error: string | null;
  workspaceName?: string;
  branch?: string;
  baseBranch?: string;
  remote?: string;
}
