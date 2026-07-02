"""Summarize a WCNP health check result into a concise triage report.

Usage via run_skill_script:
  skill_name: health-triage
  script_path: scripts/summarize_health.py
  args: { "health_result": <JSON string from wcnp_check_app_health> }

Parses the health check JSON and outputs a formatted triage summary
with severity classification and recommended next actions.
"""

import json
import sys
from pydantic import BaseModel, Field, ValidationError

class HealthTriageArgs(BaseModel):
    health_result: dict = Field(default_factory=dict, description="JSON output from wcnp_check_app_health")

def summarize(health_result: dict) -> str:
    overall = health_result.get("overall_status", "unknown")
    anomaly = health_result.get("anomaly_detected", False)
    root_cause = health_result.get("root_cause", "none identified")
    attribution = health_result.get("failure_attribution", "unknown")
    correlations = health_result.get("correlations", [])
    clusters = health_result.get("clusters", {})
    checks = health_result.get("checks", {})

    # Classify severity
    if overall == "unhealthy" and anomaly:
        severity = "🔴 CRITICAL"
    elif overall == "unhealthy":
        severity = "🟠 HIGH"
    elif overall == "degraded":
        severity = "🟡 MEDIUM"
    else:
        severity = "🟢 HEALTHY"

    lines = [
        f"## Health Triage Summary",
        f"",
        f"**Severity**: {severity}",
        f"**Overall Status**: {overall}",
        f"**Anomaly Detected**: {'YES' if anomaly else 'No'}",
        f"**Root Cause**: {root_cause}",
        f"**Failure Attribution**: {attribution}",
    ]

    # Cluster breakdown
    if clusters:
        lines.append("")
        lines.append("### Cluster Status")
        for cluster_name, cluster_data in clusters.items():
            status = cluster_data.get("status", "unknown") if isinstance(cluster_data, dict) else cluster_data
            lines.append(f"- **{cluster_name}**: {status}")

    # Failed checks
    failed = []
    if isinstance(checks, dict):
        for check_name, check_data in checks.items():
            if isinstance(check_data, dict) and check_data.get("status") in ("failed", "critical", "warning"):
                failed.append((check_name, check_data.get("status"), check_data.get("message", "")))

    if failed:
        lines.append("")
        lines.append("### Failed Checks")
        for name, status, msg in failed:
            lines.append(f"- **{name}** [{status}]: {msg}")

    # Correlations
    if correlations:
        lines.append("")
        lines.append("### Correlations")
        for corr in correlations:
            if isinstance(corr, str):
                lines.append(f"- {corr}")
            elif isinstance(corr, dict):
                lines.append(f"- {corr.get('description', str(corr))}")

    # Recommended actions
    lines.append("")
    lines.append("### Recommended Next Steps")
    if anomaly:
        lines.append("1. **Load incident-rca skill** — trace the anomaly to code/commits/PRs")
    if attribution == "downstream_dependency":
        lines.append("2. **Load dependency-mapping skill** — check downstream service health")
    if attribution == "this_app":
        lines.append("2. **Run wcnp_analyze** with targeted checks for the failing signal")
    if not anomaly and overall == "healthy":
        lines.append("- No action required — application is healthy")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raw_input = sys.argv[1] if len(sys.argv) > 1 else "{}"
        
        # Sometimes the LLM double-encodes the JSON, so we parse it first to handle strings
        parsed = json.loads(raw_input)
        if isinstance(parsed, dict):
            # If the health_result inside the dict is a string, parse it
            hr = parsed.get("health_result", {})
            if isinstance(hr, str):
                parsed["health_result"] = json.loads(hr) if hr.strip() else {}
                
        args = HealthTriageArgs.model_validate(parsed)
        print(summarize(args.health_result))
    except (json.JSONDecodeError, ValidationError, TypeError, KeyError) as exc:
        print(f"Error parsing input: Schema Validation Error: {exc}")
        sys.exit(1)
