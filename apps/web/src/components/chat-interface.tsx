import { useCallback, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Square } from "lucide-react";
import { cn } from "@/lib/utils";

interface ChatInterfaceProps {
  disabled: boolean;
  isStreaming: boolean;
  onSubmit: (prompt: string) => void;
  onStop: () => void;
}

export function ChatInterface({ disabled, isStreaming, onSubmit, onStop }: ChatInterfaceProps) {
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
    // Auto-resize textarea
    e.target.style.height = "auto";
    e.target.style.height = `${e.target.scrollHeight}px`;
  }, []);

  return (
    <div className="border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container mx-auto max-w-4xl px-4 py-4">
        <div className="relative flex items-end gap-2">
          <div className="relative flex-1">
            <Textarea
              ref={textareaRef}
              value={value}
              onChange={handleChange}
              className={cn(
                "min-h-[52px] max-h-[200px] resize-none rounded-2xl border-border/50 pr-12 text-sm",
                "focus-visible:ring-1 focus-visible:ring-ring/50",
                "placeholder:text-muted-foreground/50",
              )}
              placeholder={isStreaming ? "Streaming..." : "Send a message..."}
              disabled={disabled || isStreaming}
              onKeyDown={handleKeyDown}
              rows={1}
            />
            <div className="absolute bottom-2 right-2">
              {isStreaming ? (
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 rounded-full hover:bg-destructive/10"
                  onClick={onStop}
                >
                  <Square className="h-4 w-4 fill-current text-destructive" />
                  <span className="sr-only">Stop</span>
                </Button>
              ) : (
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className={cn(
                    "h-8 w-8 rounded-full",
                    value.trim() && !disabled
                      ? "bg-primary text-primary-foreground hover:bg-primary/90"
                      : "text-muted-foreground/50",
                  )}
                  onClick={handleSubmit}
                  disabled={disabled || !value.trim()}
                >
                  <Send className="h-4 w-4" />
                  <span className="sr-only">Send</span>
                </Button>
              )}
            </div>
          </div>
        </div>
        <p className="mt-2 text-center text-xs text-muted-foreground/60">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>
    </div>
  );
}
