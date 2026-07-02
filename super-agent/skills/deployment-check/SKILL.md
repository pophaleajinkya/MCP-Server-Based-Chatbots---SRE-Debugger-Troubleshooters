---
name: deployment-check
description: >
  Deployment tracking, CRQ (Change Request) management, and CCM configuration
  across WCNP, OneOps, and Managed Services. Use when the user asks "show
  deployments", "what was deployed", "CRQ details", "CRQ status", "any active
  CRQs", "CCM changes", "deployment history", "approve CRQ", "change approvers",
  "blackout schedule", or post-deployment health validation.
metadata:
  adk_additional_tools:
    # Deployment tools
    - fetch_wcnp_deployments
    - fetch_oneops_deployments
    - fetch_managed_service_deployments
    - fetch_all_deployments
    # CRQ tools (Seedbees)
    - fetch_active_crqs
    - fetch_deployments_by_crq
    - fetch_crqs_by_window
    # CRQ tools (ChangeIQ)
    - get_crq_details
    - get_change_approvers
    - get_change_history
    - change_conflicts
    - policy_manager_details
    - get_change_blackout_schedules
    - get_focus_freeze_analysis
    - changes_under_manager
    - approve_change_request
    - create_change_request
    # CCM tools
    - fetch_ccm_changes
    - fetch_ccm_changes_for_wcnp_app
    - fetch_wcnp_ops_ccm_data
---

# Deployment Tracking, CRQ Management & CCM

## When to Use This Skill

Activate this skill when the user asks about:
- Recent deployments ("show deployments in the last 1 hour")
- Deployment history for a specific app
- **CRQ details, status, or info** ("get CRQ details CHG1234567", "status of CHG1234567")
- Active, scheduled, or in-progress CRQs
- CRQ approvers, history, conflicts, or policy info
- Blackout schedules and freeze windows
- CCM configuration changes or current config
- Post-deployment health validation
- Cross-platform deployment view (WCNP + OneOps + Managed Services)

## Step-by-Step Workflows

### Workflow 1: Check Recent Deployments

**WCNP deployments:**
```
fetch_wcnp_deployments(namespace=<namespace>, hours=3)
```

**All platforms combined:**
```
fetch_all_deployments(namespace=<namespace>, hours=3)
```

**OneOps deployments:**
```
fetch_oneops_deployments(assembly=<assembly>, hours=3)
```

### Workflow 2: CRQ Details & Status

**🎯 CRQ details by ID (DEFAULT for any CRQ lookup):**
```
get_crq_details(crq_number="CHG1234567")
```
Use `get_crq_details` when the user asks:
- "get CRQ details for CHG1234567"
- "what is the status of CHG1234567"
- "show CRQ info", "who owns this CRQ"
- Any question about a CRQ that does NOT mention deployments

**Deployments linked to a CRQ (only when user asks about deployments):**
```
fetch_deployments_by_crq(crq_number="CHG1234567")
```

**Active CRQs:**
```
fetch_active_crqs()
```

**CRQs in a time window:**
```
fetch_crqs_by_window(start_time="2026-04-14T00:00:00Z",
                     end_time="2026-04-14T12:00:00Z")
```

### Workflow 3: CRQ Intelligence (ChangeIQ)

**Who needs to approve a CRQ:**
```
get_change_approvers(crq_number="CHG1234567")
```

**Audit trail / history:**
```
get_change_history(crq_number="CHG1234567")
```

**Conflicting changes:**
```
change_conflicts(crq_number="CHG1234567")
```

**Policy manager info:**
```
policy_manager_details(crq_number="CHG1234567")
```

**Blackout / freeze schedules:**
```
get_change_blackout_schedules()
get_change_blackout_schedules(crq_number="CHG1234567")
```

**Focus freeze analysis:**
```
get_focus_freeze_analysis(crq_number="CHG1234567")
```

**All changes under a manager:**
```
changes_under_manager(manager_id="john.doe")
```

**⚠️ Approve a CRQ (confirm with user first):**
```
approve_change_request(crq_number="CHG1234567", comments="Approved")
```

**⚠️ Create a new CRQ (gather all fields first):**
```
create_change_request(short_description="...", assignment_group="...")
```

### Workflow 4: CCM Configuration

**CCM change history:**
```
fetch_ccm_changes(services=["cart-service"], hours=3)
```

**CCM changes for a WCNP app (auto-resolves service name):**
```
fetch_ccm_changes_for_wcnp_app(namespace=<namespace>, app=<app>, hours=3)
```

**Current live CCM config snapshot:**
```
fetch_wcnp_ops_ccm_data(namespace=<namespace>, app=<app>, cluster_id=<cluster>)
```

### Workflow 5: Post-Deployment Validation

Chain these steps:
1. `fetch_wcnp_deployments(namespace, hours=2)` — find the deployment
2. Load `health-triage` skill → `wcnp_check_app_health` — check health post-deploy
3. Load `log-analysis` skill → check for new exceptions since deployment time
4. Compare latency before/after deployment

## Important Rules

- **CRQ details → use `get_crq_details`**, NOT `fetch_deployments_by_crq`
  - `get_crq_details` queries ChangeIQ (ServiceNow) directly — fast and works for any CRQ
  - `fetch_deployments_by_crq` searches Seedbees deployment pipelines — only finds CRQs with linked deployments
- **Always specify time ranges** — deployments without a time window may return too many results
- **CCM queries need explicit context** — "Get CCM for TG2" is too vague.
  Always include: cluster purpose, market, region.
- **Tier classification**: T0 = critical, T1 = important, Other = standard
- **Write operations** (`approve_change_request`, `create_change_request`) — always confirm with the user before calling
- Results include deployer identity, version, pipeline, and CRQ correlation
