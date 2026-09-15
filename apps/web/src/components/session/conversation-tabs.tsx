import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ConversationEntry } from "@/types";

interface ConversationTabsProps {
  conversations: ConversationEntry[];
  activeId: string;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onCreate: () => void;
}

export function ConversationTabs({ conversations, activeId, onSelect, onClose, onCreate }: ConversationTabsProps) {
  return (
    <div className="flex h-11 shrink-0 items-end gap-1 overflow-x-auto border-b bg-muted/20 px-3" role="tablist" aria-label="Workspace conversations">
      {conversations.map((conversation) => {
        const active = conversation.conversation_id === activeId;
        return (
          <div key={conversation.conversation_id} className={`group relative flex h-9 max-w-56 shrink-0 items-center rounded-t-md border border-b-0 ${active ? "border-border bg-background" : "border-transparent hover:bg-muted/60"}`}>
          <button
            id={`conversation-tab-${conversation.conversation_id}`}
            type="button"
            role="tab"
            aria-selected={active}
            aria-controls={`conversation-panel-${conversation.conversation_id}`}
            onClick={() => onSelect(conversation.conversation_id)}
            className={`flex min-w-0 h-full items-center gap-2 px-3 pr-1 text-sm transition-colors ${active ? "text-foreground" : "text-muted-foreground hover:text-foreground"}`}
          >
            <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${conversation.streaming ? "animate-pulse bg-blue-500" : "bg-muted-foreground/40"}`} aria-hidden="true" />
            <span className="truncate">{conversation.title || "New session"}</span>
          </button>
          <button type="button" onClick={() => onClose(conversation.conversation_id)} className="mr-1 rounded p-1 text-muted-foreground opacity-0 hover:bg-muted hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100" aria-label={`Close ${conversation.title || "New session"} tab`} title="Close tab">
            <X className="h-3.5 w-3.5" />
          </button>
          </div>
        );
      })}
      <Button type="button" size="icon" variant="ghost" className="mb-1 h-7 w-7 shrink-0" onClick={onCreate} aria-label="Start a new session" title="Start a new session">
        <Plus className="h-4 w-4" />
      </Button>
    </div>
  );
}
