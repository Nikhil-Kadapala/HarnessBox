import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { SessionView } from "@/components/session/session-view";
import { ConversationTabs } from "@/components/session/conversation-tabs";
import { useSharedSessionManager } from "@/hooks/use-session-manager";
import { useConversationManager } from "@/hooks/use-conversation-manager";
import { useDiscovery } from "@/hooks/use-discovery";
import { getProject } from "@/lib/api";

export function SessionPage() {
  const { sessionId: workspaceId } = useParams({ from: "/session/$sessionId" });
  const manager = useSharedSessionManager();
  const conversations = useConversationManager();
  const { harnesses } = useDiscovery();
  const navigate = useNavigate();
  const workspace = manager.sessions.get(workspaceId) ?? null;
  const allWorkspaceConversations = conversations.conversationsByWorkspace[workspaceId] ?? [];
  const closedIds = conversations.closedByWorkspace[workspaceId] ?? [];
  const workspaceConversations = allWorkspaceConversations.filter((item) => !closedIds.includes(item.conversation_id));
  const activeId = conversations.activeByWorkspace[workspaceId];
  const activeConversation = workspaceConversations.find((item) => item.conversation_id === activeId) ?? null;
  const [defaultHarness, setDefaultHarness] = useState(workspace?.harness ?? "claude-code");
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    if (!workspace) return;
    let cancelled = false;
    const load = async () => {
      try {
        const project = workspace.projectId ? await getProject(workspace.projectId) : null;
        const harness = project?.workspace_settings.default_harness ?? workspace.harness ?? "claude-code";
        if (cancelled) return;
        setDefaultHarness(harness);
        await conversations.loadWorkspace(workspaceId, harness);
      } catch (error) {
        if (!cancelled) setLoadError(error instanceof Error ? error.message : "Could not load conversations.");
      }
    };
    void load();
    return () => { cancelled = true; };
  }, [workspaceId, workspace?.projectId, workspace?.harness, conversations.loadWorkspace]);

  const handleSendPrompt = useCallback((prompt: string) => {
    if (activeConversation) void conversations.sendPrompt(workspaceId, activeConversation.conversation_id, prompt);
  }, [activeConversation, conversations.sendPrompt, workspaceId]);

  const handleCreateConversation = useCallback(() => {
    void conversations.createNewConversation(workspaceId, defaultHarness).catch((error) => {
      setLoadError(error instanceof Error ? error.message : "Could not start a new session.");
    });
  }, [conversations.createNewConversation, defaultHarness, workspaceId]);

  if (!workspace) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="space-y-2 text-center">
          <p className="text-sm text-muted-foreground">Workspace not found</p>
          <button onClick={() => navigate({ to: "/" })} className="text-sm text-accent hover:underline">Back to dashboard</button>
        </div>
      </div>
    );
  }

  if (!activeConversation) {
    return <div className="flex flex-1 items-center justify-center gap-2 text-sm text-muted-foreground">{loadError ? <span role="alert">{loadError}</span> : <><Loader2 className="h-4 w-4 animate-spin" /> Loading sessions…</>}</div>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col" role="tabpanel" id={`conversation-panel-${activeConversation.conversation_id}`} aria-labelledby={`conversation-tab-${activeConversation.conversation_id}`}>
      <ConversationTabs
        conversations={workspaceConversations}
        activeId={activeConversation.conversation_id}
        onSelect={(conversationId) => conversations.openConversation(workspaceId, conversationId)}
        onClose={(conversationId) => conversations.closeConversation(workspaceId, conversationId)}
        onCreate={handleCreateConversation}
      />
      {loadError && <p role="alert" className="border-b bg-destructive/10 px-4 py-2 text-sm text-destructive">{loadError}</p>}
      <SessionView
        session={workspace}
        conversation={activeConversation}
        harnesses={harnesses}
        onSelectHarness={(harness) => conversations.selectHarness(workspaceId, activeConversation.conversation_id, harness)}
        onSendPrompt={handleSendPrompt}
        onStop={() => conversations.stopPrompt(activeConversation.conversation_id)}
      />
    </div>
  );
}
