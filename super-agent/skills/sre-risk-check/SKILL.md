---
name: sre-risk-check
description: >
  Holistic SRE pre-deployment risk assessment for an active Change Request (CRQ).
  Combines CRQ operational checks (blackout, conflicts, approvals), current app
  health baseline, blast radius analysis, and progressive code review into a
  single composite risk score with a go/no-go recommendation.
  Use when the user asks "SRE risk check on CHG1234567", "risk assessment for CRQ",
  "is this CRQ safe to deploy", "pre-deploy risk check", "review CRQ risk",
  or "deployment risk analysis".
metadata:
  adk_additional_tools:
    # ── Phase 1: CRQ Gate ──
    - get_crq_details
    - get_change_blackout_schedules
    - change_conflicts
    - get_change_approvers
    - get_focus_freeze_analysis
    # ── Phase 2: Operational Context ──
    - wcnp_check_app_health
    - wcnp_get_app_clusters
    - wcnp_list_deployments
    - fetch_wcnp_downstream_dependencies
    - fetch_deployments_by_crq
    - fetch_wcnp_deployments
    # ── Phase 3: Code Review ──
    - compare_commits
    - get_file_diff
    - get_file_at_commit
    - get_commit
    - get_pr_for_commit
    - blame_file_lines
    - search_code_in_repo
    - list_tags
---

# SRE Risk Check — Holistic Pre-Deployment Risk Assessment

## When to Use This Skill

Activate this skill **only** when the user explicitly asks for:
- "SRE risk check on CHG1234567"
- "Risk assessment for CRQ CHG1234567"
- "Is this CRQ safe to deploy?"
- "Pre-deploy risk check for CHG1234567"
- "Deployment risk analysis for CHG1234567"

Do **NOT** activate for:
- General CRQ status queries → use `deployment-check` skill
- Standalone code reviews → use `release-review` skill
- Health checks without a CRQ → use `health-triage` skill

## Required Information

You need a **CRQ number** (e.g., `CHG1234567`). If the user doesn't provide one, ask for it.

---

## Architecture: 4-Phase Risk Assessment

```
Phase 1: CRQ Gate           → Is this CRQ even deployable?
Phase 2: Operational Context → How risky is the environment?
Phase 3: Code Review         → How risky is the code change?
Phase 4: Composite Score     → Single weighted go/no-go verdict
```

Each phase feeds data into the final composite risk score computed in Phase 4.

---

## MANDATORY Step-by-Step Workflow

> **ENFORCEMENT RULE**: You MUST execute ALL phases in order.
> You MUST NOT skip any phase. You MUST NOT summarize without executing.
> Each step has a required tool call — make that call and process the result
> before moving on.

---

## Phase 1: CRQ Gate (Operational Readiness)

**Goal**: Determine if this CRQ is operationally clear to deploy.

### Step 1.1: Get CRQ Details (MANDATORY)

```
get_crq_details(crq_number="CHG1234567")
```

**GATE CHECK — CRQ State:**

If CRQ state is **terminal** (Closed Complete, Closed, Closed Unsuccessful,
Canceled, Cancelled):

> 🛑 **STOP HERE** — CRQ is closed. Display the CRQ details and inform the user.
> Risk check is only meaningful for active CRQs.

If CRQ state is **active**, record:
- `crq_state` — current state
- `assignment_group` — who owns it
- `planned_start` / `planned_end` — deployment window
- `short_description` — what's changing

### Step 1.2: Blackout / Freeze Check (MANDATORY)

Run both in parallel:

```
get_change_blackout_schedules(crq_number="CHG1234567")
get_focus_freeze_analysis(crq_number="CHG1234567")
```

Record:
- `in_blackout` — true/false, is the CRQ's window inside a blackout?
- `in_freeze` — true/false, is the CRQ impacted by a focus freeze?
- `blackout_details` — window dates if applicable

### Step 1.3: Conflict Check (MANDATORY)

```
change_conflicts(crq_number="CHG1234567")
```

Record:
- `conflict_count` — number of conflicting CRQs
- `conflict_crqs` — list of conflicting CRQ numbers

### Step 1.4: Approval Status (MANDATORY)

```
get_change_approvers(crq_number="CHG1234567")
```

Record:
- `all_approved` — true/false, are all approvals in place?
- `pending_approvers` — list of approvers who haven't approved yet

### Step 1.5: Display Phase 1 Summary

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 PHASE 1: CRQ GATE — CHG1234567
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 CRQ State:      <state>
 Description:    <short_description>
 Planned Window: <start> → <end>
 Blackout:       ✅ Clear / 🔴 IN BLACKOUT
 Focus Freeze:   ✅ Clear / 🔴 IN FREEZE
 Conflicts:      ✅ None / ⚠️ <N> conflicts
 Approvals:      ✅ All approved / ⚠️ <N> pending
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**If in blackout or freeze**: Warn prominently but continue — the user asked for
the risk assessment, so complete it. Flag in the final score.

---

## Phase 2: Operational Context (Environment Risk)

