import type { IncomingMessage } from "node:http";

export function initAuthToken(): string {
  return "";
}

export function getAuthToken(): string {
  return "";
}

export function validateAuth(_req?: IncomingMessage): boolean {
  // Local developer mode: open localhost access without tokens
  return true;
}

