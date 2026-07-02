"""Classify health-check results into signal tiers and explain the rollup.

Usage via run_skill_script:
  skill_name: health-triage
  script_path: scripts/classify_signal_tiers.py
  args: { "health_result": <JSON from wcnp_check_app_health> }

Reads the tiered status fields produced by the MCP analyze_tool and
generates a human-readable explanation of how overall_status was derived,
whether a resource advisory is active, and what the tier override means.
"""

import json
import sys
from pydantic import BaseModel, Field, ValidationError


_GOLDEN_NAMES = {
    "istio_client_latency", "istio_server_latency",
    "istio_client_success_rate", "istio_server_success_rate",
    "istio_client_success", "istio_server_success",
    "restarts",
}

_RESOURCE_NAMES = {"cpu", "memory", "node_cpu"}


class Args(BaseModel):
    health_result: dict = Field(default_factory=dict)


def classify(health_result: dict) -> str:
    golden_status = health_result.get("golden_signal_status", "unknown")
    resource_status = health_result.get("resource_signal_status", "unknown")
    overall = health_result.get("overall_status", "unknown")
    tier_override = health_result.get("tier_override_active", False)
    resource_advisory = health_result.get("resource_advisory", [])
    traffic_adj = health_result.get("traffic_adjusted_latency")
    checks = health_result.get("checks", {})

    lines = [
        "## Signal Tier Classification",
        "",
        f"| Tier | Status |",
        f"|------|--------|",
        f"| **Golden Signals** | {golden_status} |",
        f"| **Resource Signals** | {resource_status} |",
        f"| **Overall (golden-driven)** | {overall} |",
        "",
    ]

    if tier_override:
        lines.extend([
            "### ⚠️ Tier Override Active",
            "",
            "Resource signals are degraded but golden signals are healthy.",
            "This means the app is functioning correctly for users despite",
            "elevated resource usage — **no escalation is warranted.**",
            "",
        ])

    # Golden signal detail
    golden_checks = []
    for name in _GOLDEN_NAMES:
        data = checks.get(name)
        if isinstance(data, dict):
            golden_checks.append((name, data.get("status", "unknown")))
    if golden_checks:
        lines.append("### Golden Signal Detail")
        lines.append("")
        lines.append("| Check | Status |")
        lines.append("|-------|--------|")
        for name, status in sorted(golden_checks):
            lines.append(f"| {name} | {status} |")
        lines.append("")

    # Resource advisory
    if resource_advisory:
        lines.append("### Resource Advisory")
        lines.append("")
        for adv in resource_advisory:
            check = adv.get("check", "unknown")
            status = adv.get("status", "unknown")
            chronicity = adv.get("chronicity", "unknown")
            cv = adv.get("coefficient_of_variation")
            cv_str = f" (CV={cv})" if cv is not None else ""
            lines.append(
                f"- **{check}**: {status} — {chronicity}{cv_str}"
            )
        lines.append("")

    # Traffic-adjusted latency
    if traffic_adj and isinstance(traffic_adj, dict):
        lines.append("### Traffic-Adjusted Latency")
        lines.append("")
        if traffic_adj.get("adjustment_applied"):
            lines.append(
                f"- Raw latency deviation: {traffic_adj['raw_latency_deviation_percent']}%"
            )
            lines.append(
                f"- Traffic deviation: {traffic_adj['traffic_deviation_percent']}%"
            )
            lines.append(
                f"- **Adjusted latency deviation: {traffic_adj['adjusted_latency_deviation_percent']}%**"
            )
            lines.append(f"- {traffic_adj.get('reason', '')}")
        else:
            lines.append(
                f"- Latency deviation: {traffic_adj['raw_latency_deviation_percent']}% "
                f"(no traffic adjustment needed)"
            )
        lines.append("")

    # Guidance
    lines.append("### Interpretation Guide")
    lines.append("")
    if overall == "healthy" and tier_override:
        lines.append(
            "The application is healthy for users. Resource pressure is noted "
            "but does not require immediate action. Monitor for golden signal "
            "degradation."
        )
    elif overall == "unhealthy":
        lines.append(
            "Golden signals indicate user-facing impact. Prioritize investigating "
            "latency, error rates, and restarts before resource issues."
        )
    elif overall == "degraded":
        lines.append(
            "Golden signals show partial degradation. Check if error rates or "
            "latency are trending toward unhealthy thresholds."
        )
    else:
        lines.append("All signals are within normal ranges.")

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
