import { useMemo } from "react";
import { m } from "framer-motion";
import type { SessionContextStats } from "@/types";
import {
  CATEGORY_STYLES,
  formatTokenCount,
  getDisplayCategories,
} from "./shared";

interface ContextTrackerProps {
  contextStats: SessionContextStats | null;
}

export function ContextTracker({ contextStats }: ContextTrackerProps) {
  const displayCategories = useMemo(
    () => (contextStats ? getDisplayCategories(contextStats) : []),
    [contextStats],
  );

  const usedPercent = contextStats
    ? Math.min(Math.max(contextStats.percentUsed, 0), 100)
    : 0;

  const totalSegmentTokens = displayCategories.reduce(
    (sum, category) => sum + category.tokens,
    0,
  );

  // Loading state
  if (!contextStats) {
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
          Context usage appears after the first completed status poll.
        </p>
      </div>
    );
  }

  return (
    <>
      {/* Progress Bar */}
      <div className="mb-5 flex h-2 overflow-hidden rounded-full bg-muted">
        {displayCategories.map((category) => {
          const style = CATEGORY_STYLES[category.key] ?? {
            color: "#d4d4d8",
            label: category.label,
          };
          return (
            <m.div
              key={category.key}
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ duration: 0.35, ease: "easeOut" }}
              style={{
                backgroundColor: style.color,
                flexGrow: Math.max(category.tokens, 1),
                transformOrigin: "left",
              }}
            />
          );
        })}
        {contextStats.contextWindow > totalSegmentTokens && (
          <div
            className="bg-muted"
            style={{ flexGrow: contextStats.contextWindow - totalSegmentTokens }}
          />
        )}
      </div>

      {/* Category List */}
      <div className="space-y-3">
        {displayCategories.map((category) => {
          const style = CATEGORY_STYLES[category.key] ?? {
            color: "#d4d4d8",
            label: category.label,
          };
          return (
            <div
              key={category.key}
              className="flex items-center justify-between gap-4"
            >
              <div className="flex min-w-0 items-center gap-3">
                <span
                  className="h-4 w-4 shrink-0 rounded-sm"
                  style={{ backgroundColor: style.color }}
                />
                <span className="truncate text-sm font-medium text-foreground/90">
                  {style.label}
                </span>
              </div>
              <span className="shrink-0 text-sm font-semibold text-muted-foreground">
                {formatTokenCount(category.tokens)}
              </span>
            </div>
          );
        })}
      </div>
    </>
  );
}
