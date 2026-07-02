"""Unit tests for src/agent/agent.py"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json

from src.agent.agent import (
    DependencyAgent,
    _route_after_parse,
    _format_response,
    _extract_app_name_from_dict,
    _get_apps_for_namespace,
    _suggest_wcnp,
    _fetch_wcnp,
    _fetch_oneops,
    _fetch_managed_service,
    _build_managed_sre_params,
    _missing_managed_params,
)


class TestRouteAfterParse:
    """Tests for _route_after_parse function."""

    def test_route_returns_next_step(self):
        """Test that route returns the next_step from state."""
        state = {"next_step": "fetch_wcnp"}
        assert _route_after_parse(state) == "fetch_wcnp"

    def test_route_returns_error_when_missing(self):
        """Test that route returns 'error' when next_step is missing."""
        state = {}
        assert _route_after_parse(state) == "error"

    def test_route_various_steps(self):
        """Test routing to various steps."""
        for step in ["fetch_wcnp", "suggest_wcnp", "fetch_oneops", "fetch_managed_service", "error"]:
            state = {"next_step": step}
            assert _route_after_parse(state) == step


class TestFormatResponse:
    """Tests for _format_response function."""

    def test_format_response_returns_state(self):
        """Test that format_response returns the state unchanged."""
        state = {
            "session_id": "test-123",
            "dependencies": [{"name": "dep1"}],
            "messages": ["Found 1 dep"]
        }
        result = _format_response(state)
        assert result == state


class TestExtractAppNameFromDict:
    """Tests for _extract_app_name_from_dict function."""

    def test_extract_app_name(self):
        """Test extracting app_name field."""
        assert _extract_app_name_from_dict({"app_name": "my-app"}) == "my-app"

    def test_extract_appName(self):
        """Test extracting appName field (camelCase)."""
        assert _extract_app_name_from_dict({"appName": "my-app"}) == "my-app"

    def test_extract_name(self):
        """Test extracting name field."""
        assert _extract_app_name_from_dict({"name": "my-app"}) == "my-app"

    def test_extract_releaseName(self):
        """Test extracting releaseName field."""
        assert _extract_app_name_from_dict({"releaseName": "my-app"}) == "my-app"

    def test_extract_priority_order(self):
        """Test that app_name has priority over others."""
        app = {
            "app_name": "first",
            "appName": "second",
            "name": "third",
            "releaseName": "fourth"
        }
        assert _extract_app_name_from_dict(app) == "first"

    def test_extract_empty_dict(self):
        """Test extracting from empty dict."""
        assert _extract_app_name_from_dict({}) is None


class TestGetAppsForNamespace:
    """Tests for _get_apps_for_namespace function."""

    @pytest.mark.asyncio
    async def test_get_apps_success_list_response(self):
        """Test successful app fetch with list response."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {"app_name": "app1"},
            {"app_name": "app2"},
        ]
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _get_apps_for_namespace("prod")

            assert result["success"] is True
            assert result["namespace"] == "prod"
            assert "app1" in result["available_apps"]
            assert "app2" in result["available_apps"]

    @pytest.mark.asyncio
    async def test_get_apps_success_dict_with_apps_key(self):
        """Test successful app fetch with dict response containing 'apps'."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "apps": [{"app_name": "app1"}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _get_apps_for_namespace("staging")

            assert result["success"] is True
            assert "app1" in result["available_apps"]

    @pytest.mark.asyncio
    async def test_get_apps_no_apps_found(self):
        """Test when no apps are found."""
        mock_response = MagicMock()
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _get_apps_for_namespace("empty-ns")

            assert result["success"] is False
            assert result["available_apps"] == []

    @pytest.mark.asyncio
    async def test_get_apps_exception(self):
        """Test exception handling in get_apps."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get.side_effect = Exception("Network error")
            mock_client.return_value.__aenter__.return_value = mock_instance

            result = await _get_apps_for_namespace("error-ns")

            assert result["success"] is False
            assert "error" in result


