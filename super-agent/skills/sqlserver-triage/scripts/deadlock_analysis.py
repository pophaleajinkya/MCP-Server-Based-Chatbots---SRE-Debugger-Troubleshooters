"""Analyze SQL Server deadlock and blocking data from health check results.

Usage via run_skill_script:
  skill_name: sqlserver-triage
  script_path: scripts/deadlock_analysis.py
  args: { "health_result": <JSON from sqlserver_check_database_health> }

Produces:
- Deadlock frequency and victim analysis
- Blocking chain visualization
- Wait stats breakdown
- Actionable remediation steps
"""

import json
import sys


def deadlock_analysis(health_result: dict) -> str:
    checks = health_result.get("checks", {})
    database = health_result.get("database_name", health_result.get("database", "unknown"))
    overall = health_result.get("overall_status", "unknown")

    deadlock_data = checks.get("deadlocks", {})
    cpu_data = checks.get("cpu", {})
    io_data = checks.get("io_latency", {})
    wait_data = checks.get("wait_stats", {})
    conn_data = checks.get("connections", checks.get("connection_count", {}))

    lines = [
        f"## SQL Server Analysis: {database}",
        "",
        f"**Overall Status**: {overall}",
        "",
    ]

    # Deadlock section
    if isinstance(deadlock_data, dict):
        status = deadlock_data.get("status", "unknown")
        count = deadlock_data.get("count", deadlock_data.get("deadlock_count", 0))
        victims = deadlock_data.get("victims", [])

        lines.append(f"### Deadlocks: {count} detected ({status})")
        lines.append("")

        if victims:
            lines.append("| Time | Victim Process | Wait Resource | Duration |")
            lines.append("|---|---|---|---|")
            for v in victims[:20]:
                ts = v.get("timestamp", v.get("time", "?"))
                proc = v.get("process", v.get("spid", "?"))
                resource = v.get("wait_resource", v.get("resource", "?"))
                duration = v.get("duration_ms", v.get("duration", "?"))
                lines.append(f"| {ts} | {proc} | `{resource}` | {duration}ms |")
        elif count > 0:
            lines.append(f"*{count} deadlocks detected but no victim details available.*")
        else:
            lines.append("✅ No deadlocks detected.")
    else:
        lines.append("### Deadlocks: No data available")

    lines.append("")

    # Resource pressure overview
    lines.append("### Resource Pressure")
    lines.append("")
    lines.append("| Resource | Status | Value |")
    lines.append("|---|---|---|")

    for name, data in [("CPU", cpu_data), ("I/O Latency", io_data),
                       ("Connections", conn_data), ("Wait Stats", wait_data)]:
        if isinstance(data, dict):
            status = data.get("status", "?")
            value = data.get("value", data.get("utilization_pct", data.get("count", "?")))
            lines.append(f"| {name} | {status} | {value} |")

    lines.append("")

    # Remediation
    lines.append("### Remediation")
    deadlock_status = deadlock_data.get("status", "") if isinstance(deadlock_data, dict) else ""
    deadlock_count = deadlock_data.get("count", 0) if isinstance(deadlock_data, dict) else 0

    if deadlock_status in ("critical", "failed", "unhealthy") or deadlock_count > 10:
        lines.append("**Deadlock remediation:**")
        lines.append("1. Identify the conflicting queries using `sys.dm_exec_query_stats`")
        lines.append("2. Ensure consistent lock ordering across transactions")
        lines.append("3. Keep transactions short — minimize lock hold duration")
        lines.append("4. Consider READ_COMMITTED_SNAPSHOT isolation level")
        lines.append("5. Add appropriate indexes to reduce scan locks")
    elif deadlock_count > 0:
        lines.append("- Minor deadlocks detected — monitor but no immediate action needed")
    else:
        lines.append("- ✅ No deadlock or blocking issues detected")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        raw = args.get("health_result", "{}")
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw
        print(deadlock_analysis(data if isinstance(data, dict) else {}))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}. Expected JSON with 'health_result' key.")
        sys.exit(1)
