import { useCallback, useState } from "react";
import { Outlet, useNavigate, useRouter } from "@tanstack/react-router";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { HarnessSidebar } from "@/components/layout/harness-sidebar";
import { HarnessHeader } from "@/components/layout/harness-header";
import { SessionConfigPanel } from "@/components/session/session-config-panel";
import { SessionManagerProvider, useSessionManager } from "@/hooks/use-session-manager";
import { appStorage } from "@/lib/storage-schema";
import type { CreateSessionRequest } from "@/types";

export function AppLayout() {
  const manager = useSessionManager();
  const navigate = useNavigate();
  const router = useRouter();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [prefillRepoUrl, setPrefillRepoUrl] = useState<string | undefined>();

  const currentPath = router.state.location.pathname;
  const currentView: "board" | "session" | "settings" =
    currentPath.startsWith("/session") ? "session" :
    currentPath.startsWith("/settings") ? "settings" : "board";

  const handleNewSession = useCallback((repoUrl?: string) => {
    setPrefillRepoUrl(repoUrl);
    setSheetOpen(true);
  }, []);

  const handleCloseSheet = useCallback(() => {
    setSheetOpen(false);
    setPrefillRepoUrl(undefined);
  }, []);

  const handleCreateSession = useCallback(
    (config: CreateSessionRequest) => {
      const mergedEnv = { ...config.env_vars };
      for (const k of appStorage.apiKeys) {
        if (k.name && k.value && !(k.name in mergedEnv)) {
          mergedEnv[k.name] = k.value;
        }
      }

      const sessionId = crypto.randomUUID();
      manager.createSession({ ...config, env_vars: mergedEnv, session_id: sessionId });

      handleCloseSheet();
      navigate({ to: "/session/$sessionId", params: { sessionId } });
    },
    [manager, handleCloseSheet, navigate],
  );

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
            onNewSession={handleNewSession}
            onDestroySession={manager.destroySession}
            currentView={currentView}
            onNavigateToBoard={handleNavigateToBoard}
            onNavigateToSettings={handleNavigateToSettings}
          />
          <SidebarInset className="max-h-screen overflow-hidden">
            <HarnessHeader session={currentView === "session" ? manager.activeSession : null} />
            <div className="flex flex-1 flex-col min-h-0 overflow-y-auto">
              <Outlet />
            </div>
          </SidebarInset>

          <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
            <SheetContent side="right" className="sm:max-w-xl w-full overflow-y-auto">
              <SheetHeader>
                <SheetTitle>New Session</SheetTitle>
              </SheetHeader>
              <SessionConfigPanel
                onSubmit={handleCreateSession}
                onCancel={handleCloseSheet}
                defaultRepoUrl={prefillRepoUrl}
              />
            </SheetContent>
          </Sheet>
        </SidebarProvider>
      </TooltipProvider>
    </SessionManagerProvider>
  );
}
