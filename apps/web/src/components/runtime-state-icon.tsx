import { AlertCircle, Box, CirclePause, CircleStop, LoaderCircle } from "lucide-react";
import { runtimeAppearance } from "@/lib/runtime-state";

export function RuntimeStateIcon({ state, className = "" }: { state: string; className?: string }) {
  const appearance = runtimeAppearance(state);
  const normalizedState = state.toLowerCase();
  const isBusy = normalizedState === "creating" || normalizedState === "starting" || normalizedState === "ending" || normalizedState === "dying";
  const StateIcon = normalizedState === "paused"
    ? CirclePause
    : normalizedState === "dead" || normalizedState === "stopped" || normalizedState === "killed" || normalizedState === "ended"
      ? CircleStop
      : normalizedState === "failed" || normalizedState === "error"
        ? AlertCircle
        : isBusy
          ? LoaderCircle
          : Box;

  return (
    <span
      role="img"
      aria-label={`Runtime environment: ${appearance.label}`}
      title={`Runtime environment: ${appearance.label}`}
      className="inline-flex shrink-0"
    >
      <StateIcon aria-hidden="true" className={`${appearance.className} ${isBusy ? "animate-spin" : ""} ${className}`.trim()} />
    </span>
  );
}
