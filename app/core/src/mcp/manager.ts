import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import path from "node:path";
import {
  getRepoRoot,
  resolvePythonExe,
  resolveMemvisionRoot,
  resolveMemvisionDbPath,
  resolveMemvisionScreenshotsDir,
  type AppConfig,
} from "../config.js";
import { toolResultBuffer } from "./buffer.js";
import { traceBus } from "../trace/bus.js";

export interface UnifiedTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  sourceServer: "memvision" | "cli-bridge" | "internal";
}

export interface ToolExecutionResult {
  content: string;
  isError: boolean;
  bufferId?: string;
  image?: {
    data: string;
    mimeType: string;
  };
}

export class McpManager {
  private memClient: Client | null = null;
  private memTransport: StdioClientTransport | null = null;
  private cliClient: Client | null = null;
  private cliTransport: StdioClientTransport | null = null;

  private tools = new Map<string, UnifiedTool>();
  private serverStatus = {
    memvision: { connected: false, error: null as string | null, toolCount: 0 },
    "cli-bridge": { connected: false, error: null as string | null, toolCount: 0 },
  };

  constructor(private config: AppConfig) {}

  private getCleanEnv(overrides?: Record<string, string>): Record<string, string> {
    const clean: Record<string, string> = {};
    for (const [k, v] of Object.entries(process.env)) {
      if (v !== undefined) clean[k] = v;
    }
    if (overrides) {
      Object.assign(clean, overrides);
    }
    return clean;
  }

  private unwrapMcpResult(content: unknown): unknown {
    if (!content) return content;
    if (Array.isArray(content)) {
      if (content.length === 1 && content[0]?.type === "text" && typeof content[0].text === "string") {
        try {
          return JSON.parse(content[0].text);
        } catch {
          return content[0].text;
        }
      }
      return content.map((item) => {
        if (item?.type === "text" && typeof item.text === "string") {
          try {
            return JSON.parse(item.text);
          } catch {
            return item.text;
          }
        }
        return item;
      });
    }
    return content;
  }

