"""Classify anomalous signals as chronic vs acute from health-check results.

Usage via run_skill_script:
  skill_name: health-triage
  script_path: scripts/chronic_vs_acute.py
  args: { "health_result": <JSON from wcnp_check_app_health> }

Scans all checks for chronicity data (produced by the range-query
engine's coefficient_of_variation analysis) and presents a summary
that helps the LLM decide whether to escalate or accept as baseline.
"""

import json
import sys
from pydantic import BaseModel, Field, ValidationError


class Args(BaseModel):
    health_result: dict = Field(default_factory=dict)


def _extract_chronicity(check_data: dict) -> dict | None:
    """Extract chronicity info from a check's anomaly_details or baseline_context."""
    for key in ("anomaly_details", "app_baseline_context"):
        ctx = check_data.get(key, {})
        if isinstance(ctx, dict) and ctx.get("chronicity"):
            return {
                "chronicity": ctx["chronicity"],
                "coefficient_of_variation": ctx.get("coefficient_of_variation"),
                "clean_baseline": ctx.get("clean_baseline"),
                "clean_days_count": ctx.get("clean_days_count"),
            }
    return None


def classify(health_result: dict) -> str:
    checks = health_result.get("checks", {})

    chronic: list[tuple[str, str, dict]] = []
    acute: list[tuple[str, str, dict]] = []
    unknown: list[tuple[str, str]] = []

    for name, data in checks.items():
        if not isinstance(data, dict):
            continue
        status = data.get("status", "healthy")
        if status in ("healthy", "skipped"):
            continue

        info = _extract_chronicity(data)
        if info is None:
            unknown.append((name, status))
        elif info["chronicity"] == "chronic":
            chronic.append((name, status, info))
        elif info["chronicity"] == "acute":
            acute.append((name, status, info))
        else:
            unknown.append((name, status))

    lines = [
        "## Chronicity Analysis",
        "",
        f"- **Acute signals** (recent change): {len(acute)}",
        f"- **Chronic signals** (stable baseline): {len(chronic)}",
        f"- **Unknown** (insufficient history): {len(unknown)}",
        "",
    ]

    if acute:
        lines.append("### 🔴 Acute — Investigate These")
        lines.append("")
        lines.append("These signals changed recently and deviate from historical norms.")
        lines.append("")
        lines.append("| Check | Status | CV | Baseline |")
        lines.append("|-------|--------|----|----------|")
        for name, status, info in sorted(acute, key=lambda x: x[1]):
            cv = info.get("coefficient_of_variation", "—")
            bl = info.get("clean_baseline", "—")
            lines.append(f"| {name} | {status} | {cv} | {bl} |")
        lines.append("")

    if chronic:
        lines.append("### 🟡 Chronic — Accept or Re-baseline")
        lines.append("")
        lines.append(
            "These signals have been consistently elevated across multiple "
            "historical windows. Consider updating thresholds or investigating "
            "long-term capacity needs."
        )
        lines.append("")
        lines.append("| Check | Status | CV | Baseline | Days |")
        lines.append("|-------|--------|----|----------|------|")
        for name, status, info in sorted(chronic, key=lambda x: x[1]):
            cv = info.get("coefficient_of_variation", "—")
            bl = info.get("clean_baseline", "—")
            days = info.get("clean_days_count", "—")
            lines.append(f"| {name} | {status} | {cv} | {bl} | {days} |")
        lines.append("")

    if unknown:
        lines.append("### ⚪ Unknown Chronicity")
        lines.append("")
        for name, status in unknown:
            lines.append(f"- **{name}**: {status}")
        lines.append("")

    # Guidance
    lines.append("### Recommended Action")
    lines.append("")
    if acute and not chronic:
        lines.append(
            "All degraded signals are acute — this is likely a recent regression. "
            "Prioritize investigation and look for recent deployments or config changes."
        )
    elif chronic and not acute:
        lines.append(
            "All degraded signals are chronic — the app has been in this state "
            "across multiple historical windows. This is likely a known baseline. "
            "Consider adjusting alert thresholds or planning capacity improvements."
        )
    elif acute and chronic:
        lines.append(
            "Mixed signals detected. Focus on the **acute** signals first — they "
            "represent recent changes. Chronic signals may be pre-existing conditions "
            "that don't require immediate action."
        )
    else:
        lines.append("No degraded signals with chronicity data found.")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            hr = parsed.get("health_result", {})
            if isinstance(hr, str):
                parsed["health_result"] = json.loads(hr) if hr.strip() else {}
        args = Args.model_validate(parsed)
        print(classify(args.health_result))
    except (json.JSONDecodeError, ValidationError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}")
        sys.exit(1)
