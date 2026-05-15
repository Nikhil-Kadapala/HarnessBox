import { useState } from "react";
import { Gauge as GaugeIcon, DollarSign } from "lucide-react";
import { Gauge } from "@/components/ui/gauge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import type { CostBreakdown, SessionContextStats } from "@/types";

interface SessionMetricsProps {
  contextStats: SessionContextStats | null;
  costStats: CostBreakdown | null;
}

type TabType = "context" | "cost";

export function SessionMetrics({ contextStats, costStats }: SessionMetricsProps) {
  const [activeTab, setActiveTab] = useState<TabType>("context");
  const [open, setOpen] = useState(false);

  // Don't show button if no stats available
  if (!contextStats && !costStats) {
    return null;
  }

  const hasContext = contextStats && contextStats.percentUsed > 0;
  const hasCost = costStats && costStats.total_cost_usd > 0;

  // Show primary metric (prefer context if both available)
  const primaryValue = hasContext ? contextStats.percentUsed : 0;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="sm"
          className="h-8 gap-2 px-3 text-xs font-mono"
        >
          <GaugeIcon className="h-3.5 w-3.5" />
          <span>{primaryValue}%</span>
          {hasCost && <DollarSign className="h-3 w-3 text-muted-foreground" />}
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Session Metrics</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          {/* Tab Navigation */}
          <div className="flex gap-2 border-b">
            <button
              onClick={() => setActiveTab("context")}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "context"
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              disabled={!hasContext}
            >
              Context
            </button>
            <button
              onClick={() => setActiveTab("cost")}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "cost"
                  ? "border-foreground text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              disabled={!hasCost}
            >
              Cost
            </button>
          </div>

          {/* Tab Content */}
          <div className="py-4">
            {activeTab === "context" && hasContext && (
              <ContextTab contextStats={contextStats} />
            )}
            {activeTab === "cost" && hasCost && (
              <CostTab costStats={costStats} />
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ContextTab({ contextStats }: { contextStats: SessionContextStats }) {
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-center">
        <Gauge
          size="large"
          value={contextStats.percentUsed}
          showValue
        />
      </div>
      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Tokens Used</span>
          <span className="font-mono">{contextStats.tokensUsed.toLocaleString()}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Context Window</span>
          <span className="font-mono">{contextStats.contextWindow.toLocaleString()}</span>
        </div>
        {contextStats.model && (
          <div className="flex justify-between text-sm">
            <span className="text-muted-foreground">Model</span>
            <span className="font-mono text-xs">{contextStats.model}</span>
          </div>
        )}
      </div>
      {contextStats.categories.length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">Breakdown by Category</div>
          {contextStats.categories.map((cat) => (
            <div key={cat.key} className="flex justify-between text-sm">
              <span className="text-muted-foreground">{cat.label}</span>
              <span className="font-mono text-xs">{cat.tokens.toLocaleString()}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CostTab({ costStats }: { costStats: CostBreakdown }) {
  // Calculate a percentage for the gauge (cap at 100%, use $0.10 as max for visualization)
  const maxCostForGauge = 0.1;
  const costPercent = Math.min((costStats.total_cost_usd / maxCostForGauge) * 100, 100);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-center">
        <Gauge
          size="large"
          value={costPercent}
          showValue={false}
        />
      </div>
      <div className="space-y-2">
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Total Cost</span>
          <span className="font-mono font-medium">${costStats.total_cost_usd.toFixed(4)}</span>
        </div>
        <div className="flex justify-between text-sm">
          <span className="text-muted-foreground">Turns</span>
          <span className="font-mono">{costStats.turn_count}</span>
        </div>
      </div>
      {Object.keys(costStats.per_model).length > 0 && (
        <div className="space-y-2">
          <div className="text-xs font-medium text-muted-foreground">Per-Model Breakdown</div>
          {Object.entries(costStats.per_model).map(([model, data]) => (
            <div key={model} className="space-y-1 rounded-lg bg-secondary/50 p-3">
              <div className="text-sm font-medium truncate">{model}</div>
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Input → Output</span>
                <span className="font-mono">
                  {data.input_tokens.toLocaleString()} → {data.output_tokens.toLocaleString()}
                </span>
              </div>
              <div className="flex justify-between text-xs">
                <span className="text-muted-foreground">Cost</span>
                <span className="font-mono font-medium">${data.cost_usd.toFixed(4)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
