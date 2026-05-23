import * as React from "react"
import {
  ArrowCounterClockwiseIcon,
  ArchiveIcon,
  GitBranchIcon,
  GitPullRequestIcon,
  MagnifyingGlassIcon,
  PauseIcon,
  StopIcon,
} from "@phosphor-icons/react"
import { Loader2, RefreshCw } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Skeleton } from "@/components/ui/skeleton"
import {
  fetchSessions,
  fetchSessionStats,
  transitionSession,
  pauseSession,
  resumeSession,
  stopSession,
  createPR,
} from "@/lib/sessions/client"
import { KANBAN_COLUMNS, getColumnForState } from "@/lib/sessions/columns"
import type { SessionCard, SessionStats } from "@/lib/sessions/types"
import { cn } from "@/lib/utils"

interface SessionBoardAppProps {
  onSelectSession?: (sessionId: string) => void
}

export function SessionBoardApp({ onSelectSession }: SessionBoardAppProps) {
  const [sessions, setSessions] = React.useState<SessionCard[]>([])
  const [query, setQuery] = React.useState("")
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)

  const loadBoard = React.useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      setSessions(await fetchSessions())
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load sessions.")
    } finally {
      setIsLoading(false)
    }
  }, [])

  React.useEffect(() => {
    loadBoard()
  }, [loadBoard])

  const withOptimistic = React.useCallback(
    async (sessionId: string, optimisticStatus: string, action: () => Promise<void>) => {
      const prev = sessions
      setSessions((cur) =>
        cur.map((s) => (s.id === sessionId ? { ...s, status: optimisticStatus } : s)),
      )
      try {
        await action()
      } catch (err) {
        setSessions(prev)
        setError(err instanceof Error ? err.message : "Action failed.")
      }
    },
    [sessions],
  )

  const handleTransition = React.useCallback(
    (sessionId: string, targetState: string) =>
      withOptimistic(sessionId, targetState, () => transitionSession(sessionId, targetState).then(() => {})),
    [withOptimistic],
  )

  const handlePause = React.useCallback(
    (sessionId: string) =>
      withOptimistic(sessionId, "paused", () => pauseSession(sessionId).then(() => {})),
    [withOptimistic],
  )

  const handleResume = React.useCallback(
    (sessionId: string) =>
      withOptimistic(sessionId, "active", () => resumeSession(sessionId).then(() => {})),
    [withOptimistic],
  )

  const handleStop = React.useCallback(
    (sessionId: string) =>
      withOptimistic(sessionId, "failed", () => stopSession(sessionId)),
    [withOptimistic],
  )

  const handleCreatePR = React.useCallback(
    async (sessionId: string) => {
      const session = sessions.find((s) => s.id === sessionId)
      const title = session?.title ?? "Agent changes"
      const prev = sessions
      setSessions((cur) =>
        cur.map((s) => (s.id === sessionId ? { ...s, status: "in_review" } : s)),
      )
      try {
        const updated = await createPR(sessionId, title)
        setSessions((cur) =>
          cur.map((s) => (s.id === sessionId ? { ...s, ...updated } : s)),
        )
      } catch (err) {
        setSessions(prev)
        setError(err instanceof Error ? err.message : "PR creation failed.")
      }
    },
    [sessions],
  )

  const visible = searchSessions(sessions, query)
  const showLoading = isLoading && sessions.length === 0

  const columns = React.useMemo(
    () =>
      KANBAN_COLUMNS.map((col) => ({
        ...col,
        sessions: visible.filter((s) => getColumnForState(s.status) === col.id),
      })),
    [visible],
  )

  return (
    <div className="flex h-full min-h-0 flex-col bg-background text-foreground">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
        <div className="relative flex min-w-48 flex-1 items-center">
          <MagnifyingGlassIcon
            aria-hidden="true"
            className="pointer-events-none absolute left-2.5 size-4 text-muted-foreground"
          />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search sessions..."
            className="h-8 border-0 bg-muted/60 pl-8"
          />
        </div>

        <Button variant="outline" size="sm" onClick={loadBoard} disabled={isLoading} className="cursor-pointer">
          {isLoading ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <RefreshCw className="size-4" />
          )}
          {isLoading ? "Refreshing..." : "Refresh"}
        </Button>
      </header>

      {error && (
        <div className="border-b bg-destructive/10 px-4 py-2 text-sm text-destructive">
          {error}
          <Button
            variant="ghost"
            size="sm"
            className="ml-2 h-auto p-0 text-destructive underline"
            onClick={() => setError(null)}
          >
            Dismiss
          </Button>
        </div>
      )}

      <section className="flex min-h-0 flex-1">
        <ScrollArea className="min-h-0 flex-1">
          <div className="flex min-h-full gap-3 p-4">
            {showLoading ? (
              <BoardLoadingSkeleton />
            ) : (
              columns.map((col) => (
                <KanbanColumn
                  key={col.id}
                  id={col.id}
                  title={col.title}
                  sessions={col.sessions}
                  onSelectSession={onSelectSession}
                  actions={{
                    onTransition: handleTransition,
                    onPause: handlePause,
                    onResume: handleResume,
                    onStop: handleStop,
                    onCreatePR: handleCreatePR,
                  }}
                />
              ))
            )}
          </div>
        </ScrollArea>
      </section>
    </div>
  )
}

