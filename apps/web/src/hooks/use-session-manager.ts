import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import {
  createSession as apiCreateSession,
  destroySession as apiDestroySession,
  listSessions,
} from "@/lib/api";
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
  | { type: "clear_events"; sessionId: string };

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

  const createSessionAndActivate = useCallback(
    async (config: CreateSessionRequest) => {
      try {
        const res = await apiCreateSession(config);
        const entry: SessionEntry = {
          id: res.session_id,
          harness: res.harness,
          status: "active",
          createdAt: res.created_at,
          events: [],
          error: null,
          workspaceName: res.workspace_name,
        };
        dispatch({ type: "add_session", entry });
        setActiveSessionId(res.session_id);
        return res.session_id;
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to create session";
        throw new Error(message);
      }
    },
    [],
  );

  const switchSession = useCallback((id: string) => {
    setActiveSessionId(id);
  }, []);

  const reconnectSession = useCallback(
    async (sessionId: string) => {
      const entry = sessions.get(sessionId);
      const lastSeq = entry?.events.at(-1)?.sequence;

      const controller = new AbortController();
      abortRefs.current.set(`reconnect-${sessionId}`, controller);

      try {
        for await (const event of streamSSE({
          url: `/v1/sessions/${sessionId}/events`,
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

  const sendPrompt = useCallback(
    async (sessionId: string, prompt: string) => {
      dispatch({ type: "set_status", sessionId, status: "streaming" });

      const controller = new AbortController();
      abortRefs.current.set(sessionId, controller);

      try {
        for await (const event of streamSSE({
          url: `/v1/sessions/${sessionId}/prompt`,
          method: "POST",
          body: { prompt },
          signal: controller.signal,
        })) {
          dispatch({ type: "append_event", sessionId, event });
          const newStatus = statusFromEvent(event);
          if (newStatus && newStatus !== "streaming") {
            dispatch({ type: "set_status", sessionId, status: newStatus });
          }
        }
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
      abortRefs.current.get(sessionId)?.abort();
      abortRefs.current.get(`reconnect-${sessionId}`)?.abort();
      abortRefs.current.delete(sessionId);
      abortRefs.current.delete(`reconnect-${sessionId}`);

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

  return {
    sessions,
    activeSessionId,
    activeSession,
    createSession: createSessionAndActivate,
    switchSession,
    reconnectSession,
    sendPrompt,
    stopStreaming,
    destroySession: destroySessionById,
  };
}