class TestSuggestWcnp:
    """Tests for _suggest_wcnp function."""

    @pytest.mark.asyncio
    async def test_suggest_wcnp_success(self):
        """Test successful WCNP suggestion."""
        state = {
            "session_id": "test-123",
            "namespace": "prod",
            "messages": []
        }

        with patch("src.agent.agent._get_apps_for_namespace", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "success": True,
                "available_apps": ["app1", "app2"],
                "message": "Found 2 apps"
            }

            result = await _suggest_wcnp(state)

            assert result["available_apps"] == ["app1", "app2"]
            assert result["dependencies"] == []
            assert len(result["messages"]) > 0

    @pytest.mark.asyncio
    async def test_suggest_wcnp_failure(self):
        """Test WCNP suggestion failure."""
        state = {
            "session_id": "test-456",
            "namespace": "invalid-ns",
            "messages": []
        }

        with patch("src.agent.agent._get_apps_for_namespace", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "success": False,
                "message": "No apps found",
                "error": "Namespace not found"
            }

            result = await _suggest_wcnp(state)

            assert "error" in result


class TestFetchWcnp:
    """Tests for _fetch_wcnp function."""

    @pytest.mark.asyncio
    async def test_fetch_wcnp_both_directions(self):
        """Test fetching WCNP dependencies in both directions."""
        state = {
            "session_id": "test-123",
            "app_name": "my-app",
            "namespace": "prod",
            "direction": None,
            "messages": []
        }

        with patch("src.agent.agent.get_upstream_and_downstream_dependencies", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (
                [{"name": "up-dep"}],
                [{"name": "down-dep"}],
                {"upstream_count": 1, "downstream_count": 1, "total": 2}
            )

            result = await _fetch_wcnp(state)

            assert result["upstream_dependencies"] == [{"name": "up-dep"}]
            assert result["downstream_dependencies"] == [{"name": "down-dep"}]
            assert len(result["dependencies"]) == 2

    @pytest.mark.asyncio
    async def test_fetch_wcnp_upstream_only(self):
        """Test fetching WCNP dependencies upstream only."""
        state = {
            "session_id": "test-456",
            "app_name": "my-app",
            "namespace": "prod",
            "direction": "upstream",
            "messages": []
        }

        with patch("src.agent.agent.get_upstream_and_downstream_dependencies", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (
                [{"name": "up1"}, {"name": "up2"}],
                [],
                {"upstream_count": 2}
            )

            result = await _fetch_wcnp(state)

            assert result["dependencies"] == [{"name": "up1"}, {"name": "up2"}]
            assert result["source_breakdown"]["upstream_count"] == 2

    @pytest.mark.asyncio
    async def test_fetch_wcnp_downstream_only(self):
        """Test fetching WCNP dependencies downstream only."""
        state = {
            "session_id": "test-789",
            "app_name": "my-app",
            "namespace": "prod",
            "direction": "downstream",
            "messages": []
        }

        with patch("src.agent.agent.get_upstream_and_downstream_dependencies", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = (
                [],
                [{"name": "down1"}],
                {"downstream_count": 1}
            )

            result = await _fetch_wcnp(state)

            assert result["dependencies"] == [{"name": "down1"}]

    @pytest.mark.asyncio
    async def test_fetch_wcnp_exception(self):
        """Test error handling in _fetch_wcnp."""
        state = {
            "session_id": "test-error",
            "app_name": "error-app",
            "namespace": "prod",
            "direction": None,
            "messages": []
        }

        with patch("src.agent.agent.get_upstream_and_downstream_dependencies", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("Service error")

            result = await _fetch_wcnp(state)

            assert "error" in result
            assert result["error"] == "Service error"


class TestFetchOneOps:
    """Tests for _fetch_oneops function."""

    @pytest.mark.asyncio
    async def test_fetch_oneops_both_directions(self):
        """Test fetching OneOps dependencies in both directions."""
        state = {
            "session_id": "test-123",
            "org": "mexicoecomm",
            "platform": "rmsag2",
            "assembly": "mx-rms",
            "direction": None,
            "messages": []
        }

        with patch("src.agent.agent.fetch_oneops_upstream_dependencies", new_callable=AsyncMock) as mock_up, \
             patch("src.agent.agent.fetch_oneops_downstream_dependencies", new_callable=AsyncMock) as mock_down:
            mock_up.return_value = [{"name": "up-dep", "tier": None}]
            mock_down.return_value = [{"name": "down-dep"}]

            result = await _fetch_oneops(state)

            assert len(result["upstream_dependencies"]) == 1
            assert len(result["downstream_dependencies"]) == 1

    @pytest.mark.asyncio
    async def test_fetch_oneops_upstream_only(self):
        """Test fetching OneOps upstream only."""
        state = {
            "session_id": "test-456",
            "org": "org",
            "platform": "plat",
            "assembly": "asm",
            "direction": "upstream",
            "messages": []
        }

        with patch("src.agent.agent.fetch_oneops_upstream_dependencies", new_callable=AsyncMock) as mock_up, \
             patch("src.agent.agent.fetch_oneops_downstream_dependencies", new_callable=AsyncMock) as mock_down:
            mock_up.return_value = [{"name": "up"}]

            result = await _fetch_oneops(state)

            mock_down.assert_not_called()
            # Raw data passed through as-is — direction is set by _extract_deps in sre_ops_service
            assert result["dependencies"] == [{"name": "up"}]

    @pytest.mark.asyncio
    async def test_fetch_oneops_downstream_only(self):
        """Test fetching OneOps downstream only."""
        state = {
            "session_id": "test-789",
            "org": "org",
            "platform": "plat",
            "assembly": "asm",
            "direction": "downstream",
            "messages": []
        }

        with patch("src.agent.agent.fetch_oneops_upstream_dependencies", new_callable=AsyncMock) as mock_up, \
             patch("src.agent.agent.fetch_oneops_downstream_dependencies", new_callable=AsyncMock) as mock_down:
            mock_down.return_value = [{"name": "down"}]

            result = await _fetch_oneops(state)

            mock_up.assert_not_called()
            # Raw data passed through as-is — direction is set by _extract_deps in sre_ops_service
            assert result["dependencies"] == [{"name": "down"}]

    @pytest.mark.asyncio
    async def test_fetch_oneops_exception(self):
        """Test error handling in _fetch_oneops."""
        state = {
            "session_id": "test-error",
            "org": "org",
            "platform": "plat",
            "assembly": "asm",
            "direction": None,
            "messages": []
        }

        with patch("src.agent.agent.fetch_oneops_upstream_dependencies", new_callable=AsyncMock) as mock_up:
            mock_up.side_effect = Exception("OneOps error")

            result = await _fetch_oneops(state)

            assert "error" in result


class TestBuildManagedSreParams:
    """Tests for _build_managed_sre_params function."""

    def test_build_params_cassandra(self):
        """Test building params for Cassandra."""
        state = {
            "service_type": "cassandra",
            "assembly": "mx-rms",
            "platform": "rmsag2"
        }
        result = _build_managed_sre_params(state)
        
        assert result["serviceType"] == "cassandra"
        assert result["assembly"] == "mx-rms"
        assert result["platform"] == "rmsag2"

    def test_build_params_meghacache(self):
        """Test building params for MeghaCache."""
        state = {
            "service_type": "meghacache",
            "assembly": "payments-prod",
            "platform": "pay-platform"
        }
        result = _build_managed_sre_params(state)
        
        assert result["serviceType"] == "meghacache"

    def test_build_params_cosmos(self):
        """Test building params for Cosmos."""
        state = {
            "service_type": "cosmos",
            "resource_group": "my-rg",
            "subscription_id": "sub-123",
            "database_name": "orders-db"
        }
        result = _build_managed_sre_params(state)
        
        assert result["serviceType"] == "cosmos"
        assert result["resourceGroup"] == "my-rg"
        assert result["subscriptionId"] == "sub-123"
        assert result["databaseName"] == "orders-db"

    def test_build_params_sqlserver(self):
        """Test building params for SQL Server."""
        state = {
            "service_type": "sqlserver",
            "resource_group": "prod-rg",
            "subscription_id": "sub-456",
            "database_name": "inventory"
        }
        result = _build_managed_sre_params(state)
        
        assert result["serviceType"] == "sqlserver"


class TestMissingManagedParams:
    """Tests for _missing_managed_params function."""

    def test_no_missing_cassandra(self):
        """Test no missing params for complete Cassandra config."""
        state = {
            "service_type": "cassandra",
            "assembly": "mx-rms",
            "platform": "rmsag2"
        }
        assert _missing_managed_params(state) == []

    def test_missing_cassandra_params(self):
        """Test missing params for incomplete Cassandra config."""
        state = {
            "service_type": "cassandra",
            "assembly": "mx-rms",
            "platform": None
        }
        result = _missing_managed_params(state)
        assert "platform" in result

    def test_no_missing_cosmos(self):
        """Test no missing params for complete Cosmos config."""
        state = {
            "service_type": "cosmos",
            "resource_group": "rg",
            "subscription_id": "sub",
            "database_name": "db"
        }
        assert _missing_managed_params(state) == []

    def test_missing_cosmos_params(self):
        """Test missing params for incomplete Cosmos config."""
        state = {
            "service_type": "cosmos",
            "resource_group": "rg",
            "subscription_id": None,
            "database_name": None
        }
        result = _missing_managed_params(state)
        assert len(result) == 2

    def test_missing_service_type(self):
        """Test missing service_type."""
        state = {"service_type": None}
        result = _missing_managed_params(state)
        assert "service_type" in result

    def test_unknown_service_type(self):
        """Test unknown service type."""
        state = {"service_type": "unknown"}
        result = _missing_managed_params(state)
        assert "service_type" in result


class TestFetchManagedService:
    """Tests for _fetch_managed_service function."""

    @pytest.mark.asyncio
    async def test_fetch_managed_service_success(self):
        """Test successful managed service fetch."""
        state = {
            "session_id": "test-123",
            "service_type": "cassandra",
            "assembly": "mx-rms",
            "platform": "rmsag2",
            "messages": []
        }

        with patch("src.agent.agent.fetch_managed_service_upstream_dependencies", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = [{"name": "cassandra-dep", "tier": None}]

            result = await _fetch_managed_service(state)

            assert len(result["dependencies"]) == 1
            # Raw data passed through as-is — null fields are preserved
            assert result["dependencies"][0]["tier"] is None

    @pytest.mark.asyncio
    async def test_fetch_managed_service_exception(self):
        """Test error handling in _fetch_managed_service."""
        state = {
            "session_id": "test-error",
            "service_type": "cosmos",
            "resource_group": "rg",
            "subscription_id": "sub",
            "database_name": "db",
            "messages": []
        }

        with patch("src.agent.agent.fetch_managed_service_upstream_dependencies", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("Managed service error")

            result = await _fetch_managed_service(state)

            assert "error" in result


class TestDependencyAgent:
    """Tests for DependencyAgent class."""

    def test_agent_initialization(self):
        """Test agent initialization creates graph."""
        with patch("src.agent.agent.llm_client") as mock_llm:
            mock_llm.chat = MagicMock()
            
            agent = DependencyAgent()
            
            assert agent.llm is not None
            assert agent.graph is not None

    @pytest.mark.asyncio
    async def test_parse_query_wcnp_with_both_params(self):
        """Test parse query routes to fetch_wcnp when app and namespace present."""
        with patch("src.agent.agent.llm_client") as mock_llm:
            mock_chat = AsyncMock()
            mock_chat.ainvoke.return_value = MagicMock(
                content=json.dumps({
                    "app_name": "my-app",
                    "namespace": "prod",
                    "direction": None,
                    "org": None,
                    "platform": None,
                    "assembly": None,
                    "service_type": None,
                    "resource_group": None,
                    "subscription_id": None,
                    "database_name": None
                })
            )
            mock_llm.chat = mock_chat
            
            agent = DependencyAgent()
            state = {
                "query": "get deps for my-app in prod",
                "session_id": "test-123",
                "query_type": "wcnp",
                "conversation_history": [],
                "messages": []
            }
            
            result = await agent._parse_query(state)
            
            assert result["next_step"] == "fetch_wcnp"
            assert result["app_name"] == "my-app"
            assert result["namespace"] == "prod"

    @pytest.mark.asyncio
    async def test_parse_query_wcnp_namespace_only(self):
        """Test parse query routes to suggest_wcnp when only namespace present."""
        with patch("src.agent.agent.llm_client") as mock_llm:
            mock_chat = AsyncMock()
            mock_chat.ainvoke.return_value = MagicMock(
                content=json.dumps({
                    "app_name": None,
                    "namespace": "prod",
                    "direction": None,
                    "org": None,
                    "platform": None,
                    "assembly": None,
                    "service_type": None,
                    "resource_group": None,
                    "subscription_id": None,
                    "database_name": None
                })
            )
            mock_llm.chat = mock_chat
            
            agent = DependencyAgent()
            state = {
                "query": "get apps in prod",
                "session_id": "test-456",
                "query_type": "wcnp",
                "conversation_history": [],
                "messages": []
            }
            
            result = await agent._parse_query(state)
            
            assert result["next_step"] == "suggest_wcnp"

    @pytest.mark.asyncio
    async def test_parse_query_oneops(self):
        """Test parse query routes to fetch_oneops."""
        with patch("src.agent.agent.llm_client") as mock_llm:
            mock_chat = AsyncMock()
            mock_chat.ainvoke.return_value = MagicMock(
                content=json.dumps({
                    "app_name": None,
                    "namespace": None,
                    "direction": None,
                    "org": "mexicoecomm",
                    "platform": "rmsag2",
                    "assembly": "mx-rms",
                    "service_type": None,
                    "resource_group": None,
                    "subscription_id": None,
                    "database_name": None
                })
            )
            mock_llm.chat = mock_chat
            
            agent = DependencyAgent()
            state = {
                "query": "get deps for org=mexicoecomm platform=rmsag2 assembly=mx-rms",
                "session_id": "test-789",
                "query_type": "oneops",
                "conversation_history": [],
                "messages": []
            }
            
            result = await agent._parse_query(state)
            
            assert result["next_step"] == "fetch_oneops"

    @pytest.mark.asyncio
    async def test_parse_query_oneops_missing_params(self):
        """Test parse query errors when OneOps params missing."""
        with patch("src.agent.agent.llm_client") as mock_llm:
            mock_chat = AsyncMock()
            mock_chat.ainvoke.return_value = MagicMock(
                content=json.dumps({
                    "app_name": None,
                    "namespace": None,
                    "direction": None,
                    "org": "mexicoecomm",
                    "platform": None,
                    "assembly": None,
                    "service_type": None,
                    "resource_group": None,
                    "subscription_id": None,
                    "database_name": None
                })
            )
            mock_llm.chat = mock_chat
            
            agent = DependencyAgent()
            state = {
                "query": "oneops deps",
                "session_id": "test-missing",
                "query_type": "oneops",
                "conversation_history": [],
                "messages": []
            }
            
            result = await agent._parse_query(state)
            
            assert result["next_step"] == "error"
            assert "Missing OneOps parameters" in result["error"]

    @pytest.mark.asyncio
    async def test_parse_query_managed_service(self):
        """Test parse query routes to fetch_managed_service."""
        with patch("src.agent.agent.llm_client") as mock_llm:
            mock_chat = AsyncMock()
            mock_chat.ainvoke.return_value = MagicMock(
                content=json.dumps({
                    "app_name": None,
                    "namespace": None,
                    "direction": None,
                    "org": None,
                    "platform": "rmsag2",
                    "assembly": "mx-rms",
                    "service_type": "cassandra",
                    "resource_group": None,
                    "subscription_id": None,
                    "database_name": None
                })
            )
            mock_llm.chat = mock_chat
            
            agent = DependencyAgent()
            state = {
                "query": "cassandra deps assembly=mx-rms platform=rmsag2",
                "session_id": "test-managed",
                "query_type": "managed_service",
                "conversation_history": [],
                "messages": []
            }
            
            result = await agent._parse_query(state)
            
            assert result["next_step"] == "fetch_managed_service"

    @pytest.mark.asyncio
    async def test_parse_query_json_decode_error(self):
        """Test parse query handles JSON decode error."""
        with patch("src.agent.agent.llm_client") as mock_llm:
            mock_chat = AsyncMock()
            mock_chat.ainvoke.return_value = MagicMock(content="invalid json")
            mock_llm.chat = mock_chat
            
            agent = DependencyAgent()
            state = {
                "query": "test",
                "session_id": "test-json-error",
                "query_type": "wcnp",
                "conversation_history": [],
                "messages": []
            }
            
            result = await agent._parse_query(state)
            
            assert result["next_step"] == "error"
            assert "JSON" in result["error"]

    @pytest.mark.asyncio
    async def test_parse_query_generic_exception(self):
        """Test parse query handles generic exception."""
        with patch("src.agent.agent.llm_client") as mock_llm:
            mock_chat = AsyncMock()
            mock_chat.ainvoke.side_effect = Exception("LLM error")
            mock_llm.chat = mock_chat
            
            agent = DependencyAgent()
            state = {
                "query": "test",
                "session_id": "test-exception",
                "query_type": "wcnp",
                "conversation_history": [],
                "messages": []
            }
            
            result = await agent._parse_query(state)
            
            assert result["next_step"] == "error"
            assert "Failed to parse query" in result["error"]

    @pytest.mark.asyncio
    async def test_process_query_full_flow(self):
        """Test full process_query flow."""
        with patch("src.agent.agent.llm_client") as mock_llm, \
             patch("src.agent.agent.get_upstream_and_downstream_dependencies", new_callable=AsyncMock) as mock_deps:
            mock_chat = AsyncMock()
            mock_chat.ainvoke.return_value = MagicMock(
                content=json.dumps({
                    "app_name": "my-app",
                    "namespace": "prod",
                    "direction": None,
                    "org": None,
                    "platform": None,
                    "assembly": None,
                    "service_type": None,
                    "resource_group": None,
                    "subscription_id": None,
                    "database_name": None
                })
            )
            mock_llm.chat = mock_chat
            mock_deps.return_value = (
                [{"name": "up-dep"}],
                [{"name": "down-dep"}],
                {"upstream_count": 1, "downstream_count": 1, "total": 2}
            )
            
            agent = DependencyAgent()
            result = await agent.process_query(
                "get deps for my-app in prod",
                "session-123",
                query_type="wcnp"
            )
            
            assert result["success"] is True
            assert result["app_name"] == "my-app"
            assert result["namespace"] == "prod"
            assert len(result["dependencies"]) == 2


class TestDependencyAgentSingleton:
    """Tests for dependency_agent singleton."""

    def test_singleton_exists(self):
        """Test that singleton instance exists."""
        from src.agent.agent import dependency_agent
        assert dependency_agent is not None
        assert isinstance(dependency_agent, DependencyAgent)