**Goal**: Assess the operational risk of the deployment target.

### Step 2.1: Resolve App, Namespace, and Versions (MANDATORY)

```
fetch_deployments_by_crq(crq_number="CHG1234567")
```

Extract:
- **app_name** — application being deployed
- **namespace** — Kubernetes namespace
- **head_version** — version being deployed (newest record)
- **base_version** — rollback / currently-running version

**Version resolution cascade** (if base_version is missing):

**Fallback A** — WCNP current version:
```
wcnp_get_app_clusters(namespace=<namespace>, app=<app>)
```
Extract the currently deployed image tag as `base_version`.
Also extract `github_owner` and `github_repo` from this response.

**Fallback B** — Seedbees deployment history:
```
fetch_wcnp_deployments(namespace=<namespace>, app_name=<app>, hours_ago=720)
```
Find the most recent **successful** deployment that is NOT head_version.
Use that version as `base_version`.

**Fallback C** — Ask the user for both versions.

> **IMPORTANT**: Do NOT proceed to Phase 3 without both versions resolved.

### Step 2.2: App Tier and Blast Radius (MANDATORY)

If not already returned by Step 2.1:
```
wcnp_get_app_clusters(namespace=<namespace>, app=<app>)
```

Then check downstream dependencies:
```
fetch_wcnp_downstream_dependencies(namespace=<namespace>, app=<app>)
```

Record:
- `app_tier` — tier-0, tier-1, or other
- `downstream_count` — number of downstream dependent services
- `downstream_tier0_count` — how many downstream deps are tier-0
- `cluster_count` — how many clusters the app runs on
- `github_owner` / `github_repo` — for Phase 3

### Step 2.2b: GitHub Repo Resolution Cascade (if github_url is empty)

If `wcnp_get_app_clusters` returns an empty `github_url` / `github_owner` / `github_repo`,
do NOT skip Phase 3 immediately. Try these fallbacks in order:

**Fallback G1** — Infer from app name or CRQ description:
- The CRQ `short_description` (from Phase 1) often mentions the repo name or branches.
  Look for patterns like `org/repo`, branch names like `intl-dc/release/BRANCH`, or
  explicit repo references.
- The deployment branches (from `fetch_deployments_by_crq` response) may contain the
  org/repo path. For example, a branch like `intl-dc/release/...` suggests org `intl-dc`.

**Fallback G2** — Probe GitHub Enterprise by app name:
Try to find the repo by probing likely org/repo combinations using `list_tags`:
```
list_tags(owner=<likely_org>, repo=<app_name>)
```
Build candidate org names from:
- The namespace prefix (e.g., `intl-audit` namespace → try org `intl-audit`)
- The namespace root (e.g., `intl-audit` → try org `intl`)
- The `assignment_group` from CRQ details (often maps to the GitHub org)
- Common Walmart orgs: `intl-ecomm-svcs`, `intl-dc`, `walmart`
- The `repoName` field from Seedbees deployment data (if present)

If `list_tags` returns results (even empty list without error), the repo exists.
If it returns a 404 error, try the next org candidate.

**Fallback G3** — Ask the user:
If all automated fallbacks fail, ask the user:
> "I couldn't find the GitHub repo for `<app_name>`. WCNP metadata doesn't have it
> registered. Could you provide the GitHub owner/repo (e.g., `org-name/repo-name`)
> so I can review the code changes?"

> **IMPORTANT**: Only skip Phase 3 if you exhaust ALL fallbacks AND the user
> cannot provide the repo. Mark code risk as UNKNOWN in that case.

### Step 2.3: Current Health Baseline (MANDATORY)

```
wcnp_check_app_health(namespace=<namespace>, app=<app>)
```

Record:
- `health_status` — healthy / degraded / unhealthy
- `anomaly_detected` — true/false
- `active_issues` — list of current health issues (if any)

> **Why**: If the app is already unhealthy, deploying adds risk. If healthy,
> we have a clean baseline to compare post-deployment.

### Step 2.4: Display Phase 2 Summary

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 PHASE 2: OPERATIONAL CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 App:             <app_name>
 Namespace:       <namespace>
 Tier:            <tier> (🔴 Tier-0 / 🟠 Tier-1 / ⚪ Other)
 Clusters:        <N>
 Downstream Deps: <N> (<M> tier-0)
 Current Health:  ✅ Healthy / 🟡 Degraded / 🔴 Unhealthy
 Anomalies:       ✅ None / ⚠️ Active
 New Version:     <head_version> (deploying)
 Old Version:     <base_version> (rollback target)
 GitHub:          <owner>/<repo>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Phase 3: Code Review (Code Change Risk)

**Goal**: Review the actual code diff between versions for security, performance,
and breaking-change risks.

### Step 3.1: Get File Manifest (MANDATORY)

```
compare_commits(owner=<owner>, repo=<repo>, base=<base_version>, head=<head_version>)
```

If versions are image tags (e.g., `1.4.1`), try with `v` prefix (e.g., `v1.4.1`)
if the first attempt fails. If that also fails:
```
list_tags(owner=<owner>, repo=<repo>)
```
Find the closest matching tags and retry.

