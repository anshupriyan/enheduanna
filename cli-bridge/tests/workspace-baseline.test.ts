import { describe, it, expect } from "vitest";
import { resolveSafePath, scanForUnsafePaths } from "../src/index.js";
import * as path from "path";
import * as fs from "fs";
import * as os from "os";

describe("Workspace Mode Baseline Characterization Tests", () => {
  const root = fs.realpathSync(process.cwd());

  describe("resolveSafePath (legacy baseline)", () => {
    it("resolves an existing file inside the root", () => {
      const target = "package.json";
      const resolved = resolveSafePath(root, target);
      expect(resolved.toLowerCase()).toBe(path.join(root, "package.json").toLowerCase());
    });

    it("resolves a non-existent file inside an existing workspace folder", () => {
      const target = "src/non-existent-test-file.xyz";
      const resolved = resolveSafePath(root, target);
      expect(resolved.toLowerCase()).toBe(path.join(root, "src", "non-existent-test-file.xyz").toLowerCase());
    });

    it("resolves a nested non-existent path where parent does not exist yet", () => {
      const target = "temp_test_dir/nested/newfile.txt";
      const resolved = resolveSafePath(root, target);
      expect(resolved.toLowerCase()).toBe(path.resolve(root, target).toLowerCase());
    });

    it("throws when path traverses outside root via ../", () => {
      expect(() => resolveSafePath(root, "../outside.txt")).toThrow(/Access denied/);
      expect(() => resolveSafePath(root, "src/../../outside.txt")).toThrow(/Access denied/);
    });

    it("throws when given an absolute path outside the root", () => {
      const tempOutside = os.tmpdir();
      if (!tempOutside.toLowerCase().startsWith(root.toLowerCase())) {
        expect(() => resolveSafePath(root, tempOutside)).toThrow(/Access denied/);
      }
    });

    it("detects dangling symlink and throws Access Denied (GHSA-8jc4-x8v7-2q9r)", () => {
      const danglingLink = path.join(root, "test-dangling-symlink.lnk");
      try {
        // Attempt creating a dangling symlink
        fs.symlinkSync("non-existent-target-file.xyz", danglingLink, "file");
        expect(() => resolveSafePath(root, "test-dangling-symlink.lnk")).toThrow(/Access denied/);
      } catch (err: any) {
        // If unprivileged symlink creation is not permitted on Windows without Dev Mode, skip gracefully
        if (err.code !== "EPERM") {
          throw err;
        }
      } finally {
        try {
          if (fs.existsSync(danglingLink) || fs.lstatSync(danglingLink).isSymbolicLink()) {
            fs.unlinkSync(danglingLink);
          }
        } catch {
          // ignore cleanup
        }
      }
    });
  });

  describe("scanForUnsafePaths (legacy baseline)", () => {
    it("identifies paths resolving outside workspace root", () => {
      const outsideArg = path.join(path.dirname(root), "secret.txt");
      const unsafe = scanForUnsafePaths("cat", [outsideArg]);
      expect(unsafe).toContain(outsideArg);
    });

    it("flags relative traversal arguments", () => {
      const unsafe = scanForUnsafePaths("type", ["../secret.txt"]);
      expect(unsafe).toContain("../secret.txt");
    });

    it("passes safe arguments inside root", () => {
      const unsafe = scanForUnsafePaths("git", ["status", "package.json"]);
      expect(unsafe).toEqual([]);
    });

    it("ignores URLs in arguments", () => {
      const unsafe = scanForUnsafePaths("git", ["clone", "https://github.com/example/repo.git"]);
      expect(unsafe).toEqual([]);
    });
  });
});
