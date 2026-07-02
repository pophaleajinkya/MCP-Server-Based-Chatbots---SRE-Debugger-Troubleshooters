"""Tests for MCP tool definitions and schema compliance.

Verifies that every tool in this MCP server is compatible with
super-agent (Anthropic/Claude JSON Schema rules) before registration.
"""

import json
import pytest
from src.server import mcp


def get_tool_schemas() -> list[dict]:
    """Return all tool schemas in Anthropic format for validation."""
    tools = mcp._tool_manager.list_tools()
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema or {},
        }
        for t in tools
    ]


# ── Schema compliance tests ───────────────────────────────────────────────────

def test_tools_are_registered():
    """At least one tool must be registered."""
    tools = get_tool_schemas()
    assert tools, "No tools registered — add at least one @mcp.tool()"


@pytest.mark.parametrize("tool", get_tool_schemas())
def test_tool_has_description(tool):
    """Every tool must have a non-empty description."""
    assert tool["description"], (
        f"Tool '{tool['name']}' has no description — "
        "the orchestrator LLM uses this to decide when to call the tool"
    )
    assert len(tool["description"]) > 20, (
        f"Tool '{tool['name']}' description is too short — be specific about input/output"
    )


@pytest.mark.parametrize("tool", get_tool_schemas())
def test_tool_schema_is_object(tool):
    """inputSchema top-level type must be 'object' (Anthropic requirement)."""
    schema = tool["input_schema"]
    schema_type = schema.get("type")
    assert schema_type == "object", (
        f"Tool '{tool['name']}' inputSchema.type={schema_type!r} — "
        "Anthropic requires top-level type='object'"
    )


@pytest.mark.parametrize("tool", get_tool_schemas())
def test_tool_schema_no_defaults(tool):
    """inputSchema must not contain 'default' (Anthropic rejects it)."""
    schema_str = json.dumps(tool["input_schema"])
    assert '"default"' not in schema_str, (
        f"Tool '{tool['name']}' inputSchema contains 'default' — "
        "Anthropic rejects this. Remove all default values."
    )


@pytest.mark.parametrize("tool", get_tool_schemas())
def test_tool_schema_no_legacy_keys(tool):
    """inputSchema must not use legacy JSON Schema keys."""
    BANNED = {"$ref", "definitions", "$schema", "if", "then", "else"}
    schema_str = json.dumps(tool["input_schema"])
    found = [k for k in BANNED if f'"{k}"' in schema_str]
    assert not found, (
        f"Tool '{tool['name']}' inputSchema uses banned keys {found} — "
        "Anthropic rejects these. Use inline schemas instead."
    )


@pytest.mark.parametrize("tool", get_tool_schemas())
def test_tool_schema_is_json_serialisable(tool):
    """inputSchema must be JSON-serialisable (catches circular refs)."""
    try:
        json.dumps(tool["input_schema"])
    except (TypeError, ValueError) as exc:
        pytest.fail(f"Tool '{tool['name']}' inputSchema is not JSON-serialisable: {exc}")


# ── Resource tests ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_agent_guide_resource_exists():
    """The agent guide resource must be registered and non-empty."""
    resources = await mcp._resource_manager.list_resources()
    guide_uris = [r.uri for r in resources if str(r.uri).endswith("://agent-guide")]
    assert guide_uris, (
        "No agent guide resource found (URI ending in '://agent-guide'). "
        "Add a @mcp.resource('<scheme>://agent-guide') — super-agent injects it "
        "into the orchestrator LLM's system prompt."
    )


@pytest.mark.asyncio
async def test_agent_guide_content_is_not_empty():
    """The agent guide must have meaningful content."""
    resources = await mcp._resource_manager.list_resources()
    for r in resources:
        if str(r.uri).endswith("://agent-guide"):
            content = await mcp._resource_manager.read_resource(r.uri)
            text = "".join(
                c.text for c in content
                if hasattr(c, "text") and c.text
            )
            assert len(text.strip()) > 50, (
                f"Agent guide at '{r.uri}' has too little content — "
                "add tool routing rules and domain constraints"
            )
