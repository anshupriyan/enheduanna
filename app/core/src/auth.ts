import crypto from "node:crypto";
import type { IncomingMessage } from "node:http";

let localAuthToken: string = "";

export function initAuthToken(): string {
  if (!localAuthToken) {
    localAuthToken = crypto.randomBytes(32).toString("hex");
    console.log("==================================================================");
    console.log("  🔐 Enheduanna Localhost Auth Token:");
    console.log(`  ${localAuthToken}`);
    console.log("==================================================================");
  }
  return localAuthToken;
}

export function getAuthToken(): string {
  if (!localAuthToken) {
    return initAuthToken();
  }
  return localAuthToken;
}

export function validateAuth(req: IncomingMessage): boolean {
  const token = getAuthToken();

  // 1. Check Authorization header
  const authHeader = req.headers["authorization"];
  if (authHeader) {
    const parts = authHeader.split(" ");
    if (parts.length === 2 && parts[0].toLowerCase() === "bearer" && parts[1] === token) {
      return true;
    }
  }

  // 2. Check query parameter (essential for browser EventSource /trace)
  const url = new URL(req.url || "/", `http://${req.headers.host || "127.0.0.1"}`);
  const qToken = url.searchParams.get("token");
  if (qToken === token) {
    return true;
  }

  // 3. Check Cookie
  const cookieHeader = req.headers["cookie"];
  if (cookieHeader) {
    const cookies = cookieHeader.split(";").map((c) => c.trim());
    for (const c of cookies) {
      if (c.startsWith("enheduanna_token=")) {
        const val = c.substring("enheduanna_token=".length);
        if (val === token) {
          return true;
        }
      }
    }
  }

  return false;
}
