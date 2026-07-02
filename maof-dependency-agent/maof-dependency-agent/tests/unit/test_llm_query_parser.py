"""Unit tests for src/services/llm_query_parser.py"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import json

from src.services.llm_query_parser import LLMQueryParser


class TestLLMQueryParser:
    """Tests for LLMQueryParser class."""

    def test_parser_initialization(self):
        """Test parser initializes with LLM client."""
        with patch("src.services.llm_query_parser.llm_client") as mock_llm:
            mock_llm.async_client = MagicMock()
            mock_llm.model = "gpt-4.1"
            
            parser = LLMQueryParser()
            
            assert parser.client is not None
            assert parser.model == "gpt-4.1"

    @pytest.mark.asyncio
    async def test_parse_query_success(self):
        """Test successful query parsing."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({
                        "app_name": "payment-service",
                        "namespace": "production",
                        "confidence": 0.95,
                        "reasoning": "Found appName and namespace in query"
                    })
                )
            )
        ]
        
        with patch("src.services.llm_query_parser.llm_client") as mock_llm:
            mock_async_client = AsyncMock()
            mock_async_client.chat.completions.create.return_value = mock_response
            mock_llm.async_client = mock_async_client
            mock_llm.model = "gpt-4.1"
            
            parser = LLMQueryParser()
            result = await parser.parse_query(
                "get dependencies for payment-service in production",
                "session-123"
            )
            
            assert result["app_name"] == "payment-service"
            assert result["namespace"] == "production"
            assert result["tool_name"] == "get_app_dependencies"

    @pytest.mark.asyncio
    async def test_parse_query_partial_extraction(self):
        """Test parsing with partial parameters extracted."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({
                        "app_name": None,
                        "namespace": "staging",
                        "confidence": 0.7,
                        "reasoning": "Only namespace found"
                    })
                )
            )
        ]
        
        with patch("src.services.llm_query_parser.llm_client") as mock_llm:
            mock_async_client = AsyncMock()
            mock_async_client.chat.completions.create.return_value = mock_response
            mock_llm.async_client = mock_async_client
            mock_llm.model = "gpt-4.1"
            
            parser = LLMQueryParser()
            result = await parser.parse_query(
                "get apps in staging",
                "session-456"
            )
            
            assert result["app_name"] is None
            assert result["namespace"] == "staging"

    @pytest.mark.asyncio
    async def test_parse_query_api_error(self):
        """Test handling of API error during parsing."""
        with patch("src.services.llm_query_parser.llm_client") as mock_llm:
            mock_async_client = AsyncMock()
            mock_async_client.chat.completions.create.side_effect = Exception("API Error")
            mock_llm.async_client = mock_async_client
            mock_llm.model = "gpt-4.1"
            
            parser = LLMQueryParser()
            result = await parser.parse_query(
                "test query",
                "session-error"
            )
            
            assert result["app_name"] is None
            assert result["namespace"] is None
            assert result["response"] == "test query"

    @pytest.mark.asyncio
    async def test_parse_query_json_decode_error(self):
        """Test handling of invalid JSON response."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(content="not valid json")
            )
        ]
        
        with patch("src.services.llm_query_parser.llm_client") as mock_llm:
            mock_async_client = AsyncMock()
            mock_async_client.chat.completions.create.return_value = mock_response
            mock_llm.async_client = mock_async_client
            mock_llm.model = "gpt-4.1"
            
            parser = LLMQueryParser()
            result = await parser.parse_query(
                "test query",
                "session-json-error"
            )
            
            assert result["app_name"] is None
            assert result["namespace"] is None

    @pytest.mark.asyncio
    async def test_parse_query_result_structure(self):
        """Test that result has expected structure."""
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({
                        "app_name": "my-app",
                        "namespace": "prod"
                    })
                )
            )
        ]
        
        with patch("src.services.llm_query_parser.llm_client") as mock_llm:
            mock_async_client = AsyncMock()
            mock_async_client.chat.completions.create.return_value = mock_response
            mock_llm.async_client = mock_async_client
            mock_llm.model = "gpt-4.1"
            
            parser = LLMQueryParser()
            result = await parser.parse_query("test", "session")
            
            # Verify all expected keys are present
            assert "agent_name" in result
            assert "description" in result
            assert "response" in result
            assert "app_name" in result
            assert "namespace" in result
            assert "tool_name" in result

    @pytest.mark.asyncio
    async def test_parse_query_long_query_truncated_in_log(self):
        """Test that long queries work correctly."""
        long_query = "get dependencies for payment-service in production " * 10
        
        mock_response = MagicMock()
        mock_response.choices = [
            MagicMock(
                message=MagicMock(
                    content=json.dumps({
                        "app_name": "payment-service",
                        "namespace": "production"
                    })
                )
            )
        ]
        
        with patch("src.services.llm_query_parser.llm_client") as mock_llm:
            mock_async_client = AsyncMock()
            mock_async_client.chat.completions.create.return_value = mock_response
            mock_llm.async_client = mock_async_client
            mock_llm.model = "gpt-4.1"
            
            parser = LLMQueryParser()
            result = await parser.parse_query(long_query, "session-long")
            
            assert result["app_name"] == "payment-service"