  public async init(): Promise<void> {
    const repoRoot = getRepoRoot();
    const pythonExe = resolvePythonExe();

    // 1. Connect to memvision
    try {
      const configuredCwd = this.config.mcpServers.memvision.cwd;
      const memCwd = configuredCwd
        ? (path.isAbsolute(configuredCwd) ? configuredCwd : path.resolve(repoRoot, configuredCwd))
        : resolveMemvisionRoot();

      const memvisionEnv: Record<string, string> = {
        MEMVISION_DB_PATH: resolveMemvisionDbPath(),
        MEMVISION_SCREENSHOTS_DIR: resolveMemvisionScreenshotsDir(),
        ...(this.config.mcpServers.memvision.env || {}),
      };

      this.memTransport = new StdioClientTransport({
        command: pythonExe,
        args: this.config.mcpServers.memvision.args,
        cwd: memCwd,
        env: this.getCleanEnv(memvisionEnv),
      });

      this.memClient = new Client({ name: "enheduanna-core", version: "1.0.0" }, { capabilities: {} });
      await this.memClient.connect(this.memTransport);

      const memTools = await this.memClient.listTools();
      for (const t of memTools.tools) {
        this.tools.set(t.name, {
          name: t.name,
          description: t.description || "",
          inputSchema: (t.inputSchema as Record<string, unknown>) || { type: "object", properties: {} },
          sourceServer: "memvision",
        });
      }

      this.serverStatus.memvision.connected = true;
      this.serverStatus.memvision.toolCount = memTools.tools.length;
      traceBus.emitTrace({
        type: "system",
        source: "mcp-memvision",
        title: "memvision Connected",
        data: { toolCount: memTools.tools.length, tools: memTools.tools.map((t) => t.name) },
      });
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      this.serverStatus.memvision.connected = false;
      this.serverStatus.memvision.error = errMsg;
      traceBus.emitTrace({
        type: "error",
        source: "mcp-memvision",
        title: "memvision Connection Failed",
        data: { error: errMsg },
      });
      console.error("[McpManager] memvision failed to connect:", errMsg);
    }

    // 2. Connect to cli-bridge
    try {
      const cliCwd = path.isAbsolute(this.config.mcpServers["cli-bridge"].cwd)
        ? this.config.mcpServers["cli-bridge"].cwd
        : path.join(repoRoot, this.config.mcpServers["cli-bridge"].cwd);

      this.cliTransport = new StdioClientTransport({
        command: this.config.mcpServers["cli-bridge"].command,
        args: this.config.mcpServers["cli-bridge"].args,
        cwd: cliCwd,
        env: this.getCleanEnv(this.config.mcpServers["cli-bridge"].env),
      });

      this.cliClient = new Client({ name: "enheduanna-core", version: "1.0.0" }, { capabilities: {} });
      await this.cliClient.connect(this.cliTransport);

      const cliTools = await this.cliClient.listTools();
      for (const t of cliTools.tools) {
        this.tools.set(t.name, {
          name: t.name,
          description: t.description || "",
          inputSchema: (t.inputSchema as Record<string, unknown>) || { type: "object", properties: {} },
          sourceServer: "cli-bridge",
        });
      }

      this.serverStatus["cli-bridge"].connected = true;
      this.serverStatus["cli-bridge"].toolCount = cliTools.tools.length;
      traceBus.emitTrace({
        type: "system",
        source: "mcp-cli-bridge",
        title: "cli-bridge Connected",
        data: { toolCount: cliTools.tools.length, tools: cliTools.tools.map((t) => t.name) },
      });
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      this.serverStatus["cli-bridge"].connected = false;
      this.serverStatus["cli-bridge"].error = errMsg;
      traceBus.emitTrace({
        type: "error",
        source: "mcp-cli-bridge",
        title: "cli-bridge Connection Failed",
        data: { error: errMsg },
      });
      console.error("[McpManager] cli-bridge failed to connect:", errMsg);
    }

    // 3. Register internal virtual tool: get_full_result
    this.tools.set("get_full_result", {
      name: "get_full_result",
      description: "Retrieves the complete, untruncated content of a previous tool result using its result_id buffer handle.",
      inputSchema: {
        type: "object",
        properties: {
          result_id: {
            type: "string",
            description: "The unique ID (e.g. buf_a1b2) returned by a truncated tool output.",
          },
        },
        required: ["result_id"],
      },
      sourceServer: "internal",
    });
  }

  public getTools(): UnifiedTool[] {
    return Array.from(this.tools.values());
  }

  public getResponsesApiTools(): Array<{ type: "function"; name: string; description: string; parameters: Record<string, unknown> }> {
    return this.getTools().map((t) => ({
      type: "function",
      name: t.name,
      description: t.description,
      parameters: t.inputSchema,
    }));
  }

  public getChatCompletionsTools(): Array<{ type: "function"; function: { name: string; description: string; parameters: Record<string, unknown> } }> {
    return this.getTools().map((t) => ({
      type: "function",
      function: {
        name: t.name,
        description: t.description,
        parameters: t.inputSchema,
      },
    }));
  }

