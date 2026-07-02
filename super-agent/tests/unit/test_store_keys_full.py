"""
Comprehensive unit tests for app.store.keys — 100% coverage.

Tests every key builder function and both module-level constants.
Validates key format, component embedding, collision prevention,
and special character handling.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.store.keys import (
    A2A_AGENTS_KEY,
    MCP_SERVERS_KEY,
    key_app_state,
    key_events,
    key_idem_inject,
    key_llm_pending,
    key_session,
    key_session_meta,
    key_session_shared,
    key_session_visibility,
    key_sessions_index,
    key_sessions_public,
    key_sessions_zset,
    key_ui_events,
    key_ui_stream,
)


# ── Constants ─────────────────────────────────────────────────────────────────

class TestConstants:

    def test_mcp_servers_key_value(self):
        assert MCP_SERVERS_KEY == "agent:mcp_servers"

    def test_a2a_agents_key_value(self):
        assert A2A_AGENTS_KEY == "agent:a2a_agents"

    def test_constants_are_strings(self):
        assert isinstance(MCP_SERVERS_KEY, str)
        assert isinstance(A2A_AGENTS_KEY, str)

    def test_constants_differ(self):
        assert MCP_SERVERS_KEY != A2A_AGENTS_KEY


# ── key_session ───────────────────────────────────────────────────────────────

class TestKeySession:

    def test_format(self):
        assert key_session("health_agent", "admin", "s1") == "adk:session:health_agent:admin:s1"

    def test_embeds_all_parts(self):
        k = key_session("myapp", "user42", "session-xyz")
        assert "myapp" in k and "user42" in k and "session-xyz" in k

    def test_different_apps_differ(self):
        assert key_session("a", "u", "s") != key_session("b", "u", "s")

    def test_different_users_differ(self):
        assert key_session("a", "u1", "s") != key_session("a", "u2", "s")

    def test_different_sessions_differ(self):
        assert key_session("a", "u", "s1") != key_session("a", "u", "s2")


# ── key_events ────────────────────────────────────────────────────────────────

class TestKeyEvents:

    def test_format(self):
        assert key_events("ha", "admin", "s1") == "adk:events:ha:admin:s1"

    def test_differs_from_session(self):
        assert key_events("a", "u", "s") != key_session("a", "u", "s")


# ── key_app_state ─────────────────────────────────────────────────────────────

class TestKeyAppState:

    def test_format(self):
        assert key_app_state("health_agent") == "adk:app_state:health_agent"

    def test_different_apps_differ(self):
        assert key_app_state("a") != key_app_state("b")


# ── key_user_state ────────────────────────────────────────────────────────────

class TestKeyUserState:

    def test_format(self):
        from app.store.keys import key_user_state
        assert key_user_state("ha", "alice") == "adk:user_state:ha:alice"

    def test_different_users_differ(self):
        from app.store.keys import key_user_state
        assert key_user_state("a", "u1") != key_user_state("a", "u2")


# ── key_sessions_index ────────────────────────────────────────────────────────

class TestKeySessionsIndex:

    def test_format(self):
        assert key_sessions_index("ha", "admin") == "adk:sessions:ha:admin"


# ── key_sessions_zset (previously untested) ───────────────────────────────────

class TestKeySessionsZset:

    def test_format(self):
        assert key_sessions_zset("ha", "admin") == "adk:sessions_z:ha:admin"

    def test_differs_from_legacy_index(self):
        assert key_sessions_zset("a", "u") != key_sessions_index("a", "u")

    def test_embeds_user(self):
        assert "bob" in key_sessions_zset("app", "bob")


# ── key_session_meta (previously untested) ────────────────────────────────────

class TestKeySessionMeta:

    def test_format(self):
        assert key_session_meta("ha", "admin") == "adk:session_meta:ha:admin"

    def test_embeds_app_and_uid(self):
        k = key_session_meta("myapp", "alice")
        assert "myapp" in k and "alice" in k

    def test_differs_from_zset(self):
        assert key_session_meta("a", "u") != key_sessions_zset("a", "u")


# ── key_sessions_public (previously untested) ─────────────────────────────────

class TestKeySessionsPublic:

    def test_format(self):
        assert key_sessions_public("ha") == "adk:sessions_public:ha"

    def test_embeds_app(self):
        assert "myapp" in key_sessions_public("myapp")


# ── key_session_visibility (previously untested) ──────────────────────────────

class TestKeySessionVisibility:

    def test_format(self):
        assert key_session_visibility("ha", "s1") == "agent:session_visibility:ha:s1"

    def test_embeds_session_id(self):
        k = key_session_visibility("app", "sess-abc-123")
        assert "sess-abc-123" in k


# ── key_session_shared (previously untested) ──────────────────────────────────

class TestKeySessionShared:

    def test_format(self):
        assert key_session_shared("ha", "s1") == "agent:session_shared:ha:s1"

    def test_differs_from_visibility(self):
        assert key_session_shared("a", "s") != key_session_visibility("a", "s")


# ── key_ui_events ─────────────────────────────────────────────────────────────

class TestKeyUiEvents:

    def test_format(self):
        assert key_ui_events("ha", "admin", "s1") == "agent:ui_events:ha:admin:s1"

    def test_differs_from_adk_events(self):
        assert key_ui_events("a", "u", "s") != key_events("a", "u", "s")


# ── key_ui_stream (previously untested) ───────────────────────────────────────

class TestKeyUiStream:

    def test_format(self):
        assert key_ui_stream("ha", "admin", "s1") == "agent:ui_stream:ha:admin:s1"

    def test_differs_from_ui_events(self):
        assert key_ui_stream("a", "u", "s") != key_ui_events("a", "u", "s")

    def test_embeds_all_parts(self):
        k = key_ui_stream("myapp", "alice", "sess99")
        assert "myapp" in k and "alice" in k and "sess99" in k


# ── key_llm_pending (previously untested) ─────────────────────────────────────

class TestKeyLlmPending:

    def test_format(self):
        assert key_llm_pending("ha", "admin", "s1") == "agent:llm_pending:ha:admin:s1"

    def test_differs_from_ui_stream(self):
        assert key_llm_pending("a", "u", "s") != key_ui_stream("a", "u", "s")


# ── key_idem_inject (previously untested) ─────────────────────────────────────

class TestKeyIdemInject:

    def test_format(self):
        assert key_idem_inject("ha", "admin", "s1", "key1") == (
            "agent:idem_inject:ha:admin:s1:key1"
        )

    def test_embeds_idem_key(self):
        k = key_idem_inject("a", "u", "s", "lc:INC123:verdict:3")
        assert "lc:INC123:verdict:3" in k

    def test_different_idem_keys_differ(self):
        k1 = key_idem_inject("a", "u", "s", "key1")
        k2 = key_idem_inject("a", "u", "s", "key2")
        assert k1 != k2

    def test_different_sessions_differ(self):
        k1 = key_idem_inject("a", "u", "s1", "key")
        k2 = key_idem_inject("a", "u", "s2", "key")
        assert k1 != k2


# ── Cross-function collision tests ────────────────────────────────────────────

class TestNoCollisions:
    """Ensure no two distinct key builders produce the same string for equal inputs."""

    def test_all_three_arg_builders_differ(self):
        """All (app, uid, sid) builders must produce unique keys."""
        builders = [key_session, key_events, key_ui_events, key_ui_stream, key_llm_pending]
        keys = [fn("a", "u", "s") for fn in builders]
        assert len(keys) == len(set(keys)), f"Collision detected among {keys}"

    def test_two_arg_builders_differ(self):
        """All (app, uid) builders must produce unique keys."""
        builders = [key_sessions_index, key_sessions_zset, key_session_meta]
        keys = [fn("a", "u") for fn in builders]
        assert len(keys) == len(set(keys))

    def test_visibility_and_shared_differ(self):
        assert key_session_visibility("a", "s") != key_session_shared("a", "s")


# ── Special character handling ────────────────────────────────────────────────

class TestSpecialCharacters:

    def test_email_as_uid(self):
        k = key_session("app", "user@walmart.com", "s1")
        assert "user@walmart.com" in k

    def test_uuid_as_sid(self):
        sid = "550e8400-e29b-41d4-a716-446655440000"
        k = key_session("app", "u", sid)
        assert sid in k

    def test_slash_in_app_name(self):
        k = key_app_state("org/app")
        assert "org/app" in k

    def test_colon_in_idem_key(self):
        k = key_idem_inject("a", "u", "s", "lc:INC:v:fp:3")
        assert "lc:INC:v:fp:3" in k
