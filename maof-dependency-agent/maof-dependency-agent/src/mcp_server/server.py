"""MCP server for dependency agent — exposes tools over streamable HTTP.

Design principle: tools are thin service calls. No LLM inside any tool.
The client LLM (ADK/Claude/etc) owns all intelligence — parameter extraction,
routing, multi-turn context. Tools just execute.

Mount in FastAPI:
    from src.mcp_server.server import mcp
    app.mount("/mcp", mcp.streamable_http_app())

Endpoint:
    POST /mcp/   ← single stateless JSON-RPC endpoint (Istio-friendly)
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "dependency-agent",
    streamable_http_path="/",   # mount("/mcp", ...) → endpoint at /mcp/
    stateless_http=True,        # no session-ID required — matches health_mcp pattern
    instructions=(
        "Fetch application dependency graphs from SRE-OPS and DX Console.\n"
        "All tools are thin service calls — no LLM inside. You handle all reasoning.\n"
        "\n"
        "── WCNP (Kubernetes) ────────────────────────────────────────────────\n"
        "  list_apps_in_namespace(namespace)\n"
        "    → Use first when only namespace is known. Returns available app names.\n"
        "\n"
        "  fetch_wcnp_upstream_dependencies(app_name, namespace)\n"
        "    → Who calls INTO this app? Requires app_name + namespace.\n"
        "\n"
        "  fetch_wcnp_downstream_dependencies(app_name, namespace)\n"
        "    → What does this app call OUT TO? Requires app_name + namespace.\n"
        "\n"
        "── OneOps ───────────────────────────────────────────────────────────\n"
        "  fetch_oneops_upstream_dependencies(org, platform, assembly)\n"
        "    → Who calls INTO this OneOps app? Requires org + platform + assembly.\n"
        "\n"
        "  fetch_oneops_downstream_dependencies(org, platform, assembly)\n"
        "    → What does this OneOps app call OUT TO? Requires org + platform + assembly.\n"
        "\n"
        "── Managed Services (upstream only) ─────────────────────────────────\n"
        "  fetch_cassandra_upstream_dependencies(assembly, platform)\n"
        "  fetch_meghacache_upstream_dependencies(assembly, platform)\n"
        "  fetch_cosmos_upstream_dependencies(resource_group, subscription_id, database_name)\n"
        "  fetch_sqlserver_upstream_dependencies(resource_group, subscription_id, database_name)"
    ),
)

# Import tool modules after `mcp` is defined so @mcp.tool decorators register correctly.
from src.mcp_server.tools import wcnp, oneops, managed_service, graph  # noqa: E402, F401
# Import resources and prompts — registers @mcp.resource and @mcp.prompt decorators.
from src.mcp_server import resources_and_prompts  # noqa: E402, F401
