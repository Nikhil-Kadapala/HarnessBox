/**
 * Session Board — Kanban-style view of HarnessBox sessions
 *
 * Ported from Cursor's Agent Kanban with adaptations for HarnessBox.
 * Provides:
 * - Grouped columns (status, repository, date)
 * - Session cards with status, repo, artifacts
 * - Search and filtering
 * - Create session dialog
 */

import * as React from "react"
import {
  ArrowClockwiseIcon,
  CaretLeftIcon,
  CaretRightIcon,
  CirclesFourIcon,
  ClockIcon,
  GitBranchIcon,
  ImageSquareIcon,
  KanbanIcon,
  MagnifyingGlassIcon,
  PlusIcon,
} from "@phosphor-icons/react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Separator } from "@/components/ui/separator"
import { fetchSessions } from "@/lib/sessions/client"
import type {
  GroupBy,
  SessionCard,
  SidebarFilter,
} from "@/lib/sessions/types"
import { cn } from "@/lib/utils"

type IconComponent = React.ElementType

type GroupOption = {
  id: GroupBy
  label: string
  icon: IconComponent
}

type SelectableGroupOption = GroupOption & {
  selectable: boolean
}

const defaultGroupBy: GroupBy = "status"

const groupOptions: GroupOption[] = [
  { id: "status", label: "Status", icon: CirclesFourIcon },
  { id: "repository", label: "Repository", icon: KanbanIcon },
  { id: "createdAt", label: "Created date", icon: ClockIcon },
]

const dateBucketOrder = new Map([
  ["Today", 0],
  ["Yesterday", 1],
  ["This week", 2],
  ["This month", 3],
  ["Older", 4],
  ["No date", 5],
])

const sidebarFilters: {
  id: SidebarFilter
  label: string
  icon: IconComponent
}[] = [
  { id: "all", label: "All sessions", icon: CirclesFourIcon },
  { id: "recentlyActive", label: "Recently active", icon: ClockIcon },
  { id: "paused", label: "Paused", icon: GitBranchIcon },
  { id: "failed", label: "Failed", icon: ImageSquareIcon },
]

const boardLoadingColumns: {
  id: string
  title: string
  icon: IconComponent
  cards: number
}[] = [
  { id: "creating", title: "Creating", icon: CirclesFourIcon, cards: 2 },
  { id: "active", title: "Active", icon: ClockIcon, cards: 3 },
  { id: "paused", title: "Paused", icon: KanbanIcon, cards: 1 },
]

const loadingCardLineWidths = [
  ["w-11/12", "w-2/3"],
  ["w-4/5", "w-1/2"],
  ["w-3/4", "w-5/6"],
] as const

