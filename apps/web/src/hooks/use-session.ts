import { useCallback, useRef, useState } from "react";
import { streamSSE } from "@/lib/sse";
import type { SessionConfig, SessionState, UniversalEvent } from "@/types";

export function useSession() {
  const [state, setState] = useState<SessionState>("idle");
  const [events, setEvents] = useState<UniversalEvent[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const createSession = useCallback(async (config: SessionConfig) => {
    setError(null);
    setEvents([]);
    setSessionId(null);
    setState("creating");

    try {
      const res = await fetch("/api/v1/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: config.provider,
          harness: config.harness,
          env_vars: config.env_vars,
          skip_permissions: config.skip_permissions,
        }),
      });

      if (!res.ok) {
        if (res.status === 502 || res.status === 503) {
          throw new Error(
            "Cannot reach the HarnessBox server. Start it with: cd sdk && uv run uvicorn harnessbox.server:create_app --factory --port 8000",
          );
        }
        let message = `Failed to create session (${res.status})`;
        try {
          const body = await res.json();
          if (body.error) message = body.error;
        } catch {
          const text = await res.text().catch(() => "");
          if (text) message = text;
        }
        throw new Error(message);
      }

      let session: { session_id: string };
      try {
        session = await res.json();
      } catch {
        throw new Error("Invalid response from server — is the backend running?");
      }

      setSessionId(session.session_id);
      setState("idle");
      return session.session_id;
    } catch (err) {
      let message = err instanceof Error ? err.message : "Unknown error";
      if (err instanceof TypeError && message === "Failed to fetch") {
        message =
          "Cannot reach the HarnessBox server. Start it with: cd sdk && uv run uvicorn harnessbox.server:create_app --factory --port 8000";
      }
      setError(message);
      setState("error");
      return null;
    }
  }, []);

  const sendPrompt = useCallback(
    async (prompt: string) => {
      if (!sessionId) return;
      setError(null);
      setState("streaming");

      try {
        const controller = new AbortController();
        abortRef.current = controller;

        for await (const event of streamSSE(
          `/api/v1/sessions/${sessionId}/prompt`,
          { prompt },
          controller.signal,
        )) {
          setEvents((prev) => [...prev, event]);
        }

        setState("idle");
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          setState("idle");
          return;
        }
        const message = err instanceof Error ? err.message : "Unknown error";
        setError(message);
        setState("error");
      } finally {
        abortRef.current = null;
      }
    },
    [sessionId],
  );

  const stop = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setEvents([]);
    setSessionId(null);
    setError(null);
    setState("idle");
  }, []);

  const isStreaming = state === "streaming";
  const isCreating = state === "creating";
  const hasSession = sessionId !== null;

  return {
    state,
    events,
    sessionId,
    error,
    isStreaming,
    isCreating,
    hasSession,
    createSession,
    sendPrompt,
    stop,
    reset,
  };
}
