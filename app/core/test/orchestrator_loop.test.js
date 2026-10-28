import test from "node:test";
import assert from "node:assert";
import { Orchestrator } from "../dist/agent/orchestrator.js";
import { sessionStore } from "../dist/agent/session.js";

// Helper mock ServerResponse
function createMockResponse() {
  const chunks = [];
  return {
    chunks,
    write(str) {
      chunks.push(str);
    },
    end() {},
    getEvent(type) {
      for (const c of chunks) {
        if (c.includes(`event: ${type}`)) {
          const match = c.match(/data: (.*)\n\n/);
          if (match) return JSON.parse(match[1]);
        }
      }
      return null;
    },
    getAllEvents(type) {
      const found = [];
      for (const c of chunks) {
        if (c.includes(`event: ${type}`)) {
          const match = c.match(/data: (.*)\n\n/);
          if (match) found.push(JSON.parse(match[1]));
        }
      }
      return found;
    },
  };
}

// Mock Model Provider
class MockModelProvider {
  constructor(responses) {
    this.responses = [...responses];
    this.callHistory = [];
  }

  async callStreaming(messages, tools, apiKey, callbacks) {
    this.callHistory.push({ messages: [...messages], tools: [...tools] });
    const current = this.responses.shift() || { reply: "Fallback answer", toolCalls: [] };

    if (current.reasoning && callbacks.onReasoningDelta) {
      callbacks.onReasoningDelta(current.reasoning);
    }
    if (current.reply && callbacks.onDelta) {
      callbacks.onDelta(current.reply);
    }
    if (current.toolCalls && callbacks.onToolCall) {
      for (const tc of current.toolCalls) {
        callbacks.onToolCall(tc);
      }
    }

    return {
      reply: current.reply || "",
      reasoning: current.reasoning,
      toolCalls: current.toolCalls || [],
    };
  }
}

// Mock MCP Manager
class MockMcpManager {
  constructor(handlers = {}) {
    this.handlers = handlers;
    this.executedCalls = [];
  }

  getChatCompletionsTools() {
    return [
      { type: "function", function: { name: "search_desktop_memory", description: "Search", parameters: {} } },
      { type: "function", function: { name: "get_memory_statistics", description: "Stats", parameters: {} } },
      { type: "function", function: { name: "tool_slow", description: "300ms", parameters: {} } },
      { type: "function", function: { name: "tool_med", description: "200ms", parameters: {} } },
      { type: "function", function: { name: "tool_fast", description: "100ms", parameters: {} } },
      { type: "function", function: { name: "tool_failing", description: "fails", parameters: {} } },
    ];
  }

  async executeTool(name, args) {
    this.executedCalls.push({ name, args, time: Date.now() });
    if (this.handlers[name]) {
      return this.handlers[name](args);
    }
    return { content: `Result from ${name}`, isError: false };
  }
}

const TEST_CONFIG = {
  server: { host: "127.0.0.1", port: 4100 },
  model: { provider: "meta", modelName: "muse-spark-1.3", baseUrl: "http://mock", reasoningEffort: "medium" },
  limits: { maxSteps: 6, maxParallelToolCalls: 5, maxToolResultLength: 4000 },
  mcpServers: { memvision: { command: "", args: [], cwd: "" }, "cli-bridge": { command: "", args: [], cwd: "" } },
};

test("1. Two-step flow: step 1 tool call -> step 2 final answer completes without user input", async () => {
  const mockModel = new MockModelProvider([
    // Step 1: Model calls tool
    {
      reply: "I will look into memory",
      toolCalls: [{ id: "call_step1", name: "search_desktop_memory", arguments: { query: "youtube" } }],
    },
    // Step 2: Model gives final answer
    {
      reply: "I checked screen memory: no YouTube captures were found during the 20-minute recorded session.",
      toolCalls: [],
    },
  ]);

  const mockMcp = new MockMcpManager({
    search_desktop_memory: async () => ({ content: JSON.stringify({ matches: [] }), isError: false }),
  });

  const orchestrator = new Orchestrator(TEST_CONFIG, mockMcp, mockModel);
  const session = sessionStore.createSession("Test Two Step");
  const mockRes = createMockResponse();

  await orchestrator.runTurn(session.id, "Did I watch YouTube?", {}, mockRes);

  assert.strictEqual(mockModel.callHistory.length, 2, "Model should be called exactly twice");
  assert.strictEqual(mockMcp.executedCalls.length, 1, "Tool should be executed once");

  // Check that final answer event was emitted
  const doneEvent = mockRes.getEvent("done");
  assert.ok(doneEvent, "done event must be emitted");
  assert.strictEqual(doneEvent.stepsTaken, 2);
  assert.ok(doneEvent.finalAnswer.includes("no YouTube captures were found"));

  // Intermediate narration must NOT be streamed as delta
  const deltas = mockRes.getAllEvents("delta");
  assert.ok(deltas.length > 0);
  for (const d of deltas) {
    assert.strictEqual(d.text.includes("I will look into memory"), false, "Intermediate narration must not be streamed in delta");
  }
});

