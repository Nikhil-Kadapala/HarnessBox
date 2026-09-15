import { useCallback, useEffect, useState } from "react";
import { Outlet, useNavigate, useRouter } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import { HarnessSidebar } from "@/components/layout/harness-sidebar";
import { HarnessHeader } from "@/components/layout/harness-header";
import { SessionManagerProvider, useSessionManager } from "@/hooks/use-session-manager";
import { appStorage } from "@/lib/storage-schema";
import { createProject as apiCreateProject, listProjects } from "@/lib/api";
import type { CreateSessionRequest, Project } from "@/types";

export function AppLayout() {
  const manager = useSessionManager();
  const navigate = useNavigate();
  const router = useRouter();
  const [projects, setProjects] = useState<Project[]>([]);
  const [creatingProjectId, setCreatingProjectId] = useState<string | null>(null);
  const [retryProject, setRetryProject] = useState<Project | null>(null);
  const [workspaceError, setWorkspaceError] = useState<string | null>(null);

  useEffect(() => {
    listProjects().then(setProjects).catch((err) => console.error("Failed to load projects", err));
  }, []);

  const currentPath = router.state.location.pathname;
  const currentView: "board" | "session" | "settings" =
    currentPath.startsWith("/session") ? "session" :
    currentPath.startsWith("/settings") ? "settings" : "board";

  const handleNewWorkspace = useCallback(
    async (project: Project) => {
      setCreatingProjectId(project.project_id);
      setRetryProject(project);
      setWorkspaceError(null);
      const env_vars: Record<string, string> = {};
      for (const k of appStorage.apiKeys) {
        if (k.name && k.value) env_vars[k.name] = k.value;
      }
      const config: CreateSessionRequest = {
        project_id: project.project_id,
        provider: project.workspace_settings.provider,
        harness: project.workspace_settings.default_harness,
        sandbox_timeout: project.workspace_settings.sandbox_timeout,
        session_timeout: project.workspace_settings.session_timeout,
        skip_permissions: project.workspace_settings.skip_permissions,
        security_policy: project.workspace_settings.security_policy,
        env_vars,
      };

      try {
        const sessionId = await manager.createSession(config);
        setRetryProject(null);
        navigate({ to: "/session/$sessionId", params: { sessionId } });
      } catch (err) {
        setWorkspaceError(err instanceof Error ? err.message : "Could not create workspace.");
      } finally {
        setCreatingProjectId(null);
      }
    },
    [manager, navigate],
  );

  const handleProjectSettings = useCallback((project: Project) => {
    navigate({ to: "/projects/$projectId/settings", params: { projectId: project.project_id } });
  }, [navigate]);

  useEffect(() => {
    if (currentPath.startsWith("/projects/")) {
      listProjects().then(setProjects).catch(() => {});
    }
  }, [currentPath]);

  const handleSelectSession = useCallback(
    (id: string) => {
      manager.switchSession(id);
      navigate({ to: "/session/$sessionId", params: { sessionId: id } });
    },
    [manager, navigate],
  );

  const handleNavigateToBoard = useCallback(() => {
    navigate({ to: "/" });
  }, [navigate]);

  const handleNavigateToSettings = useCallback(() => {
    navigate({ to: "/settings" });
  }, [navigate]);

  return (
    <SessionManagerProvider manager={manager}>
      <TooltipProvider>
        <SidebarProvider>
          <HarnessSidebar
            sessions={manager.sessions}
            activeSessionId={manager.activeSessionId}
            onSelectSession={handleSelectSession}
            projects={projects}
            onCreateProject={async (input) => {
              const project = await apiCreateProject(input);
              setProjects((current) => [...current, project].sort((a, b) => a.name.localeCompare(b.name)));
            }}
            onNewWorkspace={handleNewWorkspace}
            onProjectSettings={handleProjectSettings}
            onDestroySession={manager.destroySession}
            currentView={currentView}
            onNavigateToBoard={handleNavigateToBoard}
            onNavigateToSettings={handleNavigateToSettings}
          />
          <SidebarInset className="max-h-screen overflow-hidden">
            <HarnessHeader
              session={currentView === "session" ? manager.activeSession : null}
              onResume={manager.resumeSession}
            />
            <div className="flex flex-1 flex-col min-h-0 overflow-y-auto">
              {workspaceError && (
                <div role="alert" className="flex items-center justify-between border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
                  <span>{workspaceError}</span>
                  <button type="button" disabled={!retryProject || !!creatingProjectId} onClick={() => retryProject && void handleNewWorkspace(retryProject)} className="underline">Retry</button>
                </div>
              )}
              <Outlet />
            </div>
          </SidebarInset>
        </SidebarProvider>
      </TooltipProvider>
    </SessionManagerProvider>
  );
}