export function SessionBoardApp() {
  const [sessions, setSessions] = React.useState<SessionCard[]>([])
  const [groupBy, setGroupBy] = React.useState<GroupBy>(defaultGroupBy)
  const [sidebarFilter, setSidebarFilter] = React.useState<SidebarFilter>("all")
  const [query, setQuery] = React.useState("")
  const [isLoading, setIsLoading] = React.useState(false)
  const [error, setError] = React.useState<string | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = React.useState(false)

  const loadBoard = React.useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const loadedSessions = await fetchSessions()
      setSessions(loadedSessions)
    } catch (loadError) {
      setError(errorMessage(loadError, "Failed to load sessions."))
    } finally {
      setIsLoading(false)
    }
  }, [])

  React.useEffect(() => {
    loadBoard()
  }, [loadBoard])

  const selectableGroupOptions = React.useMemo(
    () => getSelectableGroupOptions(sessions),
    [sessions]
  )
  const selectedGroupBy = isSelectableGroupBy(groupBy, selectableGroupOptions)
    ? groupBy
    : defaultGroupBy

  const searchedSessions = searchSessions(sessions, query)
  const visibleSessions = filterSessionsBySidebar(searchedSessions, sidebarFilter)
  const showBoardLoading = isLoading && sessions.length === 0 && visibleSessions.length === 0
  const sidebarItems = sidebarFilters.map((item) => ({
    ...item,
    count: filterSessionsBySidebar(searchedSessions, item.id).length,
  }))
  const selectedGroupOption = groupOptions.find((option) => option.id === selectedGroupBy)
  const SelectedGroupIcon = selectedGroupOption?.icon
  const groups = groupSessions(visibleSessions, selectedGroupBy)

  return (
    <div className="flex h-screen min-h-0 bg-background text-foreground">
      <aside
        className={cn(
          "hidden shrink-0 border-r bg-sidebar/70 transition-[width] duration-200 lg:flex lg:flex-col",
          isSidebarCollapsed ? "w-16" : "w-64"
        )}
      >
        <div
          className={cn(
            "flex h-14 items-center px-3",
            isSidebarCollapsed ? "justify-center" : "gap-2"
          )}
        >
          {isSidebarCollapsed ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setIsSidebarCollapsed(false)}
              aria-label="Expand sidebar"
              title="Expand sidebar"
            >
              <CaretRightIcon />
            </Button>
          ) : (
            <>
              <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
                <KanbanIcon aria-hidden="true" className="size-4" />
              </div>
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-semibold">Session Board</div>
                <div className="truncate text-xs text-muted-foreground">
                  HarnessBox Sessions
                </div>
              </div>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setIsSidebarCollapsed(true)}
                aria-label="Collapse sidebar"
                title="Collapse sidebar"
              >
                <CaretLeftIcon />
              </Button>
            </>
          )}
        </div>
        <Separator />
        <nav
          className={cn(
            "flex flex-1 flex-col gap-1 text-sm",
            isSidebarCollapsed ? "items-center p-2" : "p-3"
          )}
          aria-label="Session filters"
        >
          {sidebarItems.map((item) => (
            <SidebarItem
              key={item.id}
              active={sidebarFilter === item.id}
              collapsed={isSidebarCollapsed}
              count={item.count}
              icon={item.icon}
              label={item.label}
              onSelect={() => setSidebarFilter(item.id)}
            />
          ))}
        </nav>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-3 border-b px-4">
          <div className="relative flex min-w-48 flex-1 items-center">
            <MagnifyingGlassIcon
              aria-hidden="true"
              className="pointer-events-none absolute left-2.5 size-4 text-muted-foreground"
            />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search sessions and repos..."
              className="h-8 border-0 bg-muted/60 pl-8"
            />
          </div>

          <Select
            value={selectedGroupBy}
            onValueChange={(value) => {
              if (isSelectableGroupBy(value, selectableGroupOptions)) {
                setGroupBy(value)
              } else {
                setGroupBy(defaultGroupBy)
              }
            }}
          >
            <SelectTrigger aria-label="Group sessions" className="w-[180px] h-8">
              {SelectedGroupIcon ? (
                <SelectedGroupIcon
                  aria-hidden="true"
                  className="text-muted-foreground size-4"
                />
              ) : null}
              <SelectValue />
            </SelectTrigger>
            <SelectContent align="end">
              <SelectGroup>
                {selectableGroupOptions.map((option) => (
                  <SelectItem
                    key={option.id}
                    value={option.id}
                    disabled={!option.selectable}
                  >
                    <GroupOptionContent option={option} />
                  </SelectItem>
                ))}
              </SelectGroup>
            </SelectContent>
          </Select>

          <div className="hidden shrink-0 items-center gap-2 text-xs text-muted-foreground xl:flex">
            <span>{visibleSessions.length} shown</span>
            {isLoading ? (
              <Badge variant="secondary">Syncing</Badge>
            ) : (
              <Badge variant="outline">Live data</Badge>
            )}
          </div>
          <div className="shrink-0 xl:hidden">
            {isLoading ? (
              <Badge variant="secondary">Syncing</Badge>
            ) : (
              <Badge variant="outline">Live data</Badge>
            )}
          </div>

          <Button variant="outline" size="sm" onClick={loadBoard} disabled={isLoading}>
            <ArrowClockwiseIcon className="size-4" />
            Refresh
          </Button>
          <Button size="sm">
            <PlusIcon className="size-4" />
            New session
          </Button>
        </header>

        {error ? (
          <div className="border-b bg-destructive/10 px-4 py-2 text-sm text-destructive">
            {error}
          </div>
        ) : null}

        <section className="flex min-h-0 flex-1 flex-col">
          <ScrollArea className="min-h-0 flex-1">
            <div className="flex min-h-full gap-3 p-4">
              {groups.length > 0 ? (
                groups.map((group) => (
                  <BoardColumn
                    key={group.id}
                    title={group.title}
                    icon={selectedGroupOption?.icon ?? CirclesFourIcon}
                    sessions={group.sessions}
                  />
                ))
              ) : showBoardLoading ? (
                <BoardLoadingSkeleton />
              ) : (
                <EmptyBoard />
              )}
            </div>
          </ScrollArea>
        </section>
      </main>
    </div>
  )
}

