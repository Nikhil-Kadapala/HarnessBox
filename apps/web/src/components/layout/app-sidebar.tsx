import { memo } from "react";
import { Plus, Settings, Terminal, Trash2, LayoutGrid } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import type { SessionEntry } from "@/types";

interface AppSidebarProps {
  sessions: Map<string, SessionEntry>;
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onOpenSettings: () => void;
  onOpenBoard?: () => void;
  onDestroySession: (id: string) => void;
}

const statusColors: Record<string, string> = {
  creating: "bg-warning",
  active: "bg-accent",
  streaming: "bg-accent animate-pulse",
  paused: "bg-muted-foreground/50",
  ended: "bg-muted-foreground",
  error: "bg-destructive",
};

const SessionItem = memo(function SessionItem({
  entry,
  isActive,
  onSelect,
  onDestroy,
}: {
  entry: SessionEntry;
  isActive: boolean;
  onSelect: () => void;
  onDestroy: () => void;
}) {
  return (
    <SidebarMenuItem>
      <SidebarMenuButton
        isActive={isActive}
        onClick={onSelect}
        className="group/item justify-between"
      >
        <div className="flex items-center gap-2 min-w-0">
          <div className={`h-2 w-2 shrink-0 rounded-full ${statusColors[entry.status] ?? "bg-muted"}`} />
          <span className="truncate text-xs">
            {entry.workspaceName ?? entry.id.slice(0, 8)}
          </span>
          <span className="truncate text-[10px] text-muted-foreground">
            {entry.harness}
          </span>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="h-5 w-5 p-0 opacity-0 group-hover/item:opacity-100 shrink-0"
          onClick={(e) => {
            e.stopPropagation();
            onDestroy();
          }}
        >
          <Trash2 className="h-3 w-3 text-muted-foreground hover:text-destructive" />
        </Button>
      </SidebarMenuButton>
    </SidebarMenuItem>
  );
});

export function AppSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onOpenSettings,
  onOpenBoard,
  onDestroySession,
}: AppSidebarProps) {
  const sortedSessions = [...sessions.values()].sort((a, b) => {
    const statusOrder: Record<string, number> = {
      streaming: 0,
      active: 1,
      creating: 2,
      error: 3,
      ended: 4,
    };
    const aOrder = statusOrder[a.status] ?? 5;
    const bOrder = statusOrder[b.status] ?? 5;
    if (aOrder !== bOrder) return aOrder - bOrder;
    return b.createdAt.localeCompare(a.createdAt);
  });

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader className="h-14 justify-center border-b px-3">
        <div className="flex items-center gap-2">
          <Terminal className="h-4 w-4 text-accent" />
          <span className="font-semibold text-sm tracking-tight group-data-[collapsible=icon]:hidden">
            HarnessBox
          </span>
          <Badge
            variant="outline"
            className="text-[9px] font-mono group-data-[collapsible=icon]:hidden"
          >
            console
          </Badge>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <div className="flex items-center justify-between px-2">
            <SidebarGroupLabel>Sessions</SidebarGroupLabel>
            <Button
              variant="ghost"
              size="sm"
              className="h-6 w-6 p-0"
              onClick={onNewSession}
            >
              <Plus className="h-3.5 w-3.5" />
            </Button>
          </div>
          <SidebarMenu>
            {sortedSessions.length === 0 && (
              <p className="px-3 py-4 text-xs text-muted-foreground">
                No sessions yet
              </p>
            )}
            {sortedSessions.map((entry) => (
              <SessionItem
                key={entry.id}
                entry={entry}
                isActive={entry.id === activeSessionId}
                onSelect={() => onSelectSession(entry.id)}
                onDestroy={() => onDestroySession(entry.id)}
              />
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t p-2">
        <SidebarMenu>
          {onOpenBoard && (
            <SidebarMenuItem>
              <SidebarMenuButton onClick={onOpenBoard}>
                <LayoutGrid className="h-4 w-4" />
                <span>Board View</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          )}
          <SidebarMenuItem>
            <SidebarMenuButton onClick={onOpenSettings}>
              <Settings className="h-4 w-4" />
              <span>Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>
    </Sidebar>
  );
}
