import type { UniversalEvent } from "@/types";

export interface SSEConfig {
  url: string;
  method?: "GET" | "POST";
  body?: Record<string, unknown>;
  lastEventId?: number;
  signal?: AbortSignal;
}

export async function* streamSSE(config: SSEConfig): AsyncGenerator<UniversalEvent> {
  const headers: Record<string, string> = {};
  if (config.method === "POST" || config.body) {
    headers["Content-Type"] = "application/json";
  }
  if (config.lastEventId != null) {
    headers["Last-Event-ID"] = String(config.lastEventId);
  }

  const response = await fetch(`/api${config.url}`, {
    method: config.method ?? (config.body ? "POST" : "GET"),
    headers,
    body: config.body ? JSON.stringify(config.body) : undefined,
    signal: config.signal,
  });

  if (!response.ok) {
    const text = await response.text().catch(() => "");
    throw new Error(`Server error ${response.status}: ${text || "empty response"}`);
  }

  if (!response.body) {
    throw new Error("No response body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

      let sepIndex = buffer.indexOf("\n\n");
      while (sepIndex !== -1) {
        const chunk = buffer.slice(0, sepIndex);
        buffer = buffer.slice(sepIndex + 2);

        const event = parseSSEChunk(chunk);
        if (event) yield event;

        sepIndex = buffer.indexOf("\n\n");
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseSSEChunk(chunk: string): UniversalEvent | null {
  if (!chunk.trim()) return null;

  const dataLines: string[] = [];
  for (const line of chunk.split("\n")) {
    if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trimStart());
    }
  }

  const data = dataLines.join("\n");
  if (!data.trim() || data === "[DONE]") return null;

  try {
    return JSON.parse(data) as UniversalEvent;
  } catch {
    return null;
  }
}
