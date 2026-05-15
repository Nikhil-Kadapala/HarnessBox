export interface KanbanColumnDef {
  id: string
  title: string
  states: string[]
}

export const KANBAN_COLUMNS: KanbanColumnDef[] = [
  { id: "backlog", title: "Backlog", states: ["backlog"] },
  { id: "in_progress", title: "In progress", states: ["starting", "active", "paused"] },
  { id: "in_review", title: "In review", states: ["in_review"] },
  { id: "merged", title: "Merged", states: ["merged", "ending"] },
  { id: "archived", title: "Archived", states: ["archived", "failed", "ended"] },
]

export function getColumnForState(status: string): string {
  for (const col of KANBAN_COLUMNS) {
    if (col.states.includes(status)) return col.id
  }
  return "backlog"
}
