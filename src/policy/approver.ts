import { Approver } from "./types.js";

/**
 * Default Approver: fails closed, always denying approval.
 */
export class DefaultDenyApprover implements Approver {
  request(action: string, details: Record<string, any>): boolean {
    return false;
  }
}

/**
 * Synchronous mock approver for automated testing and programmatic policy harnesses.
 */
export class SyncMockApprover implements Approver {
  private handler: (action: string, details: Record<string, any>) => boolean;

  constructor(handler: boolean | ((action: string, details: Record<string, any>) => boolean) = true) {
    if (typeof handler === "boolean") {
      this.handler = () => handler;
    } else {
      this.handler = handler;
    }
  }

  setDecision(allowed: boolean): void {
    this.handler = () => allowed;
  }

  setHandler(fn: (action: string, details: Record<string, any>) => boolean): void {
    this.handler = fn;
  }

  request(action: string, details: Record<string, any>): boolean {
    return this.handler(action, details);
  }
}
