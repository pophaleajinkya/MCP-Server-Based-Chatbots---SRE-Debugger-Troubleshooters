"""Unit tests for src/utils/llm_client.py"""
import pytest
from unittest.mock import patch, MagicMock
import httpx

from src.utils.llm_client import LLMClient


class TestLLMClientInit:
    """Tests for LLMClient initialization."""

    def test_init_with_defaults(self):
        """Test client initialization with default settings from environment."""
        # The client uses settings from the environment which are already set in conftest.py
        # We test that the client initializes with values (not null)
        from src.utils.llm_client import LLMClient
        
        client = LLMClient()
        
        # Verify client has required attributes
        assert client.api_key is not None
        assert client.endpoint is not None
        assert client.embedding_model is not None
        assert client.chat_model is not None
        assert client.client is not None

    def test_init_with_custom_params(self):
        """Test client initialization with custom parameters."""
        with patch("src.utils.llm_client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                AZURE_OPENAI_API_KEY="default-key",
                AZURE_OPENAI_ENDPOINT="https://default.openai.azure.com",
                AZURE_EMBEDDING_MODEL="default-embed",
                AZURE_OPENAI_MODEL="default-chat",
                AZURE_OPENAI_API_VERSION="2024-10-21"
            )
            
            client = LLMClient(
                api_key="custom-key",
                endpoint="https://custom.openai.azure.com",
                embedding_model="custom-embed",
                chat_model="custom-chat"
            )
            
            assert client.api_key == "custom-key"
            assert client.endpoint == "https://custom.openai.azure.com"
            assert client.embedding_model == "custom-embed"
            assert client.chat_model == "custom-chat"


class TestLLMClientAsyncClient:
    """Tests for async client property."""

    def test_async_client_lazy_initialization(self):
        """Test that async client is lazily initialized."""
        with patch("src.utils.llm_client.get_settings") as mock_settings, \
             patch("src.utils.llm_client.AsyncAzureOpenAI") as mock_async_openai, \
             patch("src.utils.llm_client.httpx.AsyncClient"):
            mock_settings.return_value = MagicMock(
                AZURE_OPENAI_API_KEY="test-key",
                AZURE_OPENAI_ENDPOINT="https://test.openai.azure.com",
                AZURE_EMBEDDING_MODEL="embed",
                AZURE_OPENAI_MODEL="chat",
                AZURE_OPENAI_API_VERSION="2024-10-21"
            )
            mock_async_openai.return_value = MagicMock()
            
            client = LLMClient()
            
            # First access creates the client
            _ = client.async_client
            assert mock_async_openai.called
            
            # Second access reuses existing
            mock_async_openai.reset_mock()
            _ = client.async_client
            assert not mock_async_openai.called


class TestLLMClientChatClient:
    """Tests for chat client property."""

    def test_chat_client_lazy_initialization(self):
        """Test that chat client is lazily initialized."""
        with patch("src.utils.llm_client.get_settings") as mock_settings, \
             patch("src.utils.llm_client.AzureChatOpenAI") as mock_chat_openai, \
             patch("src.utils.llm_client.httpx.AsyncClient"):
            mock_settings.return_value = MagicMock(
                AZURE_OPENAI_API_KEY="test-key",
                AZURE_OPENAI_ENDPOINT="https://test.openai.azure.com",
                AZURE_EMBEDDING_MODEL="embed",
                AZURE_OPENAI_MODEL="gpt-4.1",
                AZURE_OPENAI_API_VERSION="2024-10-21"
            )
            mock_chat_openai.return_value = MagicMock()
            
            client = LLMClient()
            
            # First access creates the client
            _ = client.chat
            assert mock_chat_openai.called
            
            # Verify parameters
            call_kwargs = mock_chat_openai.call_args[1]
            assert call_kwargs["azure_deployment"] == "gpt-4.1"
            assert call_kwargs["temperature"] == 0


class TestLLMClientModel:
    """Tests for model property."""

    def test_model_returns_chat_model(self):
        """Test that model property returns chat model name."""
        with patch("src.utils.llm_client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                AZURE_OPENAI_API_KEY="test-key",
                AZURE_OPENAI_ENDPOINT="https://test.openai.azure.com",
                AZURE_EMBEDDING_MODEL="embed",
                AZURE_OPENAI_MODEL="gpt-4.1",
                AZURE_OPENAI_API_VERSION="2024-10-21"
            )
            
            client = LLMClient()
            
            assert client.model == "gpt-4.1"


class TestLLMClientEmbeddings:
    """Tests for generate_embedding method."""

    def test_generate_embedding_success(self):
        """Test successful embedding generation."""
        with patch("src.utils.llm_client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                AZURE_OPENAI_API_KEY="test-key",
                AZURE_OPENAI_ENDPOINT="https://test.openai.azure.com",
                AZURE_EMBEDDING_MODEL="text-embedding-ada-002",
                AZURE_OPENAI_MODEL="gpt-4.1",
                AZURE_OPENAI_API_VERSION="2024-10-21"
            )
            
            mock_embedding_item1 = MagicMock()
            mock_embedding_item1.embedding = [0.1, 0.2, 0.3]
            mock_embedding_item2 = MagicMock()
            mock_embedding_item2.embedding = [0.4, 0.5, 0.6]
            
            mock_response = MagicMock()
            mock_response.data = [mock_embedding_item1, mock_embedding_item2]
            
            client = LLMClient()
            client.client = MagicMock()
            client.client.embeddings.create.return_value = mock_response
            
            result = client.generate_embedding(["query1", "query2"])
            
            assert len(result) == 2
            assert result[0] == [0.1, 0.2, 0.3]
            assert result[1] == [0.4, 0.5, 0.6]

    def test_generate_embedding_error(self):
        """Test embedding generation error handling."""
        with patch("src.utils.llm_client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                AZURE_OPENAI_API_KEY="test-key",
                AZURE_OPENAI_ENDPOINT="https://test.openai.azure.com",
                AZURE_EMBEDDING_MODEL="text-embedding-ada-002",
                AZURE_OPENAI_MODEL="gpt-4.1",
                AZURE_OPENAI_API_VERSION="2024-10-21"
            )
            
            client = LLMClient()
            client.client = MagicMock()
            client.client.embeddings.create.side_effect = Exception("API Error")
            
            result = client.generate_embedding(["query"])
            
            assert result == []

    def test_generate_embedding_empty_input(self):
        """Test embedding generation with empty input."""
        with patch("src.utils.llm_client.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                AZURE_OPENAI_API_KEY="test-key",
                AZURE_OPENAI_ENDPOINT="https://test.openai.azure.com",
                AZURE_EMBEDDING_MODEL="text-embedding-ada-002",
                AZURE_OPENAI_MODEL="gpt-4.1",
                AZURE_OPENAI_API_VERSION="2024-10-21"
            )
            
            mock_response = MagicMock()
            mock_response.data = []
            
            client = LLMClient()
            client.client = MagicMock()
            client.client.embeddings.create.return_value = mock_response
            
            result = client.generate_embedding([])
            
            assert result == []


class TestModuleLevelFunctions:
    """Tests for module-level functions and instances."""

    def test_default_client_exists(self):
        """Test that default_client is created."""
        from src.utils.llm_client import default_client
        assert default_client is not None

    def test_llm_client_global_instance(self):
        """Test that llm_client global instance exists."""
        from src.utils.llm_client import llm_client
        assert llm_client is not None

    def test_generate_embedding_function(self):
        """Test module-level generate_embedding function."""
        from src.utils.llm_client import generate_embedding
        assert callable(generate_embedding)
