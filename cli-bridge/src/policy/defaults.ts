import * as os from "os";
import * as path from "path";

/**
 * Returns built-in system restricted directory and file paths.
 */
export function getBuiltInRestrictedPaths(): string[] {
  const home = os.homedir();
  const restricted: string[] = [
    // Standard developer credential folders
    path.join(home, ".ssh"),
    path.join(home, ".aws"),
    path.join(home, ".gnupg"),
    path.join(home, ".azure"),
  ];

  if (process.platform === "win32") {
    const appData = process.env.APPDATA || path.join(home, "AppData", "Roaming");
    const localAppData = process.env.LOCALAPPDATA || path.join(home, "AppData", "Local");

    // Windows credential stores
    restricted.push(
      path.join(appData, "Microsoft", "Credentials"),
      path.join(localAppData, "Microsoft", "Credentials"),
      path.join(appData, "Microsoft", "Protect"),
      path.join(localAppData, "Microsoft", "Vault")
    );

    // Browser profile folders on Windows
    restricted.push(
      path.join(localAppData, "Google", "Chrome", "User Data"),
      path.join(localAppData, "Microsoft", "Edge", "User Data"),
      path.join(localAppData, "BraveSoftware", "Brave-Browser", "User Data"),
      path.join(appData, "Mozilla", "Firefox", "Profiles")
    );
  } else {
    // macOS / Linux browser profile locations
    restricted.push(
      path.join(home, ".mozilla", "firefox"),
      path.join(home, ".config", "google-chrome"),
      path.join(home, "Library", "Application Support", "Google", "Chrome")
    );
  }

  return restricted;
}

/**
 * Built-in restricted commands that are always blocked by default in policy mode.
 */
export const BUILT_IN_RESTRICTED_COMMANDS: ReadonlySet<string> = new Set([
  // Network / Exfiltration tools
  "curl",
  "wget",
  "invoke-webrequest",
  "iwr",
  "certutil",
  "bitsadmin",
  "scp",
  "ftp",
  "sftp",
  "tftp",
  "nc",
  "ncat",
  "netcat",
  "socat",

  // Destructive / System administration commands
  "format",
  "diskpart",
  "reg",
  "net",
  "net1",
  "schtasks",
  "sc",
  "takeown",
  "icacls",
  "bcdedit",
  "shutdown",
  "vssadmin",
  "cipher",
]);

/**
 * Commands that are restricted when invoked with specific flags (inline interpreters & nested shells).
 */
export interface InlineFlagCheck {
  command: string;
  flags: string[];
}

export const INLINE_INTERPRETERS: InlineFlagCheck[] = [
  { command: "cmd", flags: ["/c", "/k"] },
  { command: "powershell", flags: ["-command", "-c", "-encodedcommand", "-e", "-enc"] },
  { command: "pwsh", flags: ["-command", "-c", "-encodedcommand", "-e", "-enc"] },
  { command: "bash", flags: ["-c"] },
  { command: "sh", flags: ["-c"] },
  { command: "zsh", flags: ["-c"] },
  { command: "python", flags: ["-c", "-m"] },
  { command: "python3", flags: ["-c", "-m"] },
  { command: "py", flags: ["-c", "-m"] },
  { command: "node", flags: ["-e", "--eval"] },
  { command: "wsl", flags: ["-e", "--exec"] },
];
