"""MCP Resources — static documentation served as o2:// URIs.

Resources:
  o2://agent-guide       Full agent guide: workflow, SQL translation, log analysis
  o2://datafusion-sql    Full Apache DataFusion SQL reference (223 functions)
  o2://o2-functions      OpenObserve-specific UDFs + UDAFs
  o2://o2-guide          OpenObserve SQL philosophy, field names, VRL patterns
  o2://retry-guide       SQL self-correction retry loop protocol (dynamic: uses max_retries)
"""
from __future__ import annotations

from fastmcp.server.providers import LocalProvider

from src.config import get_settings
from src.providers._shared import (
    AGENT_GUIDE,
    DATAFUSION_SQL_DOC,
    O2_FUNCTIONS_DOC,
    O2_GUIDE_DOC,
    RETRY_GUIDE,
    read_doc,
)

provider = LocalProvider()


@provider.resource("o2://agent-guide")
def agent_guide() -> str:
    """
    OpenObserve agent guide: full workflow, SQL translation rules, log analysis
    patterns, auth refresh, and tool selection.

    Read this resource at session start to understand how to translate user
    questions into OpenObserve SQL queries and interpret results.
    """
    return read_doc(AGENT_GUIDE, "Agent guide not found. See data/resources/AGENT.md.")


@provider.resource("o2://datafusion-sql")
def datafusion_sql_resource() -> str:
    """
    Full Apache DataFusion SQL reference — 223 functions with syntax and examples.

    Read this when you need to look up:
    - Exact DataFusion function syntax (date_trunc, date_bin, array_*, window fns)
    - Whether a function is available in DataFusion
    - Quick reference patterns for time bucketing, JSON, aggregation, window analysis

    Key sections: Quick Reference, Aggregate Functions, Scalar Functions
    (array, datetime, string, math), Window Functions, Subqueries.
    """
    return read_doc(DATAFUSION_SQL_DOC, "datafusion_sql.md not found in data/resources/.")


@provider.resource("o2://o2-functions")
def o2_functions_resource() -> str:
    """
    OpenObserve-specific UDFs and UDAFs — functions beyond standard DataFusion.

    Read this when you need to look up:
    - Full-text search: match_all, fuzzy_match, fuzzy_match_all, re_match
    - Array helpers: cast_to_arr, arr_descending, arrcount, arrjoin, arrsort, arrzip
    - JSON path: spath(field, 'nested.key')
    - Time helpers: cast_to_timestamp, time_range, histogram
    - Percentile: percentile_cont (O2 version replaces DataFusion's)
    - Aggregate: summary_percentile (for pre-aggregated data)

    These functions are ONLY available in OpenObserve — not in standard DataFusion.
    """
    return read_doc(O2_FUNCTIONS_DOC, "openobserve_functions.md not found in data/resources/.")


@provider.resource("o2://o2-guide")
def o2_guide_resource() -> str:
    """
    OpenObserve SQL guide — dialect rules, standard field names, observability patterns.

    Read this when you need to understand:
    - OpenObserve SQL fundamentals and dialect characteristics
    - Standard field names (event_kubernetes_*, event_cluster_id, severity, etc.)
    - When to use FTS (match_all) vs regex (re_match) vs fuzzy (fuzzy_match)
    - Observability frameworks: RED method, USE method, SLIs/SLOs
    - VRL script templates for log parsing and enrichment
    """
    return read_doc(O2_GUIDE_DOC, "openobserve.md not found in data/resources/.")


@provider.resource("o2://retry-guide")
def retry_guide() -> str:
    """
    Super-agent retry loop protocol for self-correcting SQL queries.

    Read this once at session start. It defines the full retry loop
    the super-agent implements when execute_sql fails.
    """
    cfg = get_settings()
    template = read_doc(
        RETRY_GUIDE,
        "Retry guide not found. See data/prompts/retry_guide.md.",
    )
    return template.format(max_retries=cfg.max_retries)
