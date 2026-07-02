---
name: release-review
description: >
  Pre-production code review between two release tags. Progressively analyzes
  each changed file for security, performance, error handling, and breaking
  changes. Produces a go/no-go recommendation. Use when the user asks
  "is this release safe?", "review release v1.4.1 to v1.4.2", "can we deploy?",
  "pre-prod review", "release diff review", or "code review between tags".
metadata:
  adk_additional_tools:
    - compare_commits
    - get_file_diff
    - get_file_at_commit
    - get_commit
    - get_pr_for_commit
    - blame_file_lines
    - search_code_in_repo
    - list_tags
    - wcnp_get_app_clusters
---

# Pre-Production Release Review

## When to Use This Skill

Activate this skill when the user asks:
- "Is this release safe for production?"
- "Review release v1.4.1 → v1.4.2"
- "Can we deploy this?"
- "Pre-prod code review"
- "What changed between these tags?"
- "Review the diff between releases"

## Required Information

You MUST have these 4 values before starting the review:
- **owner** — GitHub org (e.g., `walmart-mx`)
- **repo** — Repository name (e.g., `checkout-service`)
- **base_tag** — The current production release tag (e.g., `v1.4.1`)
- **head_tag** — The candidate release tag (e.g., `v1.4.2`)

### How to Resolve owner/repo

The user can provide owner/repo in THREE ways. Use the FIRST one that applies:

**Path A — User provides a GitHub URL** (easiest — parse it):
If the user provides a link like `https://gecgithub01.walmart.com/walmart-mx/checkout-service`,
parse `owner=walmart-mx` and `repo=checkout-service` directly from the URL.
No WCNP lookup needed. Works with any GHE URL format:
- `https://gecgithub01.walmart.com/{owner}/{repo}`
- `https://gecgithub01.walmart.com/{owner}/{repo}/releases`
- `https://gecgithub01.walmart.com/{owner}/{repo}/compare/v1...v2`

**Path B — User provides owner/repo directly**:
If the user says "review walmart-mx/checkout-service v1.4.1 to v1.4.2",
use `owner=walmart-mx` and `repo=checkout-service` directly. No WCNP lookup needed.

**Path C — User provides namespace + app name**:
```
wcnp_get_app_clusters(namespace=<namespace>, app=<app>)
```
This returns `github_owner` and `github_repo` from WCNP metadata.
Use those fields directly — NEVER use the Kubernetes namespace as the GitHub owner.

### How to Resolve tags

If the user doesn't provide tags, call `list_tags(owner, repo)` and show the
most recent tags so the user can pick the base and head.

> **IMPORTANT**: Do NOT proceed without all 4 values. Ask the user for any missing info.

---

## MANDATORY Step-by-Step Workflow

> **ENFORCEMENT RULE**: You MUST execute ALL steps below in order.
> You MUST NOT skip any step. You MUST NOT summarize without executing.
> Each step has a required tool call — you MUST make that call and process
> the result before moving to the next step. Failure to execute any step
> is a protocol violation.

### Step 1: Get the File Manifest (MANDATORY)

You MUST call:

```
compare_commits(owner=<owner>, repo=<repo>, base=<base_tag>, head=<head_tag>)
```

Extract from response:
- `files_changed[]` — the complete list of modified files
- `total_commits` — how many commits between tags
- `commits[]` — commit list (display as table)
- `url` — compare URL on GitHub

Display the commit summary as a table:
| SHA | Message | Author | Date |
|-----|---------|--------|------|

Then proceed IMMEDIATELY to Step 2 with the `files_changed` array.

### Step 2: Classify and Prioritize Files (MANDATORY)

You MUST call:

```
run_skill_script(
  skill_name="release-review",
  script_path="scripts/classify_risk.py",
  args={"files_changed": <files_changed from Step 1>}
)
```

This returns files grouped by risk tier: CRITICAL → HIGH → MEDIUM → LOW → SKIP.

Display the tier summary:
| Risk Tier | File Count |
|-----------|------------|

Then proceed IMMEDIATELY to Step 3 with the prioritized file list.

### Step 3: Progressive File-by-File Analysis (MANDATORY)

You MUST analyze files in priority order: CRITICAL first, then HIGH, MEDIUM, LOW.
SKIP-tier files do not need individual review unless the filename suggests hidden risk.

For EACH file (except SKIP tier), you MUST call:

```
get_file_diff(owner=<owner>, repo=<repo>, file_path=<filename>, base=<base_tag>, head=<head_tag>)
```

After receiving the patch, analyze it against this checklist:

1. **Security** — Hardcoded secrets, SQL injection, auth bypass, input validation gaps,
   exposed sensitive data, insecure deserialization, path traversal
2. **Error Handling** — Missing try/catch, swallowed exceptions, missing null checks,
   unhandled edge cases, missing error responses
3. **Performance** — N+1 queries, unbounded loops, missing pagination, memory leaks,
   blocking I/O in async code, missing caching where expected
4. **Breaking Changes** — API signature changes, removed fields, changed response formats,
   renamed endpoints, backwards-incompatible schema changes
5. **Concurrency** — Race conditions, missing locks, shared mutable state,
   thread-unsafe operations
6. **Configuration** — Env-specific hardcoded values, missing defaults,
   missing feature flags for new behavior
7. **Observability** — Missing logging for critical paths, missing metrics,
   silent failure modes

After analyzing each file, record your finding as:

```json
{
  "file": "<filename>",
  "risk_tier": "CRITICAL|HIGH|MEDIUM|LOW",
  "verdict": "pass|concern|blocker",
  "issues": ["issue description 1", "issue description 2"]
}
```

**Verdict rules:**
- `blocker` — Security vulnerability, data loss risk, breaking change without migration,
  or critical error handling gap. MUST be fixed before production.
- `concern` — Performance issue, missing observability, non-critical code smell.
  Should be addressed but not blocking.
- `pass` — No issues found in this file.

**CONTEXT MANAGEMENT**: Keep a running tally as you go:
- "Analyzed X of Y files: Z blockers, W concerns so far"
- Do NOT try to remember full patches — only remember findings
- Old patches will naturally leave context as new ones arrive

### Step 4: Generate Final Report (MANDATORY)

After reviewing ALL files (or all non-SKIP files), you MUST call:

```
run_skill_script(
  skill_name="release-review",
  script_path="scripts/generate_review_report.py",
  args={
    "owner": "<owner>",
    "repo": "<repo>",
    "base_tag": "<base_tag>",
    "head_tag": "<head_tag>",
    "total_files": <total from Step 1>,
    "total_commits": <total_commits from Step 1>,
    "compare_url": "<url from Step 1>",
    "findings": [<all findings from Step 3>]
  }
)
```

Display the generated report to the user verbatim.

---

## Important Rules

- **NEVER load all file patches at once** — always one file at a time via `get_file_diff`
- **NEVER skip CRITICAL or HIGH tier files** — they MUST be reviewed individually
- **Process in order**: CRITICAL → HIGH → MEDIUM → LOW
- **If context is getting large** (>150 files reviewed): summarize findings so far,
  then continue with remaining files
- **For renamed files**: check if content also changed (additions > 0 or deletions > 0)
- **For deleted files**: note the deletion but skip patch analysis (no new code to review)
- **Show progress**: After every 10 files, display "Progress: X/Y files reviewed, Z blockers, W concerns"
- **If a file patch is truncated**: use `get_file_at_commit` with `line_start`/`line_end`
  to inspect the specific section that was cut off
