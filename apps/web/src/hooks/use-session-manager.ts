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
import { workspaceIdOf, workspaceStateOf } from "@/types";

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
          const state = workspaceStateOf(s);
          const id = workspaceIdOf(s);
          if (state !== "dead" && state !== "ended") {
            dispatch({
              type: "add_session",
              entry: {
                id,
                harness: s.harness,
                status: (state as SessionStatus) || "active",
                runtimeState: state,
                createdAt: s.created_at,
                events: [],
                error: null,
                workspaceName: s.workspace_name,
                branch: s.branch,
                baseBranch: s.base_branch,
                remote: s.remote,
              },
            });
            activeSessions.push(id);
          }
        }
        if (serverSessions.length > 0) {
          const active = serverSessions.find((s) => workspaceStateOf(s) === "active");
          if (active) setActiveSessionId(workspaceIdOf(active));
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
    async (config: CreateSessionRequest): Promise<string> => {
      const conns = connectionsRef.current;
      // Temporary key until the server returns the minted workspace_id.
      const pendingKey = `pending-${crypto.randomUUID()}`;
      const signal = conns.start(`create-${pendingKey}`);

      try {
        const {
          workspace_id: _wid,
          session_id: _sid,
          project_id: _pid,
          model: _model,
          ...createBody
        } = config;
        const res = await apiCreateSession(createBody, signal);
        const sessionId = workspaceIdOf(res);
        if (!sessionId) {
          throw new Error("Server did not return a workspace_id");
        }

        if (conns.isDestroyed(sessionId)) {
          conns.cleanup(`create-${pendingKey}`);
          return sessionId;
        }

        const entry: SessionEntry = {
          id: sessionId,
          harness: "claude-code",
          status: "creating",
          runtimeState: workspaceStateOf(res) || "creating",
          createdAt: res.created_at || new Date().toISOString(),
          events: [],
          error: null,
          workspaceName: res.workspace_name || config.git?.clone_dir_name || config.workspace?.clone_dir_name,
          branch: res.branch || config.git?.branch || config.workspace?.branch,
          remote: res.remote || config.git?.repo_url || config.workspace?.remote,
        };
        dispatch({ type: "add_session", entry });
        setActiveSessionId(sessionId);

        conns.cleanup(`create-${pendingKey}`);
        dispatch({
          type: "update_metadata",
          sessionId,
          metadata: {
            workspaceName: res.workspace_name,
            branch: res.branch,
            baseBranch: res.base_branch,
            remote: res.remote,
            runtimeState: workspaceStateOf(res),
          },
        });

        reconnectSession(sessionId);
        return sessionId;
      } catch (err) {
        conns.cleanup(`create-${pendingKey}`);
        if (err instanceof DOMException && err.name === "AbortError") {
          throw err;
        }
        throw err instanceof Error ? err : new Error("Failed to create session");
      }
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
