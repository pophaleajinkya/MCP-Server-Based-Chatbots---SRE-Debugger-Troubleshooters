"""Generate a structured go/no-go release review report.

Usage via run_skill_script:
  skill_name: release-review
  script_path: scripts/generate_review_report.py
  args: {
    "owner": "walmart-mx",
    "repo": "checkout-service",
    "base_tag": "v1.4.1",
    "head_tag": "v1.4.2",
    "total_files": 200,
    "total_commits": 45,
    "compare_url": "https://gecgithub01.walmart.com/...",
    "findings": [
      {
        "file": "src/auth/login.py",
        "risk_tier": "CRITICAL",
        "verdict": "blocker",
        "issues": ["Hardcoded API key on line 42", "Missing input validation on login endpoint"]
      },
      {
        "file": "src/service/cart.py",
        "risk_tier": "MEDIUM",
        "verdict": "concern",
        "issues": ["N+1 query in get_cart_items loop"]
      },
      {
        "file": "src/utils/helpers.py",
        "risk_tier": "LOW",
        "verdict": "pass",
        "issues": []
      }
    ]
  }

Returns formatted markdown report with go/no-go recommendation.
"""

import json
import sys
from datetime import datetime, timezone
from typing import Any


def generate_report(
    owner: str,
    repo: str,
    base_tag: str,
    head_tag: str,
    total_files: int,
    total_commits: int,
    compare_url: str,
    findings: list[dict[str, Any]],
) -> str:
    """Build a markdown release review report from accumulated findings."""

    blockers = [f for f in findings if f.get("verdict") == "blocker"]
    concerns = [f for f in findings if f.get("verdict") == "concern"]
    passed   = [f for f in findings if f.get("verdict") == "pass"]
    skipped  = total_files - len(findings)

    # ── Go / No-Go Decision ──────────────────────────────────────────
    if blockers:
        decision     = "NO-GO"
        decision_icon = "🔴"
        decision_text = f"**{len(blockers)} blocking issue(s)** must be resolved before production deployment."
    elif len(concerns) > 10:
        decision      = "CONDITIONAL GO"
        decision_icon = "🟡"
        decision_text = f"No blockers, but **{len(concerns)} concerns** warrant review. Proceed with caution."
    elif concerns:
        decision      = "GO (with noted concerns)"
        decision_icon = "🟢"
        decision_text = f"No blockers found. **{len(concerns)} minor concern(s)** noted for follow-up."
    else:
        decision      = "GO"
        decision_icon = "🟢"
        decision_text = "No blockers or concerns found. Code is safe for production."

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        f"# {decision_icon} Release Review: `{base_tag}` → `{head_tag}`",
        "",
        f"**Repository**: {owner}/{repo}",
        f"**Reviewed**: {now}",
        f"**Commits**: {total_commits} | **Files changed**: {total_files} | **Files reviewed**: {len(findings)} | **Skipped**: {skipped}",
        "",
        "---",
        "",
        f"## Decision: {decision}",
        "",
        decision_text,
        "",
    ]

    # ── Risk Distribution ─────────────────────────────────────────────
    tier_counts: dict[str, int] = {}
    for f in findings:
        t = f.get("risk_tier", "MEDIUM")
        tier_counts[t] = tier_counts.get(t, 0) + 1

    lines.extend([
        "## Risk Distribution",
        "",
        "| Tier | Files Reviewed | Blockers | Concerns | Passed |",
        "|------|---------------|----------|----------|--------|",
    ])

    for tier in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
        tier_findings = [f for f in findings if f.get("risk_tier") == tier]
        t_blockers    = sum(1 for f in tier_findings if f["verdict"] == "blocker")
        t_concerns    = sum(1 for f in tier_findings if f["verdict"] == "concern")
        t_passed      = sum(1 for f in tier_findings if f["verdict"] == "pass")
        if tier_findings:
            lines.append(f"| {tier} | {len(tier_findings)} | {t_blockers} | {t_concerns} | {t_passed} |")

    lines.append("")

    # ── Blockers Table ────────────────────────────────────────────────
    if blockers:
        lines.extend([
            "## 🔴 Blockers (MUST FIX before production)",
            "",
            "| # | File | Risk Tier | Issues |",
            "|---|------|-----------|--------|",
        ])
        for i, b in enumerate(blockers, 1):
            issues_str = "; ".join(b.get("issues", []))
            lines.append(f"| {i} | `{b['file']}` | {b.get('risk_tier', 'CRITICAL')} | {issues_str} |")
        lines.append("")

    # ── Concerns Table ────────────────────────────────────────────────
    if concerns:
        lines.extend([
            "## 🟡 Concerns (recommended to address)",
            "",
            "| # | File | Risk Tier | Issues |",
            "|---|------|-----------|--------|",
        ])
        for i, c in enumerate(concerns, 1):
            issues_str = "; ".join(c.get("issues", []))
            lines.append(f"| {i} | `{c['file']}` | {c.get('risk_tier', 'MEDIUM')} | {issues_str} |")
        lines.append("")

    # ── Passed Files Summary ──────────────────────────────────────────
    if passed:
        lines.extend([
            f"## ✅ Passed ({len(passed)} files)",
            "",
            "| File | Risk Tier |",
            "|------|-----------|",
        ])
        # Show max 20 passed files to keep report compact
        for p in passed[:20]:
            lines.append(f"| `{p['file']}` | {p.get('risk_tier', 'LOW')} |")
        if len(passed) > 20:
            lines.append(f"| ... and {len(passed) - 20} more | |")
        lines.append("")

    # ── Skipped Files ─────────────────────────────────────────────────
    if skipped > 0:
        lines.extend([
            f"## ⏭️ Skipped ({skipped} files)",
            "",
            f"{skipped} files were classified as SKIP tier (docs, assets, lock files, generated code) "
            "and were not individually reviewed.",
            "",
        ])

    # ── Footer ────────────────────────────────────────────────────────
    lines.extend([
        "---",
        "",
        f"[View full diff on GitHub]({compare_url})" if compare_url else "",
        "",
        f"> Generated by **release-review** skill | {now}",
    ])

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
        args = json.loads(raw)

        # Handle LLM double-encoding
        if isinstance(args, str):
            args = json.loads(args)

        required = ["owner", "repo", "base_tag", "head_tag", "findings"]
        missing = [k for k in required if k not in args]
        if missing:
            print(json.dumps({"error": f"Missing required fields: {missing}"}))
            sys.exit(1)

        report = generate_report(
            owner=args["owner"],
            repo=args["repo"],
            base_tag=args["base_tag"],
            head_tag=args["head_tag"],
            total_files=args.get("total_files", 0),
            total_commits=args.get("total_commits", 0),
            compare_url=args.get("compare_url", ""),
            findings=args["findings"],
        )
        print(report)
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(json.dumps({"error": f"Failed to parse input: {exc}"}))
        sys.exit(1)
