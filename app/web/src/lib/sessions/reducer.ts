import type { SessionEntry, SessionStatus, UniversalEvent } from "@/types";

export type SessionMap = Map<string, SessionEntry>;

export type Action =
  | { type: "add_session"; entry: SessionEntry }
  | { type: "remove_session"; sessionId: string }
  | { type: "set_status"; sessionId: string; status: SessionStatus }
  | { type: "set_error"; sessionId: string; error: string }
  | { type: "append_event"; sessionId: string; event: UniversalEvent }
  | { type: "clear_events"; sessionId: string }
  | { type: "rename_session"; sessionId: string; name: string }
  | {
      type: "update_metadata";
      sessionId: string;
      metadata: Partial<
        Pick<SessionEntry, "workspaceName" | "branch" | "baseBranch" | "remote">
      >;
    };

export function sessionsReducer(state: SessionMap, action: Action): SessionMap {
  const next = new Map(state);

  switch (action.type) {
    case "add_session": {
      next.set(action.entry.id, action.entry);
      return next;
    }
    case "remove_session": {
      next.delete(action.sessionId);
      return next;
    }
    case "set_status": {
      const entry = next.get(action.sessionId);
      if (entry) {
        next.set(action.sessionId, { ...entry, status: action.status });
      }
      return next;
    }
    case "set_error": {
      const entry = next.get(action.sessionId);
      if (entry) {
        next.set(action.sessionId, {
          ...entry,
          status: "error",
          error: action.error,
        });
      }
      return next;
    }
    case "append_event": {
      const entry = next.get(action.sessionId);
      if (entry) {
        next.set(action.sessionId, {
          ...entry,
          events: [...entry.events, action.event],
        });
      }
      return next;
    }
    case "clear_events": {
      const entry = next.get(action.sessionId);
      if (entry) {
        next.set(action.sessionId, { ...entry, events: [] });
      }
      return next;
    }
    case "rename_session": {
      const entry = next.get(action.sessionId);
      if (entry) {
        next.set(action.sessionId, { ...entry, workspaceName: action.name });
      }
      return next;
    }
    case "update_metadata": {
      const entry = next.get(action.sessionId);
      if (entry) {
        next.set(action.sessionId, { ...entry, ...action.metadata });
      }
      return next;
    }
  }
}

export function statusFromEvent(event: UniversalEvent): SessionStatus | null {
  switch (event.type) {
    case "session.started":
      return "active";
    case "session.ended":
      return event.message.metadata?.is_error ? "error" : "ended";
    case "turn.started":
      return "streaming";
    case "turn.ended":
      return "active";
    case "error":
      return "error";
    default:
      return null;
  }
}
