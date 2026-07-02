"""Calculate blast radius from upstream/downstream dependency data.

Usage via run_skill_script:
  skill_name: dependency-mapping
  script_path: scripts/blast_radius.py
  args: {
    "app_name": "cart-service",
    "upstream": <JSON from fetch_wcnp_upstream_dependencies>,
    "downstream": <JSON from fetch_wcnp_downstream_dependencies>
  }

Produces a blast radius assessment showing:
- Direct + transitive impact counts
- Risk tier classification per dependency
- Mermaid graph snippet for the blast zone
"""

import json
import re
import sys
from collections import Counter


def _safe_mermaid_id(name: str) -> str:
    """Sanitize a string for use as a Mermaid node ID (alphanumeric + underscore only)."""
    return re.sub(r"[^a-zA-Z0-9_]", "_", name)


def _safe_mermaid_label(name: str) -> str:
    """Sanitize a string for use inside Mermaid double-quoted labels.

    Escapes characters that break mermaid v11 parsing: " ( ) [ ] { } < > # & ; |
    """
    return (
        name.replace('"', "'")
        .replace("(", "❨")
        .replace(")", "❩")
        .replace("[", "⟦")
        .replace("]", "⟧")
        .replace("{", "⟨")
        .replace("}", "⟩")
        .replace("<", "‹")
        .replace(">", "›")
        .replace("#", "＃")
        .replace("&", "+")
        .replace(";", ",")
        .replace("|", "∣")
    )


def blast_radius(app_name: str, upstream: dict | list, downstream: dict | list) -> str:
    # Normalize to lists
    up_deps = upstream if isinstance(upstream, list) else upstream.get("dependencies", upstream.get("items", []))
    down_deps = downstream if isinstance(downstream, list) else downstream.get("dependencies", downstream.get("items", []))

    lines = [
        f"## Blast Radius: {app_name}",
        "",
        f"If **{app_name}** goes down:",
        "",
    ]

    # Upstream = services that CALL this app (they'd be impacted)
    lines.append(f"### 🔼 Upstream Impact ({len(up_deps)} services affected)")
    lines.append("")

    if up_deps:
        tier_counts = Counter()
        lines.append("| Service | Namespace | Tier | Platform |")
        lines.append("|---|---|---|---|")
        for dep in up_deps:
            if not isinstance(dep, dict):
                continue
            name = dep.get("app_name", dep.get("name", "?"))
            ns = dep.get("namespace", "?")
            tier = dep.get("tier", dep.get("criticality", "Other"))
            platform = dep.get("platform", "WCNP")
            tier_counts[tier] += 1
            lines.append(f"| {name} | {ns} | {tier} | {platform} |")

        lines.append("")
        lines.append("**Tier breakdown**: " + ", ".join(f"{t}: {c}" for t, c in tier_counts.most_common()))
    else:
        lines.append("*No upstream callers found — this app is a leaf service.*")

    lines.append("")

    # Downstream = services this app DEPENDS ON
    lines.append(f"### 🔽 Downstream Dependencies ({len(down_deps)} services)")
    lines.append("")

    if down_deps:
        for dep in down_deps:
            if not isinstance(dep, dict):
                continue
            name = dep.get("app_name", dep.get("name", "?"))
            dep_type = dep.get("type", dep.get("platform", "service"))
            lines.append(f"- **{name}** ({dep_type})")
    else:
        lines.append("*No downstream dependencies found.*")

    # Risk score
    lines.append("")
    lines.append("### Risk Assessment")

    t0_count = sum(1 for d in up_deps if isinstance(d, dict) and d.get("tier") in ("T0", "Tier0", "Critical"))
    total_impacted = len(up_deps)

    if t0_count > 0:
        lines.append(f"🔴 **HIGH RISK** — {t0_count} Tier-0 (critical) services depend on this app")
    elif total_impacted > 10:
        lines.append(f"🟠 **MEDIUM RISK** — {total_impacted} upstream services impacted")
    elif total_impacted > 0:
        lines.append(f"🟡 **LOW RISK** — {total_impacted} upstream services impacted")
    else:
        lines.append("🟢 **MINIMAL** — no upstream callers identified")

    # Mermaid snippet — IDs are alphanumeric-safe, labels are quoted+escaped
    if up_deps or down_deps:
        app_id = _safe_mermaid_id(app_name)
        app_label = _safe_mermaid_label(app_name)
        lines.extend(["", "### Blast Zone Graph (Mermaid)", "", "```mermaid", "graph LR"])
        for dep in up_deps[:10]:
            if not isinstance(dep, dict):
                continue
            raw = dep.get("app_name", dep.get("name", "unknown"))
            node_id = _safe_mermaid_id(raw)
            node_label = _safe_mermaid_label(raw)
            lines.append(f'    {node_id}["{node_label}"] --> {app_id}["{app_label}"]')
        for dep in down_deps[:10]:
            if not isinstance(dep, dict):
                continue
            raw = dep.get("app_name", dep.get("name", "unknown"))
            node_id = _safe_mermaid_id(raw)
            node_label = _safe_mermaid_label(raw)
            lines.append(f'    {app_id}["{app_label}"] --> {node_id}["{node_label}"]')
        lines.append("```")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

        app = args.get("app_name", "unknown-app")
        up_raw = args.get("upstream", "[]")
        down_raw = args.get("downstream", "[]")

        try:
            up = json.loads(up_raw) if isinstance(up_raw, str) else up_raw
        except (json.JSONDecodeError, TypeError):
            up = []
        try:
            down = json.loads(down_raw) if isinstance(down_raw, str) else down_raw
        except (json.JSONDecodeError, TypeError):
            down = []

        print(blast_radius(app, up or [], down or []))
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}. Expected JSON with 'app_name', 'upstream', 'downstream' keys.")
        sys.exit(1)