  public async executeTool(name: string, args: Record<string, unknown>): Promise<ToolExecutionResult> {
    const startTime = Date.now();
    const toolDef = this.tools.get(name);

    if (!toolDef) {
      const err = `Tool '${name}' not found on any active MCP server.`;
      traceBus.emitTrace({
        type: "tool_result",
        source: "orchestrator",
        title: `Tool Failed: ${name}`,
        data: { tool: name, args, error: err },
        latencyMs: Date.now() - startTime,
      });
      return { content: `Error: ${err}`, isError: true };
    }

    traceBus.emitTrace({
      type: "tool_call",
      source: toolDef.sourceServer === "memvision" ? "mcp-memvision" : toolDef.sourceServer === "cli-bridge" ? "mcp-cli-bridge" : "orchestrator",
      title: `Tool Call: ${name}`,
      data: { tool: name, args, sourceServer: toolDef.sourceServer },
    });

    try {
      let rawResult: unknown;
      let extractedImage: { data: string; mimeType: string } | undefined = undefined;

      if (name === "get_full_result") {
        const resultId = String(args.result_id || "");
        const full = toolResultBuffer.getFullResult(resultId);
        rawResult = full ? full : `Error: Buffer ID '${resultId}' not found or expired.`;
      } else if (toolDef.sourceServer === "memvision") {
        if (!this.memClient) throw new Error("memvision MCP client is not connected");
        const res = await this.memClient.callTool({ name, arguments: args });

        // Detect visual multimodal image content
        if (Array.isArray(res.content)) {
          const imgItem = (res.content as any[]).find((item: any) => item?.type === "image" && item?.data);
          if (imgItem) {
            extractedImage = {
              data: String(imgItem.data),
              mimeType: String(imgItem.mimeType || "image/jpeg"),
            };
            const nonImg = (res.content as any[]).filter((item: any) => item?.type !== "image");
            if (nonImg.length > 0) {
              rawResult = this.unwrapMcpResult(nonImg);
            } else {
              rawResult = `[Visual screenshot image successfully retrieved: format ${extractedImage.mimeType}, size ${Math.round((extractedImage.data.length * 0.75) / 1024)} KB. Visual content delivered to model.]`;
            }
          } else {
            rawResult = this.unwrapMcpResult(res.content);
          }
        } else {
          rawResult = this.unwrapMcpResult(res.content);
        }
      } else if (toolDef.sourceServer === "cli-bridge") {
        if (!this.cliClient) throw new Error("cli-bridge MCP client is not connected");
        const res = await this.cliClient.callTool({ name, arguments: args });
        rawResult = this.unwrapMcpResult(res.content);
      }

      const durationMs = Date.now() - startTime;
      const processed = toolResultBuffer.processResult(name, rawResult);

      traceBus.emitTrace({
        type: "tool_result",
        source: toolDef.sourceServer === "memvision" ? "mcp-memvision" : toolDef.sourceServer === "cli-bridge" ? "mcp-cli-bridge" : "orchestrator",
        title: `Tool Done: ${name} (${durationMs}ms)`,
        data: {
          tool: name,
          durationMs,
          outputLength: processed.text.length,
          isTruncated: processed.isTruncated,
          bufferId: processed.bufferId,
          hasImage: Boolean(extractedImage),
          preview: processed.text.substring(0, 300),
        },
        latencyMs: durationMs,
      });

      return {
        content: processed.text,
        isError: false,
        bufferId: processed.bufferId,
        image: extractedImage,
      };
    } catch (err: unknown) {
      const durationMs = Date.now() - startTime;
      const errMsg = err instanceof Error ? err.message : String(err);

      traceBus.emitTrace({
        type: "tool_result",
        source: toolDef.sourceServer === "memvision" ? "mcp-memvision" : toolDef.sourceServer === "cli-bridge" ? "mcp-cli-bridge" : "orchestrator",
        title: `Tool Error: ${name} (${durationMs}ms)`,
        data: { tool: name, error: errMsg },
        latencyMs: durationMs,
      });

      return {
        content: `Error executing tool '${name}': ${errMsg}`,
        isError: true,
      };
    }
  }

  public getStatus() {
    return {
      servers: this.serverStatus,
      totalTools: this.tools.size,
      tools: this.getTools().map((t) => ({ name: t.name, server: t.sourceServer, description: t.description })),
    };
  }

  public async close(): Promise<void> {
    try {
      if (this.memTransport) await this.memTransport.close();
      if (this.cliTransport) await this.cliTransport.close();
    } catch {}
    this.memClient = null;
    this.cliClient = null;
  }
}
