"use client";

import { cn } from "@/lib/utils";
import Plus from "lucide-react/dist/esm/icons/plus";
import ChevronRight from "lucide-react/dist/esm/icons/chevron-right";
import Trash2 from "lucide-react/dist/esm/icons/trash-2";
import LayoutDashboard from "lucide-react/dist/esm/icons/layout-dashboard";
import Settings from "lucide-react/dist/esm/icons/settings";
import GitBranch from "lucide-react/dist/esm/icons/git-branch";
import { useState, useMemo, useCallback } from "react";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarGroup,
  SidebarGroupLabel,
  SidebarGroupContent,
  SidebarMenuSub,
  SidebarMenuSubItem,
} from "@/components/ui/sidebar";
import {
  Collapsible,
  CollapsibleContent,
} from "@/components/ui/collapsible";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { footerNavLinks } from "@/components/app-shared";
import { getStoredValue } from "@/lib/storage";
import type { SessionEntry, DetectedWorkspace } from "@/types";

interface HarnessSidebarProps {
  sessions: Map<string, SessionEntry>;
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onNewSession: () => void;
  onDestroySession: (id: string) => void;
  currentView: "board" | "session" | "settings";
  onNavigateToBoard: () => void;
  onNavigateToSettings: () => void;
}

interface RepoGroup {
  name: string;
  remote: string | undefined;
  sessions: SessionEntry[];
}

function extractRepoName(remote?: string): string {
  if (!remote) return "Other";
  const cleaned = remote.replace(/\.git$/, "");
  const parts = cleaned.split("/");
  return parts.length >= 2 ? parts[parts.length - 1] : cleaned;
}

function groupByRepo(sessions: SessionEntry[]): RepoGroup[] {
  const groups = new Map<
    string,
    { remote: string | undefined; sessions: SessionEntry[] }
  >();

  // Include the detected repo from settings even if no sessions exist for it
  const detectedRepo = getStoredValue<DetectedWorkspace | null>(
    "repository",
    null,
  );
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
    .map(([name, data]) => ({
      name,
      remote: data.remote,
      sessions: data.sessions,
    }))
    .sort((a, b) => a.name.localeCompare(b.name));
}

