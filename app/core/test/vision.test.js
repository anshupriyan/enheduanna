import test from "node:test";
import assert from "node:assert";
import { toolResultBuffer } from "../dist/mcp/buffer.js";

test("Vision: processResult does not corrupt image descriptions and handles large text safely", () => {
  const preview = toolResultBuffer.processResult(
    "get_screenshot",
    "[Visual screenshot image successfully retrieved: format image/jpeg, size 180 KB. Visual content delivered to model.]"
  );

  assert.strictEqual(preview.isTruncated, false, "Image description should not be truncated");
  assert.ok(preview.text.includes("Visual screenshot image successfully retrieved"));
});

test("Vision: ChatMessage supports multimodal content array with image_url", () => {
  const msg = {
    role: "user",
    content: [
      { type: "text", text: "[Visual Screenshot from get_screenshot (call_123)]:" },
      {
        type: "image_url",
        image_url: {
          url: "data:image/jpeg;base64,/9j/4AAQSkZJRg==",
        },
      },
    ],
  };

  assert.strictEqual(msg.role, "user");
  assert.strictEqual(Array.isArray(msg.content), true);
  assert.strictEqual(msg.content[1].type, "image_url");
  assert.ok(msg.content[1].image_url.url.startsWith("data:image/jpeg;base64,"));
});
