import { useCallback, useState } from "react";
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
import { SessionView } from "@/components/session/session-view";
import { SessionConfigPanel } from "@/components/session/session-config-panel";
import { SettingsPanel } from "@/components/settings/settings-panel";
import { SessionBoardApp } from "@/components/session-board/session-board-app";
import { useSessionManager } from "@/hooks/use-session-manager";
import { getStoredValue } from "@/lib/storage";
import type { ActiveView, CreateSessionRequest } from "@/types";

export default function App() {
  const manager = useSessionManager();
  const [view, setView] = useState<ActiveView>("board");
  const [sheetOpen, setSheetOpen] = useState(false);
  const [prefillRepoUrl, setPrefillRepoUrl] = useState<string | undefined>();

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
      const storedKeys = getStoredValue<{ name: string; value: string }[]>("api-keys", []);
      const mergedEnv = { ...config.env_vars };
      for (const k of storedKeys) {
        if (k.name && k.value && !(k.name in mergedEnv)) {
          mergedEnv[k.name] = k.value;
        }
      }

      const sessionId = crypto.randomUUID();
      manager.createSession({ ...config, env_vars: mergedEnv, session_id: sessionId });

      handleCloseSheet();
      setView("session");
    },
    [manager, handleCloseSheet],
  );

  const handleSelectSession = useCallback(
    (id: string) => {
      manager.switchSession(id);
      setView("session");
    },
    [manager],
  );

  const handleNavigateToBoard = useCallback(() => {
    setView("board");
  }, []);

  const handleNavigateToSettings = useCallback(() => {
    setView("settings");
  }, []);


  const handleSendPrompt = useCallback(
    (prompt: string) => {
      if (manager.activeSessionId) {
        manager.sendPrompt(manager.activeSessionId, prompt);
      }
    },
    [manager],
  );

  const handleStop = useCallback(() => {
    if (manager.activeSessionId) {
      manager.stopStreaming(manager.activeSessionId);
    }
  }, [manager]);

  return (
    <TooltipProvider>
      <SidebarProvider>
        <HarnessSidebar
          sessions={manager.sessions}
          activeSessionId={manager.activeSessionId}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
          onDestroySession={manager.destroySession}
          currentView={view}
          onNavigateToBoard={handleNavigateToBoard}
          onNavigateToSettings={handleNavigateToSettings}
        />
        <SidebarInset>
          <HarnessHeader session={view === "session" ? manager.activeSession : null} />
          <div className="flex flex-1 flex-col min-h-0">
            {view === "settings" && (
              <SettingsPanel
                onClose={() => {
                  if (manager.activeSession) setView("session");
                  else setView("board");
                }}
              />
            )}
            {view === "session" && manager.activeSession && (
              <SessionView
                session={manager.activeSession}
                onSendPrompt={handleSendPrompt}
                onStop={handleStop}
              />
            )}
            {view === "session" && !manager.activeSession && (
              <div className="flex flex-1 items-center justify-center">
                <div className="text-center space-y-2">
                  <p className="text-sm text-muted-foreground">No active session</p>
                  <button
                    onClick={() => handleNewSession()}
                    className="text-sm text-accent hover:underline"
                  >
                    Create one
                  </button>
                </div>
              </div>
            )}
            {view === "board" && <SessionBoardApp onSelectSession={handleSelectSession} />}
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
  );
}
