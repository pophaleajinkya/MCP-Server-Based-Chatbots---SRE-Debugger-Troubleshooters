"""Database service for fetching dependencies."""
import logging
from typing import List, Dict, Union
import httpx

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

SRE_OPS_URL = f"{settings.SRE_OPS_URL}"

# verify=False is intentional: internal Walmart staging services use self-signed certs
_HTTP_CLIENT_KWARGS = {"verify": False, "timeout": 30.0}  # noqa: S501


def _extract_deps(data, direction: str) -> List[Dict]:
    """Return the raw SRE-OPS dependency list as-is, only adding a 'direction' field."""
    if isinstance(data, list):
        raw = data
    elif isinstance(data, dict):
        raw = data.get("dependencies", [])
    else:
        raw = []
    result = []
    for dep in raw:
        if isinstance(dep, dict):
            dep_copy = dict(dep)          # shallow copy — do not mutate the original
            dep_copy["direction"] = direction
            result.append(dep_copy)
    return result


async def _get(url: str, params: Dict, label: str) -> Union[list, dict]:
    """Generic GET helper with structured logging and error handling.
    Returns parsed JSON (list or dict) on success, or [] on any failure.
    """
    logger.info(f"SRE-OPS {label} request: GET {url} params={params}")
    try:
        async with httpx.AsyncClient(**_HTTP_CLIENT_KWARGS) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.ConnectError as e:
        logger.warning(f"SRE-OPS {label}: cannot connect to {url} — is SRE_OPS_URL correct? Error: {e}")
    except httpx.HTTPStatusError as e:
        logger.warning(f"SRE-OPS {label}: HTTP {e.response.status_code} from {url}: {e.response.text[:200]}")
    except Exception as e:  # noqa: BLE001
        logger.error(f"SRE-OPS {label}: unexpected error: {e}")
    return []


async def fetch_downstream_dependencies(app_name: str, namespace: str) -> List[Dict]:
    """Fetch downstream dependencies from SRE-OPS API."""
    url = f"{SRE_OPS_URL}{settings.SRE_OPS_DOWNSTREAM_PATH}"
    data = await _get(url, {"appName": app_name, "namespace": namespace}, "downstream")
    result = _extract_deps(data, "downstream")
    logger.info(f"SRE-OPS downstream: fetched {len(result)} deps for {app_name} in {namespace}")
    return result


async def fetch_upstream_dependencies(app_name: str, namespace: str) -> List[Dict]:
    """Fetch upstream dependencies from SRE-OPS API."""
    url = f"{SRE_OPS_URL}{settings.SRE_OPS_UPSTREAM_PATH}"
    data = await _get(url, {"appName": app_name, "namespace": namespace}, "upstream")
    result = _extract_deps(data, "upstream")
    logger.info(f"SRE-OPS upstream: fetched {len(result)} deps for {app_name} in {namespace}")
    return result


async def fetch_oneops_downstream_dependencies(org: str, platform: str, assembly: str) -> List[Dict]:
    """Fetch downstream dependencies from SRE-OPS API for a OneOps application.

    OneOps param mapping (sent as-is, no appName/namespace):
      org      = org
      platform = platform
      assembly = assembly
    """
    url = f"{SRE_OPS_URL}{settings.SRE_OPS_DOWNSTREAM_PATH}"
    params = {"org": org, "platform": platform, "assembly": assembly}
    data = await _get(url, params, "downstream[oneops]")
    result = _extract_deps(data, "downstream")
    logger.info(
        f"SRE-OPS downstream[oneops]: fetched {len(result)} deps "
        f"for org={org} platform={platform} assembly={assembly}"
    )
    return result


async def fetch_oneops_upstream_dependencies(org: str, platform: str, assembly: str) -> List[Dict]:
    """Fetch upstream dependencies from SRE-OPS API for a OneOps application.

    OneOps param mapping (sent as-is, no appName/namespace):
      org      = org
      platform = platform
      assembly = assembly
    """
    url = f"{SRE_OPS_URL}{settings.SRE_OPS_UPSTREAM_PATH}"
    params = {"org": org, "platform": platform, "assembly": assembly}
    data = await _get(url, params, "upstream[oneops]")
    result = _extract_deps(data, "upstream")
    logger.info(
        f"SRE-OPS upstream[oneops]: fetched {len(result)} deps "
        f"for org={org} platform={platform} assembly={assembly}"
    )
    return result


async def fetch_managed_service_upstream_dependencies(params: Dict) -> List[Dict]:
    """Fetch upstream dependencies from SRE-OPS for a managed service.

    Cassandra / MeghaCache — params must contain:
        assembly, platform, serviceType

    Cosmos / SQL — params must contain:
        resourceGroup, subscriptionId, databaseName, serviceType
    """
    url = f"{SRE_OPS_URL}{settings.SRE_OPS_UPSTREAM_PATH}"
    service_type = params.get("serviceType", "unknown")
    data = await _get(url, params, f"upstream[managed-service:{service_type}]")
    result = _extract_deps(data, "upstream")
    logger.info(
        f"SRE-OPS upstream[managed-service:{service_type}]: "
        f"fetched {len(result)} deps with params={params}"
    )
    return result


