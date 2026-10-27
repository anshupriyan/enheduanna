import * as path from "path";
import * as fs from "fs";
import {
  PolicyConfig,
  PolicyConfigSchema,
  PolicyDecision,
  PathOperation,
  Approver,
} from "./types.js";
import {
  canonicalizePath,
  isInsideOrEqual,
  arePathsEqual,
} from "./canonicalize.js";
import {
  getBuiltInRestrictedPaths,
  BUILT_IN_RESTRICTED_COMMANDS,
  INLINE_INTERPRETERS,
} from "./defaults.js";
import { DefaultDenyApprover } from "./approver.js";

// Windows shell wrapper tools and metacharacters
const WINDOWS_WRAPPERS = new Set(["npm", "npx", "yarn", "pnpm", "tsc", "jest", "eslint", "prettier"]);
const SHELL_METACHARS = ["&", "|", ";", "`", "$", ">", "<", "^"];

function globToRegex(glob: string): RegExp {
  const normalizedGlob = glob.replace(/\\/g, "/");
  if (normalizedGlob.startsWith("**/")) {
    const rest = normalizedGlob.slice(3);
    const escapedRest = rest
      .replace(/[.+^${}()|[\]\\]/g, "\\$&")
      .replace(/\*\*/g, ".*")
      .replace(/\*/g, "[^/]*")
      .replace(/\?/g, ".");
    return new RegExp(`^(?:.*/)?${escapedRest}$`, "i");
  }
  const escaped = normalizedGlob
    .replace(/[.+^${}()|[\]\\]/g, "\\$&")
    .replace(/\*\*/g, ".*")
    .replace(/\*/g, "[^/]*")
    .replace(/\?/g, ".");
  return new RegExp(`^${escaped}$`, "i");
}

function normalizeCommandName(cmd: string): string {
  // Strip leading path and extensions .exe, .cmd, .bat
  const basename = path.basename(cmd);
  const lower = basename.toLowerCase();
  return lower.replace(/\.(exe|cmd|bat)$/i, "");
}

