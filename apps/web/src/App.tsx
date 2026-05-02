import { useCallback, useState } from "react";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { AppHeader } from "@/components/layout/app-header";
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
  const [createError, setCreateError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [prefillRepoUrl, setPrefillRepoUrl] = useState<string | undefined>();

  const handleNewSession = useCallback((repoUrl?: string) => {
    setPrefillRepoUrl(repoUrl);
    setCreateError(null);
    setSheetOpen(true);
  }, []);

  const handleCloseSheet = useCallback(() => {
    setSheetOpen(false);
    setPrefillRepoUrl(undefined);
  }, []);

  const handleCreateSession = useCallback(
    async (config: CreateSessionRequest) => {
      setIsCreating(true);
      setCreateError(null);
      try {
        const storedKeys = getStoredValue<{ name: string; value: string }[]>("api-keys", []);
        const mergedEnv = { ...config.env_vars };
        for (const k of storedKeys) {
          if (k.name && k.value && !(k.name in mergedEnv)) {
            mergedEnv[k.name] = k.value;
          }
        }
        await manager.createSession({ ...config, env_vars: mergedEnv });
        handleCloseSheet();
        setView("session");
      } catch (err) {
        setCreateError(err instanceof Error ? err.message : "Failed to create session");
      } finally {
        setIsCreating(false);
      }
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

  const handleOpenSettings = useCallback(() => {
    setView("settings");
  }, []);

  const handleOpenBoard = useCallback(() => {
    setView("board");
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
        <AppSidebar
          sessions={manager.sessions}
          activeSessionId={manager.activeSessionId}
          onSelectSession={handleSelectSession}
          onNewSession={handleNewSession}
          onOpenSettings={handleOpenSettings}
          onOpenBoard={handleOpenBoard}
          onDestroySession={manager.destroySession}
        />
        <SidebarInset>
          {view !== "board" && (
            <AppHeader session={manager.activeSession} onRenameSession={manager.renameSession} />
          )}
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
            {createError && (
              <div className="mx-4 rounded border border-destructive/50 bg-destructive/10 px-3 py-2">
                <span className="text-xs text-destructive">{createError}</span>
              </div>
            )}
            <SessionConfigPanel
              onSubmit={handleCreateSession}
              onCancel={handleCloseSheet}
              disabled={isCreating}
              defaultRepoUrl={prefillRepoUrl}
            />
          </SheetContent>
        </Sheet>
      </SidebarProvider>
    </TooltipProvider>
  );
}
