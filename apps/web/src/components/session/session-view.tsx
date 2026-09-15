import { useCallback, useState } from "react";
import { sendPermission } from "@/lib/api";
import { EventFeed } from "@/components/event-feed";
import { MotionChatInterface } from "@/components/motion-chat-interface";
import { SessionCreatingView } from "./session-creating-view";
import { getLatestSessionContextStats, getLatestSessionCostStats } from "@/lib/session-context";
import type { SessionEntry } from "@/types";
import type { ConversationEntry, HarnessInfo } from "@/types";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

interface SessionViewProps {
  session: SessionEntry;
  conversation: ConversationEntry;
  harnesses: HarnessInfo[];
  onSelectHarness: (harness: string) => Promise<void>;
  onSendPrompt: (prompt: string) => void;
  onStop: () => void;
}

export function SessionView({ session, conversation, harnesses, onSelectHarness, onSendPrompt, onStop }: SessionViewProps) {
  const [harnessError, setHarnessError] = useState<string | null>(null);
  const isStreaming = conversation.streaming;
  const isCreating = session.status === "creating";
  const isEnded = session.status === "ended" || session.status === "failed";
  const isError = session.status === "error";
  const contextStats = getLatestSessionContextStats(conversation.events);
  const costStats = getLatestSessionCostStats(conversation.events);

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

      {conversation.error && <div role="alert" className="mx-4 mt-2 rounded border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive">{conversation.error}</div>}
      {harnessError && <div role="alert" className="mx-4 mt-2 rounded border border-destructive/50 bg-destructive/10 px-3 py-2 text-xs text-destructive">{harnessError}</div>}
      {conversation.events.length === 0 && !conversation.streaming && !conversation.title && (
        <div className="flex shrink-0 items-center gap-2 border-b px-4 py-2 text-sm">
          <span className="text-muted-foreground">Start this session with</span>
          <Select value={conversation.agent_type} onValueChange={(value) => {
            if (!value) return;
            setHarnessError(null);
            void onSelectHarness(value).catch((error) => setHarnessError(error instanceof Error ? error.message : "Could not change harness."));
          }}>
            <SelectTrigger className="h-8 w-44"><SelectValue /></SelectTrigger>
            <SelectContent>{harnesses.map((harness) => <SelectItem key={harness.name} value={harness.name}>{harness.name}</SelectItem>)}</SelectContent>
          </Select>
          <span className="text-xs text-muted-foreground">You can change this until the first prompt.</span>
        </div>
      )}
      <EventFeed
        events={conversation.events}
        sessionId={session.id}
        isStreaming={isStreaming}
        onPermissionRespond={handlePermissionRespond}
        onRetryPrompt={onSendPrompt}
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
