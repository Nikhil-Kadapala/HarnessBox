import { m } from "framer-motion";
import type { CostBreakdown } from "@/types";

interface CostTrackerProps {
  costStats: CostBreakdown | null;
}

export function CostTracker({ costStats }: CostTrackerProps) {
  // Loading state
  if (!costStats) {
    return (
      <div className="space-y-3">
        <div className="h-2 overflow-hidden rounded-full bg-muted">
          <m.div
            className="h-full w-1/3 rounded-full bg-muted-foreground/40"
            animate={{ opacity: [0.35, 0.8, 0.35], x: ["-100%", "300%"] }}
            transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          />
        </div>
        <p className="text-sm text-muted-foreground">
          Cost tracking appears after the first turn completes.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-4">
        <m.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.1, duration: 0.3 }}
          className="rounded-lg bg-secondary/50 p-3"
        >
          <p className="text-xs text-muted-foreground mb-1">Total Cost</p>
          <p className="text-lg font-semibold font-mono">
            ${costStats.total_cost_usd.toFixed(4)}
          </p>
        </m.div>
        <m.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ delay: 0.2, duration: 0.3 }}
          className="rounded-lg bg-secondary/50 p-3"
        >
          <p className="text-xs text-muted-foreground mb-1">Turns</p>
          <p className="text-lg font-semibold font-mono">{costStats.turn_count}</p>
        </m.div>
      </div>

      {/* Per-Model Breakdown */}
      {Object.keys(costStats.per_model).length > 0 && (
        <div className="space-y-3">
          <h3 className="text-xs font-medium text-muted-foreground">
            Per-Model Breakdown
          </h3>
          {Object.entries(costStats.per_model).map(([model, data], idx) => (
            <m.div
              key={model}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: idx * 0.1, duration: 0.3 }}
              className="space-y-2 rounded-lg bg-secondary/30 p-3"
            >
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm font-medium truncate">{model}</span>
                <span className="text-sm font-semibold font-mono">
                  ${data.cost_usd.toFixed(4)}
                </span>
              </div>
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Input tokens</span>
                <span className="font-mono">{data.input_tokens.toLocaleString()}</span>
              </div>
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Output tokens</span>
                <span className="font-mono">{data.output_tokens.toLocaleString()}</span>
              </div>
            </m.div>
          ))}
        </div>
      )}
    </div>
  );
}
