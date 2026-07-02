"""
O2 Rules Engine — loads OpenObserve-specific SQL/VRL rules from rules.json.

The rules are returned as formatted text suitable for injecting into an
LLM prompt.  No LLM is required to use this tool.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default location — can be overridden via O2_RULES_PATH env var
_DEFAULT_RULES_PATH = Path(__file__).parent.parent.parent / "data" / "rules.json"


class RulesEngine:
    """
    Hot-reloading rules engine for O2 SQL/VRL constraints.

    Reads ``rules.json`` on first access and reloads automatically
    whenever the file is modified.
    """

    def __init__(self, rules_path: str | Path | None = None) -> None:
        # Determine the source of the path and sanitize if from environment
        if rules_path:
            # Explicitly provided path - use as-is (resolved for consistency)
            self._path = Path(rules_path).resolve()
        else:
            # Check environment variable and sanitize it
            env_path = os.environ.get("O2_RULES_PATH", "")
            if env_path:
                self._path = self._sanitize_env_path(env_path)
            else:
                self._path = Path(_DEFAULT_RULES_PATH).resolve()
        
        self._rules: dict[str, Any] = {}
        self._mtime: float = 0.0
        self._load()

    def _sanitize_env_path(self, env_path: str) -> Path:
        """
        Hardened: Validate env_path as a string BEFORE using it in any Path operation.
        """
        try:
            # Get the project root (parent of parent of parent of this file)
            project_root = Path(__file__).parent.parent.parent.resolve()

            # Reject empty, null bytes, or suspicious input
            if not env_path or '\x00' in env_path or env_path.startswith(('/', '\\')) or '..' in env_path.split(os.sep):
                logger.warning(
                    "O2_RULES_PATH is empty or contains suspicious patterns. Using default rules path for security."
                )
                return Path(_DEFAULT_RULES_PATH).resolve()

            # Only allow safe characters (alphanumeric, dash, underscore, dot, slash)
            import re
            if not re.match(r'^[\w\-.\\/]+$', env_path):
                logger.warning(
                    "O2_RULES_PATH contains unsafe characters. Using default rules path for security."
                )
                return Path(_DEFAULT_RULES_PATH).resolve()

            # Now safe to use in Path
            candidate = (project_root / env_path).resolve()
            try:
                candidate.relative_to(project_root)
            except ValueError:
                logger.warning(
                    "O2_RULES_PATH points outside project directory after resolution: %s. Using default rules path for security.",
                    candidate
                )
                return Path(_DEFAULT_RULES_PATH).resolve()

            logger.info("Using rules path from O2_RULES_PATH: %s", candidate)
            return candidate
        except Exception as exc:
            logger.error(
                "Invalid O2_RULES_PATH '%s': %s. Using default rules path.",
                env_path,
                exc
            )
            return Path(_DEFAULT_RULES_PATH).resolve()
    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            logger.warning("Rules file not found: %s", self._path)
            self._rules = {}
            return
        try:
            mtime = self._path.stat().st_mtime
            if mtime == self._mtime:
                return
            self._rules = json.loads(self._path.read_text(encoding="utf-8"))
            self._mtime = mtime
            logger.info("Rules loaded from %s", self._path)
        except Exception as exc:
            logger.error("Failed to load rules: %s", exc)
            self._rules = {}

    def _maybe_reload(self) -> None:
        try:
            if self._path.exists() and self._path.stat().st_mtime != self._mtime:
                self._load()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    INTENT_CATEGORY_MAP: dict[str, str] = {
        "sql": "sql",
        "query_builder": "query_builder",
        "query_optimization": "query_optimization",
        "vrl": "vrl",
        "vrl_builder": "vrl_builder",
        "vrl_optimization": "vrl_optimization",
        "log_analysis": "log_analysis",
        "general": "",
    }

    def get_rules(self, intent: str = "sql") -> dict[str, list[str]]:
        """
        Return rules for *intent*.

        Always includes ``global`` rules.  Category rules are added when
        there is a known mapping for *intent*.
        """
        self._maybe_reload()
        global_rules: list[str] = self._rules.get("global", [])
        category = self.INTENT_CATEGORY_MAP.get(intent.lower(), intent.lower())
        category_rules: list[str] = self._rules.get(category, []) if category else []
        return {
            "global": global_rules,
            category: category_rules,
        }

    def format_rules(self, intent: str = "sql") -> str:
        """
        Return rules as a numbered text block for LLM prompt injection.

        Example output::

            Rules for SQL queries:
            1. SQL queries MUST NOT include _timestamp range filters...
            2. Use count(_timestamp) instead of count(*)...
        """
        rules = self.get_rules(intent)
        all_rules: list[str] = []
        for rule_list in rules.values():
            all_rules.extend(rule_list)

        if not all_rules:
            return "No specific rules."

        lines = [f"Rules for {intent} queries:"]
        for i, rule in enumerate(all_rules, 1):
            lines.append(f"{i}. {rule}")
        return "\n".join(lines)

    def all_categories(self) -> list[str]:
        """Return all rule category names."""
        self._maybe_reload()
        return list(self._rules.keys())


# Singleton instance
_engine: RulesEngine | None = None


def get_rules_engine() -> RulesEngine:
    global _engine
    if _engine is None:
        _engine = RulesEngine()
    return _engine