"""POST /mcp/validate — on-demand MCP server validation.

Connects to any remote MCP server, lists its Tools, Resources, and Prompts,
and runs schema checks on every tool so teams can validate before onboarding.

Request body:
  {
    "url": "https://my-mcp-server/mcp",
    "transport": "streamable_http",   // or "sse" (default: streamable_http)
    "headers": {"Authorization": "Bearer ..."}
  }

Response: full MCPValidateResponse with per-tool status + issues and
a top-level summary across all three primitive types.
"""

import json
import logging
import re
from typing import Any, Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter(tags=["mcp"])

# verify=False is intentional: internal Walmart MCP servers use self-signed certs
_HTTP_CLIENT_KWARGS: dict = {"verify": False, "follow_redirects": True}  # noqa: S501

# ── Request / Response models ──────────────────────────────────────────────────

class MCPValidateRequest(BaseModel):
    url: str = Field(..., description="Full URL of the MCP server endpoint.")
    transport: Literal["streamable_http", "sse"] = Field(
        "streamable_http",
        description="MCP transport type. Use 'streamable_http' for modern servers, 'sse' for legacy.",
    )
    headers: dict[str, str] = Field(
        default_factory=dict,
        description="Additional HTTP headers to send (e.g. Authorization).",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "url": "https://my-mcp-server.example.com/mcp",
                "transport": "streamable_http",
                "headers": {"Authorization": "Bearer my-token"},
            }
        }
    }


class ToolValidation(BaseModel):
    index: int
    name: str
    description: str
    status: Literal["ok", "warning", "error"]
    issues: list[str]
    input_schema: dict[str, Any]


class ResourceInfo(BaseModel):
    uri: str
    name: str
    description: str
    mime_type: str
    status: Literal["ok", "warning", "error"]
    issues: list[str]


class PromptInfo(BaseModel):
    name: str
    description: str
    arguments: list[dict[str, Any]]
    status: Literal["ok", "warning", "error"]
    issues: list[str]


class ValidationSummary(BaseModel):
    tools_total: int
    tools_ok: int
    tools_warnings: int
    tools_errors: int
    resources_total: int
    prompts_total: int
    overall_status: Literal["ok", "warning", "error"]


class MCPValidateResponse(BaseModel):
    server_name: str
    server_version: str
    tools: list[ToolValidation]
    resources: list[ResourceInfo]
    prompts: list[PromptInfo]
    summary: ValidationSummary


# ── Lightweight MCP validation client ─────────────────────────────────────────

_MCP_HDRS = {
    "Content-Type": "application/json",
    "Accept":       "application/json, text/event-stream",
}

_FORBIDDEN_SCHEMA_KEYS = {"definitions"}          # replaced by $defs in draft 2020-12
_DEPRECATED_SCHEMA_KEYS = {"id", "$schema"}       # can confuse validators

# ── ADK template-safety check ──────────────────────────────────────────────────
# Google ADK's instruction engine substitutes {var} with session state on every
# request.  If a guide resource or prompt description contains {X} where X is a
# valid Python identifier (and NOT already marked optional with {X?}), ADK raises
# KeyError at runtime and the agent refuses every user message.
_ADK_TEMPLATE_RE = re.compile(r"\{+[^{}]*\}+")
_ADK_STATE_PREFIXES = {"app:", "user:", "temp:"}


def _is_valid_adk_state_name(var_name: str) -> bool:
    """Return True if var_name would be treated as a session-state lookup by ADK."""
    parts = var_name.split(":")
    if len(parts) == 1:
        return var_name.isidentifier()
    if len(parts) == 2 and (parts[0] + ":") in _ADK_STATE_PREFIXES:
        return parts[1].isidentifier()
    return False


def _find_adk_unsafe_vars(text: str) -> list[str]:
    """Return list of variable names that would crash ADK's inject_session_state.

    ADK regex: r'{+[^{}]*}+'  — matches {X}, {{X}}, {X?}, {a, b}, etc.
    A match crashes ADK when:
      - stripped inner text is a valid Python identifier (or prefix:identifier)
      - AND it does NOT already end with '?' (which makes it optional/safe)
    """
    unsafe: list[str] = []
    for m in _ADK_TEMPLATE_RE.finditer(text):
        inner = m.group().lstrip("{").rstrip("}").strip()
        if inner.endswith("?"):
            continue                          # already optional — safe
        if _is_valid_adk_state_name(inner):
            unsafe.append(inner)
    return unsafe


