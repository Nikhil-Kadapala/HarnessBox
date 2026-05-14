import type { ContextCategory, CostBreakdown, SessionContextStats, UniversalEvent } from "@/types";

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

export function getLatestSessionContextStats(events: UniversalEvent[]): SessionContextStats | null {
  let latest: SessionContextStats | null = null;

  for (const event of events) {
    if (event.event_type !== "status" || !isRecord(event.metadata)) continue;

    const context = event.metadata.context;
    if (!isRecord(context)) continue;

    const tokensUsed = readNumber(context.tokens_used);
    const contextWindow = readNumber(context.context_window);
    if (tokensUsed == null || contextWindow == null) continue;

    latest = {
      tokensUsed,
      contextWindow,
      percentUsed:
        readNumber(context.percent_used) ??
        (contextWindow > 0 ? Math.round((tokensUsed / contextWindow) * 100) : 0),
      model: readString(context.model),
      categories: readCategories(context.categories),
    };
  }

  return latest;
}

export function getLatestSessionCostStats(events: UniversalEvent[]): CostBreakdown | null {
  let latest: CostBreakdown | null = null;

  for (const event of events) {
    if (event.event_type !== "status" || !isRecord(event.metadata)) continue;

    const costBreakdown = event.metadata.cost_breakdown;
    if (!isRecord(costBreakdown)) continue;

    const totalCostUsd = readNumber(costBreakdown.total_cost_usd);
    const turnCount = readNumber(costBreakdown.turn_count);
    if (totalCostUsd == null || turnCount == null) continue;

    const perModel = costBreakdown.per_model;
    const perModelParsed: Record<string, { input_tokens: number; output_tokens: number; cost_usd: number }> = {};

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

    latest = {
      total_cost_usd: totalCostUsd,
      turn_count: turnCount,
      per_model: perModelParsed,
    };
  }

  return latest;
}
