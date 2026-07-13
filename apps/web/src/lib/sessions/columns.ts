export interface KanbanColumnDef {
  id: string
  title: string
  states: string[]
}

export const KANBAN_COLUMNS: KanbanColumnDef[] = [
  { id: "running", title: "Running", states: ["starting", "active"] },
  { id: "paused", title: "Paused", states: ["paused"] },
  { id: "stopped", title: "Stopped", states: ["dying", "ended", "dead", "error"] },
]

export function getColumnForState(status: string): string {
  for (const col of KANBAN_COLUMNS) {
    if (col.states.includes(status)) return col.id
  }
  return "stopped"
}
