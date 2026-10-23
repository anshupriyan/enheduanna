import { describe, it, expect } from "vitest";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";
import { PolicyEngine } from "../src/policy/engine.js";
import { SyncMockApprover } from "../src/policy/approver.js";

describe("Policy Engine - Command Security & Evaluation", () => {
  const workspaceRoot = fs.realpathSync(process.cwd());

  const baseConfig = {
    mode: "policy" as const,
    roots: [{ path: workspaceRoot, access: "rw" as const }],
    restricted_paths: [path.join(workspaceRoot, "secret-keys")],
    restricted_paths_write: [],
    commands: {
      restricted: ["custom-restricted-tool"],
      approve: ["npm-publish", "del"],
    },
    unknown_command: "allow" as const,
  };

  it("blocks built-in restricted commands (curl, wget, certutil, diskpart, format)", () => {
    const engine = new PolicyEngine(baseConfig, { workspaceRoot });

    expect(engine.checkCommand("curl", ["https://example.com"]).allowed).toBe(false);
    expect(engine.checkCommand("C:\\Windows\\System32\\curl.exe", []).allowed).toBe(false);
    expect(engine.checkCommand("WGET", []).allowed).toBe(false);
    expect(engine.checkCommand("certutil.exe", ["-urlcache"]).allowed).toBe(false);
    expect(engine.checkCommand("format", ["D:"]).allowed).toBe(false);
    expect(engine.checkCommand("reg.exe", ["query"]).allowed).toBe(false);
  });

  it("blocks nested shells and inline interpreters with execution flags", () => {
    const engine = new PolicyEngine(baseConfig, { workspaceRoot });

    expect(engine.checkCommand("cmd.exe", ["/c", "dir"]).allowed).toBe(false);
    expect(engine.checkCommand("powershell.exe", ["-Command", "Get-Process"]).allowed).toBe(false);
    expect(engine.checkCommand("pwsh", ["-EncodedCommand", "SQBuAHYAbwBrAGUALQBXAGUAYgBSAGUAcQB1AGUAcwB0AA=="]).allowed).toBe(false);
    expect(engine.checkCommand("bash", ["-c", "ls"]).allowed).toBe(false);
    expect(engine.checkCommand("node", ["-e", "process.exit(1)"]).allowed).toBe(false);
    expect(engine.checkCommand("python", ["-c", "import os; os.system('calc')"]).allowed).toBe(false);
  });

  it("blocks user-configured restricted commands", () => {
    const engine = new PolicyEngine(baseConfig, { workspaceRoot });
    const decision = engine.checkCommand("custom-restricted-tool", []);
    expect(decision.allowed).toBe(false);
    expect(decision.ruleId).toBe("CMD_RESTRICTED_CONFIG");
  });

  it("scans arguments for paths and blocks access to restricted or out-of-boundary paths", () => {
    const engine = new PolicyEngine(baseConfig, { workspaceRoot });

    // type or cat itself is allowed, but the argument points to SSH or a restricted directory
    const sshFile = path.join(os.homedir(), ".ssh", "id_rsa");
    const sshDecision = engine.checkCommand("type", [sshFile]);
    expect(sshDecision.allowed).toBe(false);
    expect(sshDecision.ruleId).toBe("CMD_ARG_PATH_RESTRICTED");

    // Relative path traversal in argument
    const traversalDecision = engine.checkCommand("git", ["diff", "../outside.txt"]);
    expect(traversalDecision.allowed).toBe(false);
    expect(traversalDecision.ruleId).toBe("CMD_ARG_PATH_RESTRICTED");

    // Argument inside restricted_paths
    const restrictedArg = path.join(workspaceRoot, "secret-keys", "key.pem");
    const keyDecision = engine.checkCommand("cat", [restrictedArg]);
    expect(keyDecision.allowed).toBe(false);
    expect(keyDecision.ruleId).toBe("CMD_ARG_PATH_RESTRICTED");
  });

  it("blocks Windows shell wrappers containing dangerous metacharacters", () => {
    const engine = new PolicyEngine(baseConfig, { workspaceRoot });

    const safeNpm = engine.checkCommand("npm", ["run", "build"]);
    expect(safeNpm.allowed).toBe(true);

    const injectedNpm = engine.checkCommand("npm", ["run", "build", "&", "dir"]);
    expect(injectedNpm.allowed).toBe(false);
    expect(injectedNpm.ruleId).toBe("CMD_SHELL_METACHARS");
  });

  it("respects unknown_command modes (allow, deny, ask)", () => {
    // Mode: allow
    const allowEngine = new PolicyEngine({ ...baseConfig, unknown_command: "allow" }, { workspaceRoot });
    expect(allowEngine.checkCommand("git", ["status"]).allowed).toBe(true);

    // Mode: deny
    const denyEngine = new PolicyEngine({ ...baseConfig, unknown_command: "deny" }, { workspaceRoot });
    const denyDecision = denyEngine.checkCommand("git", ["status"]);
    expect(denyDecision.allowed).toBe(false);
    expect(denyDecision.ruleId).toBe("CMD_UNKNOWN_DENY");

    // Mode: ask with DefaultDenyApprover
    const askEngine = new PolicyEngine({ ...baseConfig, unknown_command: "ask" }, { workspaceRoot });
    const askDecision = askEngine.checkCommand("git", ["status"]);
    expect(askDecision.allowed).toBe(false);
    expect(askDecision.decision).toBe("rejected");

    // Mode: ask with SyncMockApprover (approves)
    const mockApprover = new SyncMockApprover(true);
    askEngine.setApprover(mockApprover);
    const approvedDecision = askEngine.checkCommand("git", ["status"]);
    expect(approvedDecision.allowed).toBe(true);
    expect(approvedDecision.decision).toBe("approved");
  });

  it("handles commands in approve list", () => {
    const mockApprover = new SyncMockApprover(false);
    const engine = new PolicyEngine(baseConfig, { approver: mockApprover, workspaceRoot });

    // Initially denied
    const rejectedDecision = engine.checkCommand("npm-publish", []);
    expect(rejectedDecision.allowed).toBe(false);
    expect(rejectedDecision.decision).toBe("rejected");

    // When approved
    mockApprover.setDecision(true);
    const approvedDecision = engine.checkCommand("npm-publish", []);
    expect(approvedDecision.allowed).toBe(true);
    expect(approvedDecision.decision).toBe("approved");
  });
});
