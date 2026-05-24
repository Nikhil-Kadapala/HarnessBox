import { SessionMetricsMenu } from "@/components/metrics/SessionMetricsMenu";
import { getLatestSessionContextStats, getLatestSessionCostStats } from "@/lib/session-context";
import type { UniversalEvent } from "@/types";

const mockEvents: UniversalEvent[] = [
  {
    type: "status",
    timestamp: "2026-05-13T18:54:00Z",
    message: {
      event_id: "test-1",
      sequence: 1,
      session_id: "test-session",
      metadata: {
        context: {
          tokens_used: 18000,
          context_window: 200000,
          percent_used: 9,
          model: "claude-sonnet-4.5",
          categories: [
            { key: "system_prompt", label: "System prompt", tokens: 3200 },
            { key: "system_tools", label: "System tools", tokens: 16100 },
            { key: "messages", label: "Messages", tokens: 122 },
          ],
        },
        cost_breakdown: {
          total_cost_usd: 0.0234,
          turn_count: 3,
          per_model: {
            "claude-sonnet-4.5": {
              input_tokens: 3200,
              output_tokens: 1800,
              cost_usd: 0.0198,
            },
            "claude-haiku-4.5": {
              input_tokens: 500,
              output_tokens: 200,
              cost_usd: 0.0036,
            },
          },
        },
      },
    },
  },
];

export default function TestCostViz() {
  const contextStats = getLatestSessionContextStats(mockEvents);
  const costStats = getLatestSessionCostStats(mockEvents);

  return (
    <div className="h-screen flex flex-col bg-background">
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="text-center space-y-6 max-w-2xl">
          <h1 className="text-2xl font-bold">Metrics Visualization Test</h1>
          <p className="text-muted-foreground">
            Click the metrics button to test tab switching and animations
          </p>
        </div>
      </div>
      <div className="relative border-t bg-background/95 backdrop-blur">
        <div className="container mx-auto max-w-4xl px-4 py-4">
          <div className="flex justify-end">
            <SessionMetricsMenu
              contextStats={contextStats}
              costStats={costStats}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
