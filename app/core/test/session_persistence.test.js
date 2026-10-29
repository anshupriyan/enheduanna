import test from "node:test";
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { SessionStore } from "../dist/agent/session.js";

test("SessionStore: saves, loads, appends, and deletes sessions from disk", () => {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "enheduanna-session-test-"));
  const tmpFile = path.join(tmpDir, "test-sessions.json");

  try {
    // 1. Initial creation
    const store1 = new SessionStore(tmpFile);
    const session1 = store1.createSession("First Conversation");
    assert.ok(fs.existsSync(tmpFile), "sessions.json file must exist on disk");

    // Append a user message
    store1.appendMessage(session1.id, {
      role: "user",
      content: "Hello Enheduanna, remember this conversation across restarts",
    });

    // 2. Re-instantiate from the same file to simulate server restart
    const store2 = new SessionStore(tmpFile);
    const reloaded = store2.getSession(session1.id);
    assert.ok(reloaded, "Session must exist after reloading from disk");
    assert.strictEqual(reloaded.messages.length, 2, "Session messages must match");
    assert.strictEqual(reloaded.messages[1].content, "Hello Enheduanna, remember this conversation across restarts");

    // 3. Delete session
    const deleted = store2.deleteSession(session1.id);
    assert.strictEqual(deleted, true, "Delete must return true");
    assert.strictEqual(store2.getSession(session1.id), undefined, "Session must no longer exist in memory");

    // 4. Verify disk reflects deletion
    const raw = fs.readFileSync(tmpFile, "utf-8");
    const onDisk = JSON.parse(raw);
    const foundOnDisk = onDisk.find((s) => s.id === session1.id);
    assert.strictEqual(foundOnDisk, undefined, "Session must no longer exist on disk");
  } finally {
    try {
      fs.rmSync(tmpDir, { recursive: true, force: true });
    } catch {}
  }
});
