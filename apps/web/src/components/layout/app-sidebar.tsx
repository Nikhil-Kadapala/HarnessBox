import { memo, useMemo, useState } from "react";
import { GitBranch, Plus, Settings, Trash2, LayoutGrid, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
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
  SidebarMenuSub,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import { AddRepoDialog } from "@/components/layout/add-repo-dialog";
import { getStoredValue } from "@/lib/storage";
import type { DetectedWorkspace, SessionEntry } from "@/types";

interface AppSidebarProps {
  sessions: Map<string, SessionEntry>;
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: (repoUrl?: string) => void;
  onOpenSettings: () => void;
  onOpenBoard?: () => void;
  onDestroySession: (id: string) => void;
}

const statusColors: Record<string, string> = {
  backlog: "bg-muted-foreground/30",
  creating: "bg-warning",
  starting: "bg-warning",
  active: "bg-accent",
  streaming: "bg-accent animate-pulse",
  paused: "bg-muted-foreground/50",
  in_review: "bg-warning",
  ending: "bg-muted-foreground/50",
  merged: "bg-accent",
  failed: "bg-destructive",
  archived: "bg-muted-foreground",
  ended: "bg-muted-foreground",
  error: "bg-destructive",
};

function extractRepoName(remote?: string): string {
  if (!remote) return "Other";
  const cleaned = remote.replace(/\.git$/, "");
  const parts = cleaned.split("/");
  return parts.length >= 2 ? parts[parts.length - 1] : cleaned;
}

interface RepoGroup {
  name: string;
  remote: string | undefined;
  sessions: SessionEntry[];
}

function groupByRepo(sessions: SessionEntry[]): RepoGroup[] {
  const groups = new Map<string, { remote: string | undefined; sessions: SessionEntry[] }>();

  // Include the detected repo from settings even if no sessions exist for it
  const detectedRepo = getStoredValue<DetectedWorkspace | null>("repository", null);
  if (detectedRepo?.remote) {
    const name = extractRepoName(detectedRepo.remote);
    groups.set(name, { remote: detectedRepo.remote, sessions: [] });
  }

  for (const s of sessions) {
    const repo = extractRepoName(s.remote);
    if (!groups.has(repo)) groups.set(repo, { remote: s.remote, sessions: [] });
    groups.get(repo)!.sessions.push(s);
  }
  return Array.from(groups.entries())
    .map(([name, data]) => ({ name, remote: data.remote, sessions: data.sessions }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

const SessionBranchItem = memo(function SessionBranchItem({
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
    <SidebarMenuSubItem>
      <SidebarMenuButton
        isActive={isActive}
        onClick={onSelect}
        className="group/item cursor-pointer justify-between h-9 px-3"
      >
        <div className="flex items-center gap-2 min-w-0">
          <GitBranch className="h-4 w-4 shrink-0 text-muted-foreground" />
          <span className="truncate text-sm">
            {entry.workspaceName ?? entry.id.slice(0, 8)}
          </span>
          <div className={`h-2 w-2 shrink-0 rounded-full ${statusColors[entry.status] ?? "bg-muted"}`} />
        </div>
        <div
          role="button"
          tabIndex={0}
          className="flex h-6 w-6 items-center justify-center rounded-md opacity-0 group-hover/item:opacity-100 shrink-0 cursor-pointer hover:bg-sidebar-accent"
          onClick={(e) => {
            e.stopPropagation();
            onDestroy();
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.stopPropagation(); onDestroy(); }
          }}
        >
          <Trash2 className="h-3.5 w-3.5 text-muted-foreground hover:text-destructive" />
        </div>
      </SidebarMenuButton>
    </SidebarMenuSubItem>
  );
});

function RepoCollapsible({
  group,
  activeSessionId,
  onSelectSession,
  onDestroySession,
  onNewSession,
}: {
  group: RepoGroup;
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onDestroySession: (id: string) => void;
  onNewSession: (repoUrl?: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const hasActive = group.sessions.some((s) => s.id === activeSessionId);

  return (
    <Collapsible open={open} onOpenChange={setOpen} className="group/collapsible">
      <SidebarMenuItem>
        <div className="group/repo flex w-full items-center cursor-pointer rounded-md hover:bg-sidebar-accent/70">
          <CollapsibleTrigger
            className="flex flex-1 items-center gap-2 cursor-pointer px-3 py-2.5 text-left font-medium min-w-0"
          >
            <ChevronRight className={`h-4 w-4 shrink-0 transition-transform ${open ? "rotate-90" : ""}`} />
            <span className="truncate text-sm">{group.name}</span>
            {hasActive && !open && (
              <div className="h-2 w-2 rounded-full bg-accent shrink-0" />
            )}
          </CollapsibleTrigger>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-6 w-6 p-0 opacity-0 group-hover/repo:opacity-100 shrink-0 mr-2 cursor-pointer"
                  onClick={() => onNewSession(group.remote)}
                />
              }
            >
              <Plus className="h-3.5 w-3.5" />
            </TooltipTrigger>
            <TooltipContent>New session</TooltipContent>
          </Tooltip>
        </div>
        <CollapsibleContent>
          <SidebarMenuSub>
            {group.sessions.map((entry) => (
              <SessionBranchItem
                key={entry.id}
                entry={entry}
                isActive={entry.id === activeSessionId}
                onSelect={() => onSelectSession(entry.id)}
                onDestroy={() => onDestroySession(entry.id)}
              />
            ))}
          </SidebarMenuSub>
        </CollapsibleContent>
      </SidebarMenuItem>
    </Collapsible>
  );
}

export function AppSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onOpenSettings,
  onOpenBoard,
  onDestroySession,
}: AppSidebarProps) {
  const [addRepoOpen, setAddRepoOpen] = useState(false);

  const sortedSessions = useMemo(() => {
    const statusOrder: Record<string, number> = {
      streaming: 0,
      active: 1,
      creating: 2,
      paused: 3,
      in_review: 4,
      error: 5,
      failed: 6,
      ended: 7,
    };
    return [...sessions.values()].sort((a, b) => {
      const aOrder = statusOrder[a.status] ?? 8;
      const bOrder = statusOrder[b.status] ?? 8;
      if (aOrder !== bOrder) return aOrder - bOrder;
      return b.createdAt.localeCompare(a.createdAt);
    });
  }, [sessions]);

  const repoGroups = useMemo(() => groupByRepo(sortedSessions), [sortedSessions]);

  return (
    <Sidebar collapsible="icon" variant="sidebar">
      <SidebarHeader className="h-16 justify-center border-b px-4">
        <div className="flex items-center gap-2.5">
          <img src="/logo-icon.png" alt="HarnessBox" className="h-6 w-6" />
          <span className="font-semibold text-sm tracking-tight group-data-[collapsible=icon]:hidden">
            HarnessBox
          </span>
        </div>
      </SidebarHeader>

      <SidebarContent>
        {onOpenBoard && (
          <SidebarMenuItem className="py-2 px-4">
            <SidebarMenuButton onClick={onOpenBoard} className="cursor-pointer h-10 px-4 py-4">
              <LayoutGrid className="h-4 w-4" />
              <span className="text-sm">Dashboard</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        )}
        <SidebarGroup className="px-2">
          <div className="flex items-center justify-between px-2 py-2">
            <SidebarGroupLabel className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Sessions
            </SidebarGroupLabel>
            <Tooltip>
              <TooltipTrigger
                render={
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 w-7 p-0 cursor-pointer"
                    onClick={() => setAddRepoOpen(true)}
                  />
                }
              >
                <Plus className="h-4 w-4" />
              </TooltipTrigger>
              <TooltipContent>Add Repository</TooltipContent>
            </Tooltip>
          </div>
          <SidebarMenu>
            {repoGroups.length === 0 && (
              <p className="px-4 py-6 text-sm text-muted-foreground">
                No sessions yet
              </p>
            )}
            {repoGroups.map((group) => (
              <RepoCollapsible
                key={group.name}
                group={group}
                activeSessionId={activeSessionId}
                onSelectSession={onSelectSession}
                onDestroySession={onDestroySession}
                onNewSession={onNewSession}
              />
            ))}
          </SidebarMenu>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="border-t p-3">
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton onClick={onOpenSettings} className="cursor-pointer h-10 px-3">
              <Settings className="h-4 w-4" />
              <span className="text-sm">Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarFooter>

      <AddRepoDialog
        open={addRepoOpen}
        onOpenChange={setAddRepoOpen}
        onSubmit={(repoUrl) => onNewSession(repoUrl)}
      />
    </Sidebar>
  );
}
