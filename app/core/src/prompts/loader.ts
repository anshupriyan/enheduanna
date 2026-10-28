import fs from "node:fs";
import path from "node:path";
import { getRepoRoot } from "../config.js";

const DEFAULT_TIMEZONE = "Asia/Kolkata";

export function getSystemPrompt(userTimezone: string = DEFAULT_TIMEZONE): string {
  const repoRoot = getRepoRoot();
  const promptPath = path.join(repoRoot, "app", "core", "prompts", "system_prompt.txt");

  let template = "";
  if (fs.existsSync(promptPath)) {
    try {
      template = fs.readFileSync(promptPath, "utf-8");
    } catch (err) {
      console.warn("[SystemPrompt] Failed to read prompt template, using fallback", err);
    }
  }

  if (!template) {
    template = `You are Enheduanna, an on-device AI assistant with direct access to desktop screen memory (memvision) and local workspace filesystem (cli-bridge).
Current UTC Timestamp: {{CURRENT_TIME_UTC}}
Current Local Time: {{CURRENT_TIME_LOCAL}} ({{USER_TIMEZONE}})
For past queries, always check get_memory_statistics first to know the covered time range. Never claim the user did not do something; state the coverage limit of the database.`;
  }

  const now = new Date();
  const utcIso = now.toISOString();
  let localString = "";
  try {
    localString = now.toLocaleString("en-US", {
      timeZone: userTimezone,
      dateStyle: "full",
      timeStyle: "long",
    });
  } catch {
    localString = now.toLocaleString("en-US");
  }

  return template
    .replace(/\{\{CURRENT_TIME_UTC\}\}/g, utcIso)
    .replace(/\{\{CURRENT_TIME_LOCAL\}\}/g, localString)
    .replace(/\{\{USER_TIMEZONE\}\}/g, userTimezone);
}
