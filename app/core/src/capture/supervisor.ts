import { spawn, type ChildProcess } from "node:child_process";
import path from "node:path";
import { getRepoRoot, resolvePythonExe } from "../config.js";
import { traceBus } from "../trace/bus.js";

class CaptureSupervisor {
  private process: ChildProcess | null = null;
  private startedAt: string | null = null;
  private lastError: string | null = null;

  public isRunning(): boolean {
    return this.process !== null && !this.process.killed;
  }

  public getStatus() {
    return {
      running: this.isRunning(),
      pid: this.process?.pid || null,
      startedAt: this.startedAt,
      lastError: this.lastError,
    };
  }

  public start(): { success: boolean; pid?: number; message: string } {
    if (this.isRunning()) {
      return { success: true, pid: this.process?.pid, message: "Capture loop is already running" };
    }

    const repoRoot = getRepoRoot();
    const pythonExe = resolvePythonExe();
    const memvisionDir = path.join(repoRoot, "memvison");

    try {
      this.lastError = null;
      this.process = spawn(pythonExe, ["main.py", "run", "--interval", "2.0"], {
        cwd: memvisionDir,
        stdio: ["ignore", "pipe", "pipe"],
        windowsHide: true,
      });

      this.process.on("error", (err) => {
        this.lastError = err.message;
        this.process = null;
        this.startedAt = null;
        traceBus.emitTrace({
          type: "error",
          source: "capture",
          title: "Capture Process Error",
          data: { error: err.message },
        });
      });

      this.startedAt = new Date().toISOString();
      const pid = this.process.pid;

      this.process.stdout?.on("data", (chunk) => {
        const line = chunk.toString().trim();
        if (line) {
          // Log capture output into trace bus if informative
          if (line.includes("Captured") || line.includes("Dropped") || line.includes("Sanitized")) {
            traceBus.emitTrace({
              type: "system",
              source: "capture",
              title: "Capture Loop Activity",
              data: { log: line },
            });
          }
        }
      });

      this.process.stderr?.on("data", (chunk) => {
        const err = chunk.toString().trim();
        if (err && !err.includes("UserWarning") && !err.includes("DeprecationWarning")) {
          this.lastError = err;
        }
      });

      this.process.on("exit", (code, signal) => {
        traceBus.emitTrace({
          type: "capture_toggle",
          source: "capture",
          title: "Capture Loop Stopped",
          data: { exitCode: code, signal, pid },
        });
        this.process = null;
        this.startedAt = null;
      });

      traceBus.emitTrace({
        type: "capture_toggle",
        source: "capture",
        title: "Capture Loop Started",
        data: { pid, interval: 2.0 },
      });

      return { success: true, pid, message: `Capture loop started (PID: ${pid})` };
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      this.lastError = errMsg;
      traceBus.emitTrace({
        type: "error",
        source: "capture",
        title: "Capture Loop Failed to Start",
        data: { error: errMsg },
      });
      return { success: false, message: `Failed to start capture loop: ${errMsg}` };
    }
  }

  public stop(): { success: boolean; message: string } {
    if (!this.isRunning() || !this.process) {
      return { success: true, message: "Capture loop is already stopped" };
    }

    try {
      const pid = this.process.pid;
      this.process.kill("SIGTERM");
      // Safety kill on Windows if not exited
      setTimeout(() => {
        if (this.process && !this.process.killed) {
          this.process.kill("SIGKILL");
        }
      }, 1500);

      this.process = null;
      this.startedAt = null;

      traceBus.emitTrace({
        type: "capture_toggle",
        source: "capture",
        title: "Capture Loop Stopped by User",
        data: { pid },
      });

      return { success: true, message: "Capture loop stopped successfully" };
    } catch (err: unknown) {
      const errMsg = err instanceof Error ? err.message : String(err);
      return { success: false, message: `Failed to stop capture loop: ${errMsg}` };
    }
  }

  public toggle(active?: boolean): { success: boolean; running: boolean; message: string } {
    const shouldRun = active !== undefined ? active : !this.isRunning();
    if (shouldRun) {
      const res = this.start();
      return { success: res.success, running: this.isRunning(), message: res.message };
    } else {
      const res = this.stop();
      return { success: res.success, running: this.isRunning(), message: res.message };
    }
  }

  public destroy() {
    if (this.process) {
      try {
        this.process.kill("SIGKILL");
      } catch {}
      this.process = null;
    }
  }
}

export const captureSupervisor = new CaptureSupervisor();
