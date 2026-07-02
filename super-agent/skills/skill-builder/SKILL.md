---
name: skill-builder
description: >
  Dynamic skill creator — generates new skills at runtime when no existing
  skill matches the user's request. Use when the user asks for analysis,
  detection, or workflows not covered by existing skills (e.g., anomaly
  detection, custom metric correlation, capacity forecasting, trend analysis).
  Also use when the user explicitly says "create a skill", "build a skill",
  or "I need a new workflow for X". Even if the user doesn't say "skill",
  use this whenever the task requires a reusable multi-step workflow that
  doesn't fit any existing skill.
metadata:
  adk_additional_tools:
    - wcnp_query_prometheus
    - cassandra_query_prometheus
    - cosmos_query_prometheus
    - sqlserver_query_prometheus
    - wcnp_check_app_health
    - wcnp_analyze
---

# Dynamic Skill Builder

## Purpose

You are acting as a **skill factory**. When no existing skill handles the
user's request, you create a new skill at runtime — complete with SKILL.md
instructions and executable Python scripts — then immediately load and
run it.

## When to Use

1. `list_skills()` returned no match for the user's intent
2. The user explicitly asks for a new workflow / skill / automation
3. The task requires a **reusable** multi-step analysis (not a one-off question)

## Step 1 — Analyze the Gap

Before creating anything, identify:

- **What** the user needs (anomaly detection? capacity forecast? custom correlation?)
- **Which MCP tools** provide the raw data (Prometheus queries, health checks, log analysis)
- **What processing** the script must do (z-scores, thresholds, aggregation, ranking)
- **What output format** the user expects (JSON summary, markdown table, chart data)

## Step 2 — Design the Skill

Choose a **kebab-case name** prefixed with `dynamic-`:

```
dynamic-anomaly-detection
dynamic-capacity-forecast
dynamic-error-correlation
```

Decide:
- **description** — one sentence, include triggering phrases
- **scripts** — one Python file per distinct analysis step
- **adk_tools** — which MCP tools the scripts need access to

## Step 3 — Generate the Script Code

Scripts MUST follow this exact pattern (same as all existing skills):

```python
"""Brief description of what the script does.

Usage via run_skill_script:
  skill_name: dynamic-<name>
  script_path: scripts/<name>.py
  args: { "param1": "...", "param2": "..." }
"""

import json
import sys

# Parse args — ADK passes them as JSON in sys.argv[1]
args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

# Extract parameters
param1 = args.get("param1", "default")

# ── Your analysis logic here ──────────────────────────────
# Use only stdlib — no pip install at runtime.
# Available: json, sys, statistics, math, collections,
#            datetime, re, itertools, functools, pathlib
# For Pydantic validation: from pydantic import BaseModel, Field

result = {"status": "success", "data": {}}

# MUST print JSON to stdout — this is what the LLM sees
print(json.dumps(result, indent=2))
```

**Rules for generated scripts:**
- Only use Python stdlib + pydantic (already installed)
- Never import external packages that aren't in the venv
- Always print JSON to stdout as the final output
- Include a docstring with `Usage via run_skill_script` block
- Handle missing/invalid args gracefully with defaults
- Keep scripts focused — one script per analysis type

## Step 4 — Create and Register

Call `run_skill_script` to create the skill on disk:

```
run_skill_script(
  skill_name: "skill-builder",
  script_path: "scripts/create_and_register.py",
  args: {
    "name": "dynamic-anomaly-detection",
    "description": "Detect latency/error anomalies using z-score analysis on Prometheus metrics.",
    "instructions": "## When to Use\n\nRun detect.py with app name and namespace...",
    "scripts": {
      "detect.py": "<full python source code>"
    },
    "adk_tools": ["wcnp_query_prometheus"]
  }
)
```

## Step 5 — Load and Execute

After `create_and_register.py` succeeds:

1. `load_skill("dynamic-anomaly-detection")` — activates the skill
2. `run_skill_script("dynamic-anomaly-detection", "scripts/detect.py", {args})` — runs it
3. Present results to the user

## Step 6 — Iterate if Needed

If the script output isn't right, you can re-run `create_and_register.py`
with updated code — it overwrites the previous version.

## Constraints

- **Max 10 dynamic skills per session** — `create_and_register.py` enforces this
- **Skill names must start with `dynamic-`** — prevents overwriting static skills
- **Scripts run with 120s timeout** — keep analysis fast
- **No network calls in scripts** — data fetching is done by MCP tools before/after
- **No file system writes outside /tmp** — scripts should only read args and print JSON

## Example: Anomaly Detection Skill

Here is a complete example of creating an anomaly detection skill:

### Script: `detect.py`

```python
"""Detect latency anomalies using z-score analysis.

Usage via run_skill_script:
  skill_name: dynamic-anomaly-detection
  script_path: scripts/detect.py
  args: { "metrics": {"ts1": 100, "ts2": 105, ...}, "threshold": 2.0 }
"""
import json
import sys
import statistics

args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
metrics = args.get("metrics", {})
threshold = args.get("threshold", 2.0)

if len(metrics) < 3:
    print(json.dumps({"status": "error", "message": "Need at least 3 data points"}))
    sys.exit(0)

values = list(metrics.values())
mean = statistics.mean(values)
stdev = statistics.stdev(values) if len(values) > 1 else 0.0

anomalies = []
for ts, val in metrics.items():
    if stdev > 0:
        z = (val - mean) / stdev
        if abs(z) > threshold:
            anomalies.append({"timestamp": ts, "value": val, "z_score": round(z, 2)})

print(json.dumps({
    "status": "success",
    "mean": round(mean, 2),
    "stdev": round(stdev, 2),
    "threshold": threshold,
    "total_points": len(values),
    "anomaly_count": len(anomalies),
    "anomalies": anomalies,
}))
```
