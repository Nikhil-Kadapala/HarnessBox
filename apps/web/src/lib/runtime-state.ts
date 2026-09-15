interface RuntimeAppearance {
  label: string;
  className: string;
}

const runtimeAppearances: Record<string, RuntimeAppearance> = {
  creating: { label: "Creating", className: "text-amber-500" },
  starting: { label: "Starting", className: "text-amber-500" },
  active: { label: "Running", className: "text-emerald-500" },
  streaming: { label: "Running", className: "text-blue-500" },
  running: { label: "Running", className: "text-emerald-500" },
  paused: { label: "Paused", className: "text-amber-500" },
  ending: { label: "Stopping", className: "text-muted-foreground" },
  dying: { label: "Stopping", className: "text-muted-foreground" },
  dead: { label: "Stopped", className: "text-muted-foreground" },
  stopped: { label: "Stopped", className: "text-muted-foreground" },
  killed: { label: "Stopped", className: "text-muted-foreground" },
  ended: { label: "Ended", className: "text-muted-foreground" },
  failed: { label: "Failed", className: "text-destructive" },
  error: { label: "Error", className: "text-destructive" },
};

export function runtimeAppearance(state: string): RuntimeAppearance {
  return runtimeAppearances[state.toLowerCase()] ?? {
    label: state || "Unknown",
    className: "text-muted-foreground",
  };
}

export function runtimeStateLabel(state: string): string {
  return runtimeAppearance(state).label;
}
