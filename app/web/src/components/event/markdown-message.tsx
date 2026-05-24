import { memo } from "react";
import { Streamdown } from "streamdown";
import { code } from "@streamdown/code";

interface MarkdownMessageProps {
  text: string;
  isStreaming?: boolean;
}

const plugins = { code };

export const MarkdownMessage = memo(function MarkdownMessage({
  text,
  isStreaming = false,
}: MarkdownMessageProps) {
  return (
    <div className="text-[15px] leading-relaxed text-foreground max-w-none">
      <Streamdown
        plugins={plugins}
        isAnimating={isStreaming}
        shikiTheme={["github-dark", "github-dark"]}
      >
        {text}
      </Streamdown>
    </div>
  );
});
