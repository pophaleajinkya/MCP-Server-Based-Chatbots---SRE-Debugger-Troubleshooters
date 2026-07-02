"""Validate a dynamic skill directory before the LLM tries to use it.

Usage via run_skill_script:
  skill_name: skill-builder
  script_path: scripts/validate_skill.py
  args: { "name": "dynamic-anomaly-detection" }

Checks that /tmp/dynamic-skills/<name>/ has a valid SKILL.md with correct
frontmatter and that all scripts parse without syntax errors.
"""

import ast
import json
import re
import sys
from pathlib import Path

args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
name = args.get("name", "")

if not name:
    print(json.dumps({"status": "error", "message": "'name' is required"}))
    sys.exit(1)

skill_dir = Path("/tmp/dynamic-skills") / name
problems: list[str] = []

# ── Directory exists? ─────────────────────────────────────────────────────────
if not skill_dir.is_dir():
    print(json.dumps({
        "status": "error",
        "message": f"Skill directory not found: {skill_dir}",
    }))
    sys.exit(1)

# ── SKILL.md exists and has frontmatter? ──────────────────────────────────────
skill_md = skill_dir / "SKILL.md"
if not skill_md.is_file():
    problems.append("SKILL.md not found")
else:
    content = skill_md.read_text()
    if not content.startswith("---"):
        problems.append("SKILL.md missing YAML frontmatter (must start with ---)")
    else:
        parts = content.split("---", 2)
        if len(parts) < 3:
            problems.append("SKILL.md frontmatter not closed (missing second ---)")
        else:
            fm = parts[1].strip()
            if "name:" not in fm:
                problems.append("Frontmatter missing 'name' field")
            if "description:" not in fm:
                problems.append("Frontmatter missing 'description' field")
            # Check name matches directory
            for line in fm.splitlines():
                if line.strip().startswith("name:"):
                    fm_name = line.split(":", 1)[1].strip()
                    if fm_name != name:
                        problems.append(
                            f"Frontmatter name '{fm_name}' != directory name '{name}'"
                        )
                    break

# ── Scripts parse? ────────────────────────────────────────────────────────────
scripts_dir = skill_dir / "scripts"
scripts_checked = []
if scripts_dir.is_dir():
    for py_file in sorted(scripts_dir.glob("*.py")):
        try:
            ast.parse(py_file.read_text())
            scripts_checked.append({"file": py_file.name, "valid": True})
        except SyntaxError as e:
            scripts_checked.append({
                "file": py_file.name,
                "valid": False,
                "error": f"Line {e.lineno}: {e.msg}",
            })
            problems.append(f"Script {py_file.name} has syntax error: line {e.lineno}: {e.msg}")
else:
    problems.append("No scripts/ directory found")

# ── Report ────────────────────────────────────────────────────────────────────
if problems:
    print(json.dumps({
        "status": "invalid",
        "name": name,
        "problems": problems,
        "scripts": scripts_checked,
    }))
else:
    print(json.dumps({
        "status": "valid",
        "name": name,
        "skill_dir": str(skill_dir),
        "scripts": scripts_checked,
        "message": f"Skill '{name}' is structurally valid and ready to load.",
    }))
