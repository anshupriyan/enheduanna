import { describe, it, expect } from "vitest";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";
import { PolicyEngine } from "../src/policy/engine.js";

describe("Policy Engine - Path Security & Evaluation", () => {
  const workspaceRoot = fs.realpathSync(process.cwd());
  const dummyPolicyPath = path.join(workspaceRoot, "policy.json");
  const dummyAuditLogPath = path.join(workspaceRoot, ".cli-bridge-audit.log");

  const validConfig = {
    mode: "policy" as const,
    roots: [
      { path: workspaceRoot, access: "rw" as const },
      { path: path.join(workspaceRoot, "ro-folder"), access: "ro" as const },
    ],
    restricted_paths: [
      path.join(workspaceRoot, "restricted-area"),
      "**/.env",
      "**/.env.*",
    ],
    restricted_paths_write: [
      path.join(workspaceRoot, "write-protected"),
    ],
    commands: {
      restricted: ["custom-danger"],
      approve: ["git-push"],
    },
    unknown_command: "allow" as const,
    audit_log_path: dummyAuditLogPath,
  };

  it("fails closed on invalid policy configuration", () => {
    expect(() => new PolicyEngine({ mode: "invalid" } as any)).toThrow(/Policy initialization failed/);
    expect(() => new PolicyEngine({ mode: "policy", roots: [] } as any)).toThrow(/At least one root/);
  });

  describe("Path evaluation hierarchy and edge cases", () => {
    const engine = new PolicyEngine(validConfig, {
      configPath: dummyPolicyPath,
      auditLogPath: dummyAuditLogPath,
      workspaceRoot,
    });

    it("allows reading an existing allowed file inside rw root", () => {
      const decision = engine.checkPath("package.json", "read");
      expect(decision.allowed).toBe(true);
      expect(decision.decision).toBe("allow");
      expect(decision.ruleId).toBe("PATH_ALLOWED");
    });

    it("allows writing inside rw root", () => {
      const decision = engine.checkPath("new-file.txt", "write");
      expect(decision.allowed).toBe(true);
      expect(decision.decision).toBe("allow");
    });

    it("denies writing to a ro root while allowing reading", () => {
      const readDecision = engine.checkPath(path.join(workspaceRoot, "ro-folder", "data.json"), "read");
      expect(readDecision.allowed).toBe(true);

      const writeDecision = engine.checkPath(path.join(workspaceRoot, "ro-folder", "data.json"), "write");
      expect(writeDecision.allowed).toBe(false);
      expect(writeDecision.ruleId).toBe("ROOT_READ_ONLY");

      const deleteDecision = engine.checkPath(path.join(workspaceRoot, "ro-folder", "data.json"), "delete");
      expect(deleteDecision.allowed).toBe(false);
      expect(deleteDecision.ruleId).toBe("ROOT_READ_ONLY");
    });

    it("enforces restricted_paths: restricted ALWAYS wins over allowed roots", () => {
      const target = path.join(workspaceRoot, "restricted-area", "secret.txt");
      const readDecision = engine.checkPath(target, "read");
      expect(readDecision.allowed).toBe(false);
      expect(readDecision.ruleId).toBe("PATH_RESTRICTED");

      const writeDecision = engine.checkPath(target, "write");
      expect(writeDecision.allowed).toBe(false);
      expect(writeDecision.ruleId).toBe("PATH_RESTRICTED");
    });

    it("enforces glob restrictions (e.g. **/.env)", () => {
      const envDecision = engine.checkPath(".env", "read");
      expect(envDecision.allowed).toBe(false);
      expect(envDecision.ruleId).toBe("PATH_RESTRICTED_GLOB");

      const nestedEnvDecision = engine.checkPath("subdir/.env.local", "read");
      expect(nestedEnvDecision.allowed).toBe(false);
      expect(nestedEnvDecision.ruleId).toBe("PATH_RESTRICTED_GLOB");
    });

    it("protects policy config file and audit log from all tools", () => {
      const policyDecision = engine.checkPath(dummyPolicyPath, "read");
      expect(policyDecision.allowed).toBe(false);

      const auditDecision = engine.checkPath(dummyAuditLogPath, "read");
      expect(auditDecision.allowed).toBe(false);

      const journalDecision = engine.checkPath(path.join(workspaceRoot, "PROJECT_LOG.md"), "read");
      expect(journalDecision.allowed).toBe(false);
    });

    it("protects built-in restricted locations (e.g. ~/.ssh)", () => {
      const sshPath = path.join(os.homedir(), ".ssh", "id_rsa");
      const decision = engine.checkPath(sshPath, "read");
      expect(decision.allowed).toBe(false);
      // Denied either by PATH_RESTRICTED or outside roots
      expect(["PATH_RESTRICTED", "PATH_OUTSIDE_ALLOWED_ROOTS"]).toContain(decision.ruleId);
    });

    it("enforces restricted_paths_write (read allowed, write denied)", () => {
      const target = path.join(workspaceRoot, "write-protected", "readonly-config.json");
      const readDecision = engine.checkPath(target, "read");
      expect(readDecision.allowed).toBe(true);

      const writeDecision = engine.checkPath(target, "write");
      expect(writeDecision.allowed).toBe(false);
      expect(writeDecision.ruleId).toBe("PATH_WRITE_RESTRICTED");
    });

    it("denies path traversing outside allowed roots via ../", () => {
      const decision = engine.checkPath("../outside.txt", "read");
      expect(decision.allowed).toBe(false);
      expect(decision.ruleId).toBe("PATH_OUTSIDE_ALLOWED_ROOTS");
    });

    it("denies reserved DOS device names (CON, NUL, COM1, etc.)", () => {
      expect(engine.checkPath("CON", "write").allowed).toBe(false);
      expect(engine.checkPath("NUL", "write").allowed).toBe(false);
      expect(engine.checkPath("COM1", "write").allowed).toBe(false);
      expect(engine.checkPath("aux.txt", "write").allowed).toBe(false);
    });

    it("denies Alternate Data Streams (file.txt:stream)", () => {
      const decision = engine.checkPath("file.txt:hidden", "write");
      expect(decision.allowed).toBe(false);
      expect(decision.ruleId).toBe("PATH_RESERVED_DEVICE");
    });

    it("normalizes trailing dots and spaces on Windows", () => {
      const normal = engine.checkPath("package.json", "read");
      const trailingDot = engine.checkPath("package.json.", "read");
      const trailingSpace = engine.checkPath("package.json ", "read");
      expect(trailingDot.canonicalPath).toBe(normal.canonicalPath);
      expect(trailingSpace.canonicalPath).toBe(normal.canonicalPath);
    });
  });
});
