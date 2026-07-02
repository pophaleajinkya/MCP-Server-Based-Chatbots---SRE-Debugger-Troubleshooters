"""LLM client functions and agentic loops for the lite (non-ADK) agent.

Provides:
  llm_call          — single OpenAI-compatible chat completion call
  claude_call       — single Anthropic chat completion call
  run_agent_openai  — full agentic loop using OpenAI / Element Gateway
  run_agent_claude  — full agentic loop using Claude / Walmart Stage Gateway
"""

import asyncio
import json
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.mcp.client import MCPPool
from app.request_context import get_llm_headers

log = logging.getLogger(__name__)


async def llm_call(
    client: httpx.AsyncClient,
    messages: list[dict],
    tools: list[dict] | None = None,
) -> dict:
    s = get_settings()
    body: dict[str, Any] = {
        "model":       s.openai_model,
        "messages":    messages,
        "max_tokens":  4000,
        "temperature": 0.2,
    }
    if tools:
        body["tools"]       = tools
        body["tool_choice"] = "auto"

    headers = {**s.openai_headers, **get_llm_headers()}
    r = await client.post(s.openai_url, json=body, headers=headers, timeout=s.llm_timeout_seconds)
    r.raise_for_status()
    return r.json()


async def claude_call(
    client: httpx.AsyncClient,
    system: str,
    messages: list[dict],
    tools: list[dict] | None = None,
) -> dict:
    s = get_settings()
    body: dict[str, Any] = {
        "model":      s.claude_model,
        "system":     system,
        "messages":   messages,
        "max_tokens": 4096,
    }
    if tools:
        body["tools"] = tools

    headers = {**s.claude_headers, **get_llm_headers()}
    r = await client.post(s.claude_gateway_url, json=body, headers=headers, timeout=s.llm_timeout_seconds)
    r.raise_for_status()
    return r.json()


async def run_agent_claude(mcp: MCPPool, client: httpx.AsyncClient, query: str) -> str:
    """Agentic loop using Claude — multi-round tool-use until stop_reason != tool_use."""
    s = get_settings()
    system_content = (
        "You are a WCNP health assistant. "
        "Use the available tools to answer questions about Kubernetes apps, "
        "namespaces, deployments, and Prometheus metrics on WCNP clusters.\n"
        "Always use tools when the question requires live data.\n"
    )
    if mcp.guide:
        system_content += f"\n--- AGENT GUIDE ---\n{mcp.guide}\n---\n"

    messages: list[dict] = [{"role": "user", "content": query}]

    for round_num in range(s.max_tool_rounds):
        resp        = await claude_call(client, system_content, messages, tools=mcp.claude_tools or None)
        stop_reason = resp.get("stop_reason", "end_turn")
        content     = resp.get("content", [])

        messages.append({"role": "assistant", "content": content})

        if stop_reason != "tool_use":
            return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")

        tool_use_blocks = [b for b in content if b.get("type") == "tool_use"]
        log.info("Claude round %d — executing %d tool call(s)", round_num + 1, len(tool_use_blocks))

        results = await asyncio.gather(*[
            mcp.call_tool(b["name"], b.get("input", {}))
            for b in tool_use_blocks
        ])

        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": b["id"], "content": result}
            for b, result in zip(tool_use_blocks, results)
        ]})

    # Safety net — ask for a final answer without tools
    messages.append({"role": "user", "content": "Please summarise your findings."})
    resp    = await claude_call(client, system_content, messages, tools=None)
    content = resp.get("content", [])
    return "\n".join(b.get("text", "") for b in content if b.get("type") == "text")


async def run_agent_openai(mcp: MCPPool, client: httpx.AsyncClient, query: str) -> str:
    """Agentic loop using OpenAI / Element Gateway — multi-round tool-use until finish_reason != tool_calls."""
    s = get_settings()
    system_content = (
        "You are a WCNP health assistant. "
        "Use the available tools to answer questions about Kubernetes apps, "
        "namespaces, deployments, and Prometheus metrics on WCNP clusters.\n"
        "Always use tools when the question requires live data.\n"
    )
    if mcp.guide:
        system_content += f"\n--- AGENT GUIDE ---\n{mcp.guide}\n---\n"

    messages: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": query},
    ]

    for round_num in range(s.max_tool_rounds):
        resp   = await llm_call(client, messages, tools=mcp.oai_tools or None)
        choice = resp["choices"][0]
        msg    = choice["message"]
        finish = choice.get("finish_reason", "stop")

        messages.append(msg)

        if finish != "tool_calls" or not msg.get("tool_calls"):
            return msg.get("content") or ""

        tool_calls = msg["tool_calls"]
        log.info("Round %d — executing %d tool call(s)", round_num + 1, len(tool_calls))

        results = await asyncio.gather(*[
            mcp.call_tool(tc["function"]["name"], json.loads(tc["function"]["arguments"]))
            for tc in tool_calls
        ])

        for tc, result in zip(tool_calls, results):
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

    # Safety net
    messages.append({"role": "user", "content": "Please summarise your findings."})
    resp = await llm_call(client, messages, tools=None)
    return resp["choices"][0]["message"].get("content", "")
