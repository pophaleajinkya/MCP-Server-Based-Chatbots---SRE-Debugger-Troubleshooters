"""MCP tools for OneOps — thin, structured, no internal LLM.

Tools take explicit parameters extracted by the client LLM (ADK/Claude/etc).
Intelligence stays on the client — these tools are pure service calls.
"""
import logging

from src.mcp_server.server import mcp
from src.services.sre_ops_service import (
    fetch_oneops_upstream_dependencies as _svc_upstream,
    fetch_oneops_downstream_dependencies as _svc_downstream,
)

logger = logging.getLogger(__name__)


@mcp.tool(
    name="fetch_oneops_upstream_dependencies",
    description=(
        "Fetch UPSTREAM dependencies for a OneOps application.\n"
        "Upstream = services that call INTO this app (its callers / consumers).\n"
        "Calls SRE-OPS directly — no internal LLM, structured parameters only.\n"
        "Parameters:\n"
        "  org      — OneOps organisation (e.g. 'mexicoecomm', 'walmart-ecomm')\n"
        "  platform — OneOps platform name (e.g. 'rmsag2', 'pay-platform')\n"
        "  assembly — OneOps assembly name (e.g. 'mx-rms', 'payments-prod')"
    ),
)
async def fetch_oneops_upstream_dependencies(
    org: str,
    platform: str,
    assembly: str,
) -> dict:
    """Fetch OneOps upstream (callers) from SRE-OPS — no internal LLM."""
    logger.info(f"MCP tool: fetch_oneops_upstream_dependencies org={org} platform={platform} assembly={assembly}")
    try:
        upstream = await _svc_upstream(org, platform, assembly)
        return {
            "status": "success",
            "org": org,
            "platform": platform,
            "assembly": assembly,
            "direction": "upstream",
            "dependencies": upstream,
            "total_count": len(upstream),
            "message": f"Found {len(upstream)} upstream dependencies for org={org} platform={platform} assembly={assembly}",
        }
    except Exception as e:
        logger.error(f"fetch_oneops_upstream_dependencies error: {e}")
        return {
            "status": "error",
            "org": org,
            "platform": platform,
            "assembly": assembly,
            "direction": "upstream",
            "dependencies": [],
            "total_count": 0,
            "error": str(e),
        }


@mcp.tool(
    name="fetch_oneops_downstream_dependencies",
    description=(
        "Fetch DOWNSTREAM dependencies for a OneOps application.\n"
        "Downstream = services this app calls OUT TO (its dependencies / providers).\n"
        "Calls SRE-OPS directly — no internal LLM, structured parameters only.\n"
        "Parameters:\n"
        "  org      — OneOps organisation (e.g. 'mexicoecomm', 'walmart-ecomm')\n"
        "  platform — OneOps platform name (e.g. 'rmsag2', 'pay-platform')\n"
        "  assembly — OneOps assembly name (e.g. 'mx-rms', 'payments-prod')"
    ),
)
async def fetch_oneops_downstream_dependencies(
    org: str,
    platform: str,
    assembly: str,
) -> dict:
    """Fetch OneOps downstream (callees) from SRE-OPS — no internal LLM."""
    logger.info(f"MCP tool: fetch_oneops_downstream_dependencies org={org} platform={platform} assembly={assembly}")
    try:
        downstream = await _svc_downstream(org, platform, assembly)
        return {
            "status": "success",
            "org": org,
            "platform": platform,
            "assembly": assembly,
            "direction": "downstream",
            "dependencies": downstream,
            "total_count": len(downstream),
            "message": f"Found {len(downstream)} downstream dependencies for org={org} platform={platform} assembly={assembly}",
        }
    except Exception as e:
        logger.error(f"fetch_oneops_downstream_dependencies error: {e}")
        return {
            "status": "error",
            "org": org,
            "platform": platform,
            "assembly": assembly,
            "direction": "downstream",
            "dependencies": [],
            "total_count": 0,
            "error": str(e),
        }
