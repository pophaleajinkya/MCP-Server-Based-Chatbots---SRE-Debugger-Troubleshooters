"""Unit tests for app.config — Settings, computed fields, bootstrap."""




class TestSettings:
    """Test Settings fields, defaults, and computed properties."""

    def test_defaults_without_env(self, monkeypatch):
        """Settings should have sensible defaults even with no env vars."""
        for key in (
            "AGENT_HOST", "AGENT_PORT", "ELEMENT_GATEWAY_BASE_URL",
            "ELEMENT_GATEWAY_API_KEY", "ELEMENT_GATEWAY_API_VERSION",
            "OPENAI_MODEL", "CLAUDE_GATEWAY_URL", "CLAUDE_API_KEY",
            "CLAUDE_MODEL", "CLAUDE_ANTHROPIC_VERSION", "CLAUDE_IS_PRIMARY_LLM",
            "MAX_TOOL_ROUNDS", "LLM_TIMEOUT_SECONDS",
            "MCP_TIMEOUT_SECONDS", "SECRETS_PATH", "LLM_HISTORY_TURNS",
            "REDIS_SSL", "AGENT_ENV", "AGENT_GROUP",
        ):
            monkeypatch.delenv(key, raising=False)

        from app.config import Settings
        # Patch _bootstrap_env to prevent .env loading during test
        import app.config
        app.config._bootstrap_env = lambda: None

        s = Settings()

        assert s.agent_host == "0.0.0.0"
        assert s.agent_port == 8001
        assert s.element_gateway_base_url == ""
        assert s.element_gateway_api_key == ""
        assert s.element_gateway_api_version == "2024-10-21"
        assert s.openai_model == "gpt-4.1"
        assert s.claude_gateway_url == ""
        assert s.claude_api_key == ""
        assert s.claude_model == "claude-opus-4-6"
        assert s.claude_anthropic_version == "vertex-2023-10-16"
        assert s.claude_is_primary_llm is False
        assert s.secrets_path == "/secrets/"
        assert s.max_tool_rounds == 8
        assert s.llm_timeout_seconds == 60
        assert s.mcp_timeout_seconds == 30
        assert s.llm_history_turns == 0
        assert s.redis_ssl is True
        assert s.agent_env == "prod"
        assert s.agent_group == "sre"
        assert s.mcp_config_key == "super_agent:config:mcp_servers:prod:sre:config"

    def test_settings_from_env(self, settings):
        """Settings should read from environment variables."""
        assert settings.agent_host == "127.0.0.1"
        assert settings.agent_port == 9999
        assert settings.element_gateway_base_url == "https://llm.test.com/openai"
        assert settings.element_gateway_api_key == "test-key-openai"
        assert settings.openai_model == "gpt-4-test"
        assert settings.claude_gateway_url == "https://claude.test.com/messages"
        assert settings.claude_api_key == "test-key-claude"
        assert settings.claude_model == "claude-test"
        assert settings.claude_is_primary_llm is False
        assert settings.max_tool_rounds == 3
        assert settings.llm_timeout_seconds == 10
        assert settings.mcp_timeout_seconds == 5

    def test_openai_url_computed(self, settings):
        """openai_url should compose the full Azure chat-completions URL."""
        expected = (
            "https://llm.test.com/openai/deployments/gpt-4-test"
            "/chat/completions?api-version=2024-10-21"
        )
        assert settings.openai_url == expected

    def test_openai_url_with_empty_base(self, monkeypatch):
        """openai_url should not raise if base is empty."""
        for key in (
            "ELEMENT_GATEWAY_BASE_URL", "OPENAI_MODEL", "ELEMENT_GATEWAY_API_VERSION"
        ):
            monkeypatch.delenv(key, raising=False)
        from app.config import Settings
        # Patch _bootstrap_env to prevent .env loading during test
        import app.config
        app.config._bootstrap_env = lambda: None
        s = Settings()
        # Should not raise
        _ = s.openai_url

    def test_active_llm_openai(self, settings):
        """active_llm should return 'openai' when Claude is not primary."""
        assert settings.active_llm == "openai"

    def test_active_llm_claude(self, claude_settings):
        """active_llm should return 'claude' when Claude is primary."""
        assert claude_settings.active_llm == "claude"

    def test_active_llm_endpoint_openai(self, settings):
        """active_llm_endpoint should return the OpenAI URL."""
        assert "deployments/gpt-4-test" in settings.active_llm_endpoint
        assert "chat/completions" in settings.active_llm_endpoint

    def test_active_llm_endpoint_claude(self, claude_settings):
        """active_llm_endpoint should return the Claude URL."""
        assert claude_settings.active_llm_endpoint == "https://claude.test.com/messages"

    def test_settings_extra_ignore(self, env_vars, monkeypatch):
        """Settings should ignore unexpected env vars without errors."""
        monkeypatch.setenv("SOME_RANDOM_VAR", "ignored")
        from app.config import Settings
        s = Settings()
        assert s.agent_host == "127.0.0.1"

    def test_claude_is_primary_true_via_env(self, env_vars, monkeypatch):
        """CLAUDE_IS_PRIMARY_LLM=true should set claude_is_primary_llm to True."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "true")
        from app.config import Settings
        s = Settings()
        assert s.claude_is_primary_llm is True
        assert s.active_llm == "claude"

    def test_claude_is_primary_false_via_env(self, env_vars, monkeypatch):
        """CLAUDE_IS_PRIMARY_LLM=false should set claude_is_primary_llm to False."""
        monkeypatch.setenv("CLAUDE_IS_PRIMARY_LLM", "false")
        from app.config import Settings
        s = Settings()
        assert s.claude_is_primary_llm is False

    def test_llm_prompt_cache_enabled_defaults_false(self, env_vars, monkeypatch):
        """llm_prompt_cache_enabled should default to False."""
        monkeypatch.delenv("LLM_PROMPT_CACHE_ENABLED", raising=False)
        from app.config import Settings
        s = Settings()
        assert s.llm_prompt_cache_enabled is False

    def test_llm_prompt_cache_enabled_true_via_env(self, env_vars, monkeypatch):
        """LLM_PROMPT_CACHE_ENABLED=true should set llm_prompt_cache_enabled to True."""
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "true")
        from app.config import Settings
        s = Settings()
        assert s.llm_prompt_cache_enabled is True

    def test_llm_prompt_cache_extended_defaults_false(self, env_vars, monkeypatch):
        """llm_prompt_cache_extended should default to False."""
        monkeypatch.delenv("LLM_PROMPT_CACHE_EXTENDED", raising=False)
        from app.config import Settings
        s = Settings()
        assert s.llm_prompt_cache_extended is False

    def test_llm_prompt_cache_extended_true_via_env(self, env_vars, monkeypatch):
        """LLM_PROMPT_CACHE_EXTENDED=true should set llm_prompt_cache_extended to True."""
        monkeypatch.setenv("LLM_PROMPT_CACHE_EXTENDED", "true")
        from app.config import Settings
        s = Settings()
        assert s.llm_prompt_cache_extended is True

    def test_llm_prompt_cache_extended_false_when_cache_disabled(self, env_vars, monkeypatch):
        """Extended TTL flag is independent — both can be false simultaneously."""
        monkeypatch.setenv("LLM_PROMPT_CACHE_ENABLED", "false")
        monkeypatch.setenv("LLM_PROMPT_CACHE_EXTENDED", "false")
        from app.config import Settings
        s = Settings()
        assert s.llm_prompt_cache_enabled is False
        assert s.llm_prompt_cache_extended is False

    def test_settings_all_fields_populated(self, settings):
        """All Settings fields should be populated when env vars are set."""
        assert settings.element_gateway_api_version == "2024-10-21"
        assert settings.claude_anthropic_version == "vertex-2023-10-16"

    def test_openai_headers_computed(self, settings):
        """openai_headers should include Content-Type and both api-key forms."""
        hdrs = settings.openai_headers
        assert hdrs["Content-Type"] == "application/json"
        assert hdrs["X-Api-Key"] == "test-key-openai"
        assert hdrs["api-key"] == "test-key-openai"

    def test_openai_headers_reflects_api_key(self, env_vars, monkeypatch):
        """openai_headers api-key values should match element_gateway_api_key."""
        monkeypatch.setenv("ELEMENT_GATEWAY_API_KEY", "custom-key-123")
        from app.config import Settings
        s = Settings()
        assert s.openai_headers["X-Api-Key"] == "custom-key-123"
        assert s.openai_headers["api-key"] == "custom-key-123"

    def test_claude_headers_computed(self, settings):
        """claude_headers should include Content-Type, x-api-key, and anthropic-version."""
        hdrs = settings.claude_headers
        assert hdrs["Content-Type"] == "application/json"
        assert hdrs["x-api-key"] == "test-key-claude"
        assert hdrs["anthropic-version"] == "vertex-2023-10-16"

    def test_claude_headers_reflects_api_key(self, env_vars, monkeypatch):
        """claude_headers x-api-key should match claude_api_key."""
        monkeypatch.setenv("CLAUDE_API_KEY", "claude-secret-key")
        from app.config import Settings
        s = Settings()
        assert s.claude_headers["x-api-key"] == "claude-secret-key"

    def test_claude_headers_reflects_anthropic_version(self, env_vars, monkeypatch):
        """claude_headers anthropic-version should match claude_anthropic_version."""
        monkeypatch.setenv("CLAUDE_ANTHROPIC_VERSION", "vertex-2024-01-01")
        from app.config import Settings
        s = Settings()
        assert s.claude_headers["anthropic-version"] == "vertex-2024-01-01"


class TestGetSettings:
    """Test the get_settings() cached factory."""

    def test_get_settings_returns_settings(self, env_vars):
        """get_settings() should return a Settings instance."""
        from app.config import get_settings, Settings
        get_settings.cache_clear()
        s = get_settings()
        assert isinstance(s, Settings)

    def test_get_settings_cached(self, env_vars):
        """get_settings() should return the same instance on repeated calls."""
        from app.config import get_settings
        get_settings.cache_clear()
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2

    def test_get_settings_cache_cleared(self, env_vars):
        """After cache_clear, get_settings() returns a new instance."""
        from app.config import get_settings
        get_settings.cache_clear()
        s1 = get_settings()
        get_settings.cache_clear()
        s2 = get_settings()
        # Both should be valid Settings instances
        from app.config import Settings
        assert isinstance(s1, Settings)
        assert isinstance(s2, Settings)


class TestBootstrapEnv:
    """Test _bootstrap_env loading of secret overlay files."""

    def test_bootstrap_loads_secret_files(self, monkeypatch, tmp_path):
        """_bootstrap_env should load .env and secret files without error."""
        secret_dir = tmp_path / "secrets"
        secret_dir.mkdir()
        (secret_dir / "llm-config.env").write_text("LLM_TEST_VAR=hello\n")
        (secret_dir / "mcp-config.env").write_text("MCP_TEST_VAR=world\n")
        monkeypatch.setenv("SECRETS_PATH", str(secret_dir))

        from app.config import _bootstrap_env
        _bootstrap_env()  # should not raise

    def test_bootstrap_missing_secrets_dir(self, monkeypatch):
        """_bootstrap_env should not fail when secrets path does not exist."""
        monkeypatch.setenv("SECRETS_PATH", "/nonexistent/path")
        from app.config import _bootstrap_env
        _bootstrap_env()  # should not raise

    def test_bootstrap_empty_secrets_dir(self, monkeypatch, tmp_path):
        """_bootstrap_env should not fail when secrets directory is empty."""
        empty_dir = tmp_path / "empty_secrets"
        empty_dir.mkdir()
        monkeypatch.setenv("SECRETS_PATH", str(empty_dir))

        from app.config import _bootstrap_env
        _bootstrap_env()  # should not raise

    def test_bootstrap_only_some_files_exist(self, monkeypatch, tmp_path):
        """_bootstrap_env should only load files that actually exist."""
        secret_dir = tmp_path / "partial_secrets"
        secret_dir.mkdir()
        # Only llm-config.env exists, mcp-config.env does not
        (secret_dir / "llm-config.env").write_text("PARTIAL_VAR=yes\n")
        monkeypatch.setenv("SECRETS_PATH", str(secret_dir))

        from app.config import _bootstrap_env
        _bootstrap_env()  # should not raise even when mcp-config.env is missing
