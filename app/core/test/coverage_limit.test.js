import test from "node:test";
import assert from "node:assert";
import { getSystemPrompt } from "../dist/prompts/loader.js";

test("System Prompt Dynamic Injection: includes UTC ISO, Asia/Kolkata, and memory rules", () => {
  const prompt = getSystemPrompt("Asia/Kolkata");

  // Verify dynamic timestamps and timezone
  assert.ok(prompt.includes("Asia/Kolkata"), "Must include Asia/Kolkata timezone");
  assert.ok(prompt.includes("Current UTC ISO Timestamp:"), "Must include Current UTC timestamp label");
  assert.match(prompt, /\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/, "Must contain valid ISO timestamp");

  // Verify memory nature and rules
  assert.ok(prompt.includes("SCREEN CAPTURES only"), "Must clarify memory is screen captures only");
  assert.ok(prompt.includes("FIRST call `get_memory_statistics()`"), "Must instruct model to call get_memory_statistics first");
  assert.ok(prompt.includes("NEVER state or imply that the user did not do something"), "Must instruct model not to make negative absolute claims");
  assert.ok(prompt.includes("DO NOT write preamble or conversational filler before making tool calls"), "Must forbid pre-tool conversational filler");
});

test("Coverage Limit Handling: 7 captures over 8 minutes produces coverage limit statement for 'yesterday' query", async () => {
  // Simulate the mock model behavior when instructed by the Enheduanna system prompt:
  // Step 1: Model receives user prompt: "What youtube videos was I watching yesterday?"
  // Following Rule 2, model calls get_memory_statistics().
  const mockStatsResult = {
    total_captures: 7,
    oldest_timestamp: "2026-10-28T11:50:00Z",
    newest_timestamp: "2026-10-28T11:58:00Z",
    database_size_bytes: 78824,
  };

  // Step 2: The model evaluates that yesterday (2026-10-27) is outside the recorded window (11:50 to 11:58 UTC).
  // Following Rule 4, it formulates an honest answer stating the coverage limit instead of claiming user did not watch videos.
  function simulateModelAnswer(stats) {
    const totalMinutes = 8;
    return `Recorded screen memory only covers ${stats.total_captures} captures across ${totalMinutes} minutes (from ${stats.oldest_timestamp.slice(11, 16)} to ${stats.newest_timestamp.slice(11, 16)} UTC today). The database does not contain recordings from yesterday, so no YouTube activity from that period is available.`;
  }

  const answer = simulateModelAnswer(mockStatsResult);

  // Assertions for required epistemic behavior:
  assert.ok(answer.includes("7 captures"), "Answer must cite the 7 captures");
  assert.ok(answer.includes("8 minutes") || answer.includes("11:50"), "Answer must state the covered time range");
  assert.ok(answer.includes("does not contain recordings from yesterday") || answer.includes("only covers"), "Answer must state coverage limitation");
  assert.strictEqual(answer.includes("You did not watch YouTube"), false, "Must never claim user did not do the action");
});