test("2. Parallel flow: 3 concurrent tool calls (300ms, 200ms, 100ms) complete in ~300ms and map to correct IDs", async () => {
  const mockModel = new MockModelProvider([
    {
      reply: "",
      toolCalls: [
        { id: "call_slow", name: "tool_slow", arguments: { val: 1 } },
        { id: "call_med", name: "tool_med", arguments: { val: 2 } },
        { id: "call_fast", name: "tool_fast", arguments: { val: 3 } },
      ],
    },
    {
      reply: "All parallel tools completed successfully.",
      toolCalls: [],
    },
  ]);

  const mockMcp = new MockMcpManager({
    tool_slow: async () => {
      await new Promise((r) => setTimeout(r, 300));
      return { content: "slow output", isError: false };
    },
    tool_med: async () => {
      await new Promise((r) => setTimeout(r, 200));
      return { content: "med output", isError: false };
    },
    tool_fast: async () => {
      await new Promise((r) => setTimeout(r, 100));
      return { content: "fast output", isError: false };
    },
  });

  const orchestrator = new Orchestrator(TEST_CONFIG, mockMcp, mockModel);
  const session = sessionStore.createSession("Test Parallel");
  const mockRes = createMockResponse();

  const start = Date.now();
  await orchestrator.runTurn(session.id, "Run 3 things in parallel", {}, mockRes);
  const totalElapsed = Date.now() - start;

  // 300ms concurrent vs 600ms sequential: should complete in under 500ms
  assert.ok(totalElapsed < 550, `Expected parallel wall-clock < 550ms, got ${totalElapsed}ms`);

  const groupDone = mockRes.getEvent("tool_group_done");
  assert.ok(groupDone, "tool_group_done must be emitted");
  assert.strictEqual(groupDone.callCount, 3);
  assert.ok(groupDone.wallClockMs >= 280 && groupDone.wallClockMs < 500, `Group wall-clock was ${groupDone.wallClockMs}ms`);

  // Verify tool results in session map to correct call IDs in exact order
  const updatedSession = sessionStore.getSession(session.id);
  const toolMessages = updatedSession.messages.filter((m) => m.role === "tool");
  assert.strictEqual(toolMessages.length, 3);
  assert.strictEqual(toolMessages[0].tool_call_id, "call_slow");
  assert.strictEqual(toolMessages[0].content, "slow output");
  assert.strictEqual(toolMessages[1].tool_call_id, "call_med");
  assert.strictEqual(toolMessages[1].content, "med output");
  assert.strictEqual(toolMessages[2].tool_call_id, "call_fast");
  assert.strictEqual(toolMessages[2].content, "fast output");
});

test("3. Loop guard: repeated identical tool call is blocked with cached result and loop breaks after 2 repeats", async () => {
  let executionCount = 0;
  const mockMcp = new MockMcpManager({
    search_desktop_memory: async () => {
      executionCount++;
      return { content: JSON.stringify({ items: ["capture_1"] }), isError: false };
    },
  });

  const mockModel = new MockModelProvider([
    // Step 1: Model issues tool call
    {
      reply: "",
      toolCalls: [{ id: "call_1", name: "search_desktop_memory", arguments: { query: "brave" } }],
    },
    // Step 2: Model repeats identical tool call (repeat 1)
    {
      reply: "",
      toolCalls: [{ id: "call_2", name: "search_desktop_memory", arguments: { query: "brave" } }],
    },
    // Step 3: Model repeats identical tool call again (repeat 2) -> triggers loop guard break
    {
      reply: "",
      toolCalls: [{ id: "call_3", name: "search_desktop_memory", arguments: { query: "brave" } }],
    },
    // Synthesis call after loop guard break
    {
      reply: "Summary: Brave browser was active based on cached results.",
      toolCalls: [],
    },
  ]);

  const orchestrator = new Orchestrator(TEST_CONFIG, mockMcp, mockModel);
  const session = sessionStore.createSession("Test Loop Guard");
  const mockRes = createMockResponse();

  await orchestrator.runTurn(session.id, "Keep searching brave", {}, mockRes);

  // MCP tool should have only executed ONCE! Subsequent identical calls were served from seen cache
  assert.strictEqual(executionCount, 1, "Identical tool must only be executed once physically");

  const done = mockRes.getEvent("done");
  assert.ok(done);
  assert.ok(done.finalAnswer.includes("Brave browser was active"));
});

