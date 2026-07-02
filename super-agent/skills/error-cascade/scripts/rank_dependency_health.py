"""Rank dependency health results and compute confidence for error cascade.

Usage via run_skill_script:
  skill_name: error-cascade
  script_path: scripts/rank_dependency_health.py
  args: { "dependency_results": { "dep-name": <health_result>, ... },
          "primary_app_error_deviation": <optional float — deviation% of primary app> }

Takes the Prometheus health sweep results and produces:
1. A prioritized investigation list (confirmed-bad → suspicious → chronic → healthy)
2. A CONFIDENCE verdict: can we identify the culprit from Prometheus alone?
   - CONFIDENT → one dep clearly dominates (≥ 3× second-worst)
   - NOT_CONFIDENT → ambiguous, need O2 disambiguation on the current layer's app
"""

import json
import sys
from pydantic import BaseModel, Field, ValidationError


class Args(BaseModel):
    dependency_results: dict = Field(
        default_factory=dict,
        description="Map of dependency name → wcnp_check_app_health result",
    )
    primary_app_error_deviation: float | None = Field(
        default=None,
        description="Error deviation% of the primary app (for context in report)",
    )


_SEVERITY_ORDER = {"unhealthy": 0, "degraded": 1, "healthy": 2, "unknown": 3}

_CONFIDENCE_RATIO = 3.0  # Winner must be ≥ 3× the second-worst to be confident


def _extract_error_class(result: dict) -> dict:
    """Extract 4XX/5XX breakdown from a health result."""
    checks = result.get("checks", {})
    if not isinstance(checks, dict):
        checks = {}
    traffic = checks.get("istio_traffic_spike", {})
    non_2xx = (traffic.get("non_2xx_analysis") or {}) if isinstance(traffic, dict) else {}

    four_dev = non_2xx.get("4xx_deviation_percent")
    five_dev = non_2xx.get("5xx_deviation_percent")

    # Composite deviation: max of 4xx/5xx deviation, used for confidence scoring
    devs = [d for d in (four_dev, five_dev) if d is not None and isinstance(d, (int, float))]
    max_deviation = max(devs) if devs else 0.0

    return {
        "4xx_spike": non_2xx.get("4xx_spike", False),
        "5xx_spike": non_2xx.get("5xx_spike", False),
        "4xx_current_percent": non_2xx.get("4xx_current_percent"),
        "5xx_current_percent": non_2xx.get("5xx_current_percent"),
        "4xx_deviation_percent": four_dev,
        "5xx_deviation_percent": five_dev,
        "max_deviation_percent": max_deviation,
        "non_2xx_percent": traffic.get("non_2xx_percent") if isinstance(traffic, dict) else None,
    }


def _classify_dep(name: str, result: dict) -> dict:
    """Classify a dependency into investigation categories."""
    overall = result.get("overall_status", "unknown")
    golden = result.get("golden_signal_status", "unknown")
    anomaly = result.get("anomaly_detected", False)
    attribution = result.get("failure_attribution")
    error_class = _extract_error_class(result)

    # Determine chronicity from resource advisory or checks
    chronicity = "unknown"
    advisories = result.get("resource_advisory", [])
    if isinstance(advisories, list):
        for adv in advisories:
            if isinstance(adv, dict) and adv.get("chronicity"):
                chronicity = adv["chronicity"]
                break
    # Also check anomaly details in checks
    checks_data = result.get("checks", {})
    if isinstance(checks_data, dict):
        for check_data in checks_data.values():
            if isinstance(check_data, dict):
                for ctx_key in ("anomaly_details", "baseline_context"):
                    ctx = check_data.get(ctx_key, {})
                    if isinstance(ctx, dict) and ctx.get("chronicity"):
                        chronicity = ctx["chronicity"]
                        break

    # Classification
    if overall == "error":
        # Health check itself failed (timeout, unreachable) — treat as confirmed bad
        category = "confirmed_bad"
        priority = 0
    elif golden in ("unhealthy",) and anomaly and chronicity != "chronic":
        category = "confirmed_bad"
        priority = 0
    elif golden in ("degraded",) and anomaly and chronicity != "chronic":
        category = "suspicious"
        priority = 1
    elif overall in ("unhealthy", "degraded") and chronicity == "chronic":
        category = "chronic"
        priority = 3
    elif overall in ("unhealthy", "degraded"):
        category = "suspicious"
        priority = 2
    else:
        category = "healthy"
        priority = 4

    cascade = attribution == "downstream_dependency"

    return {
        "name": name,
        "category": category,
        "priority": priority,
        "overall_status": overall,
        "golden_status": golden,
        "anomaly_detected": anomaly,
        "chronicity": chronicity,
        "failure_attribution": attribution,
        "cascade_continues": cascade,
        "error_class": error_class,
    }


