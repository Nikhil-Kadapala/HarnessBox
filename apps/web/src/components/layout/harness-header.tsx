import { SidebarTrigger } from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";
import type { SessionEntry } from "@/types";

interface HarnessHeaderProps {
  session?: SessionEntry | null;
}

const runtimeLabels: Record<string, { label: string; color: string }> = {
  creating: { label: "Creating", color: "bg-blue-400" },
  active: { label: "Running", color: "bg-accent" },
  streaming: { label: "Running", color: "bg-accent" },
  paused: { label: "Paused", color: "bg-warning" },
  dead: { label: "Killed", color: "bg-destructive" },
  ended: { label: "Ended", color: "bg-muted-foreground" },
  error: { label: "Error", color: "bg-destructive" },
};

export function HarnessHeader({ session }: HarnessHeaderProps) {
  const runtime = session?.runtimeState ?? "active";
  const { label, color } = runtimeLabels[runtime] ?? runtimeLabels.active;

  return (
    <header className="relative z-40 flex h-14 shrink-0 items-center justify-between border-b bg-background px-4">
      <div className="flex items-center gap-2">
        <SidebarTrigger className="cursor-pointer" />
        {session && (
          <div className="flex items-center gap-2">
            <span className="font-medium">
              {session.workspaceName || session.id.slice(0, 8)}
            </span>
            <Badge variant="outline" className="text-xs">
              {session.status}
            </Badge>
          </div>
        )}
      </div>

      {session && (
        <div className="absolute top-full right-4 mt-3 w-[340px] rounded-xl border border-border bg-card p-4 text-card-foreground shadow-2xl shadow-black/20">
          <h3 className="text-sm font-semibold mb-3">Sandbox Details</h3>
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">Lifecycle</span>
              <div className="flex items-center gap-1.5">
                <span className={`h-2 w-2 rounded-full ${color}`} />
                <span className="text-xs font-medium">{label}</span>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">Harness</span>
              <span className="text-xs font-mono">{session.harness}</span>
            </div>
            {session.branch && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Branch</span>
                <span className="text-xs font-mono truncate max-w-[140px]">{session.branch}</span>
              </div>
            )}
            {session.remote && (
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground">Remote</span>
                <span className="text-xs font-mono truncate max-w-[140px]">
                  {session.remote.replace(/^https?:\/\/github\.com\//, "")}
                </span>
              </div>
            )}
            <div className="flex items-center justify-between">
              <span className="text-xs text-muted-foreground">Created</span>
              <span className="text-xs">
                {new Date(session.createdAt).toLocaleString()}
              </span>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
