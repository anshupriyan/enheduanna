import * as fs from "fs";
import * as path from "path";
import { PolicyDecision } from "./types.js";

export interface AuditEntry {
  timestamp: string;
  tool: string;
  args: any;
  status: "success" | "error" | "blocked";
  decision?: string;
  ruleId?: string;
  reason?: string;
}

export class PolicyAuditLogger {
  private logPath: string;

  constructor(logPath: string) {
    this.logPath = path.resolve(logPath);
    this.ensureLogDir();
  }

  private ensureLogDir(): void {
    try {
      const dir = path.dirname(this.logPath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
    } catch (err) {
      console.error(`[cli-bridge-audit] Failed to initialize audit log directory:`, err);
    }
  }

  public getLogPath(): string {
    return this.logPath;
  }

  public logDecision(tool: string, rawArgs: any, decision: PolicyDecision, status?: "success" | "error" | "blocked"): void {
    const calculatedStatus: "success" | "error" | "blocked" =
      status || (decision.allowed ? "success" : "blocked");

    const formattedArgs = { ...rawArgs };
    if (tool === "write_file" && typeof formattedArgs.content === "string") {
      formattedArgs.content = formattedArgs.content.substring(0, 200) + (formattedArgs.content.length > 200 ? "..." : "");
    } else if (tool === "edit_file") {
      if (typeof formattedArgs.old_str === "string") {
        formattedArgs.old_str = formattedArgs.old_str.substring(0, 200) + (formattedArgs.old_str.length > 200 ? "..." : "");
      }
      if (typeof formattedArgs.new_str === "string") {
        formattedArgs.new_str = formattedArgs.new_str.substring(0, 200) + (formattedArgs.new_str.length > 200 ? "..." : "");
      }
    }

    const entry: AuditEntry = {
      timestamp: new Date().toISOString(),
      tool,
      args: formattedArgs,
      status: calculatedStatus,
      decision: decision.decision,
      ruleId: decision.ruleId,
      reason: decision.reason,
    };

    try {
      fs.appendFileSync(this.logPath, JSON.stringify(entry) + "\n", "utf-8");
    } catch (err) {
      console.error(`[cli-bridge-audit] Failed to write audit entry:`, err);
    }
  }
}