function BoardColumn({
  title,
  icon: Icon,
  sessions,
}: {
  title: string
  icon: IconComponent
  sessions: SessionCard[]
}) {
  return (
    <section className="flex w-80 shrink-0 flex-col rounded-xl bg-muted/20">
      <header className="flex items-center justify-between px-3 py-2">
        <div className="flex items-center gap-2">
          <Icon aria-hidden="true" className="size-3.5 shrink-0 text-muted-foreground" />
          <h2 className="truncate text-sm font-medium">{title}</h2>
        </div>
        <Badge variant="secondary">{sessions.length}</Badge>
      </header>
      <div className="flex flex-col gap-2 p-2">
        {sessions.map((session) => (
          <SessionCardPreview key={session.id} session={session} />
        ))}
      </div>
    </section>
  )
}

function SessionCardPreview({ session }: { session: SessionCard }) {
  const hasCardContent = Boolean(session.latestMessage || session.artifacts.length > 0)

  return (
    <Card
      size="sm"
      className="gap-3 bg-card/70 ring-border/60 transition-colors hover:bg-card/90"
    >
      <CardHeader className="gap-2">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="line-clamp-2">{session.title}</CardTitle>
          <StatusBadge status={session.status} />
        </div>
        <CardDescription className="flex items-center gap-1.5 truncate text-xs">
          <GitBranchIcon aria-hidden="true" className="size-3.5 shrink-0" />
          <span className="truncate">
            {session.repository || session.workspaceName || "No workspace"}
          </span>
        </CardDescription>
      </CardHeader>
      {hasCardContent ? (
        <CardContent className="flex flex-col gap-3">
          {session.latestMessage ? (
            <p className="line-clamp-2 text-sm text-muted-foreground">
              {session.latestMessage}
            </p>
          ) : null}
        </CardContent>
      ) : null}
      <CardFooter className="flex-wrap justify-between gap-2 border-t-0 bg-transparent text-xs text-muted-foreground">
        <span>{formatRelativeTime(session.updatedAt ?? session.createdAt)}</span>
        <span className="text-muted-foreground">{session.harness}</span>
      </CardFooter>
    </Card>
  )
}

