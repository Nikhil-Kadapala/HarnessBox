import { useCallback, useRef, useState } from "react";
import { createConversation as apiCreateConversation, listConversations, updateConversationHarness } from "@/lib/api";
import { SessionConnections } from "@/lib/sessions/connections";
import type { ConversationEntry, UniversalEvent } from "@/types";

type ConversationMetadata = Omit<ConversationEntry, "events" | "streaming" | "error">;

export function useConversationManager() {
  const [conversationsByWorkspace, setConversationsByWorkspace] = useState<Record<string, ConversationEntry[]>>({});
  const [activeByWorkspace, setActiveByWorkspace] = useState<Record<string, string>>({});
  const [closedByWorkspace, setClosedByWorkspace] = useState<Record<string, string[]>>({});
  const connections = useRef(new SessionConnections());
  const loadedWorkspaces = useRef(new Set<string>());

  const replaceWorkspace = useCallback((workspaceId: string, entries: ConversationEntry[]) => {
    setConversationsByWorkspace((current) => ({ ...current, [workspaceId]: entries }));
  }, []);

  const updateEntry = useCallback((workspaceId: string, conversationId: string, update: (entry: ConversationEntry) => ConversationEntry) => {
    setConversationsByWorkspace((current) => ({
      ...current,
      [workspaceId]: (current[workspaceId] ?? []).map((entry) => entry.conversation_id === conversationId ? update(entry) : entry),
    }));
  }, []);

  const appendEvent = useCallback((workspaceId: string, conversationId: string, event: UniversalEvent) => {
    updateEntry(workspaceId, conversationId, (entry) => {
      if (entry.events.some((item) => item.message.event_id === event.message.event_id)) return entry;
      return { ...entry, events: [...entry.events, event] };
    });
  }, [updateEntry]);

  const loadWorkspace = useCallback(async (workspaceId: string, defaultHarness: string) => {
    if (loadedWorkspaces.current.has(workspaceId)) return;
    loadedWorkspaces.current.add(workspaceId);
    try {
      let metadata: ConversationMetadata[] = await listConversations(workspaceId);
      if (metadata.length === 0) metadata = [await apiCreateConversation(workspaceId, defaultHarness)];
      replaceWorkspace(workspaceId, metadata.map((item) => ({ ...item, events: [], streaming: false, error: null })));
      setActiveByWorkspace((current) => ({ ...current, [workspaceId]: current[workspaceId] ?? metadata[0].conversation_id }));
      await Promise.all(metadata.map(async (conversation) => {
        const url = `/v1/workspaces/${encodeURIComponent(workspaceId)}/history?conversation_id=${encodeURIComponent(conversation.conversation_id)}&limit=10000`;
        try {
          const stream = connections.current.streamEvents({ key: `history-${conversation.conversation_id}`, url, method: "GET" });
          const events: UniversalEvent[] = [];
          for await (const event of stream) events.push(event);
          setConversationsByWorkspace((current) => ({
            ...current,
            [workspaceId]: (current[workspaceId] ?? []).map((entry) => entry.conversation_id === conversation.conversation_id ? { ...entry, events } : entry),
          }));
        } catch {
          // Empty conversations have no event history yet.
        }
      }));
    } catch (error) {
      loadedWorkspaces.current.delete(workspaceId);
      throw error;
    }
  }, [replaceWorkspace]);

  const openConversation = useCallback((workspaceId: string, conversationId: string) => {
    setClosedByWorkspace((current) => ({
      ...current,
      [workspaceId]: (current[workspaceId] ?? []).filter((id) => id !== conversationId),
    }));
    setActiveByWorkspace((current) => ({ ...current, [workspaceId]: conversationId }));
  }, []);

  const closeConversation = useCallback((workspaceId: string, conversationId: string) => {
    const conversations = conversationsByWorkspace[workspaceId] ?? [];
    const visible = conversations.filter((entry) =>
      entry.conversation_id !== conversationId && !(closedByWorkspace[workspaceId] ?? []).includes(entry.conversation_id),
    );
    if (visible.length === 0) return;
    setClosedByWorkspace((current) => ({
      ...current,
      [workspaceId]: [...(current[workspaceId] ?? []), conversationId],
    }));
    if (activeByWorkspace[workspaceId] === conversationId) {
      setActiveByWorkspace((current) => ({ ...current, [workspaceId]: visible[0].conversation_id }));
    }
  }, [activeByWorkspace, closedByWorkspace, conversationsByWorkspace]);

  const createNewConversation = useCallback(async (workspaceId: string, harness: string) => {
    const metadata = await apiCreateConversation(workspaceId, harness);
    const entry: ConversationEntry = { ...metadata, events: [], streaming: false, error: null };
    setConversationsByWorkspace((current) => ({ ...current, [workspaceId]: [entry, ...(current[workspaceId] ?? [])] }));
    setActiveByWorkspace((current) => ({ ...current, [workspaceId]: entry.conversation_id }));
    return entry.conversation_id;
  }, []);

  const selectHarness = useCallback(async (workspaceId: string, conversationId: string, harness: string) => {
    await updateConversationHarness(workspaceId, conversationId, harness);
    updateEntry(workspaceId, conversationId, (entry) => ({ ...entry, agent_type: harness }));
  }, [updateEntry]);

  const sendPrompt = useCallback(async (workspaceId: string, conversationId: string, prompt: string) => {
    const conversation = (conversationsByWorkspace[workspaceId] ?? []).find((item) => item.conversation_id === conversationId);
    if (!conversation) return;
    updateEntry(workspaceId, conversationId, (entry) => ({
      ...entry,
      streaming: true,
      error: null,
      title: entry.title ?? prompt.trim().slice(0, 50),
    }));
    try {
      const stream = connections.current.streamEvents({
        key: `prompt-${conversationId}`,
        url: `/v1/workspaces/${encodeURIComponent(workspaceId)}/prompt`,
        method: "POST",
        body: { prompt, harness: conversation.agent_type, conversation_id: conversationId },
      });
      for await (const event of stream) appendEvent(workspaceId, conversationId, event);
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        updateEntry(workspaceId, conversationId, (entry) => ({ ...entry, error: error instanceof Error ? error.message : "Conversation stream failed." }));
      }
    } finally {
      updateEntry(workspaceId, conversationId, (entry) => ({ ...entry, streaming: false }));
    }
  }, [appendEvent, conversationsByWorkspace, updateEntry]);

  const stopPrompt = useCallback((conversationId: string) => {
    connections.current.abort(`prompt-${conversationId}`);
  }, []);

  return {
    conversationsByWorkspace,
    activeByWorkspace,
    closedByWorkspace,
    loadWorkspace,
    openConversation,
    closeConversation,
    createNewConversation,
    selectHarness,
    sendPrompt,
    stopPrompt,
  };
}

export type ConversationManager = ReturnType<typeof useConversationManager>;
