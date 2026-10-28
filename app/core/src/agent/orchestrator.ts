import type { ServerResponse } from "node:http";
import { sessionStore } from "./session.js";
import { McpManager } from "../mcp/manager.js";
import { ModelProvider } from "../providers/meta.js";
import { traceBus } from "../trace/bus.js";
import { getApiKey, type AppConfig } from "../config.js";
import { getSystemPrompt } from "../prompts/loader.js";

export interface TurnOptions {
  maxSteps?: number;
  maxParallelToolCalls?: number;
  apiKey?: string;
  baseUrl?: string;
  modelName?: string;
  provider?: string;
}

export interface StepExecutionResult {
  step: number;
  reply: string;
  reasoning?: string;
  toolCalls: Array<{
    id: string;
    name: string;
    arguments: Record<string, unknown>;
  }>;
  toolResults: Array<{
    tool_call_id: string;
    name: string;
    content: string;
    isError?: boolean;
    durationMs: number;
    isRepeated?: boolean;
  }>;
  groupWallClockMs: number;
  isTerminal: boolean;
  isRepeatCapHit?: boolean;
}

export class Orchestrator {
  private provider: ModelProvider;

  constructor(
    private config: AppConfig,
    private mcpManager: McpManager,
    provider?: ModelProvider
  ) {
    this.provider = provider || new ModelProvider(config);
  }

