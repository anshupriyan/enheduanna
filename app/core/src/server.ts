import http, { type IncomingMessage, type ServerResponse } from "node:http";
import fs from "node:fs";
import path from "node:path";
import { validateAuth, getAuthToken } from "./auth.js";
import { traceBus } from "./trace/bus.js";
import { captureSupervisor } from "./capture/supervisor.js";
import { sessionStore } from "./agent/session.js";
import { McpManager } from "./mcp/manager.js";
import { Orchestrator } from "./agent/orchestrator.js";
import { getApiKey, getRepoRoot, type AppConfig } from "./config.js";

const MIME_TYPES: Record<string, string> = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "application/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".ico": "image/x-icon",
};

export class CoreServer {
  private server: http.Server;
  private orchestrator: Orchestrator;

  constructor(
    private config: AppConfig,
    private mcpManager: McpManager
  ) {
    this.orchestrator = new Orchestrator(config, mcpManager);
    this.server = http.createServer(this.handleRequest.bind(this));
  }

  private async parseJsonBody<T>(req: IncomingMessage): Promise<T> {
    return new Promise((resolve, reject) => {
      let body = "";
      req.on("data", (chunk) => {
        body += chunk;
        if (body.length > 2 * 1024 * 1024) {
          // 2MB limit
          req.destroy();
          reject(new Error("Request body too large"));
        }
      });
      req.on("end", () => {
        try {
          resolve(body ? JSON.parse(body) : {});
        } catch (e) {
          reject(new Error("Invalid JSON in request body"));
        }
      });
      req.on("error", reject);
    });
  }

  private sendJson(res: ServerResponse, status: number, data: unknown) {
    res.writeHead(status, {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": "*",
    });
    res.end(JSON.stringify(data));
  }

  private sendError(res: ServerResponse, status: number, message: string) {
    this.sendJson(res, status, { error: message });
  }

  private async handleRequest(req: IncomingMessage, res: ServerResponse): Promise<void> {
    // CORS preflight
    if (req.method === "OPTIONS") {
      res.writeHead(204, {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
      });
      res.end();
      return;
    }

    const host = req.headers.host || "127.0.0.1";
    const url = new URL(req.url || "/", `http://${host}`);
    const pathname = url.pathname;

    // 1. Static frontend assets (served from app/dashboard)
    if (!pathname.startsWith("/api/") && !["/chat", "/tools", "/trace", "/health"].includes(pathname)) {
      this.serveStatic(pathname, res);
      return;
    }

    // 2. Auth Gate for all core API endpoints
    if (!validateAuth(req)) {
      this.sendError(res, 401, "Unauthorized: Valid local Bearer auth token required.");
      return;
    }

    // 3. API Routes
    try {
      // GET /health
      if (req.method === "GET" && pathname === "/health") {
        const mcpStatus = this.mcpManager.getStatus();
        const captureStatus = captureSupervisor.getStatus();
        const hasKey = Boolean(getApiKey(this.config.model.provider));

        this.sendJson(res, 200, {
          status: "healthy",
          timestamp: new Date().toISOString(),
          modelConfig: {
            provider: this.config.model.provider,
            modelName: this.config.model.modelName,
            baseUrl: this.config.model.baseUrl,
            apiKeyConfigured: hasKey,
          },
          mcp: mcpStatus,
          capture: captureStatus,
        });
        return;
      }

      // GET /tools
      if (req.method === "GET" && pathname === "/tools") {
        this.sendJson(res, 200, {
          tools: this.mcpManager.getTools(),
        });
        return;
      }

      // GET /trace (SSE stream)
      if (req.method === "GET" && pathname === "/trace") {
        traceBus.handleSseStream(res);
        return;
      }

      // POST /chat (SSE stream)
      if (req.method === "POST" && pathname === "/chat") {
        const body = await this.parseJsonBody<{
          sessionId?: string;
          message?: string;
          options?: {
            maxSteps?: number;
            apiKey?: string;
            baseUrl?: string;
            modelName?: string;
            provider?: string;
          };
        }>(req);

        if (!body.message) {
          this.sendError(res, 400, "Missing 'message' field in chat request");
          return;
        }

        let sessionId = body.sessionId;
        if (!sessionId || !sessionStore.getSession(sessionId)) {
          sessionId = sessionStore.createSession().id;
        }

        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-cache, no-transform",
          Connection: "keep-alive",
          "Access-Control-Allow-Origin": "*",
        });

        await this.orchestrator.runTurn(sessionId, body.message, body.options || {}, res);
        return;
      }

