"""SQL function registry for DataFusion / OpenObserve (RFC-06).

Ported from o2-ai-agent/src/tools/sql_function_registry.py.

Provides lookup into the pre-built JSON registry of DataFusion and
OpenObserve SQL functions.  Used by the agent to verify function
availability and get signatures during query building.

The registry is loaded lazily on first use and cached in-process.
File modifications are detected via mtime so a restart is not required
when the data file is updated.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default path: <repo-root>/data/sql_functions.json
_DEFAULT_REGISTRY_PATH = Path(__file__).parent.parent.parent / "data" / "sql_functions.json"

# Module-level cache
_registry_cache: dict[str, Any] | None = None
_registry_mtime: float = 0.0

# SQL keywords that look like function calls but are always valid syntax — skip validation.
_SKIP_NAMES: frozenset[str] = frozenset({
    "count", "sum", "avg", "min", "max",   # standard aggregates
    "coalesce", "nullif", "if", "ifnull",  # conditionals
    "cast", "try_cast", "extract",          # syntax forms
    "case",
})

# Regex for extracting function-name tokens from SQL when sqlglot is unavailable.
_FUNC_NAME_RE = re.compile(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\(')


def _load_registry(path: Path | None = None) -> dict[str, Any]:
    """Load or return cached SQL function registry.

    Args:
        path: Override the default registry path (mainly for testing).

    Returns:
        Dictionary of lowercase function_name → function metadata.
    """
    global _registry_cache, _registry_mtime

    registry_path = path or _DEFAULT_REGISTRY_PATH

    if not registry_path.exists():
        logger.warning("SQL function registry not found: %s", registry_path)
        return {}

    mtime = registry_path.stat().st_mtime
    if _registry_cache is not None and mtime == _registry_mtime:
        return _registry_cache

    try:
        raw = json.loads(registry_path.read_text(encoding="utf-8"))
        registry: dict[str, Any] = {}
        functions_raw = raw if isinstance(raw, list) else raw.get("functions", [])

        if isinstance(functions_raw, dict):
            for name, func in functions_raw.items():
                registry[name.lower()] = func
        else:
            for func in functions_raw:
                name = func.get("name", "").lower()
                if name:
                    registry[name] = func

        _registry_cache = registry
        _registry_mtime = mtime
        logger.info("SQL function registry loaded: %d functions", len(registry))
        return registry
    except (json.JSONDecodeError, OSError) as exc:
        logger.error("Failed to load SQL function registry: %s", exc)
        return {}


def preload_registry() -> None:
    """Eagerly load the registry into the module-level cache.

    Call once at server startup so the first check_sql_function
    request does not incur file I/O.
    """
    _load_registry()


def get_registry_functions() -> frozenset[str]:
    """Return the set of all registered SQL function names (lowercase)."""
    return frozenset(_load_registry().keys())


def validate_sql_functions(sql: str) -> str:
    """Scan all function calls in a SQL query against the registry.

    Extracts every function name from the SQL AST (using sqlglot when
    available, regex fallback otherwise) and checks each one against the
    DataFusion/O2 registry.  Returns a JSON report listing valid and
    invalid functions, with suggestions for unknowns.

    Args:
        sql: Raw SQL string to validate.

    Returns:
        JSON string with keys: all_valid (bool), valid (list), invalid (list).
        Each invalid entry has: name, suggestions (list[str]).
    """
    if not sql or not sql.strip():
        return json.dumps({"all_valid": False, "error": "sql is required."}, indent=2)

    # Load registry once — used for both the known-set check and suggestions.
    registry = _load_registry()
    known: frozenset[str] = frozenset(registry.keys())

    function_names: list[str] = []

    try:
        import sqlglot
        import sqlglot.expressions as exp

        _SYNTAX_TYPES = frozenset({
            exp.Case, exp.Cast, exp.TryCast, exp.Extract, exp.Exists,
        })

        for dialect in ("", "postgres"):
            try:
                trees = sqlglot.parse(sql, dialect=dialect or None)
                if all(t is not None for t in trees):
                    for tree in trees:
                        if tree is None:
                            continue
                        for node in tree.walk():
                            if isinstance(node, exp.Anonymous):
                                name = node.name.lower()
                                if name:
                                    function_names.append(name)
                            elif isinstance(node, exp.Func) and not any(
                                isinstance(node, st) for st in _SYNTAX_TYPES
                            ):
                                name = node.sql_name().lower()
                                if name:
                                    function_names.append(name)
                    break
            except Exception:
                continue
    except ImportError:
        function_names = [m.lower() for m in _FUNC_NAME_RE.findall(sql)]

    # De-duplicate while preserving order.
    seen: set[str] = set()
    unique: list[str] = []
    for name in function_names:
        if name not in seen:
            seen.add(name)
            unique.append(name)

    valid: list[str] = []
    invalid: list[dict[str, Any]] = []

    for name in unique:
        if name in _SKIP_NAMES or name in known:
            valid.append(name)
            continue

        suggestions: list[str] = []
        for reg_name, meta in registry.items():
            keywords: list[str] = meta.get("keywords", [])
            subcategory: str = meta.get("subcategory", "")
            if (
                name in reg_name
                or reg_name in name
                or any(name in kw or kw in name for kw in keywords)
                or name in subcategory
            ):
                suggestions.append(reg_name)
        invalid.append({"name": name, "suggestions": suggestions[:5]})

    return json.dumps(
        {
            "all_valid": len(invalid) == 0,
            "valid": valid,
            "invalid": invalid,
            "total_functions_checked": len(unique),
        },
        indent=2,
    )


def check_sql_function(function_name: str) -> str:
    """Check if a SQL function is available in DataFusion or OpenObserve.

    Looks up the function in the registry and returns its signature,
    description, and usage examples when found.

    Args:
        function_name: Name of the SQL function to look up (case-insensitive).

    Returns:
        JSON string with function details if found, or an error payload
        with similar function suggestions when not found.
    """
    if not function_name or not function_name.strip():
        return json.dumps({"found": False, "message": "function_name is required."}, indent=2)

    registry = _load_registry()
    name_lower = function_name.strip().lower()

    if name_lower in registry:
        func_data = registry[name_lower]
        # Registry uses "example" (singular string) — normalise to list.
        example_raw = func_data.get("example") or func_data.get("examples", "")
        examples: list[str] = (
            [example_raw] if isinstance(example_raw, str) and example_raw
            else (example_raw if isinstance(example_raw, list) else [])
        )
        return json.dumps(
            {
                "found": True,
                "name": func_data.get("name", function_name),
                "category": func_data.get("category", "unknown"),
                "subcategory": func_data.get("subcategory", ""),
                "source": func_data.get("source", ""),
                "description": func_data.get("description", ""),
                "syntax": func_data.get("syntax", ""),
                "examples": examples,
                "aliases": func_data.get("aliases", []),
                "return_type": func_data.get("return_type", ""),
            },
            indent=2,
        )

    # Partial / substring matches — name, keywords, subcategory.
    partial: list[str] = []
    for name, meta in registry.items():
        keywords: list[str] = meta.get("keywords", [])
        subcategory: str = meta.get("subcategory", "")
        if (
            name_lower in name
            or name in name_lower
            or any(name_lower in kw or kw in name_lower for kw in keywords)
            or name_lower in subcategory
        ):
            partial.append(name)

    if partial:
        return json.dumps(
            {
                "found": False,
                "message": f"Function '{function_name}' not found in registry.",
                "similar_functions": partial[:5],
            },
            indent=2,
        )

    return json.dumps(
        {
            "found": False,
            "message": (
                f"Function '{function_name}' is not available in DataFusion or OpenObserve. "
                "Use check_sql_function with a different name, or see data/sql_functions.json "
                "for the full list of supported functions."
            ),
        },
        indent=2,
    )
