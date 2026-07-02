"""Generate a bad-node report from Cassandra health check results.

Usage via run_skill_script:
  skill_name: cassandra-triage
  script_path: scripts/bad_node_report.py
  args: { "health_result": <JSON from cassandra_check_cluster_health> }

Produces:
- Per-node performance comparison
- Outlier detection (nodes exceeding cluster P99)
- Actionable remediation steps per bad node
"""

import json
import sys


def bad_node_report(health_result: dict) -> str:
    checks = health_result.get("checks", {})
    cluster = health_result.get("cluster_name", health_result.get("cluster", "unknown"))
    overall = health_result.get("overall_status", "unknown")

    bad_node_data = checks.get("bad_node", checks.get("bad_node_detection", {}))
    latency_data = checks.get("latency", checks.get("p99_latency", {}))
    timeout_data = checks.get("timeouts", checks.get("timeout_spikes", {}))

    lines = [
        f"## Cassandra Bad-Node Report: {cluster}",
        "",
        f"**Overall Status**: {overall}",
        "",
    ]

    # Bad node detection
    if isinstance(bad_node_data, dict):
        status = bad_node_data.get("status", "unknown")
        bad_nodes = bad_node_data.get("bad_nodes", bad_node_data.get("outliers", []))

        lines.append(f"### Bad Node Detection: {status}")
        lines.append("")

        if bad_nodes:
            lines.append("| Node | P99 Latency | Avg Latency | Timeout Rate | Status |")
            lines.append("|---|---:|---:|---:|---|")

            for node in bad_nodes:
                name = node.get("node", node.get("host", node.get("ip", "?")))
                p99 = node.get("p99_latency_ms", node.get("p99", "?"))
                avg = node.get("avg_latency_ms", node.get("avg", "?"))
                timeouts = node.get("timeout_rate", node.get("timeouts", "?"))
                node_status = node.get("status", "outlier")
                lines.append(f"| {name} | {p99}ms | {avg}ms | {timeouts} | {node_status} |")

            lines.append("")
            lines.append(f"**{len(bad_nodes)} bad node(s)** detected as performance outliers.")
        else:
            lines.append("✅ No bad nodes detected — all nodes performing within normal range.")
    else:
        lines.append("### Bad Node Detection: No data available")

    lines.append("")

    # Cluster-wide latency
    if isinstance(latency_data, dict):
        status = latency_data.get("status", "unknown")
        p99 = latency_data.get("p99_ms", latency_data.get("value", "?"))
        lines.append(f"### Cluster P99 Latency: {p99}ms ({status})")
    lines.append("")

    # Timeout spikes
    if isinstance(timeout_data, dict):
        status = timeout_data.get("status", "unknown")
        rate = timeout_data.get("rate", timeout_data.get("value", "?"))
        lines.append(f"### Timeout Rate: {rate} ({status})")
    lines.append("")

    # Remediation
    lines.append("### Remediation Steps")
    bad_nodes = []
    if isinstance(bad_node_data, dict):
        bad_nodes = bad_node_data.get("bad_nodes", bad_node_data.get("outliers", []))

    if bad_nodes:
        lines.append("For each bad node:")
        lines.append("1. Check if the node is undergoing compaction (`nodetool compactionstats`)")
        lines.append("2. Check GC pause times — sustained >500ms pauses indicate heap pressure")
        lines.append("3. Verify disk I/O — high `await` times suggest storage bottleneck")
        lines.append("4. Check if the node was recently restarted and is still streaming")
        lines.append("5. If persistent, consider decommissioning and replacing the node")
    else:
        lines.append("- No remediation needed — cluster is healthy")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        raw = args.get("health_result", "{}")
        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw
        print(bad_node_report(data if isinstance(data, dict) else {}))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}. Expected JSON with 'health_result' key.")
        sys.exit(1)
