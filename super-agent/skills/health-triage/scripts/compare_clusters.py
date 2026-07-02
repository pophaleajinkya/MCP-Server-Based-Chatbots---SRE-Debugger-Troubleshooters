"""Compare health metrics across clusters for a WCNP application.

Usage via run_skill_script:
  skill_name: health-triage
  script_path: scripts/compare_clusters.py
  args: { "health_result": <JSON string from wcnp_check_app_health> }

Takes the multi-cluster health check output and produces a side-by-side
comparison table highlighting divergences between clusters.
"""

import json
import sys


def compare(health_result: dict) -> str:
    clusters = health_result.get("clusters", {})

    if not clusters:
        return "No cluster data available for comparison."

    if len(clusters) < 2:
        return f"Only 1 cluster found ({list(clusters.keys())[0]}). Need 2+ clusters to compare."

    # Collect all check names across clusters
    all_checks = set()
    for cluster_data in clusters.values():
        if isinstance(cluster_data, dict):
            for check_name in cluster_data.get("checks", {}).keys():
                all_checks.add(check_name)

    cluster_names = sorted(clusters.keys())
    all_checks = sorted(all_checks)

    lines = ["## Cross-Cluster Comparison", ""]

    # Header
    header = "| Check | " + " | ".join(cluster_names) + " | Divergent? |"
    separator = "|---|" + "|".join(["---"] * len(cluster_names)) + "|---|"
    lines.extend([header, separator])

    divergent_count = 0
    for check in all_checks:
        statuses = []
        for cn in cluster_names:
            cd = clusters.get(cn, {})
            if isinstance(cd, dict):
                check_data = cd.get("checks", {}).get(check, {})
                status = check_data.get("status", "n/a") if isinstance(check_data, dict) else "n/a"
            else:
                status = "n/a"
            statuses.append(status)

        unique = set(statuses)
        divergent = len(unique) > 1 and "n/a" not in unique
        if divergent:
            divergent_count += 1
        flag = "⚠️ YES" if divergent else ""

        row = f"| {check} | " + " | ".join(statuses) + f" | {flag} |"
        lines.append(row)

    lines.append("")
    if divergent_count:
        lines.append(f"**{divergent_count} divergent check(s)** found — investigate clusters with differing status.")
    else:
        lines.append("All clusters are consistent — no divergences detected.")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        health_result_raw = args.get("health_result", "{}")

        if isinstance(health_result_raw, str):
            health_result = json.loads(health_result_raw)
        else:
            health_result = health_result_raw

        print(compare(health_result))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}. Expected JSON with 'health_result' key.")
        sys.exit(1)
