import * as fs from "fs";
import * as path from "path";

const DOS_DEVICE_REGEX = /^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?$/i;

export interface CanonicalResult {
  canonicalPath: string;
  exists: boolean;
  isDanglingSymlink: boolean;
  isReservedDevice: boolean;
}

/**
 * Strips Windows extended-length prefix (\\?\) and normalizes UNC syntax.
 */
export function stripExtendedPrefix(p: string): string {
  if (p.startsWith("\\\\?\\UNC\\")) {
    return "\\" + p.slice(7);
  }
  if (p.startsWith("\\\\?\\")) {
    return p.slice(4);
  }
  return p;
}

/**
 * Trims trailing dots and spaces from path segments (Windows file system quirk).
 */
export function normalizeWindowsTrailingChars(p: string): string {
  const parts = p.split(/[/\\]/);
  const normalizedParts = parts.map((part, index) => {
    // Preserve drive letter like "C:"
    if (index === 0 && /^[a-zA-Z]:$/.test(part)) {
      return part;
    }
    // Windows trims trailing dots and spaces in filename resolution
    return part.replace(/[. ]+$/, "");
  });
  return normalizedParts.join(path.sep);
}

/**
 * Checks if any segment of the path corresponds to a reserved DOS device name.
 */
export function hasDosDeviceName(p: string): boolean {
  const parts = p.split(/[/\\]/);
  for (const part of parts) {
    if (DOS_DEVICE_REGEX.test(part)) {
      return true;
    }
  }
  return false;
}

/**
 * Checks for Alternate Data Stream notation (e.g. file.txt:stream).
 * Drive letters (e.g. C:) are excluded.
 */
export function hasAlternateDataStream(p: string): boolean {
  // Strip drive letter if present
  const stripped = /^[a-zA-Z]:/.test(p) ? p.slice(2) : p;
  return stripped.includes(":");
}

/**
 * Canonicalizes a path securely:
 * 1. Checks for DOS device names and alternate data streams.
 * 2. Resolves relative to baseDir (defaulting to process.cwd()).
 * 3. Strips extended \\?\ prefixes and trailing dots/spaces.
 * 4. Resolves realpath (symlinks, junctions, 8.3 short names where supported by OS).
 * 5. For non-existent files: finds the nearest existing ancestor, resolves its realpath,
 *    and appends the remaining relative segments (defending against dangling symlink escapes GHSA-8jc4-x8v7-2q9r).
 */
export function canonicalizePath(userPath: string, baseDir: string = process.cwd()): CanonicalResult {
  if (hasDosDeviceName(userPath)) {
    return {
      canonicalPath: userPath,
      exists: false,
      isDanglingSymlink: false,
      isReservedDevice: true,
    };
  }

  if (hasAlternateDataStream(userPath)) {
    return {
      canonicalPath: userPath,
      exists: false,
      isDanglingSymlink: false,
      isReservedDevice: true,
    };
  }

  const cleanPath = normalizeWindowsTrailingChars(stripExtendedPrefix(userPath));
  const resolved = path.isAbsolute(cleanPath)
    ? path.resolve(cleanPath)
    : path.resolve(baseDir, cleanPath);

  try {
    const real = fs.realpathSync.native ? fs.realpathSync.native(resolved) : fs.realpathSync(resolved);
    return {
      canonicalPath: stripExtendedPrefix(real),
      exists: true,
      isDanglingSymlink: false,
      isReservedDevice: false,
    };
  } catch (err: any) {
    // Check if target is a dangling symlink
    try {
      const stat = fs.lstatSync(resolved);
      if (stat.isSymbolicLink()) {
        return {
          canonicalPath: stripExtendedPrefix(resolved),
          exists: false,
          isDanglingSymlink: true,
          isReservedDevice: false,
        };
      }
    } catch {
      // not a symlink or doesn't exist
    }

    // Walk up ancestor directories to find nearest existing directory
    let current = path.dirname(resolved);
    const segments: string[] = [path.basename(resolved)];
    let realAncestor = "";
    let foundAncestor = false;

    while (true) {
      try {
        const lstat = fs.lstatSync(current);
        if (lstat.isSymbolicLink()) {
          const resolvedSymlink = fs.realpathSync.native ? fs.realpathSync.native(current) : fs.realpathSync(current);
          realAncestor = resolvedSymlink;
        } else {
          realAncestor = fs.realpathSync.native ? fs.realpathSync.native(current) : fs.realpathSync(current);
        }
        foundAncestor = true;
        break;
      } catch (ancestorErr: any) {
        if (ancestorErr.code === "ENOENT") {
          const parent = path.dirname(current);
          if (parent === current) {
            break; // reached root
          }
          segments.unshift(path.basename(current));
          current = parent;
        } else {
          break;
        }
      }
    }

    if (foundAncestor) {
      const reconstructed = path.resolve(realAncestor, ...segments);
      return {
        canonicalPath: stripExtendedPrefix(reconstructed),
        exists: false,
        isDanglingSymlink: false,
        isReservedDevice: false,
      };
    }

    return {
      canonicalPath: stripExtendedPrefix(resolved),
      exists: false,
      isDanglingSymlink: false,
      isReservedDevice: false,
    };
  }
}

/**
 * Compares two paths taking platform case sensitivity into account (case-insensitive on Windows/macOS).
 */
export function arePathsEqual(pathA: string, pathB: string): boolean {
  if (process.platform === "win32" || process.platform === "darwin") {
    return path.normalize(pathA).toLowerCase() === path.normalize(pathB).toLowerCase();
  }
  return path.normalize(pathA) === path.normalize(pathB);
}

/**
 * Checks if targetPath is inside or equal to parentDir.
 */
export function isInsideOrEqual(parentDir: string, targetPath: string): boolean {
  const normParent = path.normalize(parentDir);
  const normTarget = path.normalize(targetPath);

  const rel = path.relative(normParent, normTarget);
  if (rel === "" || (!rel.startsWith("..") && !path.isAbsolute(rel))) {
    // On Windows, verify same drive letter
    if (process.platform === "win32") {
      const rootParent = path.parse(normParent).root.toLowerCase();
      const rootTarget = path.parse(normTarget).root.toLowerCase();
      if (rootParent !== rootTarget) return false;
    }
    return true;
  }
  return false;
}
