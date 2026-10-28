export interface ApprovalRequest {
  id: string;
  sessionId: string;
  step: number;
  toolCallId: string;
  toolName: string;
  title: string;
  description: string;
  args: Record<string, unknown>;
  status: "pending" | "approved" | "denied" | "timeout";
  createdAt: number;
  resolve: (decision: boolean) => void;
}

class ApprovalManager {
  private pending = new Map<string, ApprovalRequest>();

  public needsApproval(toolName: string, args: Record<string, unknown>): { needs: boolean; title?: string; description?: string } {
    if (toolName === "request_path_access") {
      const p = String(args.path || "");
      const access = String(args.access || "ro");
      return {
        needs: true,
        title: "Filesystem Path Access Request",
        description: `Enheduanna is requesting permission to access path "${p}" (${access === "rw" ? "read/write" : "read-only"}). Allow access for this session?`,
      };
    }

    if (toolName === "execute_command") {
      const cmd = String(args.command || "");
      const argList = Array.isArray(args.args) ? args.args.join(" ") : "";
      return {
        needs: true,
        title: "Shell Command Execution Request",
        description: `Enheduanna is requesting permission to execute command: \`${cmd} ${argList}\`. Allow execution?`,
      };
    }

    if (toolName === "toggle_dev_mode") {
      const enable = Boolean(args.enable_dev_mode);
      if (enable) {
        return {
          needs: true,
          title: "Developer Mode Activation",
          description: "Enheduanna is requesting permission to enable Developer Mode (shell execution permissions). Allow activation?",
        };
      }
    }

    if (toolName === "request_command_access") {
      const cmd = String(args.command || "");
      return {
        needs: true,
        title: "Command Policy Approval Request",
        description: `Enheduanna is requesting permission to run policy-restricted command "${cmd}". Allow command?`,
      };
    }

    return { needs: false };
  }

  public createRequest(
    data: Omit<ApprovalRequest, "id" | "status" | "createdAt" | "resolve">,
    timeoutMs = 120000 // 2 minutes for user to click
  ): { request: ApprovalRequest; promise: Promise<boolean> } {
    const id = "appr_" + Math.random().toString(36).substring(2, 9);
    let resolver!: (decision: boolean) => void;
    const promise = new Promise<boolean>((res) => {
      resolver = res;
    });

    const request: ApprovalRequest = {
      ...data,
      id,
      status: "pending",
      createdAt: Date.now(),
      resolve: resolver,
    };

    const timer = setTimeout(() => {
      if (this.pending.has(id)) {
        this.resolveRequest(id, false, "timeout");
      }
    }, timeoutMs);

    this.pending.set(id, request);
    return {
      request,
      promise: promise.finally(() => clearTimeout(timer)),
    };
  }

  public resolveRequest(id: string, approved: boolean, reason?: "timeout"): boolean {
    const req = this.pending.get(id);
    if (!req) return false;
    req.status = approved ? "approved" : (reason === "timeout" ? "timeout" : "denied");
    req.resolve(approved);
    this.pending.delete(id);
    return true;
  }

  public getPending(sessionId?: string): ApprovalRequest[] {
    const list = Array.from(this.pending.values());
    if (sessionId) {
      return list.filter((r) => r.sessionId === sessionId);
    }
    return list;
  }
}

export const approvalManager = new ApprovalManager();
