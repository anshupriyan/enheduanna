import { traceBus } from "../trace/bus.js";
import { type AppConfig } from "../config.js";

export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  name?: string;
  tool_call_id?: string;
  tool_calls?: Array<{
    id: string;
    type: "function";
    function: {
      name: string;
      arguments: string;
    };
  }>;
}

export interface StreamCallbacks {
  onDelta?: (text: string) => void;
  onToolCall?: (toolCall: { id: string; name: string; arguments: Record<string, unknown> }) => void;
  onError?: (err: Error) => void;
}

export interface ModelTurnOutput {
  reply: string;
  toolCalls: Array<{
    id: string;
    name: string;
    arguments: Record<string, unknown>;
  }>;
  rawResponse?: unknown;
  usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number };
}

export class ModelProvider {
  constructor(private config: AppConfig) {}

  public async callStreaming(
    messages: ChatMessage[],
    tools: Array<{ type: "function"; function: { name: string; description: string; parameters: Record<string, unknown> } }>,
    apiKey: string,
    callbacks: StreamCallbacks,
    customBaseUrl?: string,
    customModelName?: string
  ): Promise<ModelTurnOutput> {
    const startTime = Date.now();
    const baseUrl = customBaseUrl || this.config.model.baseUrl || "https://api.meta.ai/v1";
    const model = customModelName || this.config.model.modelName || "muse-spark-1.3";

    traceBus.emitTrace({
      type: "turn_start",
      source: "meta-api",
      title: `Model Call: ${model}`,
      data: { model, baseUrl, messageCount: messages.length, toolCount: tools.length },
    });

    const endpoint = `${baseUrl.replace(/\/+$/, "")}/chat/completions`;

    const payload = {
      model,
      messages,
      tools: tools.length > 0 ? tools : undefined,
      stream: true,
      temperature: 0.2,
    };

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    if (apiKey) {
      headers["Authorization"] = `Bearer ${apiKey}`;
    }

    const response = await fetch(endpoint, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      const errText = await response.text();
      const err = new Error(`API returned HTTP ${response.status}: ${errText}`);
      traceBus.emitTrace({
        type: "error",
        source: "meta-api",
        title: `API Error: HTTP ${response.status}`,
        data: { status: response.status, error: errText },
        latencyMs: Date.now() - startTime,
      });
      callbacks.onError?.(err);
      throw err;
    }

    if (!response.body) {
      throw new Error("No response body received from model API");
    }

    let fullReply = "";
    const activeToolCalls: Map<number, { id: string; name: string; argumentsStr: string }> = new Map();
    let usage: ModelTurnOutput["usage"] = undefined;

    const reader = response.body.getReader();
    const decoder = new TextDecoder("utf-8");
    let buffer = "";

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed || trimmed.startsWith(":") || trimmed === "data: [DONE]") {
            continue;
          }

          if (trimmed.startsWith("data: ")) {
            const jsonStr = trimmed.substring(6);
            try {
              const data = JSON.parse(jsonStr);
              if (data.usage) {
                usage = data.usage;
              }

              const choice = data.choices?.[0];
              if (!choice) continue;

              const delta = choice.delta;
              if (delta?.content) {
                fullReply += delta.content;
                callbacks.onDelta?.(delta.content);
              }

              if (delta?.tool_calls) {
                for (const tc of delta.tool_calls) {
                  const idx = tc.index ?? 0;
                  if (!activeToolCalls.has(idx)) {
                    activeToolCalls.set(idx, {
                      id: tc.id || `call_${Date.now()}_${idx}`,
                      name: tc.function?.name || "",
                      argumentsStr: tc.function?.arguments || "",
                    });
                  } else {
                    const current = activeToolCalls.get(idx)!;
                    if (tc.id) current.id = tc.id;
                    if (tc.function?.name) current.name += tc.function.name;
                    if (tc.function?.arguments) current.argumentsStr += tc.function.arguments;
                  }
                }
              }
            } catch {}
          }
        }
      }
    } finally {
      reader.releaseLock();
    }

    const durationMs = Date.now() - startTime;
    const finalToolCalls: ModelTurnOutput["toolCalls"] = [];

    for (const [, tc] of activeToolCalls) {
      let parsedArgs: Record<string, unknown> = {};
      try {
        parsedArgs = tc.argumentsStr ? JSON.parse(tc.argumentsStr) : {};
      } catch {
        parsedArgs = { raw: tc.argumentsStr };
      }
      finalToolCalls.push({
        id: tc.id,
        name: tc.name,
        arguments: parsedArgs,
      });
      callbacks.onToolCall?.({
        id: tc.id,
        name: tc.name,
        arguments: parsedArgs,
      });
    }

    traceBus.emitTrace({
      type: "model_request",
      source: "meta-api",
      title: `Model Response (${durationMs}ms)`,
      data: {
        model,
        durationMs,
        replyLength: fullReply.length,
        toolCallCount: finalToolCalls.length,
        toolCalls: finalToolCalls.map((t) => ({ name: t.name, id: t.id })),
        usage,
      },
      latencyMs: durationMs,
    });

    return {
      reply: fullReply,
      toolCalls: finalToolCalls,
      usage,
    };
  }
}
