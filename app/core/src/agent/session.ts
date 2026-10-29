import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import type { ChatMessage } from "../providers/meta.js";
import { getSystemPrompt } from "../prompts/loader.js";
import { getRepoRoot } from "../config.js";

export interface Session {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

export class SessionStore {
  private sessions = new Map<string, Session>();
  private filePath: string;

  constructor(filePath?: string) {
    this.filePath = filePath || path.join(getRepoRoot(), "data", "sessions.json");
    this.loadFromDisk();
  }

  private loadFromDisk(): void {
    try {
      if (fs.existsSync(this.filePath)) {
        const raw = fs.readFileSync(this.filePath, "utf-8");
        const list: Session[] = JSON.parse(raw);
        if (Array.isArray(list) && list.length > 0) {
          for (const s of list) {
            if (s && s.id && Array.isArray(s.messages)) {
              this.sessions.set(s.id, s);
            }
          }
        }
      }
    } catch (err) {
      console.warn("[SessionStore] Failed to load sessions from disk, starting fresh:", err);
    }

    if (this.sessions.size === 0) {
      this.createSession("New Conversation");
    }
  }

  private saveToDisk(): void {
    try {
      const dir = path.dirname(this.filePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
      const data = JSON.stringify(Array.from(this.sessions.values()), null, 2);
      fs.writeFileSync(this.filePath, data, "utf-8");
    } catch (err) {
      console.warn("[SessionStore] Failed to save sessions to disk:", err);
    }
  }

  public createSession(title: string = "New Conversation"): Session {
    const id = `sess_${crypto.randomBytes(6).toString("hex")}`;
    const session: Session = {
      id,
      title,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      messages: [
        {
          role: "system",
          content: getSystemPrompt(),
        },
      ],
    };
    this.sessions.set(id, session);
    this.saveToDisk();
    return session;
  }

  public getSession(id: string): Session | undefined {
    return this.sessions.get(id);
  }

  public listSessions(): Array<Omit<Session, "messages"> & { messageCount: number }> {
    return Array.from(this.sessions.values())
      .map((s) => ({
        id: s.id,
        title: s.title,
        createdAt: s.createdAt,
        updatedAt: s.updatedAt,
        messageCount: Math.max(0, s.messages.length - 1), // minus system message
      }))
      .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  }

  public deleteSession(id: string): boolean {
    const deleted = this.sessions.delete(id);
    if (deleted) {
      this.saveToDisk();
    }
    return deleted;
  }

  public appendMessage(sessionId: string, message: ChatMessage): Session | undefined {
    const session = this.sessions.get(sessionId);
    if (!session) return undefined;

    session.messages.push(message);
    session.updatedAt = new Date().toISOString();

    // Auto-update title from first user message
    if (session.messages.length === 2 && message.role === "user") {
      const rawText =
        typeof message.content === "string"
          ? message.content
          : Array.isArray(message.content)
            ? (message.content.find((p) => p.type === "text") as { text: string })?.text || ""
            : "";
      const cleanTitle = rawText.slice(0, 40).replace(/\n/g, " ");
      session.title = cleanTitle.length > 0 ? cleanTitle : "New Conversation";
    }

    this.saveToDisk();
    return session;
  }
}

export const sessionStore = new SessionStore();
