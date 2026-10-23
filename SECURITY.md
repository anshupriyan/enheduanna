# Security Policy

`cli-bridge` handles local filesystem access and shell command execution on behalf of MCP clients. We take security boundaries seriously.

---

## Supported Versions

| Version | Supported |
|---|---|
| 0.0.x / 0.0.1+ | ✅ Yes |

---

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

If you discover a security vulnerability (such as a path traversal bypass, symlink sandbox escape, shell injection vulnerability outside Dev Mode, or unhandled permission escalation):

1. **Private Vulnerability Reporting**: Use the **Security tab** on GitHub and submit a private vulnerability report.
2. If GitHub Private Vulnerability Reporting is unavailable, contact the maintainer (`anshupriyan`) directly on GitHub.

### What to Include
- A description of the vulnerability and potential security impact.
- Steps to reproduce or a minimal proof-of-concept (PoC).
- Affected platform(s) (Windows, macOS, Linux).

---

## Response Expectations

- **Response Time**: Best effort basis. This is a solo-maintained project.
- **Triage & Patch**: Reported vulnerabilities will be triaged as quickly as possible, and a fix will be published in a patch release.

---

## Threat Model & Security Boundaries

`cli-bridge` provides two operational modes:

1. **Workspace Mode (Default)**: Strictly confines file read/write/search/grep operations and command working directories to a single designated workspace root directory using `resolveSafePath` and `fs.realpathSync`.
2. **Policy Mode (Opt-in)**: Multi-root directory access with granular permissions (`rw` vs `ro`), path restrictions, command allow/approve/deny lists, and argument path scanning.

### AI Guardrail vs. Hardened OS Sandbox
> [!IMPORTANT]
> **Policy Mode is a guardrail against AI agent mistakes, hallucinations, and indirect prompt injection — NOT a hardened OS-level sandbox against a hostile, malicious process.**
>
> Once `execute_command` executes with Dev Mode enabled, processes execute under the host user's privileges. While the policy engine normalizes commands, blocks inline interpreters, inspects argument paths, and filters dangerous utilities, a determined adversary with unrestricted native shell access could still interact with OS APIs. Treat this tool as a high-integrity control boundary for automated agents, not as a replacement for OS containerization (Docker, Windows AppContainer, Linux namespaces/seccomp).

### Path Canonicalization & Resolution Scope
- Canonicalization relies primarily on Node's native `fs.realpathSync` and `path.resolve`, alongside Windows-specific normalization (extended-length prefix stripping, trailing dot/space pruning, and ancestor directory resolution for non-existent paths).
- Dangling symlink escapes ([GHSA-8jc4-x8v7-2q9r](https://github.com/advisories/GHSA-8jc4-x8v7-2q9r)) are defended by validating directory ancestors before file creation.
- Non-standard OS filesystem edge cases (such as esoteric 8.3 short name aliasing or Alternate Data Stream manipulation) are defended via path character checks and canonical realpath resolution, but users should avoid mounting untrusted, adversarial filesystem drivers within allowed roots.

### Built-In Safety Invariants
- **Non-Removable Denylist**: Built-in restricted locations (`~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.azure`, browser profile stores, Windows credential vaults, the active policy file, audit log, and `PROJECT_LOG.md`) are hard-coded invariants. User configuration can append additional restrictions, but can never un-restrict built-in paths.
- **Restricted Always Wins**: If an allowed root encompasses a restricted folder (e.g. `C:\Users\Developer` is allowed, but `C:\Users\Developer\.ssh` is restricted), restricted paths take precedence unconditionally.
- **Inline Interpreters & Exfiltration Tools**: Shells and interpreters running inline scripts (`cmd /c`, `powershell -Command`, `pwsh -EncodedCommand`, `bash -c`, `node -e`, `python -c`) and network exfiltration tools (`curl`, `wget`, `certutil`, `bitsadmin`, `iwr`) are blocked by default.
- **Dev Mode Gate**: Dev Mode is strictly in-memory, resets to OFF on every server restart, and gates all command execution in both workspace and policy modes.

