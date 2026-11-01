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

  constructor(maxResultLength: number = 64000) {
    this.maxResultLength = maxResultLength;
  }

  public setMaxResultLength(len: number) {
    this.maxResultLength = len;
  }

  public processResult(toolName: string, rawResult: unknown): { text: string; isTruncated: boolean; bufferId?: string } {
    let text = typeof rawResult === "string" ? rawResult : JSON.stringify(rawResult, null, 2);

    // read_file and code inspection tools get a generous 128KB limit so markdown/source files are never truncated prematurely
    const effectiveLimit = toolName === "read_file" ? Math.max(this.maxResultLength, 128000) : this.maxResultLength;

    if (text.length <= effectiveLimit) {
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

    const preview = text.substring(0, effectiveLimit);
    const truncatedText = `${preview}\n\n[... Truncated ${text.length - effectiveLimit} characters. Full output size: ${text.length} chars. To inspect the complete result, call get_full_result({ result_id: "${id}" }).]`;

    return { text: truncatedText, isTruncated: true, bufferId: id };
  }

  public getFullResult(resultId: string): string | null {
    const entry = this.buffer.get(resultId);
    return entry ? entry.fullContent : null;
  }
}

export const toolResultBuffer = new ToolResultBuffer();
