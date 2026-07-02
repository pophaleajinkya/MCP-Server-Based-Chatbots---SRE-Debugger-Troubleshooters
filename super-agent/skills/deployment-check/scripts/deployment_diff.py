"""Analyze deployment differences — compare before/after versions and timings.

Usage via run_skill_script:
  skill_name: deployment-check
  script_path: scripts/deployment_diff.py
  args: { "deployments": <JSON string from fetch_wcnp_deployments or fetch_all_deployments> }

Parses deployment records and produces:
- Version change summary per app
- Deployment frequency analysis
- Timeline with gaps between deployments
"""

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone as _tz


def analyze_deployments(deployments: list) -> str:
    if not deployments:
        return "No deployment data to analyze."

    # Group by app
    by_app = defaultdict(list)
    for dep in deployments:
        app = dep.get("app_name", dep.get("app", dep.get("name", "unknown")))
        by_app[app].append(dep)

    lines = ["## Deployment Analysis", ""]

    # Summary
    total = len(deployments)
    apps = len(by_app)
    lines.append(f"**Total deployments**: {total} across **{apps} app(s)**")
    lines.append("")

    for app, deps in sorted(by_app.items()):
        lines.append(f"### {app}")

        # Sort by time
        for d in deps:
            ts = d.get("deployed_at", d.get("timestamp", d.get("created_at", "")))
            try:
                if ts and isinstance(ts, str):
                    d["_parsed_time"] = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                else:
                    d["_parsed_time"] = None
            except (ValueError, TypeError, AttributeError):
                d["_parsed_time"] = None

        # Use timezone-aware sentinel so we don't mix aware/naive datetimes
        _min_aware = datetime.min.replace(tzinfo=_tz.utc)
        deps.sort(key=lambda d: d.get("_parsed_time") or _min_aware)

        lines.append("")
        lines.append("| Time | Version | Deployer | Platform | CRQ |")
        lines.append("|---|---|---|---|---|")

        prev_version = None
        for d in deps:
            time_str = d["_parsed_time"].strftime("%Y-%m-%d %H:%M") if d["_parsed_time"] else "?"
            version = d.get("version", d.get("image_tag", "?"))
            deployer = d.get("deployer", d.get("deployed_by", "?"))
            platform = d.get("platform", "WCNP")
            crq = d.get("crq_id", d.get("crq", "—"))

            version_display = version
            if prev_version and prev_version != version:
                version_display = f"**{version}** ← {prev_version}"
            prev_version = version

            lines.append(f"| {time_str} | {version_display} | {deployer} | {platform} | {crq} |")

        # Deployment frequency
        times = [d["_parsed_time"] for d in deps if d["_parsed_time"]]
        if len(times) >= 2:
            gaps = [(times[i+1] - times[i]).total_seconds() / 60 for i in range(len(times)-1)]
            avg_gap = sum(gaps) / len(gaps)
            lines.append(f"\n*Avg gap between deployments*: {avg_gap:.0f} min")

        lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
        raw = args.get("deployments", "[]")

        if isinstance(raw, str):
            data = json.loads(raw)
        else:
            data = raw

        # Handle both list and dict with "deployments" key
        if isinstance(data, dict):
            data = data.get("deployments", data.get("items", []))
        elif not isinstance(data, list):
            data = []

        print(analyze_deployments(data))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}. Expected JSON with 'deployments' key.")
        sys.exit(1)
