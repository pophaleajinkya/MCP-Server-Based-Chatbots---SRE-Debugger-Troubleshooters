"""
Unit tests for app.store.keys — Redis key builder functions.

Verifies that every function returns the correct key string and that
the module-level constant MCP_SERVERS_KEY has the expected value.
No Redis connection is required.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestMCPServersKey:

    def test_mcp_servers_key_constant(self):
        from app.store.keys import MCP_SERVERS_KEY
        assert MCP_SERVERS_KEY == "agent:mcp_servers"


class TestKeySession:

    def test_key_session_format(self):
        from app.store.keys import key_session
        assert key_session("health_agent", "admin", "sess-1") == (
            "adk:session:health_agent:admin:sess-1"
        )

    def test_key_session_embeds_all_parts(self):
        from app.store.keys import key_session
        k = key_session("myapp", "user42", "session-xyz")
        assert "myapp" in k
        assert "user42" in k
        assert "session-xyz" in k

    def test_key_session_different_apps_produce_different_keys(self):
        from app.store.keys import key_session
        k1 = key_session("app_a", "u", "s")
        k2 = key_session("app_b", "u", "s")
        assert k1 != k2


class TestKeyEvents:

    def test_key_events_format(self):
        from app.store.keys import key_events
        assert key_events("health_agent", "admin", "sess-1") == (
            "adk:events:health_agent:admin:sess-1"
        )

    def test_key_events_different_sessions_produce_different_keys(self):
        from app.store.keys import key_events
        k1 = key_events("app", "u", "s1")
        k2 = key_events("app", "u", "s2")
        assert k1 != k2


class TestKeyAppState:

    def test_key_app_state_format(self):
        from app.store.keys import key_app_state
        assert key_app_state("health_agent") == "adk:app_state:health_agent"

    def test_key_app_state_embeds_app_name(self):
        from app.store.keys import key_app_state
        k = key_app_state("my_custom_app")
        assert "my_custom_app" in k

    def test_key_app_state_different_apps_differ(self):
        from app.store.keys import key_app_state
        assert key_app_state("app_a") != key_app_state("app_b")


class TestKeyUserState:

    def test_key_user_state_format(self):
        from app.store.keys import key_user_state
        assert key_user_state("health_agent", "alice") == (
            "adk:user_state:health_agent:alice"
        )

    def test_key_user_state_embeds_app_and_uid(self):
        from app.store.keys import key_user_state
        k = key_user_state("health_agent", "bob")
        assert "health_agent" in k
        assert "bob" in k

    def test_key_user_state_different_users_differ(self):
        from app.store.keys import key_user_state
        k1 = key_user_state("app", "alice")
        k2 = key_user_state("app", "bob")
        assert k1 != k2


class TestKeySessionsIndex:

    def test_key_sessions_index_format(self):
        from app.store.keys import key_sessions_index
        assert key_sessions_index("health_agent", "admin") == (
            "adk:sessions:health_agent:admin"
        )


class TestKeyUiEvents:

    def test_key_ui_events_format(self):
        from app.store.keys import key_ui_events
        assert key_ui_events("health_agent", "admin", "sess-1") == (
            "agent:ui_events:health_agent:admin:sess-1"
        )

    def test_key_ui_events_differs_from_adk_events(self):
        from app.store.keys import key_ui_events, key_events
        k_ui = key_ui_events("app", "u", "s")
        k_adk = key_events("app", "u", "s")
        assert k_ui != k_adk


class TestKeyNoCollisions:
    """No two distinct key builders should produce the same string."""

    def test_session_and_events_keys_differ(self):
        from app.store.keys import key_session, key_events
        assert key_session("a", "u", "s") != key_events("a", "u", "s")

    def test_app_state_and_user_state_differ(self):
        from app.store.keys import key_app_state, key_user_state
        assert key_app_state("a") != key_user_state("a", "u")

    def test_sessions_index_and_session_differ(self):
        from app.store.keys import key_sessions_index, key_session
        assert key_sessions_index("a", "u") != key_session("a", "u", "s")
