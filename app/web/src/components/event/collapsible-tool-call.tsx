import { memo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import type { UniversalEvent } from "@/types";

interface CollapsibleToolCallProps {
  events: UniversalEvent[];
  defaultOpen?: boolean;
}

const toolIcons: Record<string, string> = {
  bash: ">",
  file_change: "~",
  file_read: "#",
  web: "@",
  agent: "A",
  other: "*",
};

export const CollapsibleToolCall = memo(function CollapsibleToolCall({
  events,
  defaultOpen = false,
}: CollapsibleToolCallProps) {
  const [open, setOpen] = useState(defaultOpen);

  const startEvent = events.find((e) => e.type === "item.started");
  const resultEvent = events.find((e) => e.message.item_kind === "tool_result");
  const deltas = events.filter((e) => e.type === "item.delta");
  const isCompleted = events.some(
    (e) => e.type === "item.completed" || e.message.item_kind === "tool_result",
  );
  const isError = resultEvent?.message.item_status === "failed";

  const toolName = startEvent?.message.content?.[0]?.tool_name ?? "Tool";
  const toolKind = startEvent?.message.tool_kind ?? resultEvent?.message.tool_kind ?? "other";
  const icon = toolIcons[toolKind] ?? "*";

  const resultContent = resultEvent?.message.content?.[0];
  const completedEvent = events.find(
    (e) => e.type === "item.completed" && e.message.item_kind === "tool_call",
  );
  const deltaText =
    completedEvent?.message.content?.[0]?.text ??
    deltas.map((d) => d.message.delta ?? "").join("");

  return (
    <div className="my-1">
      <button
        className="flex items-center gap-2 py-1 w-full text-left hover:bg-secondary/50 rounded px-1 -mx-1"
        onClick={() => setOpen(!open)}
      >
        <span className="inline-flex items-center justify-center h-4 w-4 rounded text-[10px] font-mono bg-secondary text-secondary-foreground shrink-0">
          {icon}
        </span>
        <span className="text-xs font-mono text-foreground">{toolName}</span>
        <Badge
          variant={isError ? "destructive" : isCompleted ? "outline" : "secondary"}
          className="text-[10px]"
        >
          {isError ? "failed" : isCompleted ? "done" : "running"}
        </Badge>
        {open ? (
          <ChevronDown className="h-3 w-3 text-muted-foreground ml-auto" />
        ) : (
          <ChevronRight className="h-3 w-3 text-muted-foreground ml-auto" />
        )}
      </button>

      {open && (
        <div className="pl-6 mt-1 space-y-1">
          {toolKind === "bash" && resultContent?.tool_input && (
            <div className="flex items-center gap-1.5 mb-1">
              <span className="text-[10px] text-muted-foreground">$</span>
              <code className="text-xs font-mono text-foreground">
                {resultContent.tool_input}
              </code>
            </div>
          )}

          {deltaText && !resultContent?.text && (
            <div className="max-h-[200px] overflow-y-auto rounded scrollbar-thin">
              <pre className="text-[11px] text-muted-foreground font-mono whitespace-pre-wrap">
                {deltaText}
              </pre>
            </div>
          )}

          {toolKind === "bash" && resultContent?.text && (
            <div className="max-h-[200px] overflow-y-auto rounded scrollbar-thin">
              <pre className="text-[11px] text-muted-foreground font-mono whitespace-pre-wrap">
                {resultContent.text.slice(0, 3000)}
              </pre>
            </div>
          )}

          {(toolKind === "file_change" || toolKind === "file_read") && resultContent && (
            <div className="flex items-center gap-2">
              <code className="text-xs font-mono text-foreground">
                {resultContent.file_path}
              </code>
              <Badge variant="outline" className="text-[10px]">
                {resultContent.file_action}
              </Badge>
            </div>
          )}

          {toolKind !== "bash" &&
            toolKind !== "file_change" &&
            toolKind !== "file_read" &&
            resultContent?.text && (
              <ScrollArea className="max-h-[200px]">
                <pre className="text-[11px] text-muted-foreground font-mono whitespace-pre-wrap">
                  {resultContent.text.slice(0, 2000)}
                </pre>
              </ScrollArea>
            )}
        </div>
      )}
    </div>
  );
});
