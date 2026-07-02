"""Analyze Cosmos DB throttling (429) patterns from health check results.

Usage via run_skill_script:
  skill_name: cosmos-triage
  script_path: scripts/throttle_analysis.py
  args: { "health_result": <JSON from cosmos_check_account_health> }

Produces:
- Throttle rate breakdown by partition/collection
- RU utilization percentage
- Recommendations for RU provisioning
"""

import json
import sys


def analyze_throttle(health_result: dict) -> str:
    checks = health_result.get("checks", {})
    account = health_result.get("account_name", health_result.get("account", "unknown"))
    overall = health_result.get("overall_status", "unknown")

    throttle_data = checks.get("throttled", checks.get("throttled_requests", {}))
    ru_data = checks.get("ru", checks.get("ru_exhaustion", {}))
    traffic_data = checks.get("traffic", checks.get("traffic_spikes", {}))

    lines = [
        f"## Cosmos DB Throttle Analysis: {account}",
        "",
        f"**Overall Status**: {overall}",
        "",
    ]

    # Throttle check
    if isinstance(throttle_data, dict):
        status = throttle_data.get("status", "unknown")
        rate = throttle_data.get("throttle_rate", throttle_data.get("value", "N/A"))
        lines.append(f"### 429 Throttled Requests")
        lines.append(f"- **Status**: {status}")
        lines.append(f"- **Throttle Rate**: {rate}")
        if throttle_data.get("partitions"):
            lines.append("- **Hot Partitions**:")
            for p in throttle_data["partitions"][:10]:
                pk = p.get("partition_key", p.get("id", "?"))
                count = p.get("count", p.get("throttled_count", "?"))
                lines.append(f"  - `{pk}`: {count} throttled requests")
    else:
        lines.append("### 429 Throttled Requests: No data")

    lines.append("")

    # RU utilization
    if isinstance(ru_data, dict):
        status = ru_data.get("status", "unknown")
        utilization = ru_data.get("utilization_pct", ru_data.get("value", "N/A"))
        provisioned = ru_data.get("provisioned_ru", "N/A")
        consumed = ru_data.get("consumed_ru", "N/A")
        lines.append(f"### RU Utilization")
        lines.append(f"- **Status**: {status}")
        lines.append(f"- **Utilization**: {utilization}%")
        lines.append(f"- **Provisioned**: {provisioned} RU/s")
        lines.append(f"- **Consumed**: {consumed} RU/s")
    else:
        lines.append("### RU Utilization: No data")

    lines.append("")

    # Recommendations
    lines.append("### Recommendations")
    throttle_status = throttle_data.get("status", "") if isinstance(throttle_data, dict) else ""
    ru_status = ru_data.get("status", "") if isinstance(ru_data, dict) else ""

    if throttle_status in ("critical", "failed", "unhealthy"):
        lines.append("1. 🔴 **Increase provisioned RU** — active throttling detected")
        lines.append("2. Review hot partition keys — consider partition key redesign")
        lines.append("3. Enable autoscale if not already configured")
    elif throttle_status in ("warning", "degraded"):
        lines.append("1. 🟡 **Monitor RU headroom** — nearing throttle threshold")
        lines.append("2. Consider switching to autoscale provisioning")
    else:
        lines.append("- 🟢 No throttling issues detected")

    if ru_status in ("critical", "failed"):
        lines.append("- ⚠️ RU exhaustion detected — scale up immediately")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        raw = args.get("health_result", "{}")
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw
        print(analyze_throttle(data if isinstance(data, dict) else {}))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}. Expected JSON with 'health_result' key.")
        sys.exit(1)
