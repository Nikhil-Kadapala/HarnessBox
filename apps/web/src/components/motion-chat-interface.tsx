import { useCallback, useRef, useState, memo } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import Send from "lucide-react/dist/esm/icons/send";
import Square from "lucide-react/dist/esm/icons/square";
import Plus from "lucide-react/dist/esm/icons/plus";
import Paperclip from "lucide-react/dist/esm/icons/paperclip";
import ImageIcon from "lucide-react/dist/esm/icons/image";
import Mic from "lucide-react/dist/esm/icons/mic";
import { cn } from "@/lib/utils";
import { motion, useMotionValue, useSpring, AnimatePresence } from "framer-motion";

interface MotionChatInterfaceProps {
  disabled: boolean;
  isStreaming: boolean;
  onSubmit: (prompt: string) => void;
  onStop: () => void;
}

// Hoist static attachment button configs outside component (rendering-hoist-jsx)
const ATTACHMENT_BUTTONS = [
  { icon: Paperclip, label: "Attach file" },
  { icon: ImageIcon, label: "Image" },
  { icon: Mic, label: "Voice" },
] as const;

// Memoize component to prevent unnecessary re-renders (rerender-memo)
export const MotionChatInterface = memo(function MotionChatInterface({ disabled, isStreaming, onSubmit, onStop }: MotionChatInterfaceProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [value, setValue] = useState("");
  const [isFocused, setIsFocused] = useState(false);
  const [isMultiline, setIsMultiline] = useState(false);
  const [showAurora, setShowAurora] = useState(false);

  // Physics spring for input bar using motion
  const y = useMotionValue(0);
  const scale = useMotionValue(1);
  const springY = useSpring(y, { stiffness: 300, damping: 20, mass: 0.5 });
  const springScale = useSpring(scale, { stiffness: 300, damping: 15 });

  const handleSubmit = useCallback(() => {
    const trimmedValue = value.trim();
    if (!trimmedValue) return;

    // Trigger aurora burst
    setShowAurora(true);
    setTimeout(() => setShowAurora(false), 600);

    // Kick-up animation
    y.set(-8);
    scale.set(0.98);
    setTimeout(() => {
      y.set(0);
      scale.set(1);
    }, 200);

    onSubmit(trimmedValue);
    setValue("");
    setIsMultiline(false);
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }, [value, onSubmit, y, scale]);

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
    const lineHeight = 24;
    const lines = Math.floor(newHeight / lineHeight);
    setIsMultiline(lines > 1);
  }, []);

  const handleFocus = useCallback(() => {
    setIsFocused(true);
    // Subtle bounce on focus
    scale.set(1.01);
    setTimeout(() => scale.set(1), 150);
  }, [scale]);

  const handleBlur = useCallback(() => {
    setIsFocused(false);
  }, []);

  const toggleMultiline = useCallback(() => {
    setIsMultiline((prev) => !prev);
  }, []);

  return (
    <div className="relative border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      {/* Aurora burst effect */}
      <AnimatePresence>
        {showAurora && (
          <motion.div
            initial={{ opacity: 0, y: "100%" }}
            animate={{ opacity: [0, 1, 0], y: ["-100%"] }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.6, ease: "easeOut" }}
            className="absolute inset-x-0 bottom-0 h-32 pointer-events-none overflow-hidden"
          >
            <div className="absolute inset-0 bg-gradient-to-t from-primary/20 via-primary/10 to-transparent" />
          </motion.div>
        )}
      </AnimatePresence>

      <div className="container mx-auto max-w-4xl px-4 py-4 relative z-10">
        <motion.div
          style={{
            y: springY,
            scale: springScale,
          }}
          className="space-y-2"
        >
          {/* Attachment buttons (multiline mode) */}
          <AnimatePresence>
            {isMultiline && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: "auto" }}
                exit={{ opacity: 0, height: 0 }}
                transition={{ duration: 0.2 }}
              >
                <div className="flex items-center gap-2 px-2">
                  {ATTACHMENT_BUTTONS.map(({ icon: Icon, label }, idx) => (
                    <motion.div
                      key={label}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: idx * 0.05, duration: 0.2 }}
                    >
                      <Button
                        type="button"
                        size="sm"
                        variant="ghost"
                        className="h-8 text-xs text-muted-foreground hover:text-foreground"
                      >
                        <Icon className="h-3.5 w-3.5 mr-1.5" />
                        {label}
                      </Button>
                    </motion.div>
                  ))}
                </div>
              </motion.div>
            )}
          </AnimatePresence>

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
                  <motion.div
                    animate={{ rotate: isMultiline ? 45 : 0 }}
                    transition={{ duration: 0.2 }}
                  >
                    <Plus className="h-4 w-4" />
                  </motion.div>
                </Button>
                {isStreaming ? (
                  <motion.div
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                  >
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
                  </motion.div>
                ) : (
                  <motion.div
                    initial={{ scale: 0.9, opacity: 0 }}
                    animate={{ scale: 1, opacity: 1 }}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                  >
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
                  </motion.div>
                )}
              </div>
            </div>
          </div>
        </motion.div>

        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
          className="mt-2 text-center text-xs text-muted-foreground/60"
        >
          Press Enter to send, Shift+Enter for new line
        </motion.p>
      </div>
    </div>
  );
});
