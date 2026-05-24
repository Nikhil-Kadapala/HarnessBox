import { useCallback, useRef, useState, memo } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  ArrowUp,
  Plus,
  Square,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { LazyMotion, domAnimation, m, AnimatePresence } from "framer-motion";
import type { CostBreakdown, SessionContextStats } from "@/types";
import { SessionMetricsMenu } from "@/components/metrics/SessionMetricsMenu";

interface MotionChatInterfaceProps {
  disabled: boolean;
  isStreaming: boolean;
  contextStats: SessionContextStats | null;
  costStats: CostBreakdown | null;
  onSubmit: (prompt: string) => void;
  onStop: () => void;
}

export const MotionChatInterface = memo(function MotionChatInterface({
  disabled,
  isStreaming,
  contextStats,
  costStats,
  onSubmit,
  onStop,
}: MotionChatInterfaceProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("");

  const handleSubmit = useCallback(() => {
    const trimmedValue = value.trim();
    if (!trimmedValue) return;
    onSubmit(trimmedValue);
    setValue("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, onSubmit]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setValue(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${e.target.scrollHeight}px`;
  }, []);

  return (
    <LazyMotion features={domAnimation}>
      <div className="pb-4 pt-2 px-4">
        <div className="mx-auto max-w-4xl space-y-2">
          {/* Input container */}
          <div className="relative rounded-2xl border border-border/60 bg-secondary/50 transition-colors focus-within:border-border focus-within:bg-secondary/80">
            {/* Textarea */}
            <Textarea
              ref={textareaRef}
              value={value}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              className="min-h-[52px] max-h-[200px] resize-none border-0 bg-transparent px-4 pt-3.5 pb-12 text-[15px] shadow-none focus-visible:ring-0 placeholder:text-muted-foreground/50"
              placeholder={isStreaming ? "Send to interrupt..." : "Ask for follow-up changes"}
              disabled={disabled}
              rows={1}
            />

            {/* Bottom toolbar inside the input */}
            <div className="absolute bottom-2 left-2 right-2 flex items-center justify-between">
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-7 w-7 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted"
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </div>

              <div className="flex items-center gap-2">
                <SessionMetricsMenu contextStats={contextStats} costStats={costStats} />
                <AnimatePresence mode="wait">
                  {isStreaming && !value.trim() ? (
                    <m.div
                      key="stop"
                      initial={{ scale: 0.8, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0.8, opacity: 0 }}
                      transition={{ duration: 0.1 }}
                    >
                      <Button
                        type="button"
                        size="icon"
                        variant="ghost"
                        className="h-7 w-7 rounded-lg hover:bg-destructive/10"
                        onClick={onStop}
                      >
                        <Square className="h-3.5 w-3.5 fill-current text-destructive" />
                        <span className="sr-only">Stop</span>
                      </Button>
                    </m.div>
                  ) : (
                    <m.div
                      key="send"
                      initial={{ scale: 0.8, opacity: 0 }}
                      animate={{ scale: 1, opacity: 1 }}
                      exit={{ scale: 0.8, opacity: 0 }}
                      transition={{ duration: 0.1 }}
                    >
                      <Button
                        type="button"
                        size="icon"
                        className={cn(
                          "h-7 w-7 rounded-lg transition-all",
                          value.trim() && !disabled
                            ? "bg-accent text-accent-foreground hover:bg-accent/90"
                            : "bg-muted text-muted-foreground cursor-default",
                        )}
                        onClick={handleSubmit}
                        disabled={disabled || !value.trim()}
                      >
                        <ArrowUp className="h-4 w-4" />
                        <span className="sr-only">Send</span>
                      </Button>
                    </m.div>
                  )}
                </AnimatePresence>
              </div>
            </div>
          </div>

          {/* Footer row */}
          <div className="px-1 text-center text-xs text-muted-foreground/60">
            <span>Press Enter to send, Shift+Enter for new line</span>
          </div>
        </div>
      </div>
    </LazyMotion>
  );
});
