import { useCallback, useRef } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

interface PromptInputProps {
  disabled: boolean;
  isStreaming: boolean;
  onSubmit: (prompt: string) => void;
  onStop: () => void;
}

export function PromptInput({ disabled, isStreaming, onSubmit, onStop }: PromptInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleSubmit = useCallback(() => {
    const value = textareaRef.current?.value.trim();
    if (!value) return;
    onSubmit(value);
    if (textareaRef.current) textareaRef.current.value = "";
  }, [onSubmit]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  return (
    <div className="flex items-end gap-2 p-4 border-t border-border">
      <Textarea
        ref={textareaRef}
        className="min-h-[40px] max-h-[120px] resize-none text-sm font-mono"
        placeholder={isStreaming ? "Streaming..." : "Enter a prompt..."}
        disabled={disabled || isStreaming}
        onKeyDown={handleKeyDown}
        rows={1}
      />
      {isStreaming ? (
        <Button variant="destructive" size="sm" onClick={onStop} className="shrink-0">
          Stop
        </Button>
      ) : (
        <Button size="sm" onClick={handleSubmit} disabled={disabled} className="shrink-0">
          Send
        </Button>
      )}
    </div>
  );
}