def _parse_response(r: httpx.Response) -> dict:
    """Parse either a plain JSON or text/event-stream response."""
    ct = r.headers.get("content-type", "")
    if "text/event-stream" in ct:
        for line in r.text.splitlines():
            if line.startswith("data:"):
                return json.loads(line[5:].strip())
        return {}
    return r.json()


async def _rpc(
    client: httpx.AsyncClient,
    url: str,
    method: str,
    params: dict,
    req_id: int,
    session_id: str | None = None,
) -> dict:
    hdrs = dict(_MCP_HDRS)
    if session_id:
        hdrs["Mcp-Session-Id"] = session_id
    payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
    r = await client.post(url, json=payload, headers=hdrs, timeout=15)
    r.raise_for_status()
    return _parse_response(r)


async def _connect(client: httpx.AsyncClient, url: str) -> tuple[str, str, str]:
    """Initialize MCP session. Returns (session_id, server_name, server_version)."""
    r = await client.post(url, json={
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities":    {},
            "clientInfo":      {"name": "health-agent-validator", "version": "1.0"},
        },
    }, headers=_MCP_HDRS, timeout=10)
    r.raise_for_status()
    resp = _parse_response(r)

    result = resp.get("result", {})
    session_id = (
        r.headers.get("mcp-session-id") or
        r.headers.get("Mcp-Session-Id") or
        result.get("sessionId", "")
    )
    sinfo = result.get("serverInfo", {})

    # Send initialized notification (best-effort)
    try:
        hdrs = dict(_MCP_HDRS)
        if session_id:
            hdrs["Mcp-Session-Id"] = session_id
        await client.post(url, json={
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {}
        }, headers=hdrs, timeout=5)
    except Exception:
        pass

    return session_id, sinfo.get("name", "unknown"), sinfo.get("version", "unknown")


# ── Per-type validators ────────────────────────────────────────────────────────

def _validate_tool(idx: int, tool: dict) -> ToolValidation:
    name        = tool.get("name", f"<unnamed-{idx}>")
    description = tool.get("description", "")
    raw_schema  = tool.get("inputSchema") or tool.get("input_schema") or {}
    issues: list[str] = []

    # 1. input_schema must be a dict
    if not isinstance(raw_schema, dict):
        issues.append(f"input_schema is {type(raw_schema).__name__!r}, expected dict")
        return ToolValidation(
            index=idx, name=name, description=description,
            status="error", issues=issues, input_schema={},
        )

    # 2. Must be JSON-serialisable
    try:
        json.dumps(raw_schema)
    except (TypeError, ValueError) as exc:
        issues.append(f"input_schema is not JSON-serialisable: {exc}")

    # 3. Top-level type must be "object" (Anthropic requirement)
    schema_type = raw_schema.get("type")
    if not schema_type:
        issues.append("input_schema missing top-level 'type' field — Anthropic requires type='object'")
    elif schema_type != "object":
        issues.append(
            f"input_schema top-level type={schema_type!r} — Anthropic requires type='object'"
        )

    # 4. Forbidden legacy keys (invalid in JSON Schema draft 2020-12)
    bad_keys = _FORBIDDEN_SCHEMA_KEYS & raw_schema.keys()
    if bad_keys:
        issues.append(
            f"input_schema uses legacy key(s) {sorted(bad_keys)} — "
            "invalid in JSON Schema draft 2020-12; use '$defs' instead of 'definitions'"
        )

    # 5. Deprecated keys that can confuse Anthropic's validator
    dep_keys = _DEPRECATED_SCHEMA_KEYS & raw_schema.keys()
    if dep_keys:
        issues.append(
            f"input_schema contains key(s) {sorted(dep_keys)} that may cause validation issues"
        )

    # 6. Walk nested property schemas for the same checks
    for prop_name, prop_schema in raw_schema.get("properties", {}).items():
        if not isinstance(prop_schema, dict):
            continue
        nested_bad = _FORBIDDEN_SCHEMA_KEYS & prop_schema.keys()
        if nested_bad:
            issues.append(
                f"property '{prop_name}' uses legacy key(s) {sorted(nested_bad)}"
            )

    if issues:
        # Any issue that mentions a hard Anthropic constraint is an error, rest are warnings
        hard = any(
            k in " ".join(issues)
            for k in ("not JSON-serialisable", "missing top-level", "legacy key", "type=")
        )
        status: Literal["ok", "warning", "error"] = "error" if hard else "warning"
    else:
        status = "ok"

    return ToolValidation(
        index=idx, name=name, description=description,
        status=status, issues=issues, input_schema=raw_schema,
    )


