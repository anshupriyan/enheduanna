import { EventEmitter } from "node:events";
import type { ServerResponse } from "node:http";

export interface TraceEvent {
  id: string;
  timestamp: string;
  type:
    | "turn_start"
    | "turn_end"
    | "model_request"
    | "model_chunk"
    | "tool_call"
    | "tool_result"
    | "tool_group"
    | "capture_toggle"
    | "error"
    | "warning"
    | "system";
  source: "orchestrator" | "meta-api" | "mcp-memvision" | "mcp-cli-bridge" | "capture" | "system";
  title: string;
  data: Record<string, unknown>;
  latencyMs?: number;
}

// Secret scrubbing patterns (aligns with memvision privacy engine)
const REDACTION_PATTERNS = [
  /sk-[a-zA-Z0-9_-]{20,}/g,
  /sk-ant-[a-zA-Z0-9_-]{20,}/g,
  /sk-or-v1-[a-zA-Z0-9_-]{20,}/g,
  /ghp_[a-zA-Z0-9]{36,}/g,
  /Bearer\s+[a-zA-Z0-9_\-\.]{20,}/gi,
  /AIza[0-9A-Za-z-_]{35}/g,
  /["']?(?:api[_-]?key|password|secret|token)["']?\s*[:=]\s*["']?([a-zA-Z0-9_\-\.]{12,})["']?/gi,
];

export function redactSecrets(input: string): string {
  if (!input || typeof input !== "string") return input;
  let text = input;
  for (const pat of REDACTION_PATTERNS) {
    text = text.replace(pat, (match) => {
      if (match.toLowerCase().startsWith("bearer ")) {
        return "Bearer [REDACTED_TOKEN]";
      }
      return "[REDACTED_SECRET]";
    });
  }
  return text;
}

export function redactObject<T>(obj: T): T {
  if (!obj) return obj;
  try {
    const raw = JSON.stringify(obj);
    return JSON.parse(redactSecrets(raw));
  } catch {
    return obj;
  }
}

class TraceBus extends EventEmitter {
  private buffer: TraceEvent[] = [];
  private maxBufferSize = 100;

  constructor() {
    super();
    this.setMaxListeners(50);
  }

  public emitTrace(event: Omit<TraceEvent, "id" | "timestamp">): TraceEvent {
    const fullEvent: TraceEvent = {
      ...event,
      id: `tr_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`,
      timestamp: new Date().toISOString(),
      data: redactObject(event.data),
    };

    // Keep circular buffer
    this.buffer.push(fullEvent);
    if (this.buffer.length > this.maxBufferSize) {
      this.buffer.shift();
    }

    this.emit("event", fullEvent);
    return fullEvent;
  }

  public getRecentEvents(limit: number = 50): TraceEvent[] {
    return this.buffer.slice(-limit);
  }

  public handleSseStream(res: ServerResponse): () => void {
    res.writeHead(200, {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "Access-Control-Allow-Origin": "*",
    });

    // Send initial snapshot of recent events
    const initialEvents = this.getRecentEvents(30);
    for (const evt of initialEvents) {
      res.write(`data: ${JSON.stringify(evt)}\n\n`);
    }

    const listener = (evt: TraceEvent) => {
      res.write(`data: ${JSON.stringify(evt)}\n\n`);
    };

    this.on("event", listener);

    // Heartbeat every 15s to keep connection alive
    const interval = setInterval(() => {
      res.write(": keepalive\n\n");
    }, 15000);

    const cleanup = () => {
      clearInterval(interval);
      this.off("event", listener);
    };

    res.on("close", cleanup);
    res.on("error", cleanup);

    return cleanup;
  }
}

export const traceBus = new TraceBus();
