"""
OpenObserve Query Service.

All query/search operations against the O2 REST API:
  - SQL execution
  - Search around a timestamp
  - Unique field values
  - Stream listing
  - Stream schema / metadata
  - Trace retrieval

Designed to be called by MCP tool handlers in server.py.
Every public method returns a plain ``dict`` — never raises.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from re import compile as re_compile
from typing import Any

from src.config import get_settings
from src.http_client import O2ApiError, O2ConnectionError, O2HttpClient
from src.tools.sql_error_classifier import enrich_error_response

logger = logging.getLogger(__name__)

# Regex to extract identifier tokens from a user prompt (for schema pruning)
_IDENTIFIER_RE = re_compile(r"[a-zA-Z_][a-zA-Z0-9_]*")

# Hint returned to the agent whenever an O2 call fails with 401/403 so it
# knows to call pingfed_playwright_token and retry with a fresh bearer token.
_AUTH_EXPIRED_HINT = (
    "Call pingfed_playwright_token to get a fresh bearer token, "
    "then retry this tool with Authorization: Bearer <new_token>."
)


class QueryService:
    """
    Unified query service for OpenObserve.

    Args:
        client: Injected :class:`O2HttpClient`.  If ``None``, one is created
                from global settings.
    """

    def __init__(self, client: O2HttpClient | None = None) -> None:
        self._client = client or O2HttpClient()

    @property
    def org(self) -> str:
        return self._client.org

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _search_payload(
        self,
        sql: str,
        start_us: int,
        end_us: int,
        size: int,
        *,
        quick_mode: bool = False,
    ) -> dict[str, Any]:
        """
        Build the canonical OpenObserve _search POST body.

        Shape matches all repos in openobserve_plarform:
          {"query": {"sql": ..., "from": 0, "size": N, "track_total_hits": false,
                     "start_time": <us>, "end_time": <us>}}

        ``quick_mode=True`` is used for validation calls (1-row dry-run).
        """
        query: dict[str, Any] = {
            "sql": sql,
            "from": 0,
            "size": size,
            "track_total_hits": False,
            "start_time": start_us,
            "end_time": end_us,
        }
        if quick_mode:
            query["quick_mode"] = True
        return {"query": query}

    @property
    def _search_url(self) -> str:
        """Base _search endpoint with standard query params used by all repos."""
        return f"/{self.org}/_search?type=logs&use_cache=false"

    def _ok(self, **fields: Any) -> dict[str, Any]:
        return {"success": True, **fields}

    def _err(self, error: str, **fields: Any) -> dict[str, Any]:
        logger.error("QueryService error: %s", error)
        return {"success": False, "error": error, **fields}

    @staticmethod
    def _mark_auth_expired(result: dict[str, Any], status_code: int) -> None:
        """Mutate *result* to signal auth expiry when status is 401/403."""
        if status_code in (401, 403):
            result["auth_expired"] = True
            result["hint"] = _AUTH_EXPIRED_HINT

    def _handle_exc(self, exc: Exception, op: str, **ctx: Any) -> dict[str, Any]:
        if isinstance(exc, O2ApiError):
            msg = f"O2 API error ({exc.status_code}): {exc.message[:300]}"
            result = self._err(msg, **ctx)
            self._mark_auth_expired(result, exc.status_code)
            return result
        elif isinstance(exc, O2ConnectionError):
            msg = f"Connection error: {exc}"
        elif isinstance(exc, ValueError):
            msg = str(exc)
        else:
            msg = f"Unexpected error in {op}: {exc}"
        return self._err(msg, **ctx)

    # ------------------------------------------------------------------
    # SQL execution
    # ------------------------------------------------------------------

    async def execute_sql(
        self,
        sql: str,
        stream: str = "",
        time_range: str = "1h",
        limit: int = 1000,
        start_time: int | None = None,
        end_time: int | None = None,
        attempt: int = 1,
    ) -> dict[str, Any]:
        """
        Execute a SQL SELECT query.

        Args:
            sql:        SELECT statement to run.
            stream:     Stream name (for context / error messages).
            time_range: Relative window, e.g. ``"1h"``, ``"24h"``, ``"7d"``.
            limit:      Max rows to return.
            start_time: Absolute start in **microseconds** (overrides time_range).
            end_time:   Absolute end in **microseconds** (overrides time_range).
            attempt:    Retry attempt number (1-based). Included in error response
                        so the super-agent can track retry loop progress.

        Returns:
            Success: ``{"success": True, "hits": [...], "total": N, ...}``
            Failure: ``{"success": False, "error": "...", "sql_error_type": "...",
                        "correction_hint": "...", "retry_allowed": bool, ...}``
        """
        cfg = get_settings()
        t0 = time.perf_counter()
        try:
            if not sql.strip().upper().startswith("SELECT"):
                raise ValueError("Only SELECT queries are allowed.")

            # Clamp limit to [1, max_limit] so callers can't trigger runaway queries
            # by passing an arbitrarily large limit value.
            limit = max(1, min(limit, cfg.max_limit))

            if "LIMIT" not in sql.upper():
                sql = f"{sql.rstrip(';')} LIMIT {limit}"

            if start_time is not None and end_time is not None:
                start_us, end_us = start_time, end_time
            else:
                start_us, end_us = self._client.parse_time_range(time_range)

            payload = self._search_payload(sql, start_us, end_us, limit)
            data = await self._client.post(self._search_url, json=payload)

            hits = data.get("hits", [])
            return self._ok(
                hits=hits,
                total=data.get("total", len(hits)),
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
                sql=sql,
                stream=stream,
                time_range=time_range,
                attempt=attempt,
            )
        except Exception as exc:
            result = self._handle_exc(
                exc, "execute_sql",
                sql=sql, stream=stream,
                took_ms=round((time.perf_counter() - t0) * 1000, 1),
            )
            # Enrich with structured correction guidance for the super-agent retry loop
            return enrich_error_response(
                result,
                attempt=attempt,
                max_retries=cfg.max_retries,
            )

    # ------------------------------------------------------------------
    # Search around timestamp
    # ------------------------------------------------------------------

    async def search_around(
        self,
        stream: str,
        timestamp: int,
        size: int = 10,
    ) -> dict[str, Any]:
        """
        Fetch logs ±5 minutes around *timestamp* (microseconds).
        """
        try:
            params: dict[str, Any] = {"key": str(timestamp), "size": str(size)}
            data = await self._client.get(
                f"/{self.org}/{stream}/_around", params=params
            )
            return self._ok(data=data, stream=stream, timestamp=timestamp)
        except Exception as exc:
            return self._handle_exc(exc, "search_around", stream=stream, timestamp=timestamp)

    # ------------------------------------------------------------------
    # Field values
    # ------------------------------------------------------------------

    def _field_values_sql(
        self,
        stream: str,
        field: str,
        size: int,
        keyword: str,
        no_count: bool,
    ) -> str:
        """
        Build a safe GROUP BY / DISTINCT query for a single field.

        The keyword filter uses LIKE with percent-escaped literals — no string
        splicing of the WHERE clause into an already-built SQL fragment.
        """
        where = ""
        if keyword:
            # Escape LIKE metacharacters in the keyword value
            safe_kw = keyword.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
            where = f' WHERE "{field}" LIKE \'%{safe_kw}%\''

        if no_count:
            return f'SELECT DISTINCT "{field}" AS value FROM "{stream}"{where} LIMIT {size}'

        return (
            f'SELECT "{field}" AS value, COUNT(*) AS count '
            f'FROM "{stream}"{where} '
            f'GROUP BY "{field}" ORDER BY count DESC LIMIT {size}'
        )

    async def _fetch_field_values(
        self,
        stream: str,
        field: str,
        start_us: int,
        end_us: int,
        size: int,
        keyword: str,
        no_count: bool,
    ) -> dict[str, Any]:
        """Fetch values for a single field — called concurrently by get_field_values."""
        sql = self._field_values_sql(stream, field, size, keyword, no_count)
        payload = self._search_payload(sql, start_us, end_us, size)
        resp = await self._client.post(self._search_url, json=payload)

        hits = resp.get("hits", [])
        if no_count:
            values = [{"value": h["value"]} for h in hits if h.get("value") is not None]
        else:
            values = [
                {"value": h["value"], "count": h.get("count", 0)}
                for h in hits
                if h.get("value") is not None
            ]
        return {"field": field, "values": values, "unique_count": len(values)}

    async def get_field_values(
        self,
        stream: str,
        fields: list[str],
        time_range: str = "1h",
        size: int = 100,
        keyword: str = "",
        no_count: bool = False,
    ) -> dict[str, Any]:
        """
        Get unique values (with counts) for *fields* in parallel.

        All field queries are issued concurrently via asyncio.gather — no
        serial N-round-trips loop.  Uses SQL GROUP BY against /_search which
        works on any OpenObserve instance (native /_values endpoint avoided).

        Args:
            stream:    Stream name.
            fields:    List of field names to get values for.
            time_range: Relative window, e.g. ``"1h"``, ``"7d"``.
            size:      Max distinct values per field.
            keyword:   Optional substring filter applied to each field value.
            no_count:  If True use SELECT DISTINCT (no count column).

        Auth errors: If any per-field query returns 401/403, the top-level
        response will include ``auth_expired: true`` so the agent can refresh
        its token and retry the entire call.
        """
        try:
            start_us, end_us = self._client.parse_time_range(time_range)

            tasks = [
                self._fetch_field_values(stream, f, start_us, end_us, size, keyword, no_count)
                for f in fields
            ]
            raw_results = await asyncio.gather(*tasks, return_exceptions=True)

            results: list[dict[str, Any]] = []
            errors: list[str] = []
            auth_expired = False
            worst_auth_status: int = 0  # track highest auth-related status code seen

            for field, outcome in zip(fields, raw_results):
                if isinstance(outcome, Exception):
                    errors.append(f"{field}: {outcome}")
                    results.append({"field": field, "values": [], "unique_count": 0, "error": str(outcome)})
                    # Surface auth failures from any individual field query so the
                    # agent knows to call pingfed_playwright_token before retrying.
                    if isinstance(outcome, O2ApiError) and outcome.status_code in (401, 403):
                        auth_expired = True
                        if outcome.status_code > worst_auth_status:
                            worst_auth_status = outcome.status_code
                else:
                    results.append(outcome)

            response = self._ok(fields=results, stream=stream, time_range=time_range)
            if errors:
                response["partial_errors"] = errors
            if auth_expired:
                # Propagate auth_expired to the top level so the calling agent
                # detects it even when some fields succeeded (partial 401).
                self._mark_auth_expired(response, worst_auth_status)
            return response
        except Exception as exc:
            return self._handle_exc(exc, "get_field_values", stream=stream, fields=fields)

    # ------------------------------------------------------------------
    # Stream listing
    # ------------------------------------------------------------------

    async def list_streams(
        self,
        fetch_schema: bool = False,
        stream_type: str = "logs",
    ) -> dict[str, Any]:
        """List all streams in the organization."""
        try:
            params: dict[str, Any] = {
                "fetchSchema": "true" if fetch_schema else "false",
                "type": stream_type,
            }
            data = await self._client.get(f"/{self.org}/streams", params=params)
            streams = data.get("list", data.get("streams", []))
            return self._ok(streams=streams, total=len(streams), stream_type=stream_type)
        except Exception as exc:
            return self._handle_exc(exc, "list_streams")

    # ------------------------------------------------------------------
    # Stream schema / metadata
    # ------------------------------------------------------------------

    async def get_stream_schema(
        self,
        stream: str,
        stream_type: str = "logs",
        user_prompt: str = "",
        fields: str = "",
        full_schema: bool = False,
    ) -> dict[str, Any]:
        """
        Fetch and return a compact, token-efficient schema for *stream*.

        When the field count exceeds ``schema_field_threshold`` the schema
        is pruned to only include:
        - Fields mentioned in *user_prompt*
        - Essential fields (_timestamp, partition keys, FTS keys)

        The LLM can request specific fields via ``fields`` (comma-separated)
        or opt out of pruning with ``full_schema=True``.
        """
        try:
            params: dict[str, Any] = {"type": stream_type}
            data = await self._client.get(
                f"/{self.org}/streams/{stream}/schema", params=params
            )
            return _prune_schema(
                data,
                user_prompt=user_prompt,
                explicit_fields={f.strip() for f in fields.split(",") if f.strip()}
                if fields else None,
                full_schema=full_schema,
            )
        except Exception as exc:
            return self._handle_exc(exc, "get_stream_schema", stream=stream)

    # ------------------------------------------------------------------
    # Traces
    # ------------------------------------------------------------------

    async def get_latest_traces(
        self,
        stream: str,
        time_range: str = "1h",
        offset: int = 0,
        size: int = 25,
        filter_query: str = "",
    ) -> dict[str, Any]:
        """Fetch the latest distributed traces from *stream*."""
        try:
            start_us, end_us = self._client.parse_time_range(time_range)
            params: dict[str, Any] = {
                "start_time": str(start_us),
                "end_time": str(end_us),
                "from": str(offset),
                "size": str(size),
            }
            if filter_query:
                params["filter"] = filter_query

            data = await self._client.get(
                f"/{self.org}/{stream}/traces/latest", params=params
            )
            return self._ok(data=data, stream=stream, time_range=time_range)
        except Exception as exc:
            return self._handle_exc(exc, "get_latest_traces", stream=stream)

    # ------------------------------------------------------------------
    # SQL validation (lightweight — 1-second time window)
    # ------------------------------------------------------------------

    async def validate_sql(
        self,
        sql: str,
        stream: str = "",
    ) -> dict[str, Any]:
        """
        Validate *sql* against the cluster with a 1-second window.
        Returns ``{"valid": True/False, ...}``.
        """
        cfg = get_settings()
        if not cfg.enable_sql_validation:
            return {"valid": True, "message": "SQL validation disabled."}

        now_us = self._client.now_us()
        start_us = now_us - 1_000_000

        # quick_mode=True + size=1 keeps the validation cheap (o2-ai-agent pattern)
        payload = self._search_payload(sql, start_us, now_us, size=1, quick_mode=True)
        t0 = time.perf_counter()
        try:
            data = await self._client.post(self._search_url, json=payload)
            return {
                "valid": True,
                "message": "SQL query is valid.",
                "took_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
        except O2ApiError as exc:
            result: dict[str, Any] = {
                "valid": False,
                "error": exc.message[:500],
                "status_code": exc.status_code,
                "took_ms": round((time.perf_counter() - t0) * 1000, 1),
            }
            self._mark_auth_expired(result, exc.status_code)
            return result
        except Exception as exc:
            return {"valid": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # VRL validation
    # ------------------------------------------------------------------

    async def validate_vrl(
        self,
        vrl: str,
        events: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Validate *vrl* script against sample *events*.
        Returns ``{"valid": True/False, ...}``.
        """
        cfg = get_settings()
        if not cfg.enable_vrl_validation:
            return {"valid": True, "message": "VRL validation disabled."}

        sample_events = events or ['{"message": "test log line", "level": "info"}']
        payload = {"vrl": vrl, "events": sample_events}

        try:
            data = await self._client.post(f"/{self.org}/_vrl", json=payload)
            return {"valid": True, "message": "VRL script is valid.", "output": data}
        except O2ApiError as exc:
            result: dict[str, Any] = {
                "valid": False,
                "error": exc.message[:500],
                "status_code": exc.status_code,
            }
            self._mark_auth_expired(result, exc.status_code)
            return result
        except Exception as exc:
            return {"valid": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Schema pruning helpers (ported from o2-ai-agent/src/tools/stream_schema.py)
# ---------------------------------------------------------------------------


def _compact_fields(fields: list[dict[str, str]]) -> dict[str, list[str]]:
    """Group field names by type: {"Utf8": ["f1", "f2"], "Int64": ["f3"]}."""
    by_type: dict[str, list[str]] = defaultdict(list)
    for f in fields:
        ft = f.get("type", "Unknown")
        fn = f.get("name", "")
        if fn:
            by_type[ft].append(fn)
    return {t: sorted(names) for t, names in sorted(by_type.items())}


def _enabled_partition_keys(settings_data: dict[str, Any]) -> list[str]:
    """Return field names for all enabled partition keys (single pass)."""
    return [
        v["field"]
        for v in settings_data.get("partition_keys", {}).values()
        if v.get("field") and not v.get("disabled")
    ]


def _essential_fields(settings_data: dict[str, Any]) -> set[str]:
    """_timestamp + enabled partition keys + FTS keys."""
    essential: set[str] = {"_timestamp"}
    essential.update(_enabled_partition_keys(settings_data))
    essential.update(settings_data.get("full_text_search_keys", []))
    return essential


def _compact_metadata(settings_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "partition_keys": _enabled_partition_keys(settings_data),
        "full_text_search_keys": settings_data.get("full_text_search_keys", []),
        "bloom_filter_fields": settings_data.get("bloom_filter_fields", []),
        "index_all_values": settings_data.get("index_all_values", False),
    }


def _extract_prompt_fields(prompt: str, schema_names: set[str]) -> set[str]:
    lower_map = {n.lower(): n for n in schema_names}
    return {
        lower_map[tok.lower()]
        for tok in _IDENTIFIER_RE.findall(prompt)
        if tok.lower() in lower_map
    }


def _prune_schema(
    data: dict[str, Any],
    user_prompt: str = "",
    explicit_fields: set[str] | None = None,
    full_schema: bool = False,
) -> dict[str, Any]:
    """
    Return a compact, pruned schema dict.

    - full_schema=True  → return all fields in compact grouped format
    - explicit_fields   → return only those + essential fields
    - user_prompt       → extract mentioned field names, return those + essential
    - fallback          → return full schema
    """
    cfg = get_settings()
    settings_data: dict[str, Any] = data.get("settings", {})
    all_fields: list[dict[str, str]] = data.get("uds_schema", data.get("schema", []))
    total = len(all_fields)
    metadata = _compact_metadata(settings_data)
    stream_name = data.get("name", "")

    def _build(filtered: list[dict[str, str]], hint: bool = False) -> dict[str, Any]:
        result: dict[str, Any] = {
            "name": stream_name,
            "stream_type": data.get("stream_type", "logs"),
            "fields": _compact_fields(filtered),
            "settings": metadata,
            "total_fields": total,
            "returned_fields": len(filtered),
        }
        remaining = total - len(filtered)
        if hint and remaining > 0:
            result["hint"] = (
                f"{remaining} additional fields available. "
                "Call get_stream_schema with fields='f1,f2' or full_schema=true."
            )
        return result

    if full_schema or (not explicit_fields and total <= cfg.schema_field_threshold):
        return _build(all_fields)

    schema_names = {f.get("name", "") for f in all_fields} - {""}
    essential = _essential_fields(settings_data)

    if explicit_fields is not None:
        wanted = explicit_fields | essential
        return _build([f for f in all_fields if f.get("name") in wanted], hint=True)

    # Prompt-based pruning
    matched = _extract_prompt_fields(user_prompt, schema_names) if user_prompt else set()
    wanted = matched | essential

    if not matched:
        # No prompt matches — return full schema (no LLM available here)
        return _build(all_fields)

    return _build([f for f in all_fields if f.get("name") in wanted], hint=True)
