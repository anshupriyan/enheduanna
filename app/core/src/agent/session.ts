import crypto from "node:crypto";
import type { ChatMessage } from "../providers/meta.js";
import { getSystemPrompt } from "../prompts/loader.js";

export interface Session {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messages: ChatMessage[];
}

export class SessionStore {
  private sessions = new Map<string, Session>();

  constructor() {
    // Create a default session
    this.createSession("New Conversation");
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
        messageCount: s.messages.length - 1, // minus system message
      }))
      .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  }

  public deleteSession(id: string): boolean {
    return this.sessions.delete(id);
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

    return session;
  }
}

export const sessionStore = new SessionStore();
