import type { CacheStats, ContextCategory, CostBreakdown, ModelCostBreakdown, SessionContextStats, UniversalEvent } from "@/types";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readString(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function readCategories(value: unknown): ContextCategory[] {
  if (!Array.isArray(value)) return [];

  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const key = readString(item.key);
    const label = readString(item.label);
    const tokens = readNumber(item.tokens);
    if (!key || !label || tokens == null) return [];
    return [{ key, label, tokens }];
  });
}

function parseContextFromMetadata(metadata: Record<string, unknown>): SessionContextStats | null {
  const tokensUsed = readNumber(metadata.tokens_used);
  const contextWindow = readNumber(metadata.context_window);
  if (tokensUsed == null || contextWindow == null) return null;

  return {
    tokensUsed,
    contextWindow,
    percentUsed:
      readNumber(metadata.percent_used) ??
      (contextWindow > 0 ? Math.round((tokensUsed / contextWindow) * 100) : 0),
    model: readString(metadata.model),
    categories: readCategories(metadata.categories),
  };
}

function parseCostFromMetadata(metadata: Record<string, unknown>): CostBreakdown | null {
  const totalCostUsd = readNumber(metadata.total_cost_usd);
  const turnCount = readNumber(metadata.turn_count);
  if (totalCostUsd == null || turnCount == null) return null;

  const perModel = metadata.per_model;
  const perModelParsed: Record<string, ModelCostBreakdown> = {};

  if (isRecord(perModel)) {
    for (const [modelName, modelData] of Object.entries(perModel)) {
      if (!isRecord(modelData)) continue;
      const inputTokens = readNumber(modelData.input_tokens);
      const outputTokens = readNumber(modelData.output_tokens);
      const costUsd = readNumber(modelData.cost_usd);
      if (inputTokens == null || outputTokens == null || costUsd == null) continue;
      perModelParsed[modelName] = { input_tokens: inputTokens, output_tokens: outputTokens, cost_usd: costUsd };
    }
  }

  return { total_cost_usd: totalCostUsd, turn_count: turnCount, per_model: perModelParsed };
}

export function getLatestSessionContextStats(events: UniversalEvent[]): SessionContextStats | null {
  let latest: SessionContextStats | null = null;

  for (const event of events) {
    const metadata = event.message.metadata;
    if (!isRecord(metadata)) continue;

    if (event.type === "context.update") {
      const parsed = parseContextFromMetadata(metadata);
      if (parsed) latest = parsed;
    } else if (event.type === "status") {
      const context = metadata.context;
      if (isRecord(context)) {
        const parsed = parseContextFromMetadata(context);
        if (parsed) latest = parsed;
      }
    }
  }

  return latest;
}

export function getLatestSessionCostStats(events: UniversalEvent[]): CostBreakdown | null {
  let latest: CostBreakdown | null = null;

  for (const event of events) {
    const metadata = event.message.metadata;
    if (!isRecord(metadata)) continue;

    if (event.type === "cost.update") {
      const parsed = parseCostFromMetadata(metadata);
      if (parsed) latest = parsed;
    } else if (event.type === "status") {
      const costBreakdown = metadata.cost_breakdown;
      if (isRecord(costBreakdown)) {
        const parsed = parseCostFromMetadata(costBreakdown);
        if (parsed) latest = parsed;
      }
    }
  }

  return latest;
}

export function getLatestCacheStats(events: UniversalEvent[]): CacheStats | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    const metadata = event.message.metadata;
    if (
      (event.type === "turn.ended" || event.type === "session.ended") &&
      isRecord(metadata)
    ) {
      const usage = metadata.usage;
      if (isRecord(usage)) {
        const cacheRead = readNumber(usage.cache_read_input_tokens);
        const cacheCreation = readNumber(usage.cache_creation_input_tokens);
        if (cacheRead != null || cacheCreation != null) {
          return {
            cacheReadTokens: cacheRead ?? 0,
            cacheCreationTokens: cacheCreation ?? 0,
            inputTokens: readNumber(usage.input_tokens) ?? 0,
            outputTokens: readNumber(usage.output_tokens) ?? 0,
          };
        }
      }
    }
  }
  return null;
}
