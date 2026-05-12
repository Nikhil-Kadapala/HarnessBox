import { useCallback, useRef, useState, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Send, Square, Plus, Paperclip, Image as ImageIcon, Mic } from "lucide-react";
import { cn } from "@/lib/utils";
import { useSpring, animated } from "@react-spring/web";

interface EnhancedChatInterfaceProps {
  disabled: boolean;
  isStreaming: boolean;
  onSubmit: (prompt: string) => void;
  onStop: () => void;
}

export function EnhancedChatInterface({ disabled, isStreaming, onSubmit, onStop }: EnhancedChatInterfaceProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const [isMultiline, setIsMultiline] = useState(false);
  const [showAurora, setShowAurora] = useState(false);

  // Physics spring for input bar
  const [inputSpring, inputSpringApi] = useSpring(() => ({
    y: 0,
    scale: 1,
    config: { tension: 180, friction: 12 },
  }));

  // Attachment buttons stagger animation
  const [attachmentsSpring, attachmentsSpringApi] = useSpring(() => ({
    opacity: 0,
    height: 0,
    config: { tension: 280, friction: 20 },
  }));

  useEffect(() => {
    if (isMultiline) {
      attachmentsSpringApi.start({ opacity: 1, height: 40 });
    } else {
      attachmentsSpringApi.start({ opacity: 0, height: 0 });
    }
  }, [isMultiline, attachmentsSpringApi]);

  const handleSubmit = useCallback(() => {
    const trimmedValue = value.trim();
    if (!trimmedValue) return;

    // Trigger aurora burst
    setShowAurora(true);
    setTimeout(() => setShowAurora(false), 600);

    // Kick-up animation
    inputSpringApi.start({
      y: -8,
      scale: 0.98,
      immediate: false,
      onRest: () => {
        inputSpringApi.start({ y: 0, scale: 1 });
      },
    });

    onSubmit(trimmedValue);
    setValue("");
    setIsMultiline(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, onSubmit, inputSpringApi]);

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
    const newValue = e.target.value;
    setValue(newValue);

    // Auto-resize textarea
    e.target.style.height = "auto";
    const newHeight = e.target.scrollHeight;
    e.target.style.height = `${newHeight}px`;

    // Determine if multiline
    const lineHeight = 24; // approximate
    const lines = Math.floor(newHeight / lineHeight);
    setIsMultiline(lines > 1);
  }, []);

  const handleFocus = useCallback(() => {
    setIsFocused(true);
    inputSpringApi.start({
      scale: 1.01,
      config: { tension: 180, friction: 12 },
      onRest: () => {
        inputSpringApi.start({ scale: 1 });
      },
    });
  }, [inputSpringApi]);

  const handleBlur = useCallback(() => {
    setIsFocused(false);
  }, []);

  const toggleMultiline = useCallback(() => {
    setIsMultiline((prev) => !prev);
  }, []);

  return (
    <div className="relative border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      {/* Aurora burst effect */}
      {showAurora && (
        <div className="absolute inset-x-0 bottom-0 h-32 pointer-events-none overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-t from-primary/20 via-primary/10 to-transparent animate-aurora-sweep" />
        </div>
      )}

      <div className="container mx-auto max-w-4xl px-4 py-4 relative z-10">
        <animated.div
          style={{
            transform: inputSpring.y.to((y) => `translateY(${y}px)`),
            scale: inputSpring.scale,
          }}
          className="space-y-2"
        >
          {/* Attachment buttons (multiline mode) */}
          <animated.div
            style={{
              opacity: attachmentsSpring.opacity,
              height: attachmentsSpring.height,
              overflow: "hidden",
            }}
          >
            <div className="flex items-center gap-2 px-2">
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-8 text-xs text-muted-foreground hover:text-foreground"
              >
                <Paperclip className="h-3.5 w-3.5 mr-1.5" />
                Attach file
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-8 text-xs text-muted-foreground hover:text-foreground"
              >
                <ImageIcon className="h-3.5 w-3.5 mr-1.5" />
                Image
              </Button>
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="h-8 text-xs text-muted-foreground hover:text-foreground"
              >
                <Mic className="h-3.5 w-3.5 mr-1.5" />
                Voice
              </Button>
            </div>
          </animated.div>

          {/* Input area */}
          <div className="relative flex items-end gap-2">
            <div className="relative flex-1">
              <Textarea
                ref={textareaRef}
                value={value}
                onChange={handleChange}
                onFocus={handleFocus}
                onBlur={handleBlur}
                className={cn(
                  "min-h-[52px] max-h-[200px] resize-none rounded-2xl border-border/50 pr-24 text-sm transition-all",
                  "focus-visible:ring-1 focus-visible:ring-ring/50",
                  "placeholder:text-muted-foreground/50",
                  isFocused && "border-border shadow-sm",
                )}
                placeholder={isStreaming ? "Streaming..." : "Send a message..."}
                disabled={disabled || isStreaming}
                onKeyDown={handleKeyDown}
                rows={1}
              />
              <div className="absolute bottom-2 right-2 flex items-center gap-1">
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  className="h-8 w-8 rounded-full hover:bg-accent"
                  onClick={toggleMultiline}
                  title="Toggle attachments"
                >
                  <Plus className={cn("h-4 w-4 transition-transform", isMultiline && "rotate-45")} />
                </Button>
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
                      "h-8 w-8 rounded-full transition-all",
                      value.trim() && !disabled
                        ? "bg-primary text-primary-foreground hover:bg-primary/90 shadow-sm"
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
        </animated.div>

        <p className="mt-2 text-center text-xs text-muted-foreground/60">
          Press Enter to send, Shift+Enter for new line
        </p>
      </div>

      <style jsx>{`
        @keyframes aurora-sweep {
          0% {
            opacity: 0;
            transform: translateY(100%);
          }
          50% {
            opacity: 1;
          }
          100% {
            opacity: 0;
            transform: translateY(-100%);
          }
        }
        .animate-aurora-sweep {
          animation: aurora-sweep 0.6s ease-out forwards;
        }
      `}</style>
    </div>
  );
}
