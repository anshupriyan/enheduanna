import type { ServerResponse } from "node:http";
import { sessionStore } from "./session.js";
import { McpManager } from "../mcp/manager.js";
import { ModelProvider } from "../providers/meta.js";
import { traceBus } from "../trace/bus.js";
import { getApiKey, type AppConfig } from "../config.js";
import { getSystemPrompt } from "../prompts/loader.js";
import { approvalManager } from "./approval.js";
import { EvidencePacker, type PackedTimelineEvidence } from "./evidence.js";
import type { ChatMessage } from "../providers/meta.js";

export interface TurnOptions {
  maxSteps?: number;
  maxParallelToolCalls?: number;
  apiKey?: string;
  baseUrl?: string;
  modelName?: string;
  provider?: string;
  enableTwoModelRouting?: boolean;
  reasoningEffort?: "minimal" | "low" | "medium" | "high" | "max";
  images?: string[];
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
      suppressTerminalDelta?: boolean;
    }
  ): Promise<StepExecutionResult> {
    const session = sessionStore.getSession(sessionId);
    if (!session) {
      throw new Error(`Session '${sessionId}' not found`);
    }

    const isSynthesis = Boolean(context?.isFinalSynthesis);
    const tools = isSynthesis ? [] : this.mcpManager.getChatCompletionsTools();
    const apiKey = options.apiKey || getApiKey(options.provider || this.config.model.provider);

    const toolModel = options.modelName || this.config.model.toolModel || this.config.model.modelName || "muse-spark-1.3";
    const synthesisModel = this.config.model.synthesisModel || "muse-wonder-1.0";
    const activeModel = isSynthesis ? synthesisModel : toolModel;

    if (res) {
      res.write(
        `event: step_start\ndata: ${JSON.stringify({
          step,
          maxSteps,
          isSynthesis,
          model: activeModel,
          stage: isSynthesis ? "synthesis" : "tool_agent",
        })}\n\n`
      );
    }

    traceBus.emitTrace({
      type: "model_request",
      source: "orchestrator",
      title: `Step ${step}: Model Request (${activeModel})`,
      data: {
        step,
        stage: isSynthesis ? "synthesis" : "tool_agent",
        model: activeModel,
        messageCount: session.messages.length,
        toolCount: tools.length,
      },
    });

    let stepReply = "";
    let stepReasoning = "";

    const streamCallbacks = {
      onReasoningDelta: (chunk: string) => {
        stepReasoning += chunk;
        if (res) {
          res.write(`event: reasoning\ndata: ${JSON.stringify({ text: chunk, step })}\n\n`);
        }
      },
      onDelta: (chunk: string) => {
        stepReply += chunk;
        // When performing final synthesis (tools disabled), stream directly to user bubble
        if (isSynthesis && res) {
          res.write(`event: delta\ndata: ${JSON.stringify({ text: chunk })}\n\n`);
        }
      },
      onToolCall: () => {
        // Handled after streaming completes
      },
    };

    let turnOutput;
    try {
      turnOutput = await this.provider.callStreaming(
        session.messages,
        tools,
        apiKey,
        streamCallbacks,
        options.baseUrl,
        activeModel,
        options.reasoningEffort
      );
    } catch (modelErr) {
      // If synthesis model (e.g. Wonder) fails, automatically fall back to tool model (Spark)
      if (isSynthesis && activeModel !== toolModel) {
        traceBus.emitTrace({
          type: "warning",
          source: "orchestrator",
          title: `Synthesis Model Fallback: ${activeModel} -> ${toolModel}`,
          data: {
            failedModel: activeModel,
            fallbackModel: toolModel,
            error: (modelErr as Error).message,
          },
        });
        if (res) {
          res.write(
            `event: synthesis_fallback\ndata: ${JSON.stringify({
              failedModel: activeModel,
              fallbackModel: toolModel,
            })}\n\n`
          );
        }
        turnOutput = await this.provider.callStreaming(
          session.messages,
          tools,
          apiKey,
          streamCallbacks,
          options.baseUrl,
          toolModel,
          options.reasoningEffort
        );
      } else {
        throw modelErr;
      }
    }

    // 1. Terminal Response: Model provided a direct answer without tool calls
    if (!turnOutput.toolCalls || turnOutput.toolCalls.length === 0) {
      if (!isSynthesis && res && !context?.suppressTerminalDelta) {
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

      // Check for human-in-the-loop authorization
      const approvalCheck = approvalManager.needsApproval(tc.name, tc.arguments);
      if (approvalCheck.needs) {
        const { request: apprReq, promise: apprPromise } = approvalManager.createRequest({
          sessionId,
          step,
          toolCallId: tc.id,
          toolName: tc.name,
          title: approvalCheck.title || "Authorization Request",
          description: approvalCheck.description || `Enheduanna is requesting permission to execute ${tc.name}.`,
          args: tc.arguments,
        });

        if (res) {
          res.write(
            `event: approval_required\ndata: ${JSON.stringify({
              id: apprReq.id,
              step,
              toolCallId: tc.id,
              toolName: tc.name,
              title: apprReq.title,
              description: apprReq.description,
              args: tc.arguments,
            })}\n\n`
          );
        }

        traceBus.emitTrace({
          type: "system",
          source: "orchestrator",
          title: `Authorization Required: ${tc.name}`,
          data: { id: apprReq.id, toolName: tc.name, args: tc.arguments },
        });

        const userApproved = await apprPromise;

        if (res) {
          res.write(
            `event: approval_resolved\ndata: ${JSON.stringify({
              id: apprReq.id,
              decision: userApproved ? "approved" : "denied",
              toolCallId: tc.id,
              toolName: tc.name,
            })}\n\n`
          );
        }

        if (!userApproved) {
          const durationMs = Date.now() - callStart;
          const deniedMsg = `[Permission Denied by User: The user explicitly denied authorization for "${tc.name}". Please explain to the user that permission was not granted and state what alternatives are available.]`;

          if (res) {
            res.write(
              `event: tool_call_done\ndata: ${JSON.stringify({
                id: tc.id,
                name: tc.name,
                resultPreview: deniedMsg,
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
            content: deniedMsg,
            isError: true,
            durationMs,
            isRepeated: false,
          };
        }

        // If execute_command was approved, ensure Dev Mode is enabled on cli-bridge
        if (tc.name === "execute_command") {
          try {
            await this.mcpManager.executeTool("toggle_dev_mode", { enable_dev_mode: true });
          } catch {}
        }
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
              args: tc.arguments,
              resultPreview: result.content.substring(0, 300),
              resultContent: result.content,
              isTruncated: Boolean(result.bufferId),
              bufferId: result.bufferId,
              isError: result.isError,
              durationMs,
              isRepeated: false,
              hasImage: Boolean(result.image),
              imageUrl: result.image ? `data:${result.image.mimeType};base64,${result.image.data}` : undefined,
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
          image: result.image,
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
      image?: { data: string; mimeType: string };
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

    // 1. Append all tool results contiguously so that every tool_call_id is satisfied
    for (const tr of toolResults) {
      sessionStore.appendMessage(sessionId, {
        role: "tool",
        tool_call_id: tr.tool_call_id,
        name: tr.name,
        content: tr.content,
      });
    }

    // 2. Multimodal Vision: If tools returned visual image data (screenshot crop / full screenshot),
    // inject at most ONE multimodal user message AFTER all tool calls have been responded to contiguously.
    const visualResult = toolResults.find((tr) => tr.image?.data);
    if (visualResult && visualResult.image) {
      sessionStore.appendMessage(sessionId, {
        role: "user",
        content: [
          {
            type: "text",
            text: `[Visual Screenshot from ${visualResult.name} (${visualResult.tool_call_id})]: Inspect this image carefully to extract details requested by the user.`,
          },
          {
            type: "image_url",
            image_url: {
              url: `data:${visualResult.image.mimeType};base64,${visualResult.image.data}`,
            },
          },
        ],
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

    // Append user message (with visual screenshot images if attached)
    if (options.images && options.images.length > 0) {
      const contentParts: any[] = [{ type: "text", text: userPrompt }];
      for (const img of options.images) {
        const url = img.startsWith("data:") ? img : `data:image/jpeg;base64,${img}`;
        contentParts.push({ type: "image_url", image_url: { url } });
      }
      sessionStore.appendMessage(sessionId, {
        role: "user",
        content: contentParts,
      });
    } else {
      sessionStore.appendMessage(sessionId, {
        role: "user",
        content: userPrompt,
      });
    }

    const maxSteps = options.maxSteps ?? this.config.limits.maxSteps ?? 16;
    const seenToolCalls = new Map<string, string>();
    const repeatCounter = { count: 0 };
    const allTurnToolResults: Array<{ name: string; content: string }> = [];
    let step = 0;
    let finalAnswer = "";

    traceBus.emitTrace({
      type: "turn_start",
      source: "orchestrator",
      title: `Turn Started (Session: ${sessionId})`,
      data: { sessionId, promptPreview: userPrompt.substring(0, 100), maxSteps },
    });

    const enableTwoModel = Boolean(
      options.enableTwoModelRouting ?? this.config.model.enableTwoModelRouting
    );
    let consecutiveCommandCalls = 0;

    try {
      while (step < maxSteps) {
        step++;

        const stepResult = await this.executeStep(
          sessionId,
          step,
          maxSteps,
          options,
          res,
          {
            seenToolCalls,
            repeatCounter,
            suppressTerminalDelta: enableTwoModel && allTurnToolResults.length > 0,
          }
        );

        if (stepResult.toolResults && stepResult.toolResults.length > 0) {
          allTurnToolResults.push(...stepResult.toolResults);
        }

        // Operator Guard (Issue 1.B): Track consecutive shell executions
        const executedCommands = (stepResult.toolCalls || []).filter(
          (tc) => tc.name === "execute_command"
        );
        if (executedCommands.length > 0) {
          consecutiveCommandCalls += executedCommands.length;
        } else {
          consecutiveCommandCalls = 0;
        }

        if (stepResult.isTerminal) {
          finalAnswer = stepResult.reply;
          break;
        }

        // Operator Action Limit: After 3 consecutive shell executions without textual progress, break to synthesis
        if (consecutiveCommandCalls >= 3) {
          traceBus.emitTrace({
            type: "warning",
            source: "orchestrator",
            title: "Operator Action Limit: 3 consecutive commands reached, breaking to synthesis",
            data: { step, consecutiveCommandCalls },
          });
          if (res) {
            res.write(
              `event: operator_limit_reached\ndata: ${JSON.stringify({
                step,
                consecutiveCommandCalls,
              })}\n\n`
            );
          }
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
          res.write(`event: step_cap_reached\ndata: ${JSON.stringify({ maxSteps, step })}\n\n`);
          break;
        }
      }

      // Synthesis Phase:
      // 1. Two-Model Routing: when enabled and tools were run, Wonder 1.0 ALWAYS writes the final synthesized answer
      // 2. Loop Cap / Guard Fallback: if loop ended without a terminal answer, synthesize summary from retrieved evidence
      if ((enableTwoModel && allTurnToolResults.length > 0) || !finalAnswer) {
        if (allTurnToolResults.length > 0) {
          const actionResults = allTurnToolResults
            .filter(
              (tr) =>
                !tr.name.startsWith("get_recent_memory") &&
                !tr.name.startsWith("search_desktop_memory") &&
                !tr.name.startsWith("get_capture_details")
            )
            .map((tr) => `- ${tr.name}: ${tr.content.substring(0, 400)}`);

          const packed = EvidencePacker.packEvidence(allTurnToolResults, userPrompt);

          const evidenceSections: string[] = [];
          if (actionResults.length > 0) {
            evidenceSections.push(`[ACTION & TOOL EXECUTION RESULTS]:\n${actionResults.join("\n")}`);
          }
          if (packed.segments && packed.segments.length > 0) {
            evidenceSections.push(`[VERIFIED TIMELINE EVIDENCE]:\n${JSON.stringify(packed, null, 2)}`);
          }

          const evidenceText = evidenceSections.length > 0 ? evidenceSections.join("\n\n") : "[ACTIONS COMPLETED]";

          sessionStore.appendMessage(sessionId, {
            role: "user",
            content: `${evidenceText}\n\nInstructions for Wonder Synthesis:
1. Provide a detailed, articulate, and well-structured answer following the system prompt rules.
2. If file, workspace, or system actions were performed (such as copy_file, write_file, or command execution), explicitly confirm the exact files, destination paths, and actions completed.
3. For file analysis or approach notes, provide the complete, comprehensive solutions, code snippets, and architectural approaches directly in your answer. Do NOT state that you will finish later or create it in a future step.
4. VISUAL SCREENSHOT INSPECTION: If the user attached an on-screen visual crop (or if visual screenshots were retrieved), inspect the image directly using your multimodal vision to describe colors, UI components, images, styling, and visual elements visible in the crop.
5. For activity summaries, full-day logs, or video/work histories, provide an intuitive overview with clear chronological bullet points and durations.
6. Do NOT dump raw database capture IDs (like #123) or unformatted OCR text blocks. Speak naturally as a sharp, collaborative desktop intelligence assistant.`,
          });
        }

        let synthesisStep = step + 1;
        let currentSynthesisResult = await this.executeStep(
          sessionId,
          synthesisStep,
          maxSteps + 2,
          options,
          res,
          { isFinalSynthesis: true }
        );

        // If synthesis requested follow-up tools (e.g. verification like list_directory),
        // loop so the model can inspect verification results and conclude with the final answer!
        while (
          currentSynthesisResult.toolCalls &&
          currentSynthesisResult.toolCalls.length > 0 &&
          synthesisStep < maxSteps + 3
        ) {
          synthesisStep++;
          currentSynthesisResult = await this.executeStep(
            sessionId,
            synthesisStep,
            maxSteps + 3,
            options,
            res,
            { isFinalSynthesis: true }
          );
        }

        if (currentSynthesisResult.isTerminal && currentSynthesisResult.reply) {
          finalAnswer = currentSynthesisResult.reply;
        } else if (!finalAnswer && currentSynthesisResult.reply) {
          finalAnswer = currentSynthesisResult.reply;
        } else if (finalAnswer && !currentSynthesisResult.isTerminal && res) {
          // If synthesis did not terminate with an articulate answer, ensure the earlier confirmed answer is streamed
          res.write(`event: delta\ndata: ${JSON.stringify({ text: `\n\n${finalAnswer}` })}\n\n`);
        }
      }

      if (!finalAnswer) {
        finalAnswer = "I've reviewed your request but couldn't retrieve any matching memory or actions.";
        if (res) {
          res.write(`event: delta\ndata: ${JSON.stringify({ text: finalAnswer })}\n\n`);
        }
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
