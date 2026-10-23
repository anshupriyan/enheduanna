import { describe, it, expect, beforeEach, afterEach } from "vitest";
import * as path from "path";
import * as fs from "fs";
import {
  handleToolCall,
  executeTool,
  setPolicyMode,
  setDevMode,
  workspaceRoot,
} from "../src/index.js";
import { PolicyEngine } from "../src/policy/engine.js";
import { PolicyAuditLogger } from "../src/policy/audit.js";

describe("Tool Integration with Policy Engine", () => {
  const testDir = path.join(workspaceRoot, "temp_policy_integration_test");
  const roDir = path.join(testDir, "ro_dir");
  const restrictedDir = path.join(testDir, "restricted_dir");
  const auditLogFile = path.join(testDir, "integration-audit.log");
  const policyConfigFile = path.join(testDir, "policy.json");

  let engine: PolicyEngine;
  let auditLogger: PolicyAuditLogger;

  beforeEach(() => {
    // Setup test directory tree
    if (!fs.existsSync(testDir)) fs.mkdirSync(testDir, { recursive: true });
    if (!fs.existsSync(roDir)) fs.mkdirSync(roDir, { recursive: true });
    if (!fs.existsSync(restrictedDir)) fs.mkdirSync(restrictedDir, { recursive: true });

    fs.writeFileSync(path.join(testDir, "regular.txt"), "hello world regular file", "utf-8");
    fs.writeFileSync(path.join(roDir, "readonly.txt"), "hello readonly file", "utf-8");
    fs.writeFileSync(path.join(restrictedDir, "secret.txt"), "top secret content", "utf-8");
    fs.writeFileSync(path.join(testDir, ".env"), "SECRET_KEY=12345", "utf-8");

    const policyConfig = {
      mode: "policy" as const,
      roots: [
        { path: testDir, access: "rw" as const },
        { path: roDir, access: "ro" as const },
      ],
      restricted_paths: [
        restrictedDir,
        "**/.env",
      ],
      restricted_paths_write: [],
      commands: {
        restricted: ["forbidden-tool"],
        approve: [],
      },
      unknown_command: "allow" as const,
      audit_log_path: auditLogFile,
    };

    engine = new PolicyEngine(policyConfig, {
      configPath: policyConfigFile,
      auditLogPath: auditLogFile,
      workspaceRoot: testDir,
    });
    auditLogger = new PolicyAuditLogger(auditLogFile);

    setPolicyMode(engine, auditLogger);
    setDevMode(false);
  });

  afterEach(() => {
    setPolicyMode(undefined, undefined);
    setDevMode(false);
    try {
      if (fs.existsSync(testDir)) {
        fs.rmSync(testDir, { recursive: true, force: true });
      }
    } catch {
      // ignore cleanup errors
    }
  });

  it("fails if read_file skips policy check on restricted files", async () => {
    const res = await handleToolCall("read_file", {
      path: path.join(restrictedDir, "secret.txt"),
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision).toBeDefined();
    expect(res.policyDecision.allowed).toBe(false);
    expect(res.policyDecision.ruleId).toBe("PATH_RESTRICTED");
  });

  it("fails if read_file skips policy check on glob restricted files (.env)", async () => {
    const res = await handleToolCall("read_file", {
      path: path.join(testDir, ".env"),
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision.ruleId).toBe("PATH_RESTRICTED_GLOB");
  });

  it("allows read_file on valid permitted file in rw root", async () => {
    const res = await handleToolCall("read_file", {
      path: path.join(testDir, "regular.txt"),
    });
    expect(res.isError).toBeUndefined();
    expect(res.content[0].text).toContain("hello world regular file");
  });

  it("fails if write_file skips policy check on read-only root", async () => {
    const res = await handleToolCall("write_file", {
      path: path.join(roDir, "new-file.txt"),
      content: "blocked content",
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision.ruleId).toBe("ROOT_READ_ONLY");
  });

  it("fails if write_file skips policy check on restricted path", async () => {
    const res = await handleToolCall("write_file", {
      path: path.join(restrictedDir, "new-secret.txt"),
      content: "blocked secret",
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision.ruleId).toBe("PATH_RESTRICTED");
  });

  it("fails if edit_file skips policy check on read-only root", async () => {
    const res = await handleToolCall("edit_file", {
      path: path.join(roDir, "readonly.txt"),
      old_str: "hello",
      new_str: "goodbye",
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision.ruleId).toBe("ROOT_READ_ONLY");
  });

  it("fails if list_directory skips policy check on restricted directory", async () => {
    const res = await handleToolCall("list_directory", {
      path: restrictedDir,
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision.ruleId).toBe("PATH_RESTRICTED");
  });

  it("ensures list_directory filters out restricted subdirectories and files", async () => {
    const res = await handleToolCall("list_directory", {
      path: testDir,
      recursive: true,
    });
    expect(res.isError).toBeUndefined();
    const listing = res.content[0].text;
    expect(listing).toContain("regular.txt");
    expect(listing).not.toContain("secret.txt");
    expect(listing).not.toContain(".env");
  });

  it("fails if search_files skips policy check on restricted directory", async () => {
    const res = await handleToolCall("search_files", {
      path: restrictedDir,
      pattern: "*",
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision.ruleId).toBe("PATH_RESTRICTED");
  });

  it("fails if grep_content skips policy check on restricted directory", async () => {
    const res = await handleToolCall("grep_content", {
      path: restrictedDir,
      pattern: "secret",
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision.ruleId).toBe("PATH_RESTRICTED");
  });

  it("fails if execute_command executes without Dev Mode", async () => {
    setDevMode(false);
    const res = await handleToolCall("execute_command", {
      command: "git",
      args: ["status"],
    });
    expect(res.isError).toBe(true);
    expect(res.content[0].text).toContain("Shell execution is currently blocked");
  });

  it("fails if execute_command skips policy check on restricted command once Dev Mode is ON", async () => {
    setDevMode(true);
    const res = await handleToolCall("execute_command", {
      command: "curl",
      args: ["https://example.com"],
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision.ruleId).toBe("CMD_RESTRICTED_BUILTIN");
  });

  it("fails if execute_command skips policy check on argument referencing restricted path", async () => {
    setDevMode(true);
    const res = await handleToolCall("execute_command", {
      command: "type",
      args: [path.join(restrictedDir, "secret.txt")],
    });
    expect(res.isError).toBe(true);
    expect(res.policyDecision.ruleId).toBe("CMD_ARG_PATH_RESTRICTED");
  });

  it("verifies audit logger records policy decisions with ruleId and reason", async () => {
    // Invoke a blocked action through executeTool
    await executeTool("read_file", {
      path: path.join(restrictedDir, "secret.txt"),
    });

    expect(fs.existsSync(auditLogFile)).toBe(true);
    const content = fs.readFileSync(auditLogFile, "utf-8");
    expect(content).toContain("PATH_RESTRICTED");
    expect(content).toContain("blocked");
  });
});
