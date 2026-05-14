import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, LazyMotion, domAnimation, m } from "framer-motion";
import useMeasure from "react-use-measure";
import { DollarSign, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { CostBreakdown, SessionContextStats } from "@/types";
import { ContextTracker } from "./ContextTracker";
import { CostTracker } from "./CostTracker";
import { type MetricsTab, contentVariants, panelVariants } from "./shared";

interface SessionMetricsMenuProps {
  contextStats: SessionContextStats | null;
  costStats: CostBreakdown | null;
}

export function SessionMetricsMenu({ contextStats, costStats }: SessionMetricsMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<MetricsTab>("context");
  const [direction, setDirection] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const [contentRef] = useMeasure();

  // Computed values
  const usedPercent = contextStats
    ? Math.min(Math.max(contextStats.percentUsed, 0), 100)
    : 0;

  // Tab change handler
  const handleTabChange = useCallback(
    (newTab: MetricsTab) => {
      const newDirection = newTab === "cost" ? 1 : -1;
      setDirection(newDirection);
      setActiveTab(newTab);
      if (!isOpen) setIsOpen(true);
    },
    [isOpen],
  );

  // Click-outside handler
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    if (isOpen) {
      document.addEventListener("mousedown", handler);
      return () => document.removeEventListener("mousedown", handler);
    }
  }, [isOpen]);

  // Gauge stroke color based on usage
  const gaugeStroke = !contextStats
    ? "stroke-muted-foreground/50"
    : usedPercent >= 80
      ? "stroke-destructive"
      : usedPercent >= 60
        ? "stroke-warning"
        : "stroke-accent";

  // Circle progress calculation (circumference = 2πr, r=10 → ~62.83)
  const radius = 10;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (usedPercent / 100) * circumference;

  return (
    <LazyMotion features={domAnimation}>
      <div ref={containerRef} className="relative">
        {/* Panel */}
        <AnimatePresence>
          {isOpen && (
            <m.div
              key="metrics-panel"
              variants={panelVariants}
              initial="hidden"
              animate="visible"
              exit="exit"
              transition={{ type: "spring", stiffness: 420, damping: 34, mass: 0.8 }}
              className="absolute bottom-full right-0 mb-2 w-[360px] rounded-xl border border-border bg-card px-4 py-3 text-card-foreground shadow-2xl shadow-black/20"
            >
              {/* Header */}
              <div className="mb-4 flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-sm font-semibold leading-none">
                    {activeTab === "context" ? "Context Usage" : "Cost Tracking"}
                  </h2>
                </div>
                <Button
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  className="h-5 w-5 rounded-full text-muted-foreground hover:text-foreground"
                  onClick={() => setIsOpen(false)}
                >
                  <X className="h-3 w-3" />
                  <span className="sr-only">Close</span>
                </Button>
              </div>

              {/* Content Area with Measured Height */}
              <m.div className="overflow-hidden">
                <div ref={contentRef}>
                  <AnimatePresence mode="popLayout" custom={direction}>
                    {activeTab === "context" && (
                      <m.div
                        key="context-content"
                        custom={direction}
                        variants={contentVariants}
                        initial="enter"
                        animate="center"
                        exit="exit"
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                      >
                        <ContextTracker contextStats={contextStats} />
                      </m.div>
                    )}
                    {activeTab === "cost" && (
                      <m.div
                        key="cost-content"
                        custom={direction}
                        variants={contentVariants}
                        initial="enter"
                        animate="center"
                        exit="exit"
                        transition={{ duration: 0.3, ease: "easeInOut" }}
                      >
                        <CostTracker costStats={costStats} />
                      </m.div>
                    )}
                  </AnimatePresence>
                </div>
              </m.div>
            </m.div>
          )}
        </AnimatePresence>

        {/* Button - Fixed Width with Icons Only */}
        <div className="flex items-center gap-2 rounded-full bg-muted/60 px-2 py-1">
          {/* Circular Gauge */}
          <Tooltip>
            <TooltipTrigger
              render={
                <m.button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleTabChange("context");
                  }}
                  className={cn(
                    "relative flex h-6 w-6 items-center justify-center rounded-full transition-colors",
                    activeTab === "context" && isOpen && "bg-accent/20",
                  )}
                  whileTap={{ scale: 0.9 }}
                  transition={{ type: "spring", stiffness: 400, damping: 17 }}
                />
              }
            >
              <svg className="h-6 w-6 -rotate-90" viewBox="0 0 24 24">
                {/* Background circle */}
                <circle
                  cx="12"
                  cy="12"
                  r={radius}
                  className="stroke-muted"
                  strokeWidth="2"
                  fill="none"
                />
                {/* Progress circle */}
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

          {/* Dollar Icon */}
          <Tooltip>
            <TooltipTrigger
              render={
                <m.button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleTabChange("cost");
                  }}
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full transition-colors",
                    activeTab === "cost" && isOpen
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