def _compute_confidence(candidates: list[dict]) -> dict:
    """Determine if Prometheus alone can identify the culprit.

    Returns:
        {
            "confident": bool,
            "winner": str | None,          # dep name if confident
            "reason": str,
            "top_deviation": float,
            "second_deviation": float,
            "ratio": float | None,         # top / second (None if second is 0)
        }
    """
    # Only consider non-chronic, non-healthy deps
    scorable = [d for d in candidates if d["category"] in ("confirmed_bad", "suspicious")]

    if not scorable:
        return {
            "confident": False,
            "winner": None,
            "reason": "No dependencies show correlated degradation in Prometheus",
            "top_deviation": 0.0,
            "second_deviation": 0.0,
            "ratio": None,
        }

    # Rank by max error deviation
    scorable.sort(key=lambda d: d["error_class"].get("max_deviation_percent", 0), reverse=True)

    top = scorable[0]
    top_dev = top["error_class"].get("max_deviation_percent", 0)

    if len(scorable) == 1:
        return {
            "confident": True,
            "winner": top["name"],
            "reason": f"Only one degraded dependency: {top['name']} (deviation {top_dev:.1f}%)",
            "top_deviation": top_dev,
            "second_deviation": 0.0,
            "ratio": None,
        }

    second = scorable[1]
    second_dev = second["error_class"].get("max_deviation_percent", 0)

    if second_dev == 0:
        return {
            "confident": True,
            "winner": top["name"],
            "reason": f"{top['name']} has deviation {top_dev:.1f}% while next has 0%",
            "top_deviation": top_dev,
            "second_deviation": 0.0,
            "ratio": None,
        }

    ratio = top_dev / second_dev

    if ratio >= _CONFIDENCE_RATIO:
        return {
            "confident": True,
            "winner": top["name"],
            "reason": (
                f"{top['name']} deviation ({top_dev:.1f}%) is {ratio:.1f}× "
                f"the next ({second['name']} at {second_dev:.1f}%) — exceeds {_CONFIDENCE_RATIO}× threshold"
            ),
            "top_deviation": top_dev,
            "second_deviation": second_dev,
            "ratio": ratio,
        }

    return {
        "confident": False,
        "winner": None,
        "reason": (
            f"Ambiguous: {top['name']} ({top_dev:.1f}%) vs {second['name']} ({second_dev:.1f}%) "
            f"— ratio {ratio:.1f}× is below {_CONFIDENCE_RATIO}× threshold. "
            f"Use O2 disambiguation on the current layer's app."
        ),
        "top_deviation": top_dev,
        "second_deviation": second_dev,
        "ratio": ratio,
    }


