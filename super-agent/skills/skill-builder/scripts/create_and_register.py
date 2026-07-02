"""Create a dynamic skill directory on disk for the auto-loader to pick up.

Usage via run_skill_script:
  skill_name: skill-builder
  script_path: scripts/create_and_register.py
  args: {
    "name":         "dynamic-anomaly-detection",
    "description":  "Detect latency anomalies using z-score analysis...",
    "instructions": "## When to Use\\n\\nRun detect.py with ...",
    "scripts":      {"detect.py": "<python source>"},
    "adk_tools":    ["wcnp_query_prometheus"]
  }

Writes the skill directory to /tmp/dynamic-skills/<name>/ so the
before_tool_callback auto-loader in __init__.py can register it into
SkillToolset._skills on the next tool invocation.
"""

import json
import os
import re
import sys
from pathlib import Path

# ── Parse args ────────────────────────────────────────────────────────────────
args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

name: str = args.get("name", "")
description: str = args.get("description", "")
instructions: str = args.get("instructions", "")
scripts: dict = args.get("scripts", {})
adk_tools: list = args.get("adk_tools", [])

# ── Validate ──────────────────────────────────────────────────────────────────
errors = []

if not name:
    errors.append("'name' is required")
elif not re.match(r"^dynamic-[a-z0-9]+(-[a-z0-9]+)*$", name):
    errors.append(
        f"'name' must be kebab-case starting with 'dynamic-', got: {name!r}"
    )

if not description:
    errors.append("'description' is required")

if not scripts:
    errors.append("'scripts' must contain at least one {filename: source_code} entry")

# Validate script filenames — no path traversal
for filename in scripts:
    if "/" in filename or "\\" in filename or ".." in filename:
        errors.append(f"Invalid script filename (no paths allowed): {filename!r}")
    if not filename.endswith(".py"):
        errors.append(f"Script must be a .py file: {filename!r}")

if errors:
    print(json.dumps({"status": "error", "errors": errors}))
    sys.exit(1)

# ── Cap: max 10 dynamic skills per session ────────────────────────────────────
base = Path("/tmp/dynamic-skills")
base.mkdir(parents=True, exist_ok=True)

existing = [d.name for d in base.iterdir() if d.is_dir()]
if name not in existing and len(existing) >= 10:
    print(json.dumps({
        "status": "error",
        "message": f"Dynamic skill limit reached (10). Existing: {existing}",
    }))
    sys.exit(1)

# ── Write skill directory ─────────────────────────────────────────────────────
skill_dir = base / name
skill_dir.mkdir(parents=True, exist_ok=True)

# Build SKILL.md
tools_yaml = ""
if adk_tools:
    tools_lines = "\n".join(f"    - {t}" for t in adk_tools)
    tools_yaml = f"\n  adk_additional_tools:\n{tools_lines}"

metadata_block = f"metadata:{tools_yaml}" if tools_yaml else ""

skill_md = f"""---
name: {name}
description: >
  {description}
{metadata_block}
---

{instructions}
"""

(skill_dir / "SKILL.md").write_text(skill_md.strip() + "\n")

# Write scripts
if scripts:
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(exist_ok=True)
    for filename, code in scripts.items():
        (scripts_dir / filename).write_text(code)

# ── Report success ────────────────────────────────────────────────────────────
print(json.dumps({
    "status": "created",
    "name": name,
    "skill_dir": str(skill_dir),
    "scripts": list(scripts.keys()),
    "message": (
        f"Skill '{name}' written to {skill_dir}. "
        f"It will be auto-loaded on the next tool call. "
        f"Use load_skill('{name}') to activate it, then "
        f"run_skill_script('{name}', 'scripts/<script>.py', {{args}}) to execute."
    ),
}))
