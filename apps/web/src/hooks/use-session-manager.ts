import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  createSession as apiCreateSession,
  destroySession as apiDestroySession,
  listSessions,
} from "@/lib/api";
import { sessionsReducer, statusFromEvent } from "@/lib/sessions/reducer";
import { SessionConnections } from "@/lib/sessions/connections";
import type {
  CreateSessionRequest,
  SessionEntry,
  SessionStatus,
  UniversalEvent,
} from "@/types";

export function useSessionManager() {
  const [sessions, dispatch] = useReducer(sessionsReducer, new Map<string, SessionEntry>());
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const connectionsRef = useRef(new SessionConnections());
  const polledRef = useRef(false);
  const promptGenRef = useRef(0);

  const activeSession = activeSessionId ? sessions.get(activeSessionId) ?? null : null;

  useEffect(() => {
    if (polledRef.current) return;
    polledRef.current = true;

    listSessions()
      .then((serverSessions) => {
        const activeSessions: string[] = [];
        for (const s of serverSessions) {
          if (s.runtime_state !== "dead" && s.runtime_state !== "ended") {
            dispatch({
              type: "add_session",
              entry: {
                id: s.session_id,
                harness: s.harness,
                status: (s.runtime_state as SessionStatus) || "active",
                runtimeState: s.runtime_state,
                createdAt: s.created_at,
                events: [],
                error: null,
                workspaceName: s.workspace_name,
                branch: s.branch,
                baseBranch: s.base_branch,
                remote: s.remote,
              },
            });
            activeSessions.push(s.session_id);
          }
        }
        if (serverSessions.length > 0) {
          const active = serverSessions.find((s) => s.runtime_state === "active");
          if (active) setActiveSessionId(active.session_id);
        }

        // Replay events for all active sessions.
        // Try live /events first (ring buffer + subscription); fall back to
        // /history (SQLite storage) if the sandbox isn't connected yet.
        const conns = connectionsRef.current;
        for (const sessionId of activeSessions) {
          (async () => {
            try {
              const stream = conns.streamEvents({
                key: `reconnect-${sessionId}`,
                url: `/v1/workspaces/${sessionId}/events`,
                method: "GET",
              });
              for await (const event of stream) {
                dispatch({ type: "append_event", sessionId, event });
                const newStatus = statusFromEvent(event);
                if (newStatus) {
                  dispatch({ type: "set_status", sessionId, status: newStatus });
                }
              }
            } catch {
              // Live stream unavailable — load from storage history
              try {
                const historyStream = conns.streamEvents({
                  key: `history-${sessionId}`,
                  url: `/v1/workspaces/${sessionId}/history`,
                  method: "GET",
                });
                for await (const event of historyStream) {
                  dispatch({ type: "append_event", sessionId, event });
                }
              } catch {
                // No events available
              }
            }
          })();
        }
      })
      .catch(() => {});
  }, []);

  const consumeStream = useCallback(
    async (sessionId: string, stream: AsyncGenerator<UniversalEvent>) => {
      for await (const event of stream) {
        dispatch({ type: "append_event", sessionId, event });
        const newStatus = statusFromEvent(event);
        if (newStatus) {
          dispatch({ type: "set_status", sessionId, status: newStatus });
        }
      }
    },
    [],
  );

  const reconnectSession = useCallback(
    async (sessionId: string) => {
      const entry = sessions.get(sessionId);
      const lastSeq = entry?.events.at(-1)?.message.sequence;
      const conns = connectionsRef.current;

      try {
        const stream = conns.streamEvents({
          key: `reconnect-${sessionId}`,
          url: `/v1/workspaces/${sessionId}/events`,
          method: "GET",
          lastEventId: lastSeq,
        });
        await consumeStream(sessionId, stream);
      } catch (err) {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          // Reconnection failed — session may have ended
        }
      }
    },
    [sessions, consumeStream],
  );

  const createSessionOptimistic = useCallback(
    (config: CreateSessionRequest) => {
      const sessionId = config.session_id || crypto.randomUUID();
      const conns = connectionsRef.current;

      const entry: SessionEntry = {
        id: sessionId,
        harness: "claude-code",
        status: "creating",
        runtimeState: "creating",
        createdAt: new Date().toISOString(),
        events: [],
        error: null,
        workspaceName: config.workspace?.clone_dir_name,
        branch: config.workspace?.branch,
        remote: config.workspace?.remote,
      };
      dispatch({ type: "add_session", entry });
      setActiveSessionId(sessionId);

      const signal = conns.start(`create-${sessionId}`);

      apiCreateSession({ ...config, session_id: sessionId }, signal)
        .then((res) => {
          conns.cleanup(`create-${sessionId}`);

          if (conns.isDestroyed(sessionId)) return;

          dispatch({
            type: "update_metadata",
            sessionId,
            metadata: {
              workspaceName: res.workspace_name,
              branch: res.branch,
              baseBranch: res.base_branch,
              remote: res.remote,
              runtimeState: res.runtime_state,
            },
          });
          dispatch({ type: "set_status", sessionId, status: "active" });

          reconnectSession(sessionId);
        })
        .catch((err) => {
          conns.cleanup(`create-${sessionId}`);
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
    async (sessionId: string, prompt: string, harness: string) => {
      const gen = ++promptGenRef.current;
      dispatch({ type: "set_status", sessionId, status: "streaming" });
      const conns = connectionsRef.current;

      // Abort any active reconnect stream to prevent duplicate event delivery.
      // The reconnect subscribes to the event buffer which broadcasts the same
      // events that the prompt SSE response yields directly.
      conns.abort(`reconnect-${sessionId}`);

      try {
        const stream = conns.streamEvents({
          key: sessionId,
          url: `/v1/workspaces/${sessionId}/prompt`,
          method: "POST",
          body: { prompt, harness },
        });

        for await (const event of stream) {
          dispatch({ type: "append_event", sessionId, event });
          if (event.type === "error" && event.message.error_message) {
            dispatch({ type: "set_error", sessionId, error: event.message.error_message });
            continue;
          }
          const newStatus = statusFromEvent(event);
          if (newStatus && newStatus !== "streaming") {
            dispatch({ type: "set_status", sessionId, status: newStatus });
          }
        }
        dispatch({ type: "set_status", sessionId, status: "active" });
        // Resubscribe to live events for inter-turn activity
        reconnectSession(sessionId);
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          // Only reset to "active" if no newer prompt has taken over
          if (gen === promptGenRef.current) {
            dispatch({ type: "set_status", sessionId, status: "active" });
          }
          return;
        }
        const message = err instanceof Error ? err.message : "Stream error";
        dispatch({ type: "set_error", sessionId, error: message });
      }
    },
    [reconnectSession],
  );

  const stopStreaming = useCallback((sessionId: string) => {
    connectionsRef.current.abort(sessionId);
  }, []);

  const destroySessionById = useCallback(
    async (sessionId: string) => {
      const conns = connectionsRef.current;
      conns.markDestroyed(sessionId);
      conns.abortAllForSession(sessionId);

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
    createSession: createSessionOptimistic,
    switchSession,
    reconnectSession,
    sendPrompt,
    stopStreaming,
    destroySession: destroySessionById,
  };
}

export type SessionManager = ReturnType<typeof useSessionManager>;

const SessionManagerContext = createContext<SessionManager | null>(null);

export function SessionManagerProvider({
  manager,
  children,
}: {
  manager: SessionManager;
  children: ReactNode;
}) {
  return createElement(SessionManagerContext.Provider, { value: manager }, children);
}

export function useSharedSessionManager(): SessionManager {
  const manager = useContext(SessionManagerContext);
  if (!manager) {
    throw new Error("useSharedSessionManager must be used inside SessionManagerProvider");
  }
  return manager;
}
