import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  createSession as apiCreateSession,
  destroySession as apiDestroySession,
  listSessions,
} from "@/lib/api";
import { renameSession as apiRenameSession } from "@/lib/sessions/client";
import { streamSSE } from "@/lib/sse";
import type {
  CreateSessionRequest,
  SessionEntry,
  SessionStatus,
  UniversalEvent,
} from "@/types";

// --- Reducer for session state ---

type SessionMap = Map<string, SessionEntry>;

type Action =
  | { type: "add_session"; entry: SessionEntry }
  | { type: "remove_session"; sessionId: string }
  | { type: "set_status"; sessionId: string; status: SessionStatus }
  | { type: "set_error"; sessionId: string; error: string }
  | { type: "append_event"; sessionId: string; event: UniversalEvent }
  | { type: "clear_events"; sessionId: string }
  | { type: "rename_session"; sessionId: string; name: string }
  | { type: "update_metadata"; sessionId: string; metadata: Partial<Pick<SessionEntry, "workspaceName" | "branch" | "baseBranch" | "remote">> };

function sessionsReducer(state: SessionMap, action: Action): SessionMap {
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
        next.set(action.sessionId, { ...entry, status: "error", error: action.error });
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

function statusFromEvent(event: UniversalEvent): SessionStatus | null {
  switch (event.event_type) {
    case "session.started":
      return "active";
    case "session.ended":
      return event.metadata?.is_error ? "error" : "ended";
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

// --- Hook ---

export function useSessionManager() {
  const [sessions, dispatch] = useReducer(sessionsReducer, new Map<string, SessionEntry>());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const abortRefs = useRef<Map<string, AbortController>>(new Map());
  const destroyedRef = useRef<Set<string>>(new Set());
  const polledRef = useRef(false);

  const activeSession = activeSessionId ? sessions.get(activeSessionId) ?? null : null;

  // Poll existing sessions on mount (page refresh recovery)
  useEffect(() => {
    if (polledRef.current) return;
    polledRef.current = true;

    listSessions()
      .then((serverSessions) => {
        for (const s of serverSessions) {
          if (s.status !== "ended") {
            dispatch({
              type: "add_session",
              entry: {
                id: s.session_id,
                harness: s.harness,
                status: (s.status as SessionStatus) || "active",
                createdAt: s.created_at,
                events: [],
                error: null,
                workspaceName: s.workspace_name,
                branch: s.branch,
                baseBranch: s.base_branch,
                remote: s.remote,
              },
            });
          }
        }
        if (serverSessions.length > 0) {
          const active = serverSessions.find((s) => s.status === "active");
          if (active) setActiveSessionId(active.session_id);
        }
      })
      .catch(() => {});
  }, []);

  const reconnectSession = useCallback(
    async (sessionId: string) => {
      const entry = sessions.get(sessionId);
      const lastSeq = entry?.events.at(-1)?.sequence;

      const controller = new AbortController();
      abortRefs.current.set(`reconnect-${sessionId}`, controller);

      try {
        for await (const event of streamSSE({
          url: `/v1/workspaces/${sessionId}/events`,
          method: "GET",
          lastEventId: lastSeq,
          signal: controller.signal,
        })) {
          dispatch({ type: "append_event", sessionId, event });
          const newStatus = statusFromEvent(event);
          if (newStatus) {
            dispatch({ type: "set_status", sessionId, status: newStatus });
          }
        }
      } catch (err) {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          // Reconnection failed silently — session may have ended
        }
      } finally {
        abortRefs.current.delete(`reconnect-${sessionId}`);
      }
    },
    [sessions],
  );

  const createSessionOptimistic = useCallback(
    (config: CreateSessionRequest) => {
      const sessionId = config.session_id || crypto.randomUUID();

      const entry: SessionEntry = {
        id: sessionId,
        harness: config.harness,
        status: "creating",
        createdAt: new Date().toISOString(),
        events: [],
        error: null,
        workspaceName: config.workspace?.clone_dir_name,
        branch: config.workspace?.branch,
        remote: config.workspace?.remote,
      };
      dispatch({ type: "add_session", entry });
      setActiveSessionId(sessionId);

      const controller = new AbortController();
      abortRefs.current.set(`create-${sessionId}`, controller);

      apiCreateSession({ ...config, session_id: sessionId }, controller.signal)
        .then((res) => {
          abortRefs.current.delete(`create-${sessionId}`);

          if (destroyedRef.current.has(sessionId)) return;

          dispatch({
            type: "update_metadata",
            sessionId,
            metadata: {
              workspaceName: res.workspace_name,
              branch: res.branch,
              baseBranch: res.base_branch,
              remote: res.remote,
            },
          });

          reconnectSession(sessionId);
        })
        .catch((err) => {
          abortRefs.current.delete(`create-${sessionId}`);
          if (err instanceof DOMException && err.name === "AbortError") return;
          const message = err instanceof Error ? err.message : "Failed to create session";
          dispatch({ type: "set_error", sessionId, error: message });
        });

      return sessionId;
    },
    [reconnectSession],
  );

  const switchSession = useCallback((id: string) => {
    setActiveSessionId(id);
  }, []);

  const sendPrompt = useCallback(
    async (sessionId: string, prompt: string) => {
      dispatch({ type: "set_status", sessionId, status: "streaming" });

      const controller = new AbortController();
      abortRefs.current.set(sessionId, controller);

      try {
        let eventCount = 0;
        for await (const event of streamSSE({
          url: `/v1/workspaces/${sessionId}/prompt`,
          method: "POST",
          body: { prompt },
          signal: controller.signal,
        })) {
          eventCount++;
          console.log(`[SessionManager] Event #${eventCount}:`, event.event_type, event);
          dispatch({ type: "append_event", sessionId, event });
          if (event.event_type === "error" && event.error_message) {
            dispatch({ type: "set_error", sessionId, error: event.error_message });
            continue;
          }
          const newStatus = statusFromEvent(event);
          if (newStatus && newStatus !== "streaming") {
            dispatch({ type: "set_status", sessionId, status: newStatus });
          }
        }
        console.log(`[SessionManager] Stream ended. Total events: ${eventCount}`);
        dispatch({ type: "set_status", sessionId, status: "active" });
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          dispatch({ type: "set_status", sessionId, status: "active" });
          return;
        }
        const message = err instanceof Error ? err.message : "Stream error";
        dispatch({ type: "set_error", sessionId, error: message });
      } finally {
        abortRefs.current.delete(sessionId);
      }
    },
    [],
  );

  const stopStreaming = useCallback((sessionId: string) => {
    abortRefs.current.get(sessionId)?.abort();
  }, []);

  const destroySessionById = useCallback(
    async (sessionId: string) => {
      destroyedRef.current.add(sessionId);
      abortRefs.current.get(sessionId)?.abort();
      abortRefs.current.get(`reconnect-${sessionId}`)?.abort();
      abortRefs.current.get(`create-${sessionId}`)?.abort();
      abortRefs.current.delete(sessionId);
      abortRefs.current.delete(`reconnect-${sessionId}`);
      abortRefs.current.delete(`create-${sessionId}`);

      try {
        await apiDestroySession(sessionId);
      } catch {
        // best effort
      }

      dispatch({ type: "remove_session", sessionId });

      if (activeSessionId === sessionId) {
        const remaining = [...sessions.keys()].filter((k) => k !== sessionId);
        setActiveSessionId(remaining[0] ?? null);
      }
    },
    [activeSessionId, sessions],
  );

  const renameSession = useCallback(
    async (sessionId: string, name: string) => {
      try {
        await apiRenameSession(sessionId, name);
      } catch {
        return;
      }
      dispatch({ type: "rename_session", sessionId, name });
    },
    [],
  );

  return {
    sessions,
    activeSessionId,
    activeSession,
    createSession: createSessionOptimistic,
    switchSession,
    reconnectSession,
    sendPrompt,
    stopStreaming,
    destroySession: destroySessionById,
    renameSession,
  };
}
