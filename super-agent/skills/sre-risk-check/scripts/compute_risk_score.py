"""Compute a composite SRE risk score from Phase 1-3 findings.

Usage via run_skill_script:
  skill_name: sre-risk-check
  script_path: scripts/compute_risk_score.py
  args: {
    "crq_number": "CHG1234567",
    "crq_state": "Scheduled",
    "in_blackout": false,
    "in_freeze": false,
    "conflict_count": 0,
    "all_approved": true,
    "app_tier": "tier-0",
    "downstream_count": 12,
    "downstream_tier0_count": 3,
    "health_status": "healthy",
    "anomaly_detected": false,
    "code_blockers": 1,
    "code_concerns": 3,
    "code_files_reviewed": 45,
    "total_files_changed": 50,
    "total_commits": 12
  }

Returns a structured risk report with:
  - Composite score (0-100)
  - Risk level (LOW / MEDIUM / HIGH / CRITICAL)
  - Per-dimension breakdown (operational, environment, code)
  - Go/no-go recommendation with reasoning
"""

import json
import sys
from datetime import datetime, timezone
from typing import Any


# ── Scoring weights ──────────────────────────────────────────────────────────
# Each dimension contributes points to the composite score.
# Higher score = higher risk. Max theoretical score is ~200+ but we cap at 100.

# Phase 1: Operational risk factors
_OP_BLACKOUT       = 50   # deploying during a blackout is extremely risky
_OP_FREEZE         = 40   # focus freeze — nearly as bad as blackout
_OP_CONFLICT_EACH  = 8    # each conflicting CRQ adds risk
_OP_CONFLICT_MAX   = 30   # cap conflict contribution
_OP_NOT_APPROVED   = 20   # missing approvals
_OP_STATE_RISK = {        # CRQ state risk multiplier
    "new":              5,
    "assess":           5,
    "authorize":        10,  # still awaiting authorization
    "scheduled":        0,   # normal — approved and scheduled
    "implement":        0,   # actively deploying
    "in progress":      0,
    "work in progress": 0,
    "review":           0,
}

# Phase 2: Environment risk factors
_ENV_TIER = {
    "tier-0": 20,
    "tier-1": 10,
    "other":  0,
}
_ENV_DOWNSTREAM_EACH     = 2    # per downstream dep
_ENV_DOWNSTREAM_T0_EACH  = 5    # per tier-0 downstream dep (additional)
_ENV_DOWNSTREAM_MAX      = 30   # cap blast radius contribution
_ENV_HEALTH = {
    "healthy":   0,
    "degraded":  15,
    "unhealthy": 25,
}
_ENV_ANOMALY = 10  # active anomaly detected

# Phase 3: Code risk factors
_CODE_BLOCKER_EACH  = 12   # each blocker
_CODE_CONCERN_EACH  = 3    # each concern
_CODE_BLOCKER_MAX   = 40   # cap blocker contribution
_CODE_CONCERN_MAX   = 20   # cap concern contribution
_CODE_LARGE_CHANGE  = 10   # >100 files changed
_CODE_HUGE_CHANGE   = 15   # >500 files changed
_CODE_MANY_COMMITS  = 5    # >50 commits

# Risk level thresholds
_LEVEL_LOW      = 20
_LEVEL_MEDIUM   = 50
_LEVEL_HIGH     = 80
# Above 80 = CRITICAL


