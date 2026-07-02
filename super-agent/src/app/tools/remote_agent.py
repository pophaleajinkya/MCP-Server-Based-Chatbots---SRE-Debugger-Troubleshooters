"""
Remote A2A agent proxy tools.

Wraps any remote A2A-compliant agent as a callable ``FunctionTool`` that the
ADK orchestrator LLM can invoke like any other tool.

Protocol:
    POST {base_url}/a2a
    Body: JSON-RPC 2.0  method=message/send  (A2A SDK 0.3)
    Response: task.artifacts[0].parts[0].text

Usage::

    from app.tools.remote_agent import make_remote_agent_tool

    sre_tool = make_remote_agent_tool(
        name="call_sre_agent",
        description="Delegate SRE incident analysis to the remote SRE agent.",
        base_url="https://sre-agent.dev.walmart.com",
    )

    root_agent = Agent(model=_llm, tools=[sre_tool, *mcp_tools])
"""

from __future__ import annotations

import logging
import uuid
from typing import Callable

import httpx

log = logging.getLogger(__name__)

# Default timeouts for remote A2A calls (seconds).
_CONNECT_TIMEOUT = 10.0
_READ_TIMEOUT    = 120.0   # remote agent may take time to run its own tool loop


def make_remote_agent_tool(
    name: str,
    description: str,
    base_url: str,
    timeout_seconds: float = _READ_TIMEOUT,
    extra_headers: dict[str, str] | None = None,
) -> Callable:
    """
    Build an async ``FunctionTool``-compatible callable that delegates queries
    to a remote A2A agent via JSON-RPC 2.0 ``message/send`` (A2A SDK 0.3).

    Args:
        name:            Tool name shown to the orchestrator LLM (snake_case).
        description:     Natural-language description — the LLM uses this to
                         decide when to call this tool.
        base_url:        Root URL of the remote agent (e.g.
                         ``"https://sre-agent.dev.walmart.com"``).
                         The tool calls ``{base_url}/a2a``.
        timeout_seconds: Maximum wait for the remote agent to respond.
                         Increase for agents that run long tool chains.
        extra_headers:   Additional HTTP headers (e.g. auth tokens).

    Returns:
        An async callable suitable for inclusion in an ADK Agent's ``tools``
        list.  ADK auto-wraps plain async functions as ``FunctionTool``.
    """
    _headers = {"Content-Type": "application/json", **(extra_headers or {})}
    _endpoint = f"{base_url.rstrip('/')}/a2a"

    async def _call(query: str, session_id: str | None = None) -> str:
        """
        Delegate a query to the remote A2A agent and return its text response.

        Args:
            query:      The natural-language query to send.
            session_id: Optional session ID for multi-turn continuity on the
                        remote agent.  Pass the current conversation session_id
                        to maintain context across calls.

        Returns:
            The agent's text response, or an error message prefixed with
            ``[remote-agent error]`` if the call fails.
        """
        task_id = str(uuid.uuid4())
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "message/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": query}],
                    "messageId": task_id,
                },
                "configuration": {
                    **({"sessionId": session_id} if session_id else {}),
                },
            },
        }

        log.info("[remote-agent] %s → %s  (task=%s)", name, _endpoint, task_id)

        try:
            async with httpx.AsyncClient(
                headers=_headers,
                timeout=httpx.Timeout(connect=_CONNECT_TIMEOUT, read=timeout_seconds,
                                      write=10.0, pool=5.0),
                follow_redirects=True,
            ) as client:
                resp = await client.post(_endpoint, json=payload)
                resp.raise_for_status()
                body = resp.json()

        except httpx.HTTPStatusError as exc:
            log.warning("[remote-agent] %s HTTP %s: %s", name, exc.response.status_code, exc)
            return f"[remote-agent error] {name} returned HTTP {exc.response.status_code}"
        except httpx.RequestError as exc:
            log.warning("[remote-agent] %s connection error: %s", name, exc)
            return f"[remote-agent error] Could not reach {name}: {exc}"

        # ── Unwrap JSON-RPC response ───────────────────────────────────────────
        if "error" in body and body["error"]:
            err = body["error"]
            log.warning("[remote-agent] %s RPC error %s: %s", name, err.get("code"), err.get("message"))
            return f"[remote-agent error] {name}: {err.get('message', 'unknown error')}"

        task   = body.get("result", {})
        state  = task.get("status", {}).get("state", "unknown")
        log.info("[remote-agent] %s task %s → state=%s", name, task_id, state)

        # Extract text from artifacts (completed task)
        artifacts = task.get("artifacts", [])
        if artifacts:
            parts = artifacts[0].get("parts", [])
            texts = [p["text"] for p in parts if p.get("type") == "text" and p.get("text")]
            if texts:
                return "\n".join(texts)

        # Fall back to status message if no artifacts yet
        status_msg = task.get("status", {}).get("message")
        if status_msg:
            msg_parts = status_msg.get("parts", [])
            texts = [p["text"] for p in msg_parts if p.get("type") == "text" and p.get("text")]
            if texts:
                return "\n".join(texts)

        return f"[remote-agent] {name} completed with state={state} but no text output"

    # Give the function the caller-supplied identity so ADK uses the right name/doc
    _call.__name__ = name
    _call.__doc__  = description
    return _call
