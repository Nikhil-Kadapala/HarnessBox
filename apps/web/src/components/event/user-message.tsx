import { memo } from "react";
import { cn } from "@/lib/utils";

interface UserMessageProps {
  text: string;
  timestamp?: string;
}

export const UserMessage = memo(function UserMessage({ text, timestamp }: UserMessageProps) {
  return (
    <div className="flex justify-end mb-4">
      <div className="max-w-[80%]">
        <div
          className={cn(
            "rounded-2xl rounded-tr-sm px-4 py-2.5",
            "bg-secondary text-secondary-foreground",
          )}
        >
          <p className="text-[15px] whitespace-pre-wrap break-words">{text}</p>
        </div>
        {timestamp && (
          <p className="text-xs text-muted-foreground mt-1 text-right">
            {new Date(timestamp).toLocaleTimeString()}
          </p>
        )}
      </div>
    </div>
  );
});