def compute_risk_score(args: dict[str, Any]) -> str:
    """Compute composite risk score and return formatted markdown report."""

    crq_number = args.get("crq_number", "UNKNOWN")

    # ── Phase 1: Operational Score ────────────────────────────────────────
    op_score = 0
    op_factors: list[str] = []

    if args.get("in_blackout"):
        op_score += _OP_BLACKOUT
        op_factors.append(f"IN BLACKOUT (+{_OP_BLACKOUT})")

    if args.get("in_freeze"):
        op_score += _OP_FREEZE
        op_factors.append(f"IN FOCUS FREEZE (+{_OP_FREEZE})")

    conflict_count = int(args.get("conflict_count", 0))
    if conflict_count > 0:
        conflict_pts = min(conflict_count * _OP_CONFLICT_EACH, _OP_CONFLICT_MAX)
        op_score += conflict_pts
        op_factors.append(f"{conflict_count} conflict(s) (+{conflict_pts})")

    if not args.get("all_approved", True):
        op_score += _OP_NOT_APPROVED
        op_factors.append(f"Approvals pending (+{_OP_NOT_APPROVED})")

    crq_state = (args.get("crq_state") or "scheduled").lower().strip()
    state_pts = _OP_STATE_RISK.get(crq_state, 5)
    if state_pts > 0:
        op_score += state_pts
        op_factors.append(f"CRQ state '{crq_state}' (+{state_pts})")

    if not op_factors:
        op_factors.append("All clear (no operational risk factors)")

    # ── Phase 2: Environment Score ────────────────────────────────────────
    env_score = 0
    env_factors: list[str] = []

    app_tier = (args.get("app_tier") or "other").lower().strip()
    tier_pts = _ENV_TIER.get(app_tier, 0)
    if tier_pts > 0:
        env_score += tier_pts
        env_factors.append(f"App tier: {app_tier} (+{tier_pts})")

    downstream = int(args.get("downstream_count", 0))
    downstream_t0 = int(args.get("downstream_tier0_count", 0))
    if downstream > 0:
        blast_pts = min(
            downstream * _ENV_DOWNSTREAM_EACH + downstream_t0 * _ENV_DOWNSTREAM_T0_EACH,
            _ENV_DOWNSTREAM_MAX,
        )
        env_score += blast_pts
        env_factors.append(f"{downstream} downstream deps ({downstream_t0} tier-0) (+{blast_pts})")

    health = (args.get("health_status") or "healthy").lower().strip()
    health_pts = _ENV_HEALTH.get(health, 0)
    if health_pts > 0:
        env_score += health_pts
        env_factors.append(f"Current health: {health} (+{health_pts})")

    if args.get("anomaly_detected"):
        env_score += _ENV_ANOMALY
        env_factors.append(f"Active anomaly detected (+{_ENV_ANOMALY})")

    if not env_factors:
        env_factors.append("Low-risk environment (non-critical tier, healthy, no blast radius)")

    # ── Phase 3: Code Score ───────────────────────────────────────────────
    code_score = 0
    code_factors: list[str] = []
    code_unknown = False

    blockers = int(args.get("code_blockers", 0))
    concerns = int(args.get("code_concerns", 0))
    files_reviewed = int(args.get("code_files_reviewed", 0))
    total_files = int(args.get("total_files_changed", 0))
    total_commits = int(args.get("total_commits", 0))

    # If no files were reviewed, code risk is unknown (Phase 3 may have been skipped)
    if files_reviewed == 0 and total_files == 0:
        code_unknown = True
        code_factors.append("Code review not performed (UNKNOWN risk)")
    else:
        if blockers > 0:
            blocker_pts = min(blockers * _CODE_BLOCKER_EACH, _CODE_BLOCKER_MAX)
            code_score += blocker_pts
            code_factors.append(f"{blockers} blocker(s) (+{blocker_pts})")

        if concerns > 0:
            concern_pts = min(concerns * _CODE_CONCERN_EACH, _CODE_CONCERN_MAX)
            code_score += concern_pts
            code_factors.append(f"{concerns} concern(s) (+{concern_pts})")

        if total_files > 500:
            code_score += _CODE_HUGE_CHANGE
            code_factors.append(f"Huge change: {total_files} files (+{_CODE_HUGE_CHANGE})")
        elif total_files > 100:
            code_score += _CODE_LARGE_CHANGE
            code_factors.append(f"Large change: {total_files} files (+{_CODE_LARGE_CHANGE})")

        if total_commits > 50:
            code_score += _CODE_MANY_COMMITS
            code_factors.append(f"Many commits: {total_commits} (+{_CODE_MANY_COMMITS})")

        if not code_factors:
            code_factors.append("Clean code review (no blockers or concerns)")

    # ── Composite Score ───────────────────────────────────────────────────
    raw_total = op_score + env_score + code_score
    composite = min(raw_total, 100)  # cap at 100

    if composite <= _LEVEL_LOW:
        level = "LOW"
        level_icon = "🟢"
    elif composite <= _LEVEL_MEDIUM:
        level = "MEDIUM"
        level_icon = "🟡"
    elif composite <= _LEVEL_HIGH:
        level = "HIGH"
        level_icon = "🟠"
    else:
        level = "CRITICAL"
        level_icon = "🔴"

    # ── Recommendation ────────────────────────────────────────────────────
    hard_stops: list[str] = []
    cautions: list[str] = []

    if args.get("in_blackout"):
        hard_stops.append("CRQ is scheduled during a BLACKOUT window")
    if args.get("in_freeze"):
        hard_stops.append("CRQ is impacted by a FOCUS FREEZE")
    if blockers > 0:
        hard_stops.append(f"{blockers} code blocker(s) must be resolved before deployment")
    if health == "unhealthy":
        hard_stops.append("App is currently UNHEALTHY — deploying may worsen the situation")

    if not args.get("all_approved", True):
        cautions.append("Not all approvals are in place")
    if conflict_count > 0:
        cautions.append(f"{conflict_count} conflicting CRQ(s) may cause interference")
    if health == "degraded":
        cautions.append("App is currently degraded — monitor closely during deployment")
    if args.get("anomaly_detected"):
        cautions.append("Active anomaly detected — investigate before deploying")
    if concerns > 0:
        cautions.append(f"{concerns} code concern(s) should be reviewed")
    if total_files > 100:
        cautions.append(f"Large change ({total_files} files) — higher chance of unexpected impact")
    if code_unknown:
        cautions.append("Code review was not performed — code risk is unknown")

    if hard_stops:
        rec_icon = "🔴"
        rec_label = "HOLD DEPLOYMENT"
        rec_detail = "The following issues MUST be resolved before proceeding:\n"
        rec_detail += "\n".join(f"  - {s}" for s in hard_stops)
        if cautions:
            rec_detail += "\n\nAdditional cautions:\n"
            rec_detail += "\n".join(f"  - {c}" for c in cautions)
    elif cautions:
        rec_icon = "🟡"
        rec_label = "PROCEED WITH CAUTION"
        rec_detail = "No hard blockers, but the following warrant attention:\n"
        rec_detail += "\n".join(f"  - {c}" for c in cautions)
    else:
        rec_icon = "✅"
        rec_label = "SAFE TO PROCEED"
        rec_detail = "No blockers, no operational concerns, clean code review. CRQ can be executed within the planned window."

    # ── Build the report ──────────────────────────────────────────────────
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Score bar visualization (20 chars wide)
    filled = max(1, int(composite / 5))  # 1-20
    bar = "█" * filled + "░" * (20 - filled)

    lines = [
        f"# {level_icon} SRE Risk Assessment — {crq_number}",
        "",
        f"**Assessed**: {now}",
        "",
        "---",
        "",
        f"## Composite Risk Score: {composite}/100  [{bar}]  {level}",
        "",
        "| Dimension | Score | Details |",
        "|-----------|-------|---------|",
        f"| Operational | {op_score} | {'; '.join(op_factors)} |",
        f"| Environment | {env_score} | {'; '.join(env_factors)} |",
        f"| Code | {code_score}{'*' if code_unknown else ''} | {'; '.join(code_factors)} |",
        f"| **Total** | **{composite}** | **{level}** |",
        "",
    ]

    if code_unknown:
        lines.append("*\\* Code risk is UNKNOWN — Phase 3 was not completed.*")
        lines.append("")

    # Dimension breakdown
    lines.extend([
        "### Operational Risk Factors",
        "",
    ])
    for f in op_factors:
        lines.append(f"- {f}")
    lines.append("")

    lines.extend([
        "### Environment Risk Factors",
        "",
    ])
    for f in env_factors:
        lines.append(f"- {f}")
    lines.append("")

    lines.extend([
        "### Code Risk Factors",
        "",
    ])
    for f in code_factors:
        lines.append(f"- {f}")
    lines.append("")

    # Recommendation
    lines.extend([
        "---",
        "",
        f"## {rec_icon} Recommendation: {rec_label}",
        "",
        rec_detail,
        "",
        "---",
        "",
        f"> Generated by **sre-risk-check** skill | {now}",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
        args = json.loads(raw)

        # Handle LLM double-encoding
        if isinstance(args, str):
            args = json.loads(args)

        report = compute_risk_score(args)
        print(report)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(json.dumps({"error": f"Failed to parse input: {exc}"}))
        sys.exit(1)
