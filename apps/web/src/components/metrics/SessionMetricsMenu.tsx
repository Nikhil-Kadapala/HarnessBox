import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, LazyMotion, domAnimation, m } from "framer-motion";
import { DollarSign } from "lucide-react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { CostBreakdown, SessionContextStats } from "@/types";
import { ContextTracker } from "./ContextTracker";
import { CostTracker } from "./CostTracker";

interface SessionMetricsMenuProps {
  contextStats: SessionContextStats | null;
  costStats: CostBreakdown | null;
}

const panelVariants = {
  hidden: { opacity: 0, y: 8, scale: 0.96 },
  visible: { opacity: 1, y: 0, scale: 1 },
  exit: { opacity: 0, y: 6, scale: 0.97 },
};

export function SessionMetricsMenu({ contextStats, costStats }: SessionMetricsMenuProps) {
  const [contextOpen, setContextOpen] = useState(false);
  const [costOpen, setCostOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const usedPercent = contextStats
    ? Math.min(Math.max(contextStats.percentUsed, 0), 100)
    : 0;

  const toggleContext = useCallback(() => {
    setContextOpen((prev) => !prev);
    setCostOpen(false);
  }, []);

  const toggleCost = useCallback(() => {
    setCostOpen((prev) => !prev);
    setContextOpen(false);
  }, []);

  // Click-outside to close both
  useEffect(() => {
    if (!contextOpen && !costOpen) return;
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setContextOpen(false);
        setCostOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [contextOpen, costOpen]);

  // Gauge styling: green → blue → red
  const gaugeStroke = !contextStats
    ? "stroke-accent"
    : usedPercent >= 70
      ? "stroke-destructive"
      : usedPercent >= 25
        ? "stroke-blue-400"
        : "stroke-accent";

  const radius = 10;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (usedPercent / 100) * circumference;

  return (
    <LazyMotion features={domAnimation}>
      <div ref={containerRef} className="relative">
        {/* Context Panel */}
        <AnimatePresence>
          {contextOpen && (
            <m.div
              key="context-panel"
              variants={panelVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              transition={{ type: "spring", stiffness: 420, damping: 32, mass: 0.8 }}
              className="absolute bottom-full right-0 mb-2 w-[320px] rounded-xl border border-border bg-card px-4 py-3 text-card-foreground shadow-2xl shadow-black/20"
            >
              <h2 className="mb-4 text-sm font-semibold">Context Usage</h2>
              <ContextTracker contextStats={contextStats} />
            </m.div>
          )}
        </AnimatePresence>

        {/* Cost Panel */}
        <AnimatePresence>
          {costOpen && (
            <m.div
              key="cost-panel"
              variants={panelVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              transition={{ type: "spring", stiffness: 420, damping: 32, mass: 0.8 }}
              className="absolute bottom-full right-0 mb-2 w-[320px] rounded-xl border border-border bg-card px-4 py-3 text-card-foreground shadow-2xl shadow-black/20"
            >
              <h2 className="mb-4 text-sm font-semibold">Cost Tracking</h2>
              <CostTracker costStats={costStats} />
            </m.div>
          )}
        </AnimatePresence>

        {/* Trigger buttons */}
        <div className="flex items-center gap-2 rounded-full bg-muted/60 px-2 py-1">
          {/* Context gauge */}
          <Tooltip>
            <TooltipTrigger
              render={
                <m.button
                  type="button"
                  onClick={toggleContext}
                  className={cn(
                    "relative flex h-6 w-6 items-center justify-center rounded-full transition-colors",
                    contextOpen && "bg-accent/20",
                  )}
                  whileTap={{ scale: 0.9 }}
                  transition={{ type: "spring", stiffness: 400, damping: 17 }}
                />
              }
            >
              <svg className="h-6 w-6 -rotate-90" viewBox="0 0 24 24">
                <circle
                  cx="12"
                  cy="12"
                  r={radius}
                  className="stroke-muted"
                  strokeWidth="2"
                  fill="none"
                />
                <circle
                  cx="12"
                  cy="12"
                  r={radius}
                  className={gaugeStroke}
                  strokeWidth="2"
                  fill="none"
                  strokeDasharray={circumference}
                  strokeDashoffset={strokeDashoffset}
                  strokeLinecap="round"
                  style={{ transition: "stroke-dashoffset 0.5s ease" }}
                />
              </svg>
            </TooltipTrigger>
            <TooltipContent>Context usage</TooltipContent>
          </Tooltip>

          {/* Divider */}
          <div className="h-4 w-px bg-border" />

          {/* Cost icon */}
          <Tooltip>
            <TooltipTrigger
              render={
                <m.button
                  type="button"
                  onClick={toggleCost}
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full transition-colors",
                    costOpen
                      ? "bg-accent/20 text-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                  whileTap={{ scale: 0.9 }}
                  transition={{ type: "spring", stiffness: 400, damping: 17 }}
                />
              }
            >
              <DollarSign className="h-4 w-4" />
            </TooltipTrigger>
            <TooltipContent>Cost tracking</TooltipContent>
          </Tooltip>
        </div>
      </div>
    </LazyMotion>
  );
}