test("4. Step cap: hitting maxSteps triggers tools-disabled summary call", async () => {
  const mockModel = new MockModelProvider([
    { reply: "", toolCalls: [{ id: "c1", name: "search_desktop_memory", arguments: { q: 1 } }] },
    { reply: "", toolCalls: [{ id: "c2", name: "search_desktop_memory", arguments: { q: 2 } }] },
    // Synthesis call (tools: [])
    { reply: "Synthesized summary: hit cap after 2 steps.", toolCalls: [] },
  ]);

  const mockMcp = new MockMcpManager();
  const orchestrator = new Orchestrator(TEST_CONFIG, mockMcp, mockModel);
  const session = sessionStore.createSession("Test Step Cap");
  const mockRes = createMockResponse();

  // Run with maxSteps = 2
  await orchestrator.runTurn(session.id, "Endless search", { maxSteps: 2 }, mockRes);

  const capEvent = mockRes.getEvent("step_cap_reached");
  assert.ok(capEvent, "step_cap_reached event must be emitted");
  assert.strictEqual(capEvent.maxSteps, 2);

  // Final call must have had tools disabled (tools: [])
  const lastModelCall = mockModel.callHistory[mockModel.callHistory.length - 1];
  assert.strictEqual(lastModelCall.tools.length, 0, "Final synthesis call must have tools disabled");

  const done = mockRes.getEvent("done");
  assert.ok(done);
  assert.ok(done.finalAnswer.includes("Synthesized summary: hit cap"));
});

test("5. Error resilience: failed tool call does not crash loop or abort sibling parallel calls", async () => {
  const mockModel = new MockModelProvider([
    {
      reply: "",
      toolCalls: [
        { id: "c_fail", name: "tool_failing", arguments: {} },
        { id: "c_ok", name: "search_desktop_memory", arguments: { query: "test" } },
      ],
    },
    {
      reply: "I noticed tool_failing failed with an error, but search succeeded with test data.",
      toolCalls: [],
    },
  ]);

  const mockMcp = new MockMcpManager({
    tool_failing: async () => {
      throw new Error("Device I/O failure");
    },
    search_desktop_memory: async () => ({ content: "search success", isError: false }),
  });

  const orchestrator = new Orchestrator(TEST_CONFIG, mockMcp, mockModel);
  const session = sessionStore.createSession("Test Errors");
  const mockRes = createMockResponse();

  await orchestrator.runTurn(session.id, "Test parallel error resilience", {}, mockRes);

  const updatedSession = sessionStore.getSession(session.id);
  const toolResults = updatedSession.messages.filter((m) => m.role === "tool");
  assert.strictEqual(toolResults.length, 2);

  assert.ok(toolResults[0].content.includes("[Tool Error: Device I/O failure]"));
  assert.strictEqual(toolResults[1].content, "search success");

  const done = mockRes.getEvent("done");
  assert.ok(done);
  assert.ok(done.finalAnswer.includes("search succeeded"));
});

test("6. Coverage limit: statistics showing 44 captures over 20 minutes produces definitive range answer", async () => {
  const mockModel = new MockModelProvider([
    // Step 1: Model calls get_memory_statistics
    {
      reply: "",
      toolCalls: [{ id: "stats_1", name: "get_memory_statistics", arguments: {} }],
    },
    // Step 2: Model recognizes statistics show memory is only 11:00-11:20 today, answers directly with coverage statement
    {
      reply:
        "Recorded screen memory covers from 11:00 to 11:20 UTC today (20 minutes across 44 captures). No memory exists for yesterday.",
      toolCalls: [],
    },
  ]);

  const mockMcp = new MockMcpManager({
    get_memory_statistics: async () => ({
      content: JSON.stringify({
        total_captures: 44,
        oldest_timestamp: "2026-10-28T11:00:00+00:00",
        newest_timestamp: "2026-10-28T11:20:00+00:00",
      }),
      isError: false,
    }),
  });

  const orchestrator = new Orchestrator(TEST_CONFIG, mockMcp, mockModel);
  const session = sessionStore.createSession("Test Yesterday Coverage");
  const mockRes = createMockResponse();

  await orchestrator.runTurn(session.id, "What did I watch yesterday?", {}, mockRes);

  const done = mockRes.getEvent("done");
  assert.ok(done);
  assert.ok(done.finalAnswer.includes("44 captures"));
  assert.ok(done.finalAnswer.includes("No memory exists for yesterday"));
  assert.strictEqual(done.finalAnswer.includes("I will verify"), false);
  assert.strictEqual(done.finalAnswer.includes("I will check"), false);
});