Extract:
- `files_changed[]` — modified files
- `total_commits` — commit count
- `commits[]` — commit list
- `compare_url` — GitHub compare URL

Display commit table.

### Step 3.2: Classify File Risk (MANDATORY)

```
run_skill_script(
  skill_name="release-review",
  script_path="scripts/classify_risk.py",
  args={"files_changed": <files_changed>}
)
```

Display tier summary table.

### Step 3.3: Progressive File-by-File Analysis (MANDATORY)

Review files in priority order: **CRITICAL → HIGH → MEDIUM → LOW**.
SKIP-tier files do not need individual review.

For EACH non-SKIP file:

```
get_file_diff(owner=<owner>, repo=<repo>, file_path=<filename>,
              base=<base_version>, head=<head_version>)
```

Analyze each patch against:
1. **Security** — secrets, injection, auth bypass, input validation
2. **Error Handling** — missing try/catch, swallowed exceptions, null checks
3. **Performance** — N+1 queries, unbounded loops, blocking I/O, missing pagination
4. **Breaking Changes** — API changes, removed fields, schema changes
5. **Concurrency** — race conditions, missing locks, shared mutable state
6. **Configuration** — hardcoded values, missing defaults, missing feature flags
7. **Observability** — missing logging, missing metrics, silent failures

Record findings:
```json
{
  "file": "<filename>",
  "risk_tier": "CRITICAL|HIGH|MEDIUM|LOW",
  "verdict": "pass|concern|blocker",
  "issues": ["issue 1", "issue 2"]
}
```

**Verdict rules:**
- `blocker` — Security vuln, data loss risk, breaking change without migration. MUST fix.
- `concern` — Performance issue, missing observability. Should fix but not blocking.
- `pass` — No issues found.

Show progress every 10 files.

---

## Phase 4: Composite Risk Score & Recommendation

**Goal**: Combine all findings into a single weighted risk score.

### Step 4.1: Compute Risk Score (MANDATORY)

```
run_skill_script(
  skill_name="sre-risk-check",
  script_path="scripts/compute_risk_score.py",
  args={
    "crq_number": "<crq_number>",
    "crq_state": "<state>",
    "in_blackout": <true/false>,
    "in_freeze": <true/false>,
    "conflict_count": <N>,
    "all_approved": <true/false>,
    "app_tier": "<tier-0|tier-1|other>",
    "downstream_count": <N>,
    "downstream_tier0_count": <N>,
    "health_status": "<healthy|degraded|unhealthy>",
    "anomaly_detected": <true/false>,
    "code_blockers": <N>,
    "code_concerns": <N>,
    "code_files_reviewed": <N>,
    "total_files_changed": <N>,
    "total_commits": <N>
  }
)
```

This produces a composite risk score and go/no-go recommendation.

### Step 4.2: Generate Code Review Report (MANDATORY)

```
run_skill_script(
  skill_name="release-review",
  script_path="scripts/generate_review_report.py",
  args={
    "owner": "<owner>",
    "repo": "<repo>",
    "base_tag": "<base_version>",
    "head_tag": "<head_version>",
    "total_files": <total>,
    "total_commits": <total_commits>,
    "compare_url": "<url>",
    "findings": [<all findings from Phase 3>]
  }
)
```

### Step 4.3: Display Final Report (MANDATORY)

Display the risk score output from Step 4.1, then the code review report from
Step 4.2, then the CRQ context footer:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 🔗 CRQ CONTEXT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 CRQ:              <crq_number> (<state>)
 App:              <app_name> (<tier>)
 Namespace:        <namespace>
 Deploying:        <base_version> → <head_version>
 Assignment Group: <group>
 Planned Window:   <start> → <end>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## Important Rules

- **ONLY run for active CRQs** — if the CRQ is closed, STOP at Phase 1
- **Both versions MUST be resolved** before starting Phase 3
- **Version resolution order**: CRQ deployment data → WCNP current version → Seedbees history → ask user
- **NEVER use namespace as GitHub owner** — always resolve from WCNP metadata or the
  GitHub Repo Resolution Cascade (Step 2.2b)
- **Reuse release-review scripts** via `run_skill_script` — do NOT duplicate logic
- **Run Phase 1 checks in parallel** where possible (blackout + freeze + conflicts + approvers)
- **Show phase transitions** prominently so the user tracks progress
- **If CRQ spans multiple apps**: run Phases 2-3 for each app, then combine into one Phase 4 score
- **If GitHub repo is missing from WCNP metadata**: do NOT immediately skip Phase 3.
  Follow the GitHub Repo Resolution Cascade (Step 2.2b) — infer from CRQ description
  and branch names, search GHE by app name, or ask the user. Only mark as UNKNOWN
  after exhausting all fallbacks.
- **If code review cannot proceed** (tags not found, repo access denied, all GitHub
  fallbacks exhausted): still complete Phases 1-2 and produce a partial risk score
  with code risk marked as "UNKNOWN"
