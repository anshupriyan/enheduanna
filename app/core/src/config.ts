import fs from "node:fs";
import path from "node:path";
import dotenv from "dotenv";

// Find repository root
const REPO_ROOT = path.resolve(import.meta.dirname, "../../../");

// Load .env from repo root if it exists
const envPath = path.join(REPO_ROOT, ".env");
if (fs.existsSync(envPath)) {
  dotenv.config({ path: envPath });
}

export interface McpServerConfig {
  command: string;
  args: string[];
  cwd: string;
  env?: Record<string, string>;
}

export interface AppConfig {
  server: {
    host: string;
    port: number;
  };
  model: {
    provider: "meta" | "omniroute" | "openai";
    modelName: string;
    toolModel?: string;
    synthesisModel?: string;
    enableTwoModelRouting?: boolean;
    baseUrl: string;
    reasoningEffort: "minimal" | "low" | "medium" | "high" | "max";
  };
  limits: {
    maxSteps: number;
    maxParallelToolCalls: number;
    maxToolResultLength: number;
  };
  mcpServers: {
    memvision: McpServerConfig;
    "cli-bridge": McpServerConfig;
  };
}

const DEFAULT_CONFIG: AppConfig = {
  server: {
    host: "127.0.0.1",
    port: 4100,
  },
  model: {
    provider: "meta",
    modelName: "muse-spark-1.3",
    toolModel: "muse-spark-1.3",
    synthesisModel: "muse-wonder-1.0",
    enableTwoModelRouting: true,
    baseUrl: "https://api.meta.ai/v1",
    reasoningEffort: "medium",
  },
  limits: {
    maxSteps: 8,
    maxParallelToolCalls: 5,
    maxToolResultLength: 4000,
  },
  mcpServers: {
    memvision: {
      command: path.join("..", "memvison", ".venv", "Scripts", "python.exe"),
      args: ["main.py", "mcp"],
      cwd: path.resolve(REPO_ROOT, "..", "memvison"),
      env: {
        MEMVISION_DB_PATH: path.join(path.resolve(REPO_ROOT, "..", "memvison"), "data", "memvision.db"),
        MEMVISION_SCREENSHOTS_DIR: path.join(path.resolve(REPO_ROOT, "..", "memvison"), "data", "screenshots"),
      },
    },
    "cli-bridge": {
      command: "node",
      args: ["build/index.js", "--policy", "policy.json"],
      cwd: "cli-bridge",
      env: {
        WORKSPACE_ROOT: path.resolve(REPO_ROOT, ".."),
      },
    },
  },
};

export function resolveMemvisionRoot(): string {
  const candidates = [
    path.resolve(REPO_ROOT, "..", "memvison"),
    path.resolve(REPO_ROOT, "memvison"),
  ];
  for (const c of candidates) {
    if (fs.existsSync(path.join(c, "data", "memvision.db")) || fs.existsSync(path.join(c, "main.py"))) {
      return c;
    }
  }
  return path.resolve(REPO_ROOT, "..", "memvison");
}

export function resolveMemvisionDbPath(): string {
  const memRoot = resolveMemvisionRoot();
  return path.join(memRoot, "data", "memvision.db");
}

export function resolveMemvisionScreenshotsDir(): string {
  const memRoot = resolveMemvisionRoot();
  return path.join(memRoot, "data", "screenshots");
}

export function loadConfig(): AppConfig {
  const configPath = path.join(REPO_ROOT, "enheduanna.config.json");
  let cfg: AppConfig = JSON.parse(JSON.stringify(DEFAULT_CONFIG));

  if (fs.existsSync(configPath)) {
    try {
      const raw = fs.readFileSync(configPath, "utf-8");
      const parsed = JSON.parse(raw);
      cfg = {
        server: { ...cfg.server, ...parsed.server },
        model: { ...cfg.model, ...parsed.model },
        limits: { ...cfg.limits, ...parsed.limits },
        mcpServers: {
          memvision: { ...cfg.mcpServers.memvision, ...(parsed.mcpServers?.memvision || {}) },
          "cli-bridge": { ...cfg.mcpServers["cli-bridge"], ...(parsed.mcpServers?.["cli-bridge"] || {}) },
        },
      };
    } catch (err) {
      console.warn("[Config] Failed to parse enheduanna.config.json, using defaults", err);
    }
  }

  // Environment variable overrides
  if (process.env.PORT) {
    cfg.server.port = parseInt(process.env.PORT, 10);
  }
  if (process.env.HOST) {
    cfg.server.host = process.env.HOST;
  }
  if (process.env.MODEL_NAME) {
    cfg.model.modelName = process.env.MODEL_NAME;
  }
  if (process.env.TOOL_MODEL_NAME) {
    cfg.model.toolModel = process.env.TOOL_MODEL_NAME;
  }
  if (process.env.SYNTHESIS_MODEL_NAME) {
    cfg.model.synthesisModel = process.env.SYNTHESIS_MODEL_NAME;
  }
  if (process.env.ENABLE_TWO_MODEL_ROUTING !== undefined) {
    cfg.model.enableTwoModelRouting = process.env.ENABLE_TWO_MODEL_ROUTING === "true" || process.env.ENABLE_TWO_MODEL_ROUTING === "1";
  }
  if (process.env.OMNIROUTE_BASE_URL) {
    cfg.model.baseUrl = process.env.OMNIROUTE_BASE_URL;
  }

  return cfg;
}

export function resolvePythonExe(): string {
  const candidates = [
    path.join(resolveMemvisionRoot(), ".venv", "Scripts", "python.exe"),
    path.join(REPO_ROOT, "memvison", ".venv", "Scripts", "python.exe"),
    path.join(REPO_ROOT, "..", "memvison", ".venv", "Scripts", "python.exe"),
    "python",
  ];
  for (const c of candidates) {
    if (fs.existsSync(c)) {
      return c;
    }
  }
  return "python";
}

export function getApiKey(provider: string = "meta"): string {
  if (provider === "omniroute") {
    return process.env.OMNIROUTE_API_KEY || process.env.MODEL_API_KEY || process.env.META_API_KEY || "";
  }
  return process.env.META_API_KEY || process.env.MODEL_API_KEY || "";
}

export function getRepoRoot(): string {
  return REPO_ROOT;
}
