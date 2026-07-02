# Skill Writing Guide

Reference for the LLM when generating dynamic SKILL.md files at runtime.

## Directory Structure

```
<skill-name>/
├── SKILL.md       (required)  — YAML frontmatter + markdown instructions
└── scripts/       (optional)  — Python scripts executable via run_skill_script
```

## SKILL.md Format

```yaml
---
name: kebab-case-name        # must match directory name
description: >               # triggers skill discovery
  One sentence describing what the skill does and when to use it.
metadata:
  adk_additional_tools:      # MCP tools the skill's scripts need
    - tool_name_1
    - tool_name_2
---

# Skill Title

## When to Use
Describe the triggering conditions.

## Steps
1. First step
2. Second step

## Script Reference
- `scripts/analyze.py` — what it does, expected args
```

## Frontmatter Rules

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | Lowercase kebab-case, max 64 chars, must match dir name |
| `description` | Yes | Used for skill discovery — include trigger phrases |
| `metadata.adk_additional_tools` | No | List of MCP tool names the skill uses |

## Script Pattern

Every script MUST follow this structure:

```python
"""Brief description.

Usage via run_skill_script:
  skill_name: <skill-name>
  script_path: scripts/<file>.py
  args: { "key": "value" }
"""
import json
import sys

args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}

# ... analysis logic using only stdlib + pydantic ...

print(json.dumps({"status": "success", "data": result}))
```

## Available Standard Library Modules

Scripts can use: `json`, `sys`, `statistics`, `math`, `collections`,
`datetime`, `re`, `itertools`, `functools`, `pathlib`, `ast`, `csv`,
`io`, `os.path`, `textwrap`, `decimal`, `fractions`.

Plus `pydantic` (BaseModel, Field, ValidationError) which is in the venv.

## Available MCP Tools (for adk_additional_tools)

### WCNP / Kubernetes
- `wcnp_check_app_health` — full 21-check health assessment
- `wcnp_analyze` — targeted checks (cpu, memory, istio, etc.)
- `wcnp_query_prometheus` — raw PromQL queries
- `wcnp_chart` — render time-series charts

### Cassandra
- `cassandra_check_cluster_health` — cluster-level health
- `cassandra_query_prometheus` — Cassandra PromQL queries

### Cosmos DB
- `cosmos_check_account_health` — account-level health
- `cosmos_query_prometheus` — Cosmos PromQL queries

### SQL Server
- `sqlserver_check_database_health` — database-level health
- `sqlserver_query_prometheus` — SQL Server PromQL queries
