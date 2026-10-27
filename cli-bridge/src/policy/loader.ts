import * as fs from "fs";
import * as path from "path";
import { PolicyEngine } from "./engine.js";
import { PolicyAuditLogger } from "./audit.js";

export interface LoadedPolicy {
  policyEngine?: PolicyEngine;
  auditLogger?: PolicyAuditLogger;
  configPath?: string;
}

/**
 * Loads and validates policy configuration from CLI arguments or environment variables.
 * Fails closed on any I/O or schema validation error.
 */
export function loadPolicyFromArgs(argv: string[] = process.argv, defaultWorkspaceRoot: string = process.cwd()): LoadedPolicy {
  let policyPath: string | undefined;
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--policy" && argv[i + 1]) {
      policyPath = argv[i + 1];
      break;
    } else if (arg.startsWith("--policy=")) {
      policyPath = arg.substring("--policy=".length);
      break;
    }
  }

  if (!policyPath) {
    policyPath = process.env.CLI_BRIDGE_POLICY || process.env.CLI_BRIDGE_POLICY_CONFIG;
  }

  if (!policyPath) {
    return {};
  }

  const resolvedConfigPath = path.resolve(policyPath);
  let rawJson: string;
  try {
    rawJson = fs.readFileSync(resolvedConfigPath, "utf-8");
  } catch (err: any) {
    throw new Error(`Failed to read policy configuration file "${resolvedConfigPath}": ${err.message}`);
  }

  let parsed: any;
  try {
    parsed = JSON.parse(rawJson);
  } catch (err: any) {
    throw new Error(`Policy configuration file "${resolvedConfigPath}" is not valid JSON: ${err.message}`);
  }

  let effectiveWorkspaceRoot = defaultWorkspaceRoot;
  if (parsed && Array.isArray(parsed.roots) && parsed.roots.length > 0 && parsed.roots[0].path) {
    if (!defaultWorkspaceRoot || defaultWorkspaceRoot === process.cwd()) {
      effectiveWorkspaceRoot = path.resolve(parsed.roots[0].path);
    }
  }

  const engine = new PolicyEngine(parsed, {
    configPath: resolvedConfigPath,
    workspaceRoot: effectiveWorkspaceRoot,
  });

  const auditLogger = new PolicyAuditLogger(engine.getAuditLogPath());

  return {
    policyEngine: engine,
    auditLogger,
    configPath: resolvedConfigPath,
  };
}
