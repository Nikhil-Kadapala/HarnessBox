import { useCallback } from "react";
import { useParams, useNavigate } from "@tanstack/react-router";
import { SessionView } from "@/components/session/session-view";
import { useSharedSessionManager } from "@/hooks/use-session-manager";

export function SessionPage() {
  const { sessionId } = useParams({ from: "/session/$sessionId" });
  const manager = useSharedSessionManager();
  const navigate = useNavigate();

  const session = manager.sessions.get(sessionId) ?? null;

  const handleSendPrompt = useCallback(
    (prompt: string, harness?: string) => {
      manager.sendPrompt(sessionId, prompt, harness ?? session?.harness ?? "claude-code");
    },
    [manager, sessionId, session],
  );

  const handleStop = useCallback(() => {
    manager.stopStreaming(sessionId);
  }, [manager, sessionId]);

  if (!session) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="text-center space-y-2">
          <p className="text-sm text-muted-foreground">Session not found</p>
          <button
            onClick={() => navigate({ to: "/" })}
            className="text-sm text-accent hover:underline"
          >
            Back to dashboard
          </button>
        </div>
      </div>
    );
  }

  return (
    <SessionView
      session={session}
      onSendPrompt={handleSendPrompt}
      onStop={handleStop}
    />
  );
}