function looksLikePath(str: string): boolean {
  if (
    str.startsWith("http://") ||
    str.startsWith("https://") ||
    str.startsWith("git@") ||
    str.includes("://")
  ) {
    return false;
  }
  if (str.includes("../") || str.includes("..\\")) return true;
  if (/^[A-Za-z]:[/\\]/.test(str)) return true;
  if (str.startsWith("./") || str.startsWith(".\\") || str.startsWith("/") || str.startsWith("\\")) return true;
  const slashCount = (str.match(/\//g) || []).length + (str.match(/\\/g) || []).length;
  if (slashCount >= 2) return true;
  if (slashCount === 1 && /\.[A-Za-z0-9]{1,5}$/.test(str)) return true;
  return false;
}

export interface PolicyEngineOptions {
  approver?: Approver;
  configPath?: string;
  auditLogPath?: string;
  workspaceRoot?: string;
}

export class PolicyEngine {
  private config: PolicyConfig;
  private approver: Approver;
  private configPath?: string;
  private auditLogPath?: string;
  private workspaceRoot: string;
  private canonicalRoots: { path: string; access: "rw" | "ro" }[] = [];
  private sessionRoots: { path: string; access: "rw" | "ro" }[] = [];
  private sessionCommands: Set<string> = new Set();
  private canonicalRestrictedPaths: string[] = [];
  private canonicalRestrictedPathsWrite: string[] = [];
  private restrictedGlobs: RegExp[] = [];

  constructor(rawConfig: unknown, options: PolicyEngineOptions = {}) {
    // Validate config - fails closed on error
    const parsed = PolicyConfigSchema.safeParse(rawConfig);
    if (!parsed.success) {
      throw new Error(`Policy initialization failed: Invalid policy configuration. ${parsed.error.message}`);
    }
    this.config = parsed.data;
    this.approver = options.approver || new DefaultDenyApprover();
    this.configPath = options.configPath ? path.resolve(options.configPath) : undefined;
    this.workspaceRoot = options.workspaceRoot ? path.resolve(options.workspaceRoot) : process.cwd();

    // Determine audit log path
    if (this.config.audit_log_path) {
      this.auditLogPath = path.resolve(this.config.audit_log_path);
    } else if (options.auditLogPath) {
      this.auditLogPath = path.resolve(options.auditLogPath);
    } else {
      this.auditLogPath = path.join(this.workspaceRoot, ".cli-bridge-audit.log");
    }

    this.initializeCanonicalPaths();
  }

  private initializeCanonicalPaths(): void {
    // 1. Allowed roots (sorted by descending length so more specific subfolder roots match first)
    this.canonicalRoots = this.config.roots
      .map((r) => {
        const canonical = canonicalizePath(r.path, this.workspaceRoot);
        return {
          path: canonical.canonicalPath,
          access: r.access,
        };
      })
      .sort((a, b) => b.path.length - a.path.length);

    // 2. Built-in restricted paths
    const builtIns = getBuiltInRestrictedPaths();
    if (this.configPath) {
      builtIns.push(this.configPath);
    }
    if (this.auditLogPath) {
      builtIns.push(this.auditLogPath);
    }
    // Protect PROJECT_LOG.md in all roots and workspaceRoot
    builtIns.push(path.join(this.workspaceRoot, "PROJECT_LOG.md"));
    for (const r of this.canonicalRoots) {
      builtIns.push(path.join(r.path, "PROJECT_LOG.md"));
    }

    // 3. User restricted paths (separate literal paths from globs)
    for (const p of this.config.restricted_paths) {
      if (p.includes("*") || p.includes("?")) {
        this.restrictedGlobs.push(globToRegex(p));
      } else {
        builtIns.push(path.isAbsolute(p) ? p : path.resolve(this.workspaceRoot, p));
      }
    }

    this.canonicalRestrictedPaths = builtIns.map((p) => {
      const res = canonicalizePath(p, this.workspaceRoot);
      return res.canonicalPath;
    });

    // 4. Restricted paths for write
    this.canonicalRestrictedPathsWrite = this.config.restricted_paths_write.map((p) => {
      const res = canonicalizePath(p, this.workspaceRoot);
      return res.canonicalPath;
    });
  }

  public getConfig(): PolicyConfig {
    return this.config;
  }

  public getAuditLogPath(): string {
    return this.auditLogPath || path.join(this.workspaceRoot, ".cli-bridge-audit.log");
  }

  public getAllowedRoots(): { path: string; access: "rw" | "ro" }[] {
    return [...this.canonicalRoots, ...this.sessionRoots].sort((a, b) => b.path.length - a.path.length);
  }

  public getSessionRoots(): { path: string; access: "rw" | "ro" }[] {
    return this.sessionRoots;
  }

  public getSessionCommands(): string[] {
    return Array.from(this.sessionCommands);
  }

  /**
   * Adds an ephemeral session command. Restricted commands CAN NEVER be granted as a session command.
   */
  public addSessionCommand(command: string): PolicyDecision {
    const normCmd = normalizeCommandName(command);

    if (BUILT_IN_RESTRICTED_COMMANDS.has(normCmd)) {
      return {
        allowed: false,
        decision: "deny",
        ruleId: "CMD_RESTRICTED_BUILTIN",
        reason: `Cannot grant session command: Command "${command}" is restricted by system security policy.`,
        command: normCmd,
      };
    }

    const userRestricted = new Set(this.config.commands.restricted.map(normalizeCommandName));
    if (userRestricted.has(normCmd)) {
      return {
        allowed: false,
        decision: "deny",
        ruleId: "CMD_RESTRICTED_CONFIG",
        reason: `Cannot grant session command: Command "${command}" is restricted by user policy configuration.`,
        command: normCmd,
      };
    }

    this.sessionCommands.add(normCmd);

    return {
      allowed: true,
      decision: "approved",
      ruleId: "SESSION_COMMAND_ADDED",
      reason: `Session command granted for "${normCmd}".`,
      command: normCmd,
    };
  }

  /**
   * Adds an ephemeral session root. Restricted paths CAN NEVER be granted as a session root.
   */
  public addSessionRoot(rootPath: string, access: "rw" | "ro" = "ro"): PolicyDecision {
    const canonical = canonicalizePath(rootPath, this.workspaceRoot);
    const cPath = canonical.canonicalPath;

    if (canonical.isReservedDevice || canonical.isDanglingSymlink) {
      return {
        allowed: false,
        decision: "deny",
        ruleId: "PATH_INVALID",
        reason: `Cannot grant session root: Path "${rootPath}" is invalid or a reserved device.`,
        canonicalPath: cPath,
      };
    }

    // Check if path is in restricted_paths or globs - RESTRICTED CAN NEVER BE GRANTED!
    const baseName = path.basename(cPath);
    const normCanonical = cPath.replace(/\\/g, "/");
    for (const globRegex of this.restrictedGlobs) {
      if (globRegex.test(normCanonical) || globRegex.test(baseName)) {
        return {
          allowed: false,
          decision: "deny",
          ruleId: "PATH_RESTRICTED_GLOB",
          reason: `Access denied: Path "${rootPath}" matches a restricted pattern and cannot be granted as a session root.`,
          canonicalPath: cPath,
        };
      }
    }

    for (const restricted of this.canonicalRestrictedPaths) {
      if (isInsideOrEqual(restricted, cPath) || arePathsEqual(restricted, cPath)) {
        return {
          allowed: false,
          decision: "deny",
          ruleId: "PATH_RESTRICTED",
          reason: `Access denied: Path "${rootPath}" resolves into restricted location "${restricted}" and cannot be granted as a session root.`,
          canonicalPath: cPath,
        };
      }
    }

    // Add or update in sessionRoots
    const existingIndex = this.sessionRoots.findIndex((r) => arePathsEqual(r.path, cPath));
    if (existingIndex !== -1) {
      this.sessionRoots[existingIndex].access = access;
    } else {
      this.sessionRoots.push({ path: cPath, access });
    }

    this.sessionRoots.sort((a, b) => b.path.length - a.path.length);

    return {
      allowed: true,
      decision: "approved",
      ruleId: "SESSION_ROOT_ADDED",
      reason: `Session root granted for "${cPath}" (${access}).`,
      canonicalPath: cPath,
    };
  }

  public setApprover(approver: Approver): void {
    this.approver = approver;
  }

  /**
   * Synchronous path checking API.
   * Order:
   * 1. Canonicalize (strip extended prefixes, check DOS devices, ADS, dangling symlinks)
   * 2. Restricted paths (built-in + config + globs). Restricted ALWAYS wins.
   * 3. Restricted paths write (if write/delete)
   * 4. Must be inside an allowed root
   * 5. Root access level (ro vs rw)
   */
  public checkPath(userPath: string, operation: PathOperation = "read", baseDir: string = this.workspaceRoot): PolicyDecision {
    const canonical = canonicalizePath(userPath, baseDir);

    if (canonical.isReservedDevice) {
      return {
        allowed: false,
        decision: "deny",
        ruleId: "PATH_RESERVED_DEVICE",
        reason: `Access denied: Path "${userPath}" refers to a reserved device name or Alternate Data Stream.`,
        canonicalPath: canonical.canonicalPath,
      };
    }

    if (canonical.isDanglingSymlink) {
      return {
        allowed: false,
        decision: "deny",
        ruleId: "PATH_DANGLING_SYMLINK",
        reason: `Access denied: Path "${userPath}" is a dangling symbolic link.`,
        canonicalPath: canonical.canonicalPath,
      };
    }

    const cPath = canonical.canonicalPath;

    // Check glob restrictions (e.g. **/.env)
    const baseName = path.basename(cPath);
    const normCanonical = cPath.replace(/\\/g, "/");
    const normUser = userPath.replace(/\\/g, "/");
    for (const globRegex of this.restrictedGlobs) {
      if (
        globRegex.test(normCanonical) ||
        globRegex.test(baseName) ||
        globRegex.test(normUser)
      ) {
        return {
          allowed: false,
          decision: "deny",
          ruleId: "PATH_RESTRICTED_GLOB",
          reason: `Access denied: Path "${userPath}" matches restricted pattern.`,
          canonicalPath: cPath,
        };
      }
    }

    // Check against literal restricted paths
    for (const restricted of this.canonicalRestrictedPaths) {
      if (isInsideOrEqual(restricted, cPath) || arePathsEqual(restricted, cPath)) {
        return {
          allowed: false,
          decision: "deny",
          ruleId: "PATH_RESTRICTED",
          reason: `Access denied: Path "${userPath}" resolves into restricted location "${restricted}".`,
          canonicalPath: cPath,
        };
      }
    }

    // Check write-restricted paths
    if (operation === "write" || operation === "delete") {
      for (const restrictedWrite of this.canonicalRestrictedPathsWrite) {
        if (isInsideOrEqual(restrictedWrite, cPath) || arePathsEqual(restrictedWrite, cPath)) {
          return {
            allowed: false,
            decision: "deny",
            ruleId: "PATH_WRITE_RESTRICTED",
            reason: `Access denied: Path "${userPath}" is restricted from modifications.`,
            canonicalPath: cPath,
          };
        }
      }
    }

    // Must be inside an allowed root (configured roots or active session roots)
    const allRoots = [...this.canonicalRoots, ...this.sessionRoots].sort((a, b) => b.path.length - a.path.length);
    const matchingRoot = allRoots.find((root) => isInsideOrEqual(root.path, cPath));

    if (!matchingRoot) {
      if (this.config.unknown_path === "ask") {
        const approved = this.approver.request("access_path", {
          path: cPath,
          userPath,
          operation,
        });

        if (approved === true) {
          let dirToGrant = cPath;
          try {
            const stat = fs.statSync(cPath);
            if (!stat.isDirectory()) {
              dirToGrant = path.dirname(cPath);
            }
          } catch {
            dirToGrant = path.dirname(cPath);
          }
          const accessLevel: "rw" | "ro" = (operation === "write" || operation === "delete") ? "rw" : "ro";
          this.addSessionRoot(dirToGrant, accessLevel);

          return {
            allowed: true,
            decision: "approved",
            ruleId: "PATH_JIT_APPROVED",
            reason: `Access to "${userPath}" was approved by approver for this session.`,
            canonicalPath: cPath,
          };
        } else {
          return {
            allowed: false,
            decision: "rejected",
            ruleId: "PATH_JIT_REJECTED",
            reason: `Access to path "${userPath}" outside allowed roots was requested and denied by approver.`,
            canonicalPath: cPath,
          };
        }
      }

      return {
        allowed: false,
        decision: "deny",
        ruleId: "PATH_OUTSIDE_ALLOWED_ROOTS",
        reason: `Access denied: Path "${userPath}" does not reside within any allowed policy root.`,
        canonicalPath: cPath,
      };
    }

    // Root access level check
    if ((operation === "write" || operation === "delete") && matchingRoot.access === "ro") {
      return {
        allowed: false,
        decision: "deny",
        ruleId: "ROOT_READ_ONLY",
        reason: `Access denied: Root "${matchingRoot.path}" is configured as read-only.`,
        canonicalPath: cPath,
      };
    }

    return {
      allowed: true,
      decision: "allow",
      ruleId: "PATH_ALLOWED",
      reason: `Path allowed within root "${matchingRoot.path}" (${matchingRoot.access}).`,
      canonicalPath: cPath,
    };
  }

  /**
   * Helper to quickly check if a directory or file is restricted (for list/search skip logic).
   */
  public isRestrictedPath(targetPath: string, baseDir: string = this.workspaceRoot): boolean {
    const decision = this.checkPath(targetPath, "read", baseDir);
    return !decision.allowed;
  }

  /**
   * Synchronous command checking API.
   * Normalizes command, checks restricted/approve lists, argument paths, and unknown_command.
   */
  public checkCommand(command: string, args: string[] = [], cwd: string = this.workspaceRoot): PolicyDecision {
    const normCmd = normalizeCommandName(command);

    // 1. Check built-in restricted commands
    if (BUILT_IN_RESTRICTED_COMMANDS.has(normCmd)) {
      return {
        allowed: false,
        decision: "deny",
        ruleId: "CMD_RESTRICTED_BUILTIN",
        reason: `Command "${command}" is restricted by system security policy.`,
        command: normCmd,
        args,
      };
    }

    // 2. Check inline interpreters / nested shells with dangerous flags
    for (const interpreter of INLINE_INTERPRETERS) {
      if (normCmd === interpreter.command) {
        // Check if any argument matches an inline execution flag
        for (const arg of args) {
          const lowerArg = arg.toLowerCase();
          if (interpreter.flags.some((flag) => lowerArg === flag || lowerArg.startsWith(flag + ":") || lowerArg.startsWith(flag + "="))) {
            return {
              allowed: false,
              decision: "deny",
              ruleId: "CMD_RESTRICTED_INLINE_INTERPRETER",
              reason: `Command "${command}" with inline evaluation flag "${arg}" is restricted.`,
              command: normCmd,
              args,
            };
          }
        }
      }
    }

    // 3. Check user config restricted commands
    const userRestricted = new Set(this.config.commands.restricted.map(normalizeCommandName));
    if (userRestricted.has(normCmd)) {
      return {
        allowed: false,
        decision: "deny",
        ruleId: "CMD_RESTRICTED_CONFIG",
        reason: `Command "${command}" is restricted by user policy configuration.`,
        command: normCmd,
        args,
      };
    }

    // 4. Windows shell wrapper metacharacter scan
    if (WINDOWS_WRAPPERS.has(normCmd)) {
      const hasMeta = args.some((arg) => SHELL_METACHARS.some((char) => arg.includes(char)));
      if (hasMeta) {
        return {
          allowed: false,
          decision: "deny",
          ruleId: "CMD_SHELL_METACHARS",
          reason: `Command arguments contain disallowed shell metacharacters: ${SHELL_METACHARS.join(" ")}`,
          command: normCmd,
          args,
        };
      }
    }

    // 5. Argument path scan: inspect all path-like arguments against path policy
    for (const arg of args) {
      if (looksLikePath(arg)) {
        const pathDecision = this.checkPath(arg, "read", cwd);
        if (!pathDecision.allowed) {
          return {
            allowed: false,
            decision: "deny",
            ruleId: "CMD_ARG_PATH_RESTRICTED",
            reason: `Command argument "${arg}" references a restricted or disallowed path: ${pathDecision.reason}`,
            command: normCmd,
            args,
          };
        }
      }
    }

    // 6. Check CWD against path policy
    const cwdDecision = this.checkPath(cwd, "read", this.workspaceRoot);
    if (!cwdDecision.allowed) {
      return {
        allowed: false,
        decision: "deny",
        ruleId: "CMD_CWD_RESTRICTED",
        reason: `Working directory "${cwd}" is not permitted: ${cwdDecision.reason}`,
        command: normCmd,
        args,
      };
    }

    // 7. Check user config allow list
    const userAllow = new Set(this.config.commands.allow.map(normalizeCommandName));
    if (userAllow.has(normCmd)) {
      return {
        allowed: true,
        decision: "allow",
        ruleId: "CMD_ALLOWED_CONFIG",
        reason: `Command "${command}" is pre-approved by user policy configuration.`,
        command: normCmd,
        args,
      };
    }

    // 8. Check if command was granted for this session
    if (this.sessionCommands.has(normCmd)) {
      return {
        allowed: true,
        decision: "approved",
        ruleId: "CMD_SESSION_ALLOWED",
        reason: `Command "${command}" is permitted for this session.`,
        command: normCmd,
        args,
      };
    }

    // 9. Check user config approve list
    const userApprove = new Set(this.config.commands.approve.map(normalizeCommandName));
    if (userApprove.has(normCmd)) {
      return this.evaluateApproval("execute_command", { command, normCmd, args, cwd }, "CMD_APPROVE_LIST");
    }

    // 9. Handle unknown_command
    switch (this.config.unknown_command) {
      case "deny":
        return {
          allowed: false,
          decision: "deny",
          ruleId: "CMD_UNKNOWN_DENY",
          reason: `Command "${command}" is not on an approved list and unknown_command is set to "deny".`,
          command: normCmd,
          args,
        };
      case "ask":
        return this.evaluateApproval("execute_command", { command, normCmd, args, cwd }, "CMD_UNKNOWN_ASK");
      case "allow":
      default:
        return {
          allowed: true,
          decision: "allow",
          ruleId: "CMD_ALLOWED",
          reason: `Command "${command}" permitted by policy.`,
          command: normCmd,
          args,
        };
    }
  }

  private evaluateApproval(action: string, details: Record<string, any>, ruleId: string): PolicyDecision {
    const approved = this.approver.request(action, details);
    if (approved === true) {
      this.sessionCommands.add(details.normCmd);
      return {
        allowed: true,
        decision: "approved",
        ruleId,
        reason: `Command "${details.command}" was explicitly approved by approver.`,
        command: details.normCmd,
        args: details.args,
      };
    } else {
      return {
        allowed: false,
        decision: "rejected",
        ruleId,
        reason: `Command "${details.command}" required approval and was denied/rejected by approver.`,
        command: details.normCmd,
        args: details.args,
      };
    }
  }
}
