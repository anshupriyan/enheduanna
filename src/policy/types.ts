import { z } from "zod";

export const RootAccessSchema = z.enum(["rw", "ro"]);
export type RootAccess = z.infer<typeof RootAccessSchema>;

export const RootConfigSchema = z.object({
  path: z.string().min(1, "Root path must not be empty"),
  access: RootAccessSchema.default("rw"),
});
export type RootConfig = z.infer<typeof RootConfigSchema>;

export const UnknownCommandActionSchema = z.enum(["allow", "ask", "deny"]);
export type UnknownCommandAction = z.infer<typeof UnknownCommandActionSchema>;

export const UnknownPathActionSchema = z.enum(["ask", "deny"]);
export type UnknownPathAction = z.infer<typeof UnknownPathActionSchema>;

export const PolicyCommandsSchema = z.object({
  restricted: z.array(z.string()).default([]),
  allow: z.array(z.string()).default([]),
  approve: z.array(z.string()).default([]),
});
export type PolicyCommands = z.infer<typeof PolicyCommandsSchema>;

export const PolicyConfigSchema = z.object({
  mode: z.literal("policy"),
  roots: z.array(RootConfigSchema).min(1, "At least one root must be configured"),
  restricted_paths: z.array(z.string()).default([]),
  restricted_paths_write: z.array(z.string()).default([]),
  commands: PolicyCommandsSchema.default({ restricted: [], approve: [] }),
  unknown_command: UnknownCommandActionSchema.default("allow"),
  unknown_path: UnknownPathActionSchema.default("deny"),
  audit_log_path: z.string().optional(),
});
export type PolicyConfig = z.infer<typeof PolicyConfigSchema>;

export type PathOperation = "read" | "write" | "delete" | "list" | "search" | "execute";

export type DecisionType = "allow" | "ask" | "deny" | "approved" | "rejected";

export interface PolicyDecision {
  allowed: boolean;
  decision: DecisionType;
  ruleId: string;
  reason: string;
  canonicalPath?: string;
  command?: string;
  args?: string[];
}

export interface Approver {
  request(action: string, details: Record<string, any>): boolean | Promise<boolean>;
}
