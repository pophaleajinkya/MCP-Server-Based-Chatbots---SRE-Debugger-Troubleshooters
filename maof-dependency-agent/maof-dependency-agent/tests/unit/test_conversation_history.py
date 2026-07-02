"""Unit tests for src/services/conversation_history.py"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

from src.services.conversation_history import get_conversation_history


class TestGetConversationHistory:
    """Tests for get_conversation_history function."""

    @pytest.mark.asyncio
    async def test_get_history_success_list_response(self):
        """Test successful retrieval with list response format."""
        mock_conversations = [
            {"role": "user", "content": "get apps in prod"},
            {"role": "assistant", "content": "Found 10 apps"},
        ]
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = str(mock_conversations)
        mock_response.json.return_value = mock_conversations
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await get_conversation_history("session-123", limit=5)
            
            assert len(result) == 2
            assert result[0]["role"] == "user"
            assert result[1]["role"] == "assistant"

    @pytest.mark.asyncio
    async def test_get_history_success_dict_response_with_responses(self):
        """Test successful retrieval with dict response containing 'responses'."""
        mock_conversations = [
            {"role": "user", "content": "test query"},
        ]
        mock_response_data = {
            "session_id": "session-123",
            "responses": mock_conversations
        }
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = str(mock_response_data)
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await get_conversation_history("session-123")
            
            assert len(result) == 1
            assert result[0]["role"] == "user"

    @pytest.mark.asyncio
    async def test_get_history_dict_without_responses_key(self):
        """Test dict response without 'responses' key returns empty list."""
        mock_response_data = {
            "session_id": "session-123",
            "other_data": "something"
        }
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = str(mock_response_data)
        mock_response.json.return_value = mock_response_data
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await get_conversation_history("session-123")
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_history_empty_list(self):
        """Test retrieval returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await get_conversation_history("session-456")
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_history_unexpected_type(self):
        """Test retrieval with unexpected response type returns empty list."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "unexpected"
        mock_response.json.return_value = "string instead of list or dict"
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await get_conversation_history("session-789")
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_history_http_status_error(self):
        """Test handling of HTTP status error."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = httpx.HTTPStatusError(
                "Server error",
                request=MagicMock(),
                response=mock_response
            )
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await get_conversation_history("session-error")
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_history_request_error(self):
        """Test handling of request error (connection issues)."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = httpx.RequestError("Connection failed")
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await get_conversation_history("session-conn-error")
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_history_generic_exception(self):
        """Test handling of generic exception."""
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.side_effect = Exception("Unexpected error")
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            result = await get_conversation_history("session-unexpected")
            
            assert result == []

    @pytest.mark.asyncio
    async def test_get_history_default_limit(self):
        """Test default limit parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            await get_conversation_history("session-123")
            
            # Verify the call was made with default limit of 10
            call_args = mock_instance.post.call_args
            assert call_args[1]["json"]["limit"] == "10"

    @pytest.mark.asyncio
    async def test_get_history_custom_limit(self):
        """Test custom limit parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            await get_conversation_history("session-123", limit=20)
            
            call_args = mock_instance.post.call_args
            assert call_args[1]["json"]["limit"] == "20"

    @pytest.mark.asyncio
    async def test_get_history_correct_payload(self):
        """Test that correct payload is sent to API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "[]"
        mock_response.json.return_value = []
        mock_response.raise_for_status = MagicMock()
        
        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.post.return_value = mock_response
            mock_client.return_value.__aenter__.return_value = mock_instance
            
            await get_conversation_history("test-session-id", limit=5)
            
            call_args = mock_instance.post.call_args
            payload = call_args[1]["json"]
            
            assert payload["session_id"] == "test-session-id"
            assert payload["action"] == "user_conversation"
            assert payload["role"] == "all"
            assert payload["limit"] == "5"
