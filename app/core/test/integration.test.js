import test from "node:test";
import assert from "node:assert";
import { toolResultBuffer } from "../dist/mcp/buffer.js";
import { redactSecrets } from "../dist/trace/bus.js";

const TOKEN = "b1f82975bcebd22307d4e774e56cbc2f54dc096543b37a2e936433c61d858ab0";
const BASE_URL = "http://127.0.0.1:4100";

test("Acceptance Test 1: /chat without auth token returns 401", async () => {
  const res = await fetch(`${BASE_URL}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: "Hello without token" }),
  });
  assert.strictEqual(res.status, 401, "Expected 401 Unauthorized without Bearer token");
});

test("Acceptance Test 2: API key appears nowhere in browser-served files or /health", async () => {
  // Test dashboard HTML
  const rHtml = await fetch(`${BASE_URL}/`);
  const html = await rHtml.text();
  assert.strictEqual(html.includes("sk-"), false, "No secret tokens in HTML");

  // Test /health endpoint
  const rHealth = await fetch(`${BASE_URL}/health`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  const health = await rHealth.json();
  const rawHealth = JSON.stringify(health);
  assert.strictEqual(rawHealth.includes("sk-"), false, "No API keys leaked in /health");
  assert.strictEqual("apiKey" in health.modelConfig, false, "apiKey not in modelConfig");
});

test("Acceptance Test 3: Secret scrubber redacts OpenAI/Meta/Anthropic tokens", () => {
  const sensitive = "Here is my secret sk-or-v1-abcdef1234567890abcdef1234567890 and Bearer 1234567890123456789012";
  const scrubbed = redactSecrets(sensitive);
  assert.strictEqual(scrubbed.includes("sk-or-v1-"), false, "Secret key must be scrubbed");
  assert.strictEqual(scrubbed.includes("[REDACTED"), true, "Must have REDACTED tag");
});

test("Acceptance Test 4: Tool result truncation and buffer retrieval", () => {
  toolResultBuffer.setMaxResultLength(200);
  const largeOutput = "X".repeat(1000);
  const processed = toolResultBuffer.processResult("test_tool", largeOutput);

  assert.strictEqual(processed.isTruncated, true, "Output should be marked as truncated");
  assert.ok(processed.bufferId, "Buffer ID must be returned");
  assert.ok(processed.text.includes("Truncated 800 characters"), "Text must contain truncation notice");

  const full = toolResultBuffer.getFullResult(processed.bufferId);
  assert.strictEqual(full, largeOutput, "Full content must be retrievable by bufferId");
});

test("Acceptance Test 5: /tools returns all registered MCP tools from both servers", async () => {
  const res = await fetch(`${BASE_URL}/tools`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
  });
  const data = await res.json();
  assert.ok(Array.isArray(data.tools), "Tools must be an array");
  assert.ok(data.tools.length >= 18, `Expected at least 18 tools, got ${data.tools.length}`);

  const toolNames = data.tools.map((t) => t.name);
  assert.ok(toolNames.includes("search_desktop_memory"), "Must include memvision tools");
  assert.ok(toolNames.includes("read_file"), "Must include cli-bridge tools");
  assert.ok(toolNames.includes("get_full_result"), "Must include get_full_result tool");
});
