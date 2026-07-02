---
name: incident-rca
description: >
  Root cause analysis for production incidents — traces exceptions to code, commits,
  PRs, and releases via GitHub Enterprise. Checks active incidents from ServiceNow.
  Use when the user asks "explain this exception", "who wrote this code", "any active
  incidents", "root cause analysis", or when a health check shows anomaly_detected=true.
metadata:
  adk_additional_tools:
    - blame_file_line
    - blame_file_lines
    - get_commit
    - list_commits_in_window
    - get_file_at_commit
    - list_tags
    - find_tag_for_commit
    - get_pr_for_commit
    - search_code_in_repo
    - compare_commits
    - fetch_active_incidents
    - fetch_major_incidents
    - fetch_incident_details
    - fetch_incidents
    - fetch_mx_incidents
    - fetch_cl_incidents
    - fetch_ca_incidents
    - wcnp_get_app_clusters
---

# Incident Root Cause Analysis

## When to Use This Skill

Activate this skill when:
- A health check returns `anomaly_detected = true`
- User asks "explain this exception" or pastes a stack trace
- User asks "who wrote this code?" or "who introduced this bug?"
- User asks "any active incidents?" or "show incidents"
- User asks "what changed recently?" (code/commits perspective)
- User wants to trace: exception → code → commit → PR → release

## RCA Chain

```
Exception (file + line)
  → Git Blame (who wrote it)
    → Commit Details (what changed)
      → Pull Request (who reviewed)
        → Release Tag (when shipped)
```

## Step-by-Step RCA Workflow

### Step 1: Get GitHub Owner/Repo

**Always call this first** — never ask the user for the repo:

```
wcnp_get_app_clusters(namespace=<namespace>, app=<app>)
```

This returns `github_owner` and `github_repo` from WCNP metadata.

### Step 2: Exception Investigation

If the user provides a stack trace with file + line number:

```
blame_file_lines(owner=<owner>, repo=<repo>,
                 file_path="src/main/java/com/example/OrderService.java",
                 line_numbers=[42, 43, 44])
```

For a single line:
```
blame_file_line(owner=<owner>, repo=<repo>,
                file_path=<file>, line_number=<line>)
```

### Step 3: Trace the Commit

```
get_commit(owner=<owner>, repo=<repo>, sha=<commit_sha_from_blame>)
```

### Step 4: Find the Pull Request

```
get_pr_for_commit(owner=<owner>, repo=<repo>, commit_sha=<sha>)
```

### Step 5: Find the Release

```
find_tag_for_commit(owner=<owner>, repo=<repo>, commit_sha=<sha>)
```

### Step 6: Check Active Incidents

```
fetch_active_incidents()
```

For major incidents only:
```
fetch_major_incidents()
```

For market-specific incidents:
```
fetch_mx_incidents(banner="EA")    # Mexico, Express Asistida
fetch_cl_incidents()                # Chile
fetch_ca_incidents()                # Canada
```

### Step 7: Incident Details

```
fetch_incident_details(incident_number="INC52569148")
```

Returns ~40 ServiceNow fields including work notes, SLA metrics (MTTD, MTTE, MTTM, TUI).

## Code Search

To search for error patterns across the codebase:

```
search_code_in_repo(owner=<owner>, repo=<repo>, query="TimeoutException")
```

## Comparing Releases

To see what changed between two releases:

```
compare_commits(owner=<owner>, repo=<repo>, base="v1.2.0", head="v1.3.0")
```

## Commits in a Time Window

To find recent commits around an incident:

```
list_commits_in_window(owner=<owner>, repo=<repo>,
                       since_iso="2026-04-14T00:00:00Z",
                       until_iso="2026-04-14T06:00:00Z")
```

## Incident Time-Window Search

```
fetch_incidents(start_time="2026-04-14T00:00:00Z",
                end_time="2026-04-14T12:00:00Z",
                priority="P1")
```

## Important Rules

- **Always resolve owner/repo from WCNP** — never ask the user
- **Run git blame + incident check in parallel** when investigating an exception
- **Show the full chain**: code → commit → PR → release → incident
- For market incidents, use the specific market tool (fetch_mx_incidents, etc.)
