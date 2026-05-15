import { streamSSE } from "@/lib/sse";
import type { UniversalEvent } from "@/types";

export type StreamKey = string;

export interface StreamHandle {
  abort(): void;
}

export class SessionConnections {
  private controllers = new Map<StreamKey, AbortController>();
  private destroyed = new Set<string>();

  isDestroyed(sessionId: string): boolean {
    return this.destroyed.has(sessionId);
  }

  markDestroyed(sessionId: string): void {
    this.destroyed.add(sessionId);
  }

  start(key: StreamKey): AbortSignal {
    this.abort(key);
    const controller = new AbortController();
    this.controllers.set(key, controller);
    return controller.signal;
  }

  abort(key: StreamKey): void {
    this.controllers.get(key)?.abort();
    this.controllers.delete(key);
  }

  cleanup(key: StreamKey): void {
    this.controllers.delete(key);
  }

  abortAllForSession(sessionId: string): void {
    this.abort(sessionId);
    this.abort(`reconnect-${sessionId}`);
    this.abort(`create-${sessionId}`);
  }

  async *streamEvents(opts: {
    key: StreamKey;
    url: string;
    method?: "GET" | "POST";
    body?: Record<string, unknown>;
    lastEventId?: number;
  }): AsyncGenerator<UniversalEvent> {
    const signal = this.start(opts.key);
    try {
      yield* streamSSE({
        url: opts.url,
        method: opts.method,
        body: opts.body,
        lastEventId: opts.lastEventId,
        signal,
      });
    } finally {
      this.cleanup(opts.key);
    }
  }
}