      // GET /api/capture/status
      if (req.method === "GET" && pathname === "/api/capture/status") {
        this.sendJson(res, 200, captureSupervisor.getStatus());
        return;
      }

      // POST /api/capture/toggle
      if (req.method === "POST" && pathname === "/api/capture/toggle") {
        const body = await this.parseJsonBody<{ active?: boolean }>(req);
        const result = captureSupervisor.toggle(body.active);
        this.sendJson(res, 200, result);
        return;
      }

      // GET /api/sessions
      if (req.method === "GET" && pathname === "/api/sessions") {
        this.sendJson(res, 200, { sessions: sessionStore.listSessions() });
        return;
      }

      // POST /api/sessions
      if (req.method === "POST" && pathname === "/api/sessions") {
        const body = await this.parseJsonBody<{ title?: string }>(req);
        const newSession = sessionStore.createSession(body.title);
        this.sendJson(res, 201, newSession);
        return;
      }

      // GET /api/sessions/:id
      if (req.method === "GET" && pathname.startsWith("/api/sessions/")) {
        const id = pathname.substring("/api/sessions/".length);
        const session = sessionStore.getSession(id);
        if (!session) {
          this.sendError(res, 404, "Session not found");
          return;
        }
        this.sendJson(res, 200, session);
        return;
      }

      // DELETE /api/sessions/:id
      if (req.method === "DELETE" && pathname.startsWith("/api/sessions/")) {
        const id = pathname.substring("/api/sessions/".length);
        const ok = sessionStore.deleteSession(id);
        this.sendJson(res, 200, { success: ok });
        return;
      }

      // GET /api/config
      if (req.method === "GET" && pathname === "/api/config") {
        this.sendJson(res, 200, {
          provider: this.config.model.provider,
          modelName: this.config.model.modelName,
          baseUrl: this.config.model.baseUrl,
          reasoningEffort: this.config.model.reasoningEffort,
          hasApiKey: Boolean(getApiKey(this.config.model.provider)),
        });
        return;
      }

      // POST /api/config
      if (req.method === "POST" && pathname === "/api/config") {
        const body = await this.parseJsonBody<{
          provider?: "meta" | "omniroute" | "openai";
          modelName?: string;
          baseUrl?: string;
          apiKey?: string;
        }>(req);

        if (body.provider) this.config.model.provider = body.provider;
        if (body.modelName) this.config.model.modelName = body.modelName;
        if (body.baseUrl) this.config.model.baseUrl = body.baseUrl;
        if (body.apiKey) {
          if (this.config.model.provider === "omniroute") {
            process.env.OMNIROUTE_API_KEY = body.apiKey;
          } else {
            process.env.META_API_KEY = body.apiKey;
          }
        }

        traceBus.emitTrace({
          type: "system",
          source: "system",
          title: "Settings Updated",
          data: {
            provider: this.config.model.provider,
            modelName: this.config.model.modelName,
            baseUrl: this.config.model.baseUrl,
          },
        });

        this.sendJson(res, 200, { success: true });
        return;
      }

      this.sendError(res, 404, `Endpoint ${pathname} not found`);
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      this.sendError(res, 500, `Internal Server Error: ${errMsg}`);
    }
  }

  private serveStatic(urlPath: string, res: ServerResponse) {
    const repoRoot = getRepoRoot();
    const dashboardDir = path.join(repoRoot, "app", "dashboard");

    let cleanPath = urlPath === "/" ? "index.html" : urlPath.replace(/^\/+/, "");
    let filePath = path.join(dashboardDir, cleanPath);

    // Prevent directory traversal
    if (!filePath.startsWith(dashboardDir)) {
      this.sendError(res, 403, "Forbidden");
      return;
    }

    if (!fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      filePath = path.join(dashboardDir, "index.html");
    }

    if (!fs.existsSync(filePath)) {
      this.sendError(res, 404, "Dashboard file not found");
      return;
    }

    const ext = path.extname(filePath).toLowerCase();
    const contentType = MIME_TYPES[ext] || "application/octet-stream";

    res.writeHead(200, { "Content-Type": contentType });
    fs.createReadStream(filePath).pipe(res);
  }

  public listen(): Promise<void> {
    return new Promise((resolve) => {
      this.server.listen(this.config.server.port, this.config.server.host, () => {
        resolve();
      });
    });
  }

  public close(): Promise<void> {
    return new Promise((resolve) => {
      this.server.close(() => resolve());
    });
  }
}
