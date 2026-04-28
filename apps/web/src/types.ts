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

export interface SessionConfig {
  provider: string;
  harness: string;
  env_vars: Record<string, string>;
  skip_permissions: boolean;
}

export type SessionState = "idle" | "creating" | "streaming" | "ended" | "error";
