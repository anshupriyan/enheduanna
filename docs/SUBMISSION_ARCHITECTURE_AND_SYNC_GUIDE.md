# Enheduanna — Hackathon Submission Architecture & Sync Guide

**Date:** October 29, 2026  
**Project:** Enheduanna (Meta Hackathon 2026)  
**Submission Repository:** [https://github.com/anshupriyan/enheduanna-meta-submission](https://github.com/anshupriyan/enheduanna-meta-submission)  
**Active Development Directory:** `C:\meta hackathon\enheduanna`  
**Submission Staging Directory:** `C:\meta hackathon\enheduanna-submission`  

---

## 1. Executive Summary & Official Rules Clarification

### The Problem
During development, the project monorepo (`enheduanna`) had incorporated `cli-bridge` (an MCP execution tool developed prior to kickoff between July and October 24, 2026). 

On October 29, 2026, **Cerebral Valley (Hackathon Organizers)** officially ruled on prior work:
> *"Work done before kickoff counts as pre-existing, regardless of when you were approved. Building started when the Oct 26 kickoff ended at 12:24 PM ET, so your Oct 23-24 changes should be listed as pre-existing work in your submission. Your tagged Oct 26 baseline doesn't change that, since a git tag alone doesn't make earlier code count as new work.*  
> 
> *Also, the submitted repo must be a fresh public repo created on Oct 26 or later, holding only work done during the event. Keep the cli-bridge code and its git history out of it, use it as a labeled dependency if you need it, and open your 3 minute video with one line on what existed before and what you built this week."*

---

## 2. Solution Implemented: Dual-Repository Isolation

To remain 100% compliant without risking or breaking our local development setup, we established a **clean dual-repository architecture**:

```
+--------------------------------------------------------------------------------------------------+
|                                    LOCAL MACHINE (C:\meta hackathon)                             |
+--------------------------------------------------------------------------------------------------+
|                                                                                                  |
|   1. ACTIVE DEVELOPMENT MONOREPO                             2. SUBMISSION REPO (ISOLATED)       |
|      Directory: C:\meta hackathon\enheduanna                    Directory: ...\enheduanna-sub... |
|      Git Remote: origin -> enheduanna                           Git Remote: origin -> submission |
|      Tracking: cli-bridge UNTRACKED in git (.gitignore)         Remote local-dev -> enheduanna   |
|      Local Files: cli-bridge/ folder KEPT ON DISK               Git History: 51 Commits ONLY     |
|                   All servers run continuously                               Root: Oct 26 22:30   |
|                                                                                                  |
+--------------------------------------------------------------------------------------------------+
                                                                             │
                                                                             ▼ (git push)
                                                                 PUBLIC GITHUB REPO
                                                   github.com/anshupriyan/enheduanna-meta-submission
                                                   * 0 pre-hackathon commits
                                                   * 0 cli-bridge files
                                                   * 100% Oct 26-29 commit history
```

### Key Safety Guarantees
1. **Local environment remains completely functional:** The `cli-bridge/` folder in `C:\meta hackathon\enheduanna` was untracked using `git rm -r --cached cli-bridge`. **No files were deleted from the disk.** All running servers, configs, and node modules continue working as before.
2. **Submission repo is mathematically clean:**
   - Root commit is `f627fa1` (Mon Oct 26, 22:30:48 IST / 1:00 PM EDT), committed **36 minutes after kickoff ended**.
   - `cli-bridge` source code and its pre-kickoff history (July–Oct 24) are completely absent.
   - All 51 commits retain their genuine hackathon author and committer dates.

---

## 3. Required Submission Disclosures

Cerebral Valley mandates two specific disclosures:

### A. The 3-Minute Video Opening Line (Mandatory)
You **must** open your video presentation with this exact clarification:
> *"Before the hackathon, I had built a standalone MCP tool called `cli-bridge`. This week, I built Enheduanna: an autonomous desktop copilot featuring the MemVision continuous perceptual memory engine and a dual-model Meta Muse agentic orchestrator."*

### B. Written Submission Form (Prior Work Section)
> **Pre-existing Work Disclosure:**  
> *"Enheduanna uses `cli-bridge` (https://github.com/anshupriyan/cli-bridge) as an external, policy-gated Model Context Protocol (MCP) execution dependency for sandboxed command execution. `cli-bridge` was developed prior to kickoff and is disclosed per hackathon rules.*  
>  
> *All other code in this repository—including the MemVision continuous perceptual memory engine (`memvison/`), spatial blackout curtain redaction, text stability gating, draft collapsing, the dual-model Meta Muse (Spark 1.3 / Wonder 1.0) ReAct orchestrator (`app/core/`), multi-modal screenshot grounding, and the glassmorphic dashboard (`app/dashboard/`)—was conceived and built entirely during the hackathon week (Oct 26–29, 2026)."*

---

## 4. How to Manage Future Development & Syncing

### Day-to-Day Coding (Zero Tension)
- **Do 100% of your coding and testing inside:** `C:\meta hackathon\enheduanna`
- Because `cli-bridge/` is in `.gitignore`, every new commit you make in `enheduanna` will naturally only contain changes to `app/`, `memvison/`, and `docs/`.
- You do **not** need to worry about the submission repository while coding.

---

### How to Sync New Work to the Submission Repo (When Ready)

When you finish a coding session or before final submission, sync your changes in **3 simple commands**:

#### Step 1: Open PowerShell in the submission folder
```powershell
Set-Location "C:\meta hackathon\enheduanna-submission"
```

#### Step 2: Fetch your latest local commits
```powershell
git fetch local-dev
```

#### Step 3: Apply the new commits to `main`
- **Option A (Cherry-pick specific commits or range):**
  ```powershell
  # Cherry-pick a single commit:
  git cherry-pick <commit-hash>

  # Cherry-pick a range of commits:
  git cherry-pick <first-new-commit>^..<last-new-commit>
  ```
- **Option B (Milestone pull of all working files):**
  ```powershell
  git checkout local-dev/main -- app memvison docs
  git commit -m "feat: integrate latest hackathon improvements"
  ```

#### Step 4: Push to the clean GitHub submission repo
```powershell
git push origin main
```

---

## 5. Verification Commands (The 4 Audit Checks)

Run these checks in `C:\meta hackathon\enheduanna-submission` anytime to verify complete compliance:

```powershell
# 1. Verify root commit is strictly Oct 26 post-kickoff (22:30 IST):
git log --reverse --format="%h | %ad | %cd | %s" --date=iso | Select-Object -First 3

# 2. Verify cli-bridge is completely absent from all commit history (must return nothing):
git log --all -- cli-bridge

# 3. Verify clean refs (must show only refs/heads/main and remotes):
git for-each-ref

# 4. Verify total hackathon commit count:
git rev-list --all --count
```

---

## 6. Directory Reference Summary

| Path | Purpose | Git Tracking |
| :--- | :--- | :--- |
| `C:\meta hackathon\enheduanna` | **Active Coding Monorepo** | Tracks `app/`, `memvison/`, docs. `cli-bridge/` ignored via `.gitignore`. |
| `C:\meta hackathon\enheduanna-submission` | **Clean Submission Staging** | Mirror of `github.com/anshupriyan/enheduanna-meta-submission`. |
| `C:\meta hackathon\cli-bridge` | **Standalone Tool Repo** | Original independent tool repository (`origin -> cli-bridge`). |
| `C:\meta hackathon\memvison` | **Standalone Scribe Repo** | 100% hackathon perceptual memory engine repository. |

