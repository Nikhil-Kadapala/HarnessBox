import { useCallback } from "react";
import { sendPermission } from "@/lib/api";
import { EventFeed } from "@/components/event-feed";
import { PromptInput } from "@/components/prompt-input";
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

  const handlePermissionRespond = useCallback(
    (requestId: string, behavior: "allow" | "deny") => {
      sendPermission(session.id, requestId, behavior).catch(() => {});
    },
    [session.id],
  );

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
        onPermissionRespond={handlePermissionRespond}
      />

      <div className="shrink-0">
        <PromptInput
          disabled={isCreating || isEnded || isError}
          isStreaming={isStreaming}
          onSubmit={onSendPrompt}
          onStop={onStop}
        />
      </div>
    </div>
  );
}
