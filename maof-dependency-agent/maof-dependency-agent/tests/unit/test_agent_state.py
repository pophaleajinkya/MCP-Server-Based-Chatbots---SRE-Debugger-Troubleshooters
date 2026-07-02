"""Unit tests for src/models/agent_state.py"""
import pytest
from src.models.agent_state import DependencyAgentState


class TestDependencyAgentState:
    """Tests for DependencyAgentState TypedDict."""

    def test_state_type_is_typed_dict(self):
        """Test that DependencyAgentState is a TypedDict."""
        # TypedDict is a dict subclass at runtime
        state: DependencyAgentState = {
            "query": "test query",
            "session_id": "session-123",
            "conversation_history": None,
            "query_type": "wcnp",
            "app_name": "test-app",
            "namespace": "prod",
            "available_apps": None,
            "org": None,
            "platform": None,
            "assembly": None,
            "service_type": None,
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "direction": None,
            "dependencies": [],
            "upstream_dependencies": None,
            "downstream_dependencies": None,
            "source_breakdown": {},
            "messages": [],
            "error": None,
            "next_step": "",
        }
        assert isinstance(state, dict)
        assert state["query"] == "test query"
        assert state["session_id"] == "session-123"

    def test_wcnp_state_fields(self):
        """Test WCNP-related state fields."""
        state: DependencyAgentState = {
            "query": "get deps for payment-service in prod",
            "session_id": "session-456",
            "conversation_history": [],
            "query_type": "wcnp",
            "app_name": "payment-service",
            "namespace": "prod",
            "available_apps": ["app1", "app2"],
            "org": None,
            "platform": None,
            "assembly": None,
            "service_type": None,
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "direction": "upstream",
            "dependencies": [{"name": "dep1"}],
            "upstream_dependencies": [{"name": "up1"}],
            "downstream_dependencies": None,
            "source_breakdown": {"upstream_count": 1},
            "messages": ["Found 1 dependency"],
            "error": None,
            "next_step": "fetch_wcnp",
        }
        assert state["app_name"] == "payment-service"
        assert state["namespace"] == "prod"
        assert state["available_apps"] == ["app1", "app2"]
        assert state["direction"] == "upstream"

    def test_oneops_state_fields(self):
        """Test OneOps-related state fields."""
        state: DependencyAgentState = {
            "query": "get deps for org=mexicoecomm platform=rmsag2 assembly=mx-rms",
            "session_id": "session-789",
            "conversation_history": None,
            "query_type": "oneops",
            "app_name": None,
            "namespace": None,
            "available_apps": None,
            "org": "mexicoecomm",
            "platform": "rmsag2",
            "assembly": "mx-rms",
            "service_type": None,
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "direction": None,
            "dependencies": [],
            "upstream_dependencies": None,
            "downstream_dependencies": None,
            "source_breakdown": {},
            "messages": [],
            "error": None,
            "next_step": "fetch_oneops",
        }
        assert state["org"] == "mexicoecomm"
        assert state["platform"] == "rmsag2"
        assert state["assembly"] == "mx-rms"
        assert state["query_type"] == "oneops"

    def test_managed_service_cassandra_state(self):
        """Test Managed Service (Cassandra) state fields."""
        state: DependencyAgentState = {
            "query": "cassandra deps assembly=mx-rms platform=rmsag2",
            "session_id": "session-cassandra",
            "conversation_history": None,
            "query_type": "managed_service",
            "app_name": None,
            "namespace": None,
            "available_apps": None,
            "org": None,
            "platform": "rmsag2",
            "assembly": "mx-rms",
            "service_type": "cassandra",
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "direction": None,
            "dependencies": [],
            "upstream_dependencies": None,
            "downstream_dependencies": None,
            "source_breakdown": {},
            "messages": [],
            "error": None,
            "next_step": "fetch_managed_service",
        }
        assert state["service_type"] == "cassandra"
        assert state["platform"] == "rmsag2"
        assert state["assembly"] == "mx-rms"

    def test_managed_service_cosmos_state(self):
        """Test Managed Service (Cosmos) state fields."""
        state: DependencyAgentState = {
            "query": "cosmos deps resourceGroup=my-rg subscriptionId=sub-123 databaseName=orders-db",
            "session_id": "session-cosmos",
            "conversation_history": None,
            "query_type": "managed_service",
            "app_name": None,
            "namespace": None,
            "available_apps": None,
            "org": None,
            "platform": None,
            "assembly": None,
            "service_type": "cosmos",
            "resource_group": "my-rg",
            "subscription_id": "sub-123",
            "database_name": "orders-db",
            "direction": None,
            "dependencies": [],
            "upstream_dependencies": None,
            "downstream_dependencies": None,
            "source_breakdown": {},
            "messages": [],
            "error": None,
            "next_step": "fetch_managed_service",
        }
        assert state["service_type"] == "cosmos"
        assert state["resource_group"] == "my-rg"
        assert state["subscription_id"] == "sub-123"
        assert state["database_name"] == "orders-db"

    def test_error_state(self):
        """Test state with error."""
        state: DependencyAgentState = {
            "query": "invalid query",
            "session_id": "session-error",
            "conversation_history": None,
            "query_type": "wcnp",
            "app_name": None,
            "namespace": None,
            "available_apps": None,
            "org": None,
            "platform": None,
            "assembly": None,
            "service_type": None,
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "direction": None,
            "dependencies": [],
            "upstream_dependencies": None,
            "downstream_dependencies": None,
            "source_breakdown": {},
            "messages": ["Parse error"],
            "error": "Could not extract parameters",
            "next_step": "error",
        }
        assert state["error"] == "Could not extract parameters"
        assert state["next_step"] == "error"

    def test_conversation_history_field(self):
        """Test conversation history field."""
        history = [
            {"role": "user", "content": "get apps in prod"},
            {"role": "assistant", "content": "Found 10 apps"}
        ]
        state: DependencyAgentState = {
            "query": "get deps for app1",
            "session_id": "session-history",
            "conversation_history": history,
            "query_type": "wcnp",
            "app_name": "app1",
            "namespace": "prod",
            "available_apps": None,
            "org": None,
            "platform": None,
            "assembly": None,
            "service_type": None,
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "direction": None,
            "dependencies": [],
            "upstream_dependencies": None,
            "downstream_dependencies": None,
            "source_breakdown": {},
            "messages": [],
            "error": None,
            "next_step": "fetch_wcnp",
        }
        assert state["conversation_history"] == history
        assert len(state["conversation_history"]) == 2

    def test_dependencies_with_data(self):
        """Test state with populated dependencies."""
        deps = [
            {"name": "dep1", "direction": "upstream"},
            {"name": "dep2", "direction": "downstream"},
        ]
        state: DependencyAgentState = {
            "query": "get all deps",
            "session_id": "session-deps",
            "conversation_history": None,
            "query_type": "wcnp",
            "app_name": "my-app",
            "namespace": "prod",
            "available_apps": None,
            "org": None,
            "platform": None,
            "assembly": None,
            "service_type": None,
            "resource_group": None,
            "subscription_id": None,
            "database_name": None,
            "direction": None,
            "dependencies": deps,
            "upstream_dependencies": [deps[0]],
            "downstream_dependencies": [deps[1]],
            "source_breakdown": {"upstream_count": 1, "downstream_count": 1, "total": 2},
            "messages": ["Found 2 deps"],
            "error": None,
            "next_step": "format_response",
        }
        assert len(state["dependencies"]) == 2
        assert state["source_breakdown"]["total"] == 2