  /**
   * Executes a single step of the agentic interaction:
   * 1. Calls the model with available tools and messages
   * 2. If tools are requested, executes them concurrently (respecting parallelism limits and repeat caching)
   * 3. Records assistant calls and tool results into the session
   */
  public async executeStep(
    sessionId: string,
    step: number,
    maxSteps: number,
    options: TurnOptions,
    res?: ServerResponse,
    context?: {
      seenToolCalls?: Map<string, string>;
      repeatCounter?: { count: number };
      isFinalSynthesis?: boolean;
    }
  ): Promise<StepExecutionResult> {
    const session = sessionStore.getSession(sessionId);
    if (!session) {
      throw new Error(`Session '${sessionId}' not found`);
    }

    const isSynthesis = Boolean(context?.isFinalSynthesis);
    const tools = isSynthesis ? [] : this.mcpManager.getChatCompletionsTools();
    const apiKey = options.apiKey || getApiKey(options.provider || this.config.model.provider);

    if (res) {
      res.write(
        `event: step_start\ndata: ${JSON.stringify({
          step,
          maxSteps,
          isSynthesis,
        })}\n\n`
      );
    }

    let stepReply = "";
    let stepReasoning = "";

    const turnOutput = await this.provider.callStreaming(
      session.messages,
      tools,
      apiKey,
      {
        onReasoningDelta: (chunk) => {
          stepReasoning += chunk;
          if (res) {
            res.write(`event: reasoning\ndata: ${JSON.stringify({ text: chunk, step })}\n\n`);
          }
        },
        onDelta: (chunk) => {
          stepReply += chunk;
          // When performing final synthesis (tools disabled), stream directly to user bubble
          if (isSynthesis && res) {
            res.write(`event: delta\ndata: ${JSON.stringify({ text: chunk })}\n\n`);
          }
        },
        onToolCall: () => {
          // Handled after streaming completes
        },
      },
      options.baseUrl,
      options.modelName
    );

    // 1. Terminal Response: Model provided a direct answer without tool calls
    if (!turnOutput.toolCalls || turnOutput.toolCalls.length === 0) {
      // If not already streamed as synthesis, stream the full final answer text
      if (!isSynthesis && res) {
        res.write(`event: delta\ndata: ${JSON.stringify({ text: turnOutput.reply })}\n\n`);
      }

      sessionStore.appendMessage(sessionId, {
        role: "assistant",
        content: turnOutput.reply,
        reasoning_content: turnOutput.reasoning,
      });

      return {
        step,
        reply: turnOutput.reply,
        reasoning: turnOutput.reasoning,
        toolCalls: [],
        toolResults: [],
        groupWallClockMs: 0,
        isTerminal: true,
      };
    }

    // 2. Intermediate Tool Calls: Model requested tool executions
    // Emit narration event if model produced intermediate text, but do not stream it as final answer
    if (turnOutput.reply && res) {
      res.write(
        `event: step_narration\ndata: ${JSON.stringify({
          step,
          text: turnOutput.reply,
        })}\n\n`
      );
    }

    // Save assistant message with tool_calls in conversation history
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
      reasoning_content: turnOutput.reasoning,
    });

    const maxParallel = options.maxParallelToolCalls ?? this.config.limits.maxParallelToolCalls ?? 5;
    const activeCalls = turnOutput.toolCalls.slice(0, maxParallel);
    const skippedCalls = turnOutput.toolCalls.slice(maxParallel);

    if (res) {
      res.write(
        `event: tool_group_start\ndata: ${JSON.stringify({
          step,
          count: turnOutput.toolCalls.length,
          executed: activeCalls.length,
          skipped: skippedCalls.length,
          toolCalls: turnOutput.toolCalls.map((tc) => ({
            id: tc.id,
            name: tc.name,
            args: tc.arguments,
          })),
        })}\n\n`
      );
    }

    const seen = context?.seenToolCalls || new Map<string, string>();
    const repeatCounter = context?.repeatCounter || { count: 0 };
    let isRepeatCapHit = false;

    const groupStart = Date.now();

    // Execute active tool calls concurrently
    const callPromises = activeCalls.map(async (tc) => {
      const callStart = Date.now();
      const cacheKey = `${tc.name}:${JSON.stringify(tc.arguments)}`;

      // Loop Guard: Check for identical tool call repeat in this turn
      if (seen.has(cacheKey)) {
        repeatCounter.count++;
        if (repeatCounter.count >= 2) {
          isRepeatCapHit = true;
        }

        const cachedContent = seen.get(cacheKey)!;
        const content = `[Notice: This identical tool call was already executed earlier in this turn. Reusing previous result to avoid redundant execution.]\n${cachedContent}`;
        const durationMs = Date.now() - callStart;

        if (res) {
          res.write(
            `event: tool_call_done\ndata: ${JSON.stringify({
              id: tc.id,
              name: tc.name,
              resultPreview: content.substring(0, 300),
              isTruncated: false,
              isError: false,
              durationMs,
              isRepeated: true,
            })}\n\n`
          );
        }

        return {
          tool_call_id: tc.id,
          name: tc.name,
          content,
          isError: false,
          durationMs,
          isRepeated: true,
        };
      }

      // Fresh tool execution
      if (res) {
        res.write(
          `event: tool_call_start\ndata: ${JSON.stringify({
            id: tc.id,
            name: tc.name,
            args: tc.arguments,
          })}\n\n`
        );
      }

      try {
        const result = await this.mcpManager.executeTool(tc.name, tc.arguments);
        const durationMs = Date.now() - callStart;
        seen.set(cacheKey, result.content);

        if (res) {
          res.write(
            `event: tool_call_done\ndata: ${JSON.stringify({
              id: tc.id,
              name: tc.name,
              resultPreview: result.content.substring(0, 300),
              isTruncated: Boolean(result.bufferId),
              bufferId: result.bufferId,
              isError: result.isError,
              durationMs,
              isRepeated: false,
            })}\n\n`
          );
        }

        return {
          tool_call_id: tc.id,
          name: tc.name,
          content: result.content,
          isError: result.isError,
          durationMs,
          isRepeated: false,
        };
      } catch (toolErr) {
        const durationMs = Date.now() - callStart;
        const errMsg = toolErr instanceof Error ? toolErr.message : String(toolErr);
        const content = `[Tool Error: ${errMsg}]`;

        if (res) {
          res.write(
            `event: tool_call_done\ndata: ${JSON.stringify({
              id: tc.id,
              name: tc.name,
              resultPreview: content,
              isTruncated: false,
              isError: true,
              durationMs,
              isRepeated: false,
            })}\n\n`
          );
        }

        return {
          tool_call_id: tc.id,
          name: tc.name,
          content,
          isError: true,
          durationMs,
          isRepeated: false,
        };
      }
    });

    const settled = await Promise.allSettled(callPromises);
    const groupWallClockMs = Date.now() - groupStart;

    const toolResults: Array<{
      tool_call_id: string;
      name: string;
      content: string;
      isError?: boolean;
      durationMs: number;
      isRepeated?: boolean;
    }> = [];

    for (let i = 0; i < settled.length; i++) {
      const item = settled[i];
      if (item.status === "fulfilled") {
        toolResults.push(item.value);
      } else {
        toolResults.push({
          tool_call_id: activeCalls[i].id,
          name: activeCalls[i].name,
          content: `[Tool Execution Failed: ${item.reason}]`,
          isError: true,
          durationMs: 0,
        });
      }
    }

    // Append skipped calls exceeding maxParallelToolCalls
    for (const skipped of skippedCalls) {
      toolResults.push({
        tool_call_id: skipped.id,
        name: skipped.name,
        content: `[Skipped: Exceeded maximum parallel tool call limit of ${maxParallel} for this step. Please issue in the next step if still needed.]`,
        isError: false,
        durationMs: 0,
      });
    }

    // Append all tool results to session history matching tool_call_ids in order
    for (const tr of toolResults) {
      sessionStore.appendMessage(sessionId, {
        role: "tool",
        tool_call_id: tr.tool_call_id,
        name: tr.name,
        content: tr.content,
      });
    }

    // Emit tool_group_done
    if (res) {
      res.write(
        `event: tool_group_done\ndata: ${JSON.stringify({
          step,
          callCount: turnOutput.toolCalls.length,
          wallClockMs: groupWallClockMs,
          calls: toolResults.map((tr) => ({
            id: tr.tool_call_id,
            name: tr.name,
            durationMs: tr.durationMs,
            isError: tr.isError,
            isRepeated: tr.isRepeated,
          })),
        })}\n\n`
      );
    }

    traceBus.emitTrace({
      type: "tool_group",
      source: "orchestrator",
      title: `Parallel Tool Execution: ${toolResults.length} calls (${groupWallClockMs}ms wall-clock)`,
      data: {
        step,
        callCount: toolResults.length,
        wallClockMs: groupWallClockMs,
        tools: toolResults.map((t) => ({
          name: t.name,
          durationMs: t.durationMs,
          isError: t.isError,
          isRepeated: t.isRepeated,
        })),
      },
      latencyMs: groupWallClockMs,
    });

    return {
      step,
      reply: turnOutput.reply,
      reasoning: turnOutput.reasoning,
      toolCalls: turnOutput.toolCalls,
      toolResults,
      groupWallClockMs,
      isTerminal: false,
      isRepeatCapHit,
    };
  }

  /**
   * Runs an entire multi-step agentic turn wrapped in a loop:
   * - Executes steps up to maxSteps
   * - Protects against infinite loops via 2-repeat duplicate detection
   * - Performs tools-disabled synthesis when the step cap is reached
   * - Streams only the final answer text to the client
   */
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

    // Refresh dynamic system prompt with current UTC/local timestamps and timezone
    const dynamicPrompt = getSystemPrompt();
    if (session.messages.length > 0 && session.messages[0].role === "system") {
      session.messages[0].content = dynamicPrompt;
    } else {
      session.messages.unshift({ role: "system", content: dynamicPrompt });
    }

    // Append user message
    sessionStore.appendMessage(sessionId, {
      role: "user",
      content: userPrompt,
    });

    const maxSteps = options.maxSteps ?? this.config.limits.maxSteps ?? 6;
    const seenToolCalls = new Map<string, string>();
    const repeatCounter = { count: 0 };
    let step = 0;
    let finalAnswer = "";

    traceBus.emitTrace({
      type: "turn_start",
      source: "orchestrator",
      title: `Turn Started (Session: ${sessionId})`,
      data: { sessionId, promptPreview: userPrompt.substring(0, 100), maxSteps },
    });

    try {
      while (step < maxSteps) {
        step++;

        const stepResult = await this.executeStep(
          sessionId,
          step,
          maxSteps,
          options,
          res,
          { seenToolCalls, repeatCounter }
        );

        if (stepResult.isTerminal) {
          finalAnswer = stepResult.reply;
          break;
        }

        // Loop Guard: Break if 2 identical tool calls were repeated
        if (stepResult.isRepeatCapHit || repeatCounter.count >= 2) {
          traceBus.emitTrace({
            type: "warning",
            source: "orchestrator",
            title: "Loop Guard Triggered: Repeated tool calls detected",
            data: { step, repeats: repeatCounter.count },
          });
          break;
        }

        // If step limit reached, break to synthesis
        if (step >= maxSteps) {
          break;
        }
      }

      // If loop concluded without a direct terminal answer (hit step limit or loop guard), synthesize final summary
      if (!finalAnswer) {
        res.write(`event: step_cap_reached\ndata: ${JSON.stringify({ maxSteps, step })}\n\n`);

        sessionStore.appendMessage(sessionId, {
          role: "system",
          content:
            "[System instruction: Step limit reached. Please synthesize a final answer based on all information retrieved so far. State what was found and clearly state what remains unknown.]",
        });

        const synthesisResult = await this.executeStep(
          sessionId,
          step + 1,
          maxSteps,
          options,
          res,
          { isFinalSynthesis: true }
        );

        finalAnswer = synthesisResult.reply;
      }

      // Conclude SSE stream
      res.write(
        `event: done\ndata: ${JSON.stringify({
          sessionId,
          finalAnswer,
          messageCount: session.messages.length,
          stepsTaken: step,
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