function BoardLoadingSkeleton() {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-label="Loading sessions"
      className="flex min-h-[60vh] flex-1 gap-3"
    >
      <span className="sr-only">Loading sessions</span>
      {boardLoadingColumns.map((column) => {
        const Icon = column.icon

        return (
          <section
            key={column.id}
            className="flex w-80 shrink-0 flex-col rounded-xl border bg-muted/20 shadow-sm"
          >
            <header className="flex items-center justify-between px-3 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="flex size-5 items-center justify-center rounded-md bg-background/70 text-muted-foreground">
                  <Icon aria-hidden="true" className="size-3.5" />
                </span>
                <div
                  className="h-3 w-20 animate-pulse rounded-full bg-muted"
                  aria-hidden="true"
                />
              </div>
              <div
                className="h-5 w-8 animate-pulse rounded-full bg-background/80 ring-1 ring-border/60"
                aria-hidden="true"
              />
            </header>
            <div className="flex flex-col gap-2 p-2">
              {Array.from({ length: column.cards }).map((_, cardIndex) => {
                const [titleWidth] =
                  loadingCardLineWidths[cardIndex % loadingCardLineWidths.length]

                return (
                  <Card
                    key={`${column.id}-${cardIndex}`}
                    size="sm"
                    className="gap-3 bg-card/70 ring-border/60"
                  >
                    <CardHeader className="gap-2">
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex min-w-0 flex-1 flex-col gap-2">
                          <div
                            className={cn(
                              "h-3 animate-pulse rounded-full bg-muted",
                              titleWidth
                            )}
                            aria-hidden="true"
                          />
                          <div
                            className="h-3 w-7/12 animate-pulse rounded-full bg-muted/70"
                            aria-hidden="true"
                          />
                        </div>
                        <div
                          className="h-5 w-16 animate-pulse rounded-full bg-muted/80"
                          aria-hidden="true"
                        />
                      </div>
                    </CardHeader>
                    <CardFooter className="flex-wrap justify-between gap-2 border-t-0 bg-transparent">
                      <div
                        className="h-2.5 w-12 animate-pulse rounded-full bg-muted"
                        aria-hidden="true"
                      />
                      <div
                        className="h-2.5 w-8 animate-pulse rounded-full bg-muted/70"
                        aria-hidden="true"
                      />
                    </CardFooter>
                  </Card>
                )
              })}
            </div>
          </section>
        )
      })}
    </div>
  )
}

function GroupOptionContent({ option }: { option: SelectableGroupOption }) {
  const Icon = option.icon

  return (
    <span className="flex min-w-0 items-center gap-2">
      <Icon aria-hidden="true" className="shrink-0 text-muted-foreground size-4" />
      <span className="truncate">{groupOptionLabel(option)}</span>
    </span>
  )
}

function SidebarItem({
  active,
  collapsed = false,
  count,
  icon: Icon,
  label,
  onSelect,
}: {
  active: boolean
  collapsed?: boolean
  count: number
  icon: IconComponent
  label: string
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      aria-label={collapsed ? `${label}: ${count}` : undefined}
      onClick={onSelect}
      title={collapsed ? `${label}: ${count}` : undefined}
      className={cn(
        "relative flex w-full items-center gap-2 rounded-lg text-muted-foreground transition-colors outline-none hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground focus-visible:ring-2 focus-visible:ring-ring [&_svg]:size-4 [&_svg]:shrink-0",
        collapsed ? "size-11 justify-center p-0" : "px-2 py-1.5 text-left",
        active && "bg-sidebar-accent text-sidebar-accent-foreground"
      )}
    >
      <Icon aria-hidden="true" />
      {collapsed ? (
        <Badge
          variant={active ? "secondary" : "outline"}
          className="absolute -right-1 -top-1 h-4 min-w-4 px-1 text-[0.65rem]"
        >
          {count}
        </Badge>
      ) : (
        <>
          <span className="min-w-0 flex-1 truncate">{label}</span>
          <Badge variant={active ? "secondary" : "outline"}>{count}</Badge>
        </>
      )}
    </button>
  )
}

