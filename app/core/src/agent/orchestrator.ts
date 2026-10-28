import type { ServerResponse } from "node:http";
import { sessionStore } from "./session.js";
import { McpManager } from "../mcp/manager.js";
import { ModelProvider, type ChatMessage } from "../providers/meta.js";
import { traceBus } from "../trace/bus.js";
import { getApiKey, type AppConfig } from "../config.js";

export interface TurnOptions {
  maxSteps?: number;
  apiKey?: string;
  baseUrl?: string;
  modelName?: string;
  provider?: string;
}

export class Orchestrator {
  private provider: ModelProvider;

  constructor(
    private config: AppConfig,
    private mcpManager: McpManager
  ) {
    this.provider = new ModelProvider(config);
  }

  public async runTurn(
    sessionId: string,
    userPrompt: string,
    options: TurnOptions,
    res: ServerResponse
  ): Promise<void> {
    const session = sessionStore.getSession(sessionId);
    if (!session) {
      res.write(`event: error\ndata: ${JSON.stringify({ error: `Session '${sessionId}' not found` })}\n\n`);
      res.end();
      return;
    }

    // Append user message
    sessionStore.appendMessage(sessionId, {
      role: "user",
      content: userPrompt,
    });

    const apiKey = options.apiKey || getApiKey(options.provider || this.config.model.provider);
    const maxSteps = options.maxSteps ?? this.config.limits.maxSteps ?? 1;
    const tools = this.mcpManager.getChatCompletionsTools();

    let step = 0;
    let finalAnswer = "";

    traceBus.emitTrace({
      type: "turn_start",
      source: "orchestrator",
      title: `Turn Started (Session: ${sessionId})`,
      data: { sessionId, promptPreview: userPrompt.substring(0, 100), maxSteps },
    });

    try {
      while (step <= maxSteps) {
        step++;
        let stepDeltaText = "";

        // Send model call event
        res.write(
          `event: step_start\ndata: ${JSON.stringify({
            step,
            maxSteps,
          })}\n\n`
        );

        const turnOutput = await this.provider.callStreaming(
          session.messages,
          tools,
          apiKey,
          {
            onDelta: (chunk) => {
              stepDeltaText += chunk;
              res.write(`event: delta\ndata: ${JSON.stringify({ text: chunk })}\n\n`);
            },
            onToolCall: (tc) => {
              res.write(
                `event: tool_call_start\ndata: ${JSON.stringify({
                  id: tc.id,
                  name: tc.name,
                  args: tc.arguments,
                })}\n\n`
              );
            },
          },
          options.baseUrl,
          options.modelName
        );

        finalAnswer += turnOutput.reply;

        // If no tool calls, model gave direct answer
        if (!turnOutput.toolCalls || turnOutput.toolCalls.length === 0) {
          sessionStore.appendMessage(sessionId, {
            role: "assistant",
            content: turnOutput.reply,
          });
          break;
        }

        // Record assistant tool calls in conversation history
        sessionStore.appendMessage(sessionId, {
          role: "assistant",
          content: turnOutput.reply || "",
          tool_calls: turnOutput.toolCalls.map((tc) => ({
            id: tc.id,
            type: "function",
            function: {
              name: tc.name,
              arguments: JSON.stringify(tc.arguments),
            },
          })),
        });

        // Execute all tool calls in parallel
        const toolExecutionPromises = turnOutput.toolCalls.map(async (tc) => {
          const result = await this.mcpManager.executeTool(tc.name, tc.arguments);
          res.write(
            `event: tool_call_done\ndata: ${JSON.stringify({
              id: tc.id,
              name: tc.name,
              resultPreview: result.content.substring(0, 300),
              isTruncated: !!result.bufferId,
              bufferId: result.bufferId,
              isError: result.isError,
            })}\n\n`
          );

          return {
            tool_call_id: tc.id,
            name: tc.name,
            content: result.content,
          };
        });

        const settledResults = await Promise.allSettled(toolExecutionPromises);

        // Append tool results to session history
        for (const item of settledResults) {
          if (item.status === "fulfilled") {
            sessionStore.appendMessage(sessionId, {
              role: "tool",
              tool_call_id: item.value.tool_call_id,
              name: item.value.name,
              content: item.value.content,
            });
          }
        }

        // If we reached maxSteps, make one final call to generate synthesis
        if (step >= maxSteps) {
          res.write(`event: synthesis_start\ndata: ${JSON.stringify({ step })}\n\n`);
          const synthesisOutput = await this.provider.callStreaming(
            session.messages,
            [], // no tools in synthesis phase
            apiKey,
            {
              onDelta: (chunk) => {
                finalAnswer += chunk;
                res.write(`event: delta\ndata: ${JSON.stringify({ text: chunk })}\n\n`);
              },
            },
            options.baseUrl,
            options.modelName
          );

          sessionStore.appendMessage(sessionId, {
            role: "assistant",
            content: synthesisOutput.reply,
          });
          break;
        }
      }

      // Conclude SSE stream
      res.write(
        `event: done\ndata: ${JSON.stringify({
          sessionId,
          finalAnswer,
          messageCount: session.messages.length,
        })}\n\n`
      );
      res.end();

      traceBus.emitTrace({
        type: "turn_end",
        source: "orchestrator",
        title: `Turn Complete (${sessionId})`,
        data: { sessionId, stepsTaken: step, answerLength: finalAnswer.length },
      });
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      res.write(`event: error\ndata: ${JSON.stringify({ error: errMsg })}\n\n`);
      res.end();
    }
  }
}
