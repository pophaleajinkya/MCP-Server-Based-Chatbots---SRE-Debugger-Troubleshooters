"""Dependency service — fetches from SRE-OPS only (Topology removed)."""
import logging
from typing import List, Tuple, Dict, Optional

from src.services.sre_ops_service import (
    fetch_downstream_dependencies,
    fetch_upstream_dependencies,
)

logger = logging.getLogger(__name__)


async def get_upstream_and_downstream_dependencies(
    app_name: str,
    namespace: str,
    direction: Optional[str] = None,
) -> Tuple[List[Dict], List[Dict], Dict]:
    """
    Fetch upstream and/or downstream dependencies from SRE-OPS.

    Raw SRE-OPS objects are returned as-is — no fields are removed or renamed.
    _extract_deps in sre_ops_service already adds a 'direction' field to each record.

    Args:
        app_name:  Application/deployment name
        namespace: Kubernetes namespace
        direction: "upstream", "downstream", "both", or None (both)

    Returns:
        Tuple of (upstream_deps, downstream_deps, source_breakdown)
    """
    logger.info(
        f"Fetching dependencies: appName={app_name}, namespace={namespace}, direction={direction}"
    )

    upstream_deps: List[Dict] = []
    downstream_deps: List[Dict] = []

    if direction in ("upstream", "both", None):
        upstream_deps = await fetch_upstream_dependencies(app_name, namespace)

    if direction in ("downstream", "both", None):
        downstream_deps = await fetch_downstream_dependencies(app_name, namespace)

    source_breakdown = {
        "upstream_count": len(upstream_deps),
        "downstream_count": len(downstream_deps),
        "total": len(upstream_deps) + len(downstream_deps),
    }

    logger.info(
        f"Fetched dependencies: upstream={len(upstream_deps)}, downstream={len(downstream_deps)}"
    )

    return upstream_deps, downstream_deps, source_breakdown