interface CardActions {
  onTransition: (sessionId: string, targetState: string) => void
  onPause: (sessionId: string) => void
  onResume: (sessionId: string) => void
  onStop: (sessionId: string) => void
  onCreatePR: (sessionId: string) => void
}

function KanbanColumn({
  id,
  title,
  sessions,
  onSelectSession,
  actions,
}: {
  id: string
  title: string
  sessions: SessionCard[]
  onSelectSession?: (sessionId: string) => void
  actions: CardActions
}) {
  return (
    <section className="flex w-72 shrink-0 flex-col">
      <header className="flex items-center justify-center gap-2 px-3 py-2">
        <ColumnDot columnId={id} />
        <h2 className="text-sm font-medium">{title}</h2>
        <Badge variant="secondary" className="text-xs">
          {sessions.length}
        </Badge>
      </header>
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-3">
        {sessions.map((session) => (
          <SessionCardItem
            key={session.id}
            session={session}
            columnId={id}
            onSelect={onSelectSession ? () => onSelectSession(session.id) : undefined}
            actions={actions}
          />
        ))}
        {sessions.length === 0 && (
          <p className="py-6 text-center text-xs text-muted-foreground">No sessions</p>
        )}
      </div>
    </section>
  )
}

const LIVE_COLUMNS = new Set(["in_progress", "in_review"])

function SessionCardItem({
  session,
  columnId,
  onSelect,
  actions,
}: {
  session: SessionCard
  columnId: string
  onSelect?: () => void
  actions: CardActions
}) {
  const [stats, setStats] = React.useState<SessionStats | null>(null)

  React.useEffect(() => {
    if (!LIVE_COLUMNS.has(columnId)) return
    let cancelled = false
    fetchSessionStats(session.id).then((s) => {
      if (!cancelled) setStats(s)
    })
    return () => { cancelled = true }
  }, [session.id, columnId])

  const hasStats = stats && (stats.insertions > 0 || stats.deletions > 0 || stats.commit_count > 0)

  return (
    <Card
      size="sm"
      className={cn(
        "gap-2 bg-card/70 ring-border/60 transition-colors hover:bg-card/90",
        onSelect && "cursor-pointer",
      )}
      onClick={onSelect}
    >
      <CardHeader className="gap-1.5">
        <div className="flex items-start justify-between gap-2">
          <CardTitle className="line-clamp-1 text-sm">
            {session.title}
          </CardTitle>
          <StatusBadge status={session.status} />
        </div>
        {session.branch && (
          <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <GitBranchIcon aria-hidden="true" className="size-3 shrink-0" />
            <span className="truncate">{session.branch}</span>
            {session.baseBranch && session.baseBranch !== session.branch && (
              <span className="text-[10px] text-muted-foreground/60">← {session.baseBranch}</span>
            )}
          </div>
        )}
      </CardHeader>

      {session.latestMessage && (
        <CardContent>
          <p className="line-clamp-2 text-xs text-muted-foreground">
            {session.latestMessage}
          </p>
        </CardContent>
      )}

      <CardFooter className="flex-wrap justify-between gap-2 border-t-0 bg-transparent text-xs text-muted-foreground">
        <div className="flex items-center gap-2">
          <span>{formatRelativeTime(session.updatedAt ?? session.createdAt)}</span>
          {hasStats && (
            <>
              <span className="text-green-600">+{stats.insertions}</span>
              <span className="text-red-500">-{stats.deletions}</span>
              {stats.commit_count > 0 && (
                <span>{stats.commit_count} {stats.commit_count === 1 ? "commit" : "commits"}</span>
              )}
            </>
          )}
        </div>
        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
          {session.ciStatus && <CIStatusDot status={session.ciStatus} />}
          {session.prUrl && (
            <a
              href={session.prUrl}
              target="_blank"
              rel="noreferrer"
              className="text-foreground hover:underline"
            >
              <GitPullRequestIcon className="size-3" />
            </a>
          )}
          {session.totalCostUsd != null && session.totalCostUsd > 0 && (
            <span className="font-mono">${session.totalCostUsd.toFixed(2)}</span>
          )}
          <ColumnAction
            columnId={columnId}
            session={session}
            actions={actions}
          />
        </div>
      </CardFooter>
    </Card>
  )
}

