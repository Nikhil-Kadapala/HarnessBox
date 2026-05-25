import type { ContextCategory, SessionContextStats } from "@/types";

// ============================================================================
// Constants
// ============================================================================

export const CATEGORY_STYLES: Record<string, { color: string; label: string }> = {
  system_prompt: { color: "#9ca3af", label: "System prompt" },
  system_tools: { color: "#7dd3fc", label: "System tools" },
  memory_files: { color: "#fb923c", label: "Memory files" },
  tools: { color: "#a78bfa", label: "Tools" },
  rules: { color: "#4ade80", label: "Rules" },
  skills: { color: "#fdba74", label: "Skills" },
  mcp: { color: "#d8a7ca", label: "MCP" },
  subagents: { color: "#93c5fd", label: "Subagents" },
  messages: { color: "#f29a8a", label: "Messages" },
  conversation: { color: "#f29a8a", label: "Conversation" },
  free_space: { color: "#3f3f46", label: "Free space" },
  autocompact_buffer: { color: "#71717a", label: "Autocompact buffer" },
  used_context: { color: "#f29a8a", label: "Used context" },
} as const;

const CATEGORY_ORDER = [
  "system_prompt",
  "system_tools",
  "memory_files",
  "tools",
  "rules",
  "skills",
  "mcp",
  "subagents",
  "messages",
  "conversation",
  "free_space",
  "autocompact_buffer",
] as const;

// ============================================================================
// Utilities
// ============================================================================

export function formatTokenCount(tokens: number): string {
  if (tokens >= 1_000_000) return `${(tokens / 1_000_000).toFixed(1)}M`;
  if (tokens >= 1_000) return `${(tokens / 1_000).toFixed(1)}K`;
  return tokens.toLocaleString();
}

export function getDisplayCategories(stats: SessionContextStats): ContextCategory[] {
  if (stats.categories.length === 0) {
    return [
      {
        key: "used_context",
        label: CATEGORY_STYLES.used_context.label,
        tokens: stats.tokensUsed,
      },
    ];
  }

  return [...stats.categories].sort((a, b) => {
    const aIndex = CATEGORY_ORDER.indexOf(a.key as (typeof CATEGORY_ORDER)[number]);
    const bIndex = CATEGORY_ORDER.indexOf(b.key as (typeof CATEGORY_ORDER)[number]);
    if (aIndex === -1 && bIndex === -1) return a.label.localeCompare(b.label);
    if (aIndex === -1) return 1;
    if (bIndex === -1) return -1;
    return aIndex - bIndex;
  });
}
