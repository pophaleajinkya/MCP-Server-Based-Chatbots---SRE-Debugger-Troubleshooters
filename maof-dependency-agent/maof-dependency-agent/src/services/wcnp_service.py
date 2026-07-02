"""WCNP (DX Console) service — plain HTTP calls, no LangGraph, no LLM."""
import logging
from typing import Any, Dict, Optional

import httpx

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
_HTTP_CLIENT_KWARGS = {"verify": False, "timeout": 30.0}  # noqa: S501


def _extract_app_name_from_dict(app: Dict[str, Any]) -> Optional[str]:
    return (
        app.get("app_name")
        or app.get("appName")
        or app.get("name")
        or app.get("releaseName")
    )


async def get_apps_for_namespace(namespace: str) -> Dict[str, Any]:
    """Fetch all app names in a WCNP namespace from DX Console.

    Returns a dict with status, namespace, available_apps, message, error.
    Never raises — errors are returned as a dict with status=error.
    """
    try:
        url = f"{settings.DX_CONSOLE_URL}{settings.DX_CONSOLE_APPS_PATH}"
        params = {"profile": "prod", "namespace": namespace}
        async with httpx.AsyncClient(**_HTTP_CLIENT_KWARGS) as client:
            response = await client.get(
                url, headers={"Content-Type": "application/json"}, params=params
            )
            response.raise_for_status()
            data = response.json()

        if isinstance(data, list):
            apps = [_extract_app_name_from_dict(a) for a in data if isinstance(a, dict)]
        else:
            raw = data.get("apps") or data.get("applications") or data.get("data") or []
            apps = [_extract_app_name_from_dict(a) for a in raw if isinstance(a, dict)]

        apps = list(dict.fromkeys(a for a in apps if a))

        if apps:
            return {
                "status": "success",
                "namespace": namespace,
                "available_apps": apps,
                "total_count": len(apps),
                "message": f"Found {len(apps)} apps in namespace '{namespace}'.",
            }
        return {
            "status": "success",
            "namespace": namespace,
            "available_apps": [],
            "total_count": 0,
            "message": f"No apps found in namespace '{namespace}'. Verify the namespace name.",
        }
    except Exception as e:
        logger.error(f"get_apps_for_namespace error namespace={namespace}: {e}")
        return {
            "status": "error",
            "namespace": namespace,
            "available_apps": [],
            "total_count": 0,
            "error": str(e),
            "message": f"Failed to fetch apps for namespace '{namespace}'.",
        }
