import crypto from "node:crypto";

export interface BufferedResult {
  id: string;
  toolName: string;
  fullContent: string;
  createdAt: number;
}

export class ToolResultBuffer {
  private buffer = new Map<string, BufferedResult>();
  private maxEntries = 50;
  private maxResultLength: number;

  constructor(maxResultLength: number = 4000) {
    this.maxResultLength = maxResultLength;
  }

  public setMaxResultLength(len: number) {
    this.maxResultLength = len;
  }

  public processResult(toolName: string, rawResult: unknown): { text: string; isTruncated: boolean; bufferId?: string } {
    let text = typeof rawResult === "string" ? rawResult : JSON.stringify(rawResult, null, 2);

    if (text.length <= this.maxResultLength) {
      return { text, isTruncated: false };
    }

    const id = `buf_${crypto.randomBytes(4).toString("hex")}`;
    this.buffer.set(id, {
      id,
      toolName,
      fullContent: text,
      createdAt: Date.now(),
    });

    // Trim old buffer entries
    if (this.buffer.size > this.maxEntries) {
      const oldest = Array.from(this.buffer.keys())[0];
      this.buffer.delete(oldest);
    }

    const preview = text.substring(0, this.maxResultLength);
    const truncatedText = `${preview}\n\n[... Truncated ${text.length - this.maxResultLength} characters. Full output size: ${text.length} chars. To inspect the complete result, call get_full_result({ result_id: "${id}" })]`;

    return { text: truncatedText, isTruncated: true, bufferId: id };
  }

  public getFullResult(resultId: string): string | null {
    const entry = this.buffer.get(resultId);
    return entry ? entry.fullContent : null;
  }
}

export const toolResultBuffer = new ToolResultBuffer();