def rank(dependency_results: dict, primary_app_error_deviation: float | None = None) -> str:
    classified = []
    for name, result in dependency_results.items():
        if not isinstance(result, dict):
            continue
        classified.append(_classify_dep(name, result))

    # Sort by priority (confirmed_bad first)
    classified.sort(key=lambda x: (x["priority"], x["name"]))

    confirmed = [d for d in classified if d["category"] == "confirmed_bad"]
    suspicious = [d for d in classified if d["category"] == "suspicious"]
    chronic = [d for d in classified if d["category"] == "chronic"]
    healthy = [d for d in classified if d["category"] == "healthy"]

    # Compute confidence
    confidence = _compute_confidence(classified)

    lines = [
        "## Dependency Investigation Priority",
        "",
        f"- **Confirmed bad** (investigate with logs): {len(confirmed)}",
        f"- **Suspicious** (investigate if no confirmed bad): {len(suspicious)}",
        f"- **Chronic** (pre-existing, skip): {len(chronic)}",
        f"- **Healthy** (skip): {len(healthy)}",
        "",
    ]

    if primary_app_error_deviation is not None:
        lines.append(f"Primary app error deviation: **{primary_app_error_deviation:.1f}%**")
        lines.append("")

    # Confidence verdict — prominent section
    lines.append("---")
    lines.append("")
    if confidence["confident"]:
        lines.append(f"### ✅ CONFIDENT — Prometheus identifies culprit: **{confidence['winner']}**")
        lines.append("")
        lines.append(f"Reason: {confidence['reason']}")
        lines.append("")
        lines.append(f"**→ Proceed to next layer for `{confidence['winner']}` (skip O2 disambiguation)**")
    else:
        lines.append("### ❌ NOT CONFIDENT — Prometheus is ambiguous")
        lines.append("")
        lines.append(f"Reason: {confidence['reason']}")
        lines.append("")
        lines.append("**→ Run O2 disambiguation query on the CURRENT layer's app to identify the culprit**")
    lines.append("")
    lines.append("---")
    lines.append("")

    if confirmed:
        lines.append("### 🔴 Confirmed Bad — Phase 4 (Logs) Required")
        lines.append("")
        lines.append("| Dependency | Golden | 4XX | 5XX | Cascade? |")
        lines.append("|------------|--------|-----|-----|----------|")
        for d in confirmed:
            ec = d["error_class"]
            four = f"{ec['4xx_current_percent']:.1f}%" if ec.get("4xx_current_percent") is not None else "—"
            five = f"{ec['5xx_current_percent']:.1f}%" if ec.get("5xx_current_percent") is not None else "—"
            cascade = "↓ downstream" if d["cascade_continues"] else "this_app"
            lines.append(f"| **{d['name']}** | {d['golden_status']} | {four} | {five} | {cascade} |")
        lines.append("")

    if suspicious:
        lines.append("### 🟡 Suspicious — Investigate If No Confirmed Bad")
        lines.append("")
        lines.append("| Dependency | Status | Golden | Anomaly | Chronicity |")
        lines.append("|------------|--------|--------|---------|------------|")
        for d in suspicious:
            lines.append(
                f"| {d['name']} | {d['overall_status']} | {d['golden_status']} "
                f"| {'yes' if d['anomaly_detected'] else 'no'} | {d['chronicity']} |"
            )
        lines.append("")

    if chronic:
        lines.append("### ⚪ Chronic — Pre-existing (Skip)")
        lines.append("")
        for d in chronic:
            lines.append(f"- {d['name']}: {d['overall_status']} (chronic)")
        lines.append("")

    # Cascade guidance
    cascading = [d for d in confirmed + suspicious if d["cascade_continues"]]
    if cascading:
        lines.append("### 🔄 Cascade Detected")
        lines.append("")
        lines.append(
            "The following dependencies also blame their downstream. "
            "Repeat Phases 2-4 for these:"
        )
        lines.append("")
        for d in cascading:
            lines.append(f"- **{d['name']}** → `failure_attribution = downstream_dependency`")
        lines.append("")

    # Action summary
    lines.append("### Recommended Next Steps")
    lines.append("")
    if confidence["confident"]:
        winner = confidence["winner"]
        # Find the winner in classified
        winner_dep = next((d for d in classified if d["name"] == winner), None)
        if winner_dep and winner_dep["cascade_continues"]:
            lines.append(
                f"1. **{winner}** blames its own downstream — "
                f"repeat Phases D2-D4 for `{winner}` (next cascade layer)"
            )
        elif winner_dep:
            lines.append(
                f"1. **{winner}** is the root cause (`failure_attribution = {winner_dep['failure_attribution']}`) — "
                f"run O2 DEEP analysis on `{winner}` for stack traces and error details"
            )
        else:
            lines.append(f"1. Investigate **{winner}** further")
    elif confirmed or suspicious:
        lines.append("1. **O2 disambiguation needed** — query the current layer's app logs:")
        lines.append("   ```")
        lines.append("   SELECT http_path, response_code, count(_timestamp) as error_count")
        lines.append('   FROM "<stream>"')
        lines.append("   WHERE <default_filter>")
        lines.append("     AND CAST(response_code AS INT) >= 400")
        lines.append("   GROUP BY http_path, response_code")
        lines.append("   ORDER BY error_count DESC")
        lines.append("   LIMIT 20")
        lines.append("   ```")
        lines.append("2. Match top `http_path` values against the dependency list above")
        lines.append("3. The path with the highest error count → that's the culprit dependency")
    else:
        lines.append(
            "No k8app dependencies show correlated degradation. "
            "Investigate infrastructure dependencies (meghacache, cosmos, kafka) "
            "or the originating app's own logs."
        )

    # Machine-readable summary for the LLM
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("### Machine-Readable Summary")
    lines.append("```json")
    summary = {
        "confident": confidence["confident"],
        "winner": confidence["winner"],
        "confidence_ratio": confidence["ratio"],
        "confirmed_bad": [d["name"] for d in confirmed],
        "suspicious": [d["name"] for d in suspicious],
        "chronic": [d["name"] for d in chronic],
        "healthy": [d["name"] for d in healthy],
        "cascading": [d["name"] for d in cascading] if cascading else [],
        "action": "proceed_to_next_layer" if confidence["confident"] else "o2_disambiguation",
    }
    lines.append(json.dumps(summary, indent=2))
    lines.append("```")

    return "\n".join(lines)


if __name__ == "__main__":
    try:
        raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            dr = parsed.get("dependency_results", {})
            if isinstance(dr, str):
                parsed["dependency_results"] = json.loads(dr) if dr.strip() else {}
        args = Args.model_validate(parsed)
        print(rank(args.dependency_results, args.primary_app_error_deviation))
    except (json.JSONDecodeError, ValidationError, TypeError, KeyError) as exc:
        print(f"Error parsing input: {exc}")
        sys.exit(1)