function EmptyBoard() {
  return (
    <div className="flex min-h-[50vh] flex-1 items-center justify-center">
      <Card className="w-full max-w-md text-center">
        <CardHeader>
          <CardTitle>No sessions found</CardTitle>
          <CardDescription>
            Create a session or adjust your search to populate the board.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button>
            <PlusIcon className="size-4" />
            New session
          </Button>
        </CardContent>
      </Card>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const normalized = status.toLowerCase()
  const variant =
    normalized.includes("fail") || normalized.includes("error")
      ? "destructive"
      : normalized.includes("active") || normalized.includes("streaming")
        ? "secondary"
        : normalized === "ended"
          ? "outline"
          : "outline"

  return <Badge variant={variant}>{formatStatusLabel(status)}</Badge>
}

function groupSessions(sessions: SessionCard[], groupBy: GroupBy) {
  const groups = new Map<string, SessionCard[]>()

  for (const session of sessions) {
    const title = groupTitle(session, groupBy)
    const group = groups.get(title) ?? []
    group.push(session)
    groups.set(title, group)
  }

  const entries = Array.from(groups.entries())
  if (groupBy === "createdAt") {
    entries.sort(
      ([leftTitle], [rightTitle]) => dateBucketRank(leftTitle) - dateBucketRank(rightTitle)
    )
  }

  return entries.map(([title, group]) => ({
    id: `${groupBy}-${title}`,
    title,
    sessions: group,
  }))
}

function dateBucketRank(title: string) {
  return dateBucketOrder.get(title) ?? dateBucketOrder.size
}

function groupTitle(session: SessionCard, groupBy: GroupBy) {
  if (groupBy === "createdAt") {
    return dateBucket(session.createdAt)
  }

  const value = session[groupBy]
  if (groupBy === "status" && typeof value === "string" && value.trim()) {
    return formatStatusLabel(value)
  }

  if (groupBy === "repository") {
    return session.repository || session.workspaceName || "No workspace"
  }

  return typeof value === "string" && value.trim() ? value : "Unassigned"
}

function searchSessions(sessions: SessionCard[], query: string) {
  const normalizedQuery = query.trim().toLowerCase()
  if (!normalizedQuery) {
    return sessions
  }

  return sessions.filter((session) =>
    [
      session.title,
      session.status,
      session.repository,
      session.branch,
      session.harness,
      session.workspaceName,
      session.latestMessage,
    ]
      .filter(Boolean)
      .some((value) => value?.toLowerCase().includes(normalizedQuery))
  )
}

function filterSessionsBySidebar(sessions: SessionCard[], filter: SidebarFilter) {
  if (filter === "recentlyActive") {
    return sessions.filter((session) =>
      isRecentlyActive(session.updatedAt ?? session.createdAt)
    )
  }

  if (filter === "paused") {
    return sessions.filter((session) => session.status.toLowerCase() === "paused")
  }

  if (filter === "failed") {
    return sessions.filter((session) =>
      ["error", "failed"].includes(session.status.toLowerCase())
    )
  }

  return sessions
}

function isRecentlyActive(value: string | undefined) {
  if (!value) {
    return false
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return false
  }

  const diffMs = Date.now() - date.getTime()
  return diffMs >= 0 && diffMs <= 86_400_000
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback
}

function getSelectableGroupOptions(_sessions: SessionCard[]): SelectableGroupOption[] {
  return groupOptions.map((option) => ({
    ...option,
    selectable: true, // All options always selectable
  }))
}

function groupOptionLabel(option: SelectableGroupOption) {
  return option.selectable ? option.label : `${option.label} (no data)`
}

function isSelectableGroupBy(
  value: string | null,
  options: SelectableGroupOption[]
): value is GroupBy {
  return options.some((option) => option.id === value && option.selectable)
}

function titleCase(value: string) {
  return value
    .replace(/[_-]/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function formatStatusLabel(value: string) {
  const normalized = value.trim().toLowerCase()
  if (!normalized || normalized === "unknown") {
    return "No status"
  }

  return titleCase(value)
}

function dateBucket(value: string | undefined) {
  if (!value) {
    return "No date"
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return "No date"
  }

  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffDays = Math.floor(diffMs / 86_400_000)

  if (diffDays <= 0) {
    return "Today"
  }
  if (diffDays === 1) {
    return "Yesterday"
  }
  if (diffDays < 7) {
    return "This week"
  }
  if (diffDays < 30) {
    return "This month"
  }
  return "Older"
}

function formatRelativeTime(value: string | undefined) {
  if (!value) {
    return "No activity"
  }

  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return "No activity"
  }

  const diffMs = Date.now() - date.getTime()
  const minutes = Math.max(1, Math.floor(diffMs / 60_000))
  if (minutes < 60) {
    return `${minutes}m ago`
  }

  const hours = Math.floor(minutes / 60)
  if (hours < 24) {
    return `${hours}h ago`
  }

  const days = Math.floor(hours / 24)
  return `${days}d ago`
}