def _validate_resource(resource: dict, content: str | None = None) -> ResourceInfo:
    issues: list[str] = []
    uri         = resource.get("uri", "")
    name        = resource.get("name", "")
    description = resource.get("description", "")
    mime_type   = resource.get("mimeType", "")

    if not uri:
        issues.append("resource is missing required 'uri' field")
    if not name:
        issues.append("resource is missing required 'name' field")

    # ADK template-safety: guide resources are injected into the agent instruction.
    # Any {identifier} ADK cannot resolve in session state raises KeyError at runtime.
    if content:
        unsafe_vars = _find_adk_unsafe_vars(content)
        for var in unsafe_vars:
            issues.append(
                f"ADK template conflict: `{{{var}}}` in resource content will crash the agent "
                f"— ADK tries to substitute it as session state variable `{var}` "
                f"but it is never set. Use `<{var}>` or `{{{var}?}}` instead."
            )

    status: Literal["ok", "warning", "error"]
    if any("ADK template conflict" in i or "missing required" in i for i in issues):
        status = "error"
    elif issues:
        status = "warning"
    else:
        status = "ok"

    return ResourceInfo(
        uri=uri, name=name, description=description, mime_type=mime_type,
        status=status,
        issues=issues,
    )


def _validate_prompt(prompt: dict) -> PromptInfo:
    issues: list[str] = []
    name        = prompt.get("name", "")
    description = prompt.get("description", "")
    arguments   = prompt.get("arguments", [])

    if not name:
        issues.append("prompt is missing required 'name' field")
    if not isinstance(arguments, list):
        issues.append(f"'arguments' should be a list, got {type(arguments).__name__!r}")
        arguments = []

    # ADK template-safety: check description for bare {identifier} patterns.
    # Prompt descriptions are visible in the agent's tool list — if they contain
    # {X} ADK will try to substitute it as a session variable and crash.
    if description:
        unsafe_vars = _find_adk_unsafe_vars(description)
        for var in unsafe_vars:
            issues.append(
                f"ADK template conflict: `{{{var}}}` in prompt description will crash the agent "
                f"— ADK treats it as session state variable `{var}`. "
                f"Use `<{var}>` or `{{{var}?}}` instead."
            )

    status: Literal["ok", "warning", "error"]
    if issues:
        status = "error"
    else:
        status = "ok"

    return PromptInfo(
        name=name, description=description, arguments=arguments,
        status=status,
        issues=issues,
    )


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post(
    "/mcp/validate",
    response_model=MCPValidateResponse,
    summary="Validate all tools, resources, and prompts on a remote MCP server",
    description=(
        "Connects to the specified MCP server, lists every Tool, Resource, and Prompt, "
        "and runs schema checks on each one. Use this before onboarding a new MCP server "
        "to catch invalid JSON schemas (draft 2020-12), legacy keys, and missing fields "
        "that would cause Anthropic to reject the entire tool list at runtime."
    ),
)
async def validate_mcp_server(body: MCPValidateRequest) -> MCPValidateResponse:
    log.info("MCP validation requested for url=%r transport=%r", body.url, body.transport)

    all_hdrs = {**_MCP_HDRS, **body.headers}

    async with httpx.AsyncClient(
        **_HTTP_CLIENT_KWARGS,
        headers=all_hdrs,
        timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=5.0),
    ) as client:
        # ── Connect ───────────────────────────────────────────────────────────
        session_id, server_name, server_version = await _connect(client, body.url)
        log.info("MCP validate: connected to %r v%s (session=%r)", server_name, server_version, session_id)

        # ── List Tools ────────────────────────────────────────────────────────
        tools: list[ToolValidation] = []
        try:
            resp     = await _rpc(client, body.url, "tools/list", {}, req_id=1, session_id=session_id)
            raw_tools = resp.get("result", {}).get("tools", [])
            log.info("MCP validate: found %d tool(s)", len(raw_tools))
            for idx, t in enumerate(raw_tools):
                tv = _validate_tool(idx, t)
                tools.append(tv)
                if tv.issues:
                    log.warning(
                        "Tool[%d] %r — issues: %s\nFull details:\n%s",
                        idx, tv.name, tv.issues, json.dumps(t, indent=2),
                    )
        except Exception as exc:
            log.error("MCP validate: tools/list failed: %s", exc)

        # ── List Resources ────────────────────────────────────────────────────
        resources: list[ResourceInfo] = []
        try:
            resp          = await _rpc(client, body.url, "resources/list", {}, req_id=2, session_id=session_id)
            raw_resources = resp.get("result", {}).get("resources", [])
            log.info("MCP validate: found %d resource(s)", len(raw_resources))
            for idx_r, r in enumerate(raw_resources):
                # Fetch content for text/markdown resources (agent guides) so we can
                # check for ADK template conflicts ({identifier} patterns).
                content: str | None = None
                uri = r.get("uri", "")
                mime = r.get("mimeType", "")
                if uri and ("agent-guide" in uri or "text/markdown" in mime or "text/plain" in mime):
                    try:
                        read_resp = await _rpc(
                            client, body.url, "resources/read",
                            {"uri": uri}, req_id=200 + idx_r, session_id=session_id,
                        )
                        contents = read_resp.get("result", {}).get("contents", [])
                        content = "\n".join(c.get("text", "") for c in contents if "text" in c) or None
                    except Exception as read_exc:
                        log.warning("MCP validate: could not read resource %r: %s", uri, read_exc)
                rv = _validate_resource(r, content=content)
                resources.append(rv)
                if rv.issues:
                    log.warning("Resource %r — issues: %s", uri, rv.issues)
        except Exception as exc:
            log.warning("MCP validate: resources/list failed (server may not support resources): %s", exc)

        # ── List Prompts ──────────────────────────────────────────────────────
        prompts: list[PromptInfo] = []
        try:
            resp        = await _rpc(client, body.url, "prompts/list", {}, req_id=3, session_id=session_id)
            raw_prompts = resp.get("result", {}).get("prompts", [])
            log.info("MCP validate: found %d prompt(s)", len(raw_prompts))
            for p in raw_prompts:
                prompts.append(_validate_prompt(p))
        except Exception as exc:
            log.warning("MCP validate: prompts/list failed (server may not support prompts): %s", exc)

    # ── Build summary ─────────────────────────────────────────────────────────
    tools_ok       = sum(1 for t in tools if t.status == "ok")
    tools_warnings = sum(1 for t in tools if t.status == "warning")
    tools_errors   = sum(1 for t in tools if t.status == "error")

    resources_errors = sum(1 for r in resources if r.status == "error")
    prompts_errors   = sum(1 for p in prompts if p.status == "error")

    if tools_errors > 0 or resources_errors > 0 or prompts_errors > 0:
        overall: Literal["ok", "warning", "error"] = "error"
    elif tools_warnings > 0:
        overall = "warning"
    else:
        overall = "ok"

    summary = ValidationSummary(
        tools_total=len(tools),
        tools_ok=tools_ok,
        tools_warnings=tools_warnings,
        tools_errors=tools_errors,
        resources_total=len(resources),
        prompts_total=len(prompts),
        overall_status=overall,
    )

    log.info(
        "MCP validation complete for %r — tools=%d (ok=%d warn=%d err=%d) resources=%d prompts=%d",
        server_name, len(tools), tools_ok, tools_warnings, tools_errors,
        len(resources), len(prompts),
    )

    return MCPValidateResponse(
        server_name=server_name,
        server_version=server_version,
        tools=tools,
        resources=resources,
        prompts=prompts,
        summary=summary,
    )
