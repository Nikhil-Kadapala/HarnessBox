import { useState, useEffect, useCallback, useMemo } from "react";
import {
  listSessions,
  transitionSession,
  pauseSession,
  resumeSession,
  stopSession,
  createPR,
} from "@/lib/api";
import {
  transformSessionResponseToCard,
  searchSessions,
} from "@/lib/sessions/utils";
import type { SessionCard } from "@/types";

export function useSessionBoard() {
  const [sessions, setSessions] = useState<SessionCard[]>([]);
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadBoard = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await listSessions();
      setSessions(data.map(transformSessionResponseToCard));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions.");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    loadBoard();
  }, [loadBoard]);

  const withOptimistic = useCallback(
    async (sessionId: string, optimisticStatus: string, action: () => Promise<void>) => {
      const prev = sessions;
      setSessions((cur) =>
        cur.map((s) => (s.id === sessionId ? { ...s, status: optimisticStatus } : s)),
      );
      try {
        await action();
      } catch (err) {
        setSessions(prev);
        setError(err instanceof Error ? err.message : "Action failed.");
      }
    },
    [sessions],
  );

  const handleTransition = useCallback(
    (sessionId: string, targetState: string) =>
      withOptimistic(sessionId, targetState, () => transitionSession(sessionId, targetState).then(() => {})),
    [withOptimistic],
  );

  const handlePause = useCallback(
    (sessionId: string) =>
      withOptimistic(sessionId, "paused", () => pauseSession(sessionId).then(() => {})),
    [withOptimistic],
  );

  const handleResume = useCallback(
    (sessionId: string) =>
      withOptimistic(sessionId, "active", () => resumeSession(sessionId).then(() => {})),
    [withOptimistic],
  );

  const handleStop = useCallback(
    (sessionId: string) =>
      withOptimistic(sessionId, "failed", () => stopSession(sessionId)),
    [withOptimistic],
  );

  const handleCreatePR = useCallback(
    async (sessionId: string) => {
      const session = sessions.find((s) => s.id === sessionId);
      const title = session?.title ?? "Agent changes";
      const prev = sessions;
      setSessions((cur) =>
        cur.map((s) => (s.id === sessionId ? { ...s, status: "in_review" } : s)),
      );
      try {
        const updatedRaw = await createPR(sessionId, title);
        const updated = transformSessionResponseToCard(updatedRaw);
        setSessions((cur) =>
          cur.map((s) => (s.id === sessionId ? { ...s, ...updated } : s)),
        );
      } catch (err) {
        setSessions(prev);
        setError(err instanceof Error ? err.message : "PR creation failed.");
      }
    },
    [sessions],
  );

  const visible = useMemo(() => searchSessions(sessions, query), [sessions, query]);
  const showLoading = isLoading && sessions.length === 0;

  return {
    sessions,
    query,
    setQuery,
    isLoading,
    error,
    setError,
    loadBoard,
    handleTransition,
    handlePause,
    handleResume,
    handleStop,
    handleCreatePR,
    visible,
    showLoading,
  };
}