export function HarnessSidebar({
  sessions,
  activeSessionId,
  onSelectSession,
  onNewSession,
  onDestroySession,
  currentView,
  onNavigateToBoard,
  onNavigateToSettings,
}: HarnessSidebarProps) {
  const sessionArray = useMemo(() => Array.from(sessions.values()), [sessions]);
  const repoGroups = useMemo(() => groupByRepo(sessionArray), [sessionArray]);
  const [openRepos, setOpenRepos] = useState<Set<string>>(
    () => new Set(repoGroups.map((g) => g.name)),
  );

  const toggleRepo = useCallback((repoName: string) => {
    setOpenRepos((prev) => {
      const next = new Set(prev);
      if (next.has(repoName)) next.delete(repoName);
      else next.add(repoName);
      return next;
    });
  }, []);

  return (
    <Sidebar
      className={cn(
        "*:data-[slot=sidebar-inner]:bg-background",
        "*:data-[slot=sidebar-inner]:dark:bg-[radial-gradient(60%_18%_at_10%_0%,--theme(--color-foreground/.08),transparent)]",
        "**:data-[slot=sidebar-menu-button]:[&>span]:text-foreground/75",
      )}
      collapsible="icon"
      variant="sidebar"
    >
      <SidebarHeader className="h-14 justify-center border-b px-2">
        <SidebarMenuButton size="lg" className="w-full">
          <img
            src="/logo-icon.png"
            alt="HarnessBox"
            className="h-8 w-8 shrink-0"
          />
          <span className="font-medium text-foreground">HarnessBox</span>
        </SidebarMenuButton>
      </SidebarHeader>

      <SidebarContent>
        {/* Main navigation */}
        <SidebarGroup>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <SidebarMenuButton
                  isActive={currentView === "board"}
                  onClick={onNavigateToBoard}
                  className="cursor-pointer"
                >
                  <LayoutDashboard className="h-4 w-4" />
                  <span>Dashboard</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        {/* Sessions tree */}
        <SidebarGroup>
          <div className="flex items-center justify-between px-2 py-1">
            <SidebarGroupLabel>Sessions</SidebarGroupLabel>
            <button
              className="p-1 rounded-sm transition-colors cursor-pointer opacity-30"
              title="Add Session (Coming soon)"
              disabled
            >
              <Plus className="h-4 w-4" />
            </button>
          </div>
          <SidebarGroupContent>
            <SidebarMenu>
              {repoGroups.length === 0 ? (
                <div className="px-3 py-2 text-sm text-muted-foreground">
                  No sessions yet
                </div>
              ) : (
                repoGroups.map((group) => (
                  <Collapsible
                    key={group.name}
                    open={openRepos.has(group.name)}
                    onOpenChange={() => toggleRepo(group.name)}
                  >
                    <SidebarMenuItem className="group/repo">
                      {/* Expanded sidebar view */}
                      <div className="relative flex items-center w-full group-data-[collapsible=icon]:hidden">
                        <SidebarMenuButton
                          className="flex-1 cursor-pointer pr-12"
                          onClick={() => toggleRepo(group.name)}
                        >
                          <svg
                            className="h-4 w-4 shrink-0"
                            fill="currentColor"
                            viewBox="0 0 16 16"
                          >
                            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
                          </svg>
                          <span className="flex-1 truncate min-w-0">
                            {group.name}
                          </span>
                          <ChevronRight
                            className={cn(
                              "h-4 w-4 shrink-0 transition-transform",
                              openRepos.has(group.name) && "rotate-90",
                            )}
                          />
                        </SidebarMenuButton>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            onNewSession();
                          }}
                          className="absolute right-2 opacity-0 group-hover/repo:opacity-100 p-0.5 hover:bg-accent rounded transition-opacity cursor-pointer z-10"
                          title="New Session"
                        >
                          <Plus className="h-3.5 w-3.5" />
                        </button>
                      </div>

                      {/* Collapsed sidebar view - dropdown menu */}
                      <div className="hidden group-data-[collapsible=icon]:block">
                        <DropdownMenu>
                          <DropdownMenuTrigger
                            className="peer/menu-button group/menu-button flex w-full items-center gap-2 overflow-hidden rounded-md p-2 text-left outline-none ring-sidebar-ring transition-[width,height,padding] hover:bg-sidebar-accent hover:text-sidebar-accent-foreground focus-visible:ring-2 active:bg-sidebar-accent active:text-sidebar-accent-foreground disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 data-[active=true]:bg-sidebar-accent data-[active=true]:text-sidebar-accent-foreground data-[active=true]:font-medium cursor-pointer"
                            title={group.name}
                          >
                            <svg
                              className="h-4 w-4"
                              fill="currentColor"
                              viewBox="0 0 16 16"
                            >
                              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
                            </svg>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent
                            side="right"
                            align="start"
                            className="w-48"
                          >
                            <div className="px-2 py-1.5 text-sm font-normal text-muted-foreground">
                              {group.name}
                            </div>
                            <DropdownMenuSeparator />
                            {group.sessions.length > 0 ? (
                              group.sessions.map((session) => (
                                <DropdownMenuItem
                                  key={session.id}
                                  onClick={() => onSelectSession(session.id)}
                                  className="cursor-pointer"
                                >
                                  <GitBranch className="h-3.5 w-3.5 mr-2" />
                                  <span className="truncate">
                                    {session.workspaceName ||
                                      session.id.slice(0, 8)}
                                  </span>
                                </DropdownMenuItem>
                              ))
                            ) : (
                              <DropdownMenuItem disabled>
                                <span className="text-muted-foreground text-xs">
                                  No sessions
                                </span>
                              </DropdownMenuItem>
                            )}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                              onClick={onNewSession}
                              className="cursor-pointer"
                            >
                              <Plus className="h-3.5 w-3.5 mr-2" />
                              New session
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </div>
                      <CollapsibleContent>
                        <SidebarMenuSub>
                          {group.sessions.map((session) => (
                            <SidebarMenuSubItem
                              key={session.id}
                              className="relative group/session"
                            >
                              <SidebarMenuButton
                                isActive={session.id === activeSessionId}
                                onClick={() => onSelectSession(session.id)}
                                className="w-full pr-8 cursor-pointer"
                              >
                                <span className="flex items-center gap-2 flex-1 min-w-0">
                                  <GitBranch className="h-3 w-3 shrink-0" />
                                  <span className="truncate text-xs">
                                    {session.workspaceName ||
                                      session.id.slice(0, 8)}
                                  </span>
                                </span>
                              </SidebarMenuButton>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  onDestroySession(session.id);
                                }}
                                className="absolute right-1 top-1/2 -translate-y-1/2 opacity-0 group-hover/session:opacity-100 p-1 hover:bg-destructive/10 rounded transition-opacity cursor-pointer"
                                title="Delete session"
                              >
                                <Trash2 className="h-3 w-3 text-destructive" />
                              </button>
                            </SidebarMenuSubItem>
                          ))}
                        </SidebarMenuSub>
                      </CollapsibleContent>
                    </SidebarMenuItem>
                  </Collapsible>
                ))
              )}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter className="gap-0 p-0">
        <SidebarMenu className="border-t p-2">
          <SidebarMenuItem>
            <SidebarMenuButton
              className="text-muted-foreground cursor-pointer"
              isActive={currentView === "settings"}
              size="sm"
              onClick={onNavigateToSettings}
            >
              <Settings className="h-4 w-4" />
              <span>Settings</span>
            </SidebarMenuButton>
          </SidebarMenuItem>
          {footerNavLinks.map((item) => (
            <SidebarMenuItem key={item.title}>
              <SidebarMenuButton
                className="text-muted-foreground cursor-pointer"
                isActive={item.isActive}
                size="sm"
                render={
                  <a
                    href={item.path}
                    target="_blank"
                    rel="noopener noreferrer"
                  />
                }
              >
                {item.icon}
                <span>{item.title}</span>
              </SidebarMenuButton>
            </SidebarMenuItem>
          ))}
        </SidebarMenu>
        <div className="px-4 pt-4 pb-2 transition-opacity group-data-[collapsible=icon]:pointer-events-none group-data-[collapsible=icon]:opacity-0">
          <p className="text-nowrap text-[9px] text-muted-foreground">
            © {new Date().getFullYear()} HarnessBox
          </p>
        </div>
      </SidebarFooter>
    </Sidebar>
  );
}
