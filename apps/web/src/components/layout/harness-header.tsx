import { useState } from "react";
import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { SidebarTrigger } from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import { Box, ChevronDown, GitBranch, LoaderCircle, MessagesSquare, Play } from "lucide-react";
import { RuntimeStateIcon } from "@/components/runtime-state-icon";
import { runtimeStateLabel } from "@/lib/runtime-state";
import { Button } from "@/components/ui/button";
import type { SessionEntry } from "@/types";

interface HarnessHeaderProps {
  session?: SessionEntry | null;
  onResume: (sessionId: string) => Promise<void>;
}

function repositoryName(remote: string): string {
  const cleaned = remote.trim().replace(/[?#].*$/, "").replace(/\/+$/, "").replace(/\.git$/i, "");
  return cleaned.split(/[/:]/).filter(Boolean).at(-1) ?? remote;
}

export function HarnessHeader({ session, onResume }: HarnessHeaderProps) {
  const runtime = session?.runtimeState ?? "active";
  const [detailsOpen, setDetailsOpen] = useState(false);
  const [resuming, setResuming] = useState(false);
  const [resumeError, setResumeError] = useState<string | null>(null);
  const prefersReducedMotion = useReducedMotion();
  const transition = prefersReducedMotion ? { duration: 0 } : { duration: 0.22, ease: "easeOut" as const };

  async function handleResume() {
    if (!session || resuming) return;
    setResuming(true);
    setResumeError(null);
    try {
      await onResume(session.id);
    } catch (error) {
      setResumeError(error instanceof Error ? error.message : "Could not resume this workspace.");
    } finally {
      setResuming(false);
    }
  }

  return (
    <header className="relative z-40 flex h-14 shrink-0 items-center justify-between border-b bg-background px-4">
      <div className="flex items-center gap-2">
        <SidebarTrigger className="cursor-pointer" />
        {session && (
          <div className="flex items-center gap-2">
            <span role="img" aria-label="Workspace" title="Workspace"><GitBranch aria-hidden="true" className="h-4 w-4 text-muted-foreground" /></span>
            <span className="font-medium">
              {session.workspaceName || session.id.slice(0, 8)}
            </span>
            <Badge variant="outline" className="gap-1 text-xs">
              <MessagesSquare aria-hidden="true" className="h-3 w-3" />
              Session {session.status.replaceAll("_", " ")}
            </Badge>
          </div>
        )}
      </div>

      {session && (
        <div className="absolute right-4 top-full z-50 mt-2 flex w-[min(340px,calc(100vw-2rem))] flex-col items-end">
          <motion.button
            type="button"
            aria-expanded={detailsOpen}
            aria-controls="runtime-environment-panel"
            onClick={() => setDetailsOpen((open) => !open)}
            whileTap={prefersReducedMotion ? undefined : { scale: 0.97 }}
            transition={transition}
            className="flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-3 text-sm text-card-foreground shadow-lg shadow-black/15 transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <Box className="h-4 w-4 text-sky-400" aria-hidden="true" />
            <span>Runtime Environment · {runtimeStateLabel(runtime)}</span>
            <motion.span animate={{ rotate: detailsOpen ? 180 : 0 }} transition={transition} className="inline-flex">
              <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
            </motion.span>
          </motion.button>

          <AnimatePresence initial={false}>
            {detailsOpen && (
              <motion.div
                id="runtime-environment-panel"
                key="runtime-environment-panel"
                initial={prefersReducedMotion ? false : { opacity: 0, height: 0, y: -5 }}
                animate={{ opacity: 1, height: "auto", y: 0 }}
                exit={prefersReducedMotion ? { opacity: 0, height: 0 } : { opacity: 0, height: 0, y: -5 }}
                transition={transition}
                className="mt-2 w-full overflow-hidden rounded-xl border border-border bg-card text-card-foreground shadow-2xl shadow-black/20"
              >
                <div className="p-4">
                  <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold"><Box aria-hidden="true" className="h-4 w-4 text-sky-400" />Runtime Environment</h3>
                  <p className="mb-3 text-xs text-muted-foreground">Workspace and session records stay in local HarnessBox storage. Agent execution uses the selected runtime provider.</p>
                  <div className="space-y-3">
                    <div className="space-y-1">
                      <span className="text-xs text-muted-foreground">Lifecycle</span>
                      <div className="flex items-center gap-1.5">
                        <RuntimeStateIcon state={runtime} className="h-3.5 w-3.5" />
                        <span className="text-xs font-medium">{runtimeStateLabel(runtime)}</span>
                        {runtime.toLowerCase() === "paused" && (
                          <Button type="button" size="sm" variant="outline" className="ml-2 h-7 px-2" onClick={handleResume} disabled={resuming}>
                            {resuming ? <LoaderCircle className="animate-spin" /> : <Play />}
                            {resuming ? "Resuming…" : "Resume"}
                          </Button>
                        )}
                      </div>
                      {resumeError && <p role="alert" className="mt-1 text-xs text-destructive">{resumeError}</p>}
                    </div>
                    <div className="space-y-1">
                      <span className="text-xs text-muted-foreground">Harness</span>
                      <p className="text-xs font-mono break-words">{session.harness}</p>
                    </div>
                    {session.branch && (
                      <div className="space-y-1">
                        <span className="text-xs text-muted-foreground">Branch</span>
                        <p className="break-all text-xs font-mono">{session.branch}</p>
                      </div>
                    )}
                    {session.remote && (
                      <div className="space-y-1">
                        <span className="text-xs text-muted-foreground">Repository</span>
                        <p className="break-all text-xs font-mono" title={session.remote}>
                          {repositoryName(session.remote)}
                        </p>
                      </div>
                    )}
                    <div className="space-y-1">
                      <span className="text-xs text-muted-foreground">Created</span>
                      <p className="text-xs">{new Date(session.createdAt).toLocaleString()}</p>
                    </div>
                  </div>
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </header>
  );
}
