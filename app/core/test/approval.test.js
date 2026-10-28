import test from "node:test";
import assert from "node:assert";
import { approvalManager } from "../dist/agent/approval.js";

test("Approval: needsApproval accurately detects sensitive tool calls", () => {
  // Sensitive tool calls that require interactive authorization
  assert.strictEqual(
    approvalManager.needsApproval("request_path_access", { path: "C:/", access: "ro" }).needs,
    true,
    "request_path_access must require approval"
  );

  assert.strictEqual(
    approvalManager.needsApproval("execute_command", { command: "cmd.exe", args: ["/c", "dir"] }).needs,
    true,
    "execute_command must require approval"
  );

  assert.strictEqual(
    approvalManager.needsApproval("toggle_dev_mode", { enable_dev_mode: true }).needs,
    true,
    "toggle_dev_mode with true must require approval"
  );

  assert.strictEqual(
    approvalManager.needsApproval("toggle_dev_mode", { enable_dev_mode: false }).needs,
    false,
    "toggle_dev_mode with false does not require approval"
  );

  assert.strictEqual(
    approvalManager.needsApproval("request_command_access", { command: "rm" }).needs,
    true,
    "request_command_access must require approval"
  );

  // Non-sensitive standard read tools
  assert.strictEqual(
    approvalManager.needsApproval("get_memory_statistics", {}).needs,
    false,
    "get_memory_statistics must not require approval"
  );

  assert.strictEqual(
    approvalManager.needsApproval("search_desktop_memory", { query: "test" }).needs,
    false,
    "search_desktop_memory must not require approval"
  );

  assert.strictEqual(
    approvalManager.needsApproval("list_directory", { path: "." }).needs,
    false,
    "list_directory must not require approval"
  );
});

test("Approval: createRequest and resolveRequest flow", async () => {
  const sessionId = "sess_test_123";
  const { request, promise } = approvalManager.createRequest({
    sessionId,
    step: 2,
    toolCallId: "call_abc123",
    toolName: "request_path_access",
    title: "Path Access",
    description: "Access path C:/",
    args: { path: "C:/", access: "ro" },
  });

  assert.strictEqual(request.status, "pending");
  assert.strictEqual(request.sessionId, sessionId);

  const pending = approvalManager.getPending(sessionId);
  assert.strictEqual(pending.length, 1);
  assert.strictEqual(pending[0].id, request.id);

  // Resolve with approval
  const ok = approvalManager.resolveRequest(request.id, true);
  assert.strictEqual(ok, true);

  const approvedResult = await promise;
  assert.strictEqual(approvedResult, true, "Promise must resolve with true");
  assert.strictEqual(approvalManager.getPending(sessionId).length, 0, "No pending approvals remaining");
});

test("Approval: resolveRequest with denial", async () => {
  const sessionId = "sess_test_deny";
  const { request, promise } = approvalManager.createRequest({
    sessionId,
    step: 3,
    toolCallId: "call_deny_1",
    toolName: "execute_command",
    title: "Shell Exec",
    description: "Execute bash",
    args: { command: "bash" },
  });

  const ok = approvalManager.resolveRequest(request.id, false);
  assert.strictEqual(ok, true);

  const deniedResult = await promise;
  assert.strictEqual(deniedResult, false, "Promise must resolve with false on denial");
});
