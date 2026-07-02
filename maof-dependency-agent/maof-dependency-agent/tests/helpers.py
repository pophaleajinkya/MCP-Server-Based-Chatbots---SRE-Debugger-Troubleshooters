"""
Shared helpers for integration and e2e tests.
Both suites share the same fixture base from conftest.py.
"""


def make_agent_result(
    *,
    app_name=None,
    namespace=None,
    direction=None,
    dependencies=None,
    available_apps=None,
    upstream_dependencies=None,
    downstream_dependencies=None,
    source_breakdown=None,
    messages=None,
    error=None,
):
    """
    Build a fake return value for dependency_agent.process_query().

    Both integration and e2e tests patch dependency_agent.process_query
    with an AsyncMock whose return_value is built by this helper.
    """
    deps = dependencies if dependencies is not None else []
    return {
        "app_name": app_name,
        "namespace": namespace,
        "direction": direction,
        "dependencies": deps,
        "source_breakdown": source_breakdown or {},
        "total_count": len(deps),
        "messages": messages or [],
        "error": error,
        "success": error is None,
        "available_apps": available_apps,
        "upstream_dependencies": upstream_dependencies,
        "downstream_dependencies": downstream_dependencies,
    }