function ColumnAction({
  columnId,
  session,
  actions,
}: {
  columnId: string
  session: SessionCard
  actions: CardActions
}) {
  const btn = "h-5 px-1.5 text-[10px]"

  if (columnId === "in_progress") {
    const isPaused = session.status === "paused"
    return (
      <div className="flex items-center gap-1">
        {isPaused ? (
          <Button variant="ghost" size="sm" className={btn} onClick={() => actions.onResume(session.id)}>
            <ArrowCounterClockwiseIcon className="size-3" />
            Resume
          </Button>
        ) : (
          <>
            <Button variant="ghost" size="sm" className={btn} onClick={() => actions.onPause(session.id)}>
              <PauseIcon className="size-3" />
            </Button>
            <Button variant="ghost" size="sm" className={btn} onClick={() => actions.onStop(session.id)}>
              <StopIcon className="size-3" />
            </Button>
            <Button variant="outline" size="sm" className={btn} onClick={() => actions.onTransition(session.id, "in_review")}>
              Review
            </Button>
          </>
        )}
      </div>
    )
  }

  if (columnId === "in_review") {
    return (
      <div className="flex items-center gap-1">
        <Button variant="ghost" size="sm" className={btn} onClick={() => actions.onTransition(session.id, "active")}>
          <ArrowCounterClockwiseIcon className="size-3" />
        </Button>
        {!session.prUrl && (
          <Button variant="outline" size="sm" className={btn} onClick={() => actions.onCreatePR(session.id)}>
            <GitPullRequestIcon className="size-3" />
            PR
          </Button>
        )}
      </div>
    )
  }

  if (columnId === "merged") {
    return (
      <Button variant="ghost" size="sm" className={btn} onClick={() => actions.onTransition(session.id, "archived")}>
        <ArchiveIcon className="size-3" />
        Archive
      </Button>
    )
  }

  return null
}

function CIStatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    success: "bg-green-500",
    failure: "bg-red-500",
    pending: "bg-yellow-500",
  }
  return (
    <div
      className={cn("size-2 rounded-full", colors[status] ?? "bg-muted-foreground")}
      title={`CI: ${status}`}
    />
  )
}

function StatusBadge({ status }: { status: string }) {
  const s = status ?? "unknown"
  const n = s.toLowerCase()
  const variant =
    n.includes("fail") || n.includes("error")
      ? "destructive"
      : n === "active" || n === "starting" || n === "streaming"
        ? "secondary"
        : "outline"

  return (
    <Badge variant={variant} className="shrink-0 text-[10px]">
      {formatStatusLabel(s)}
    </Badge>
  )
}

function ColumnDot({ columnId }: { columnId: string }) {
  const colors: Record<string, string> = {
    backlog: "bg-muted-foreground/40",
    in_progress: "bg-blue-500",
    in_review: "bg-yellow-500",
    merged: "bg-green-500",
    archived: "bg-muted-foreground",
  }
  return (
    <div className={cn("size-2 rounded-full", colors[columnId] ?? "bg-muted-foreground")} />
  )
}

function BoardLoadingSkeleton() {
  return (
    <>
      {KANBAN_COLUMNS.map((col) => (
        <section key={col.id} className="flex w-72 shrink-0 flex-col">
          <header className="flex items-center justify-between px-3 py-2">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-5 w-6 rounded-full" />
          </header>
          <div className="flex flex-col gap-2 p-2">
            {[0, 1].map((i) => (
              <Card key={i} size="sm" className="gap-3 bg-card/70 ring-border/60">
                <CardHeader className="gap-2">
                  <Skeleton className="h-3 w-3/4" />
                  <Skeleton className="h-3 w-1/2" />
                </CardHeader>
                <CardFooter className="border-t-0 bg-transparent">
                  <Skeleton className="h-2.5 w-12" />
                </CardFooter>
              </Card>
            ))}
          </div>
        </section>
      ))}
    </>
  )
}

function searchSessions(sessions: SessionCard[], query: string): SessionCard[] {
  const q = query.trim().toLowerCase()
  if (!q) return sessions
  return sessions.filter((s) =>
    [s.title, s.status, s.repository, s.branch, s.harness, s.workspaceName, s.latestMessage]
      .filter(Boolean)
      .some((v) => v?.toLowerCase().includes(q)),
  )
}

function formatStatusLabel(value: string): string {
  const n = value.trim().toLowerCase()
  if (!n || n === "unknown") return "No status"
  return value
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (l) => l.toUpperCase())
}

function formatRelativeTime(value: string | undefined): string {
  if (!value) return "No activity"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return "No activity"

  const diffMs = Date.now() - date.getTime()
  const minutes = Math.max(1, Math.floor(diffMs / 60_000))
  if (minutes < 60) return `${minutes}m ago`

  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`

  return `${Math.floor(hours / 24)}d ago`
}
