import { useCallback } from "react";
import { sendPermission } from "@/lib/api";
import { EventFeed } from "@/components/event-feed";
import { MotionChatInterface } from "@/components/motion-chat-interface";
import { SessionCreatingView } from "./session-creating-view";
import { getLatestSessionContextStats, getLatestSessionCostStats } from "@/lib/session-context";
import type { SessionEntry } from "@/types";

interface SessionViewProps {
  session: SessionEntry;
  onSendPrompt: (prompt: string) => void;
  onStop: () => void;
}

export function SessionView({ session, onSendPrompt, onStop }: SessionViewProps) {
  const isStreaming = session.status === "streaming";
  const isCreating = session.status === "creating";
  const isEnded = session.status === "ended" || session.status === "failed";
  const isError = session.status === "error";
  const contextStats = getLatestSessionContextStats(session.events);
  const costStats = getLatestSessionCostStats(session.events);

  const handlePermissionRespond = useCallback(
    (requestId: string, behavior: "allow" | "deny") => {
      sendPermission(session.id, requestId, behavior).catch(() => {});
    },
    [session.id],
  );

  if (isCreating) {
    return <SessionCreatingView session={session} />;
  }

  return (
    <div className="flex flex-1 flex-col min-h-0">
      {session.error && (
        <div className="mx-4 mt-2 rounded border border-destructive/50 bg-destructive/10 px-3 py-2 shrink-0">
          <span className="text-xs text-destructive">{session.error}</span>
        </div>
      )}

      <EventFeed
        events={session.events}
        sessionId={session.id}
        isStreaming={isStreaming}
        onPermissionRespond={handlePermissionRespond}
      />

      <div className="shrink-0">
        <MotionChatInterface
          disabled={isEnded || isError}
          isStreaming={isStreaming}
          contextStats={contextStats}
          costStats={costStats}
          onSubmit={onSendPrompt}
          onStop={onStop}
        />
      </div>
    </div>
  );
}
