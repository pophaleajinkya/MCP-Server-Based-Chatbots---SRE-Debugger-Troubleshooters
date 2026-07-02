"""Service for retrieving conversation history from HTTP API."""
import logging
import httpx
from typing import List, Dict, Any
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()
_HTTP_CLIENT_KWARGS = {"verify": False, "timeout": 30.0}  # noqa: S501

# HTTP API endpoint for conversation history
CONVERSATION_API_URL = settings.CONVERSATION_API_URL


async def get_conversation_history(
    session_id: str,
    limit: int = 10
) -> List[Dict[str, Any]]:
    """
    Retrieve conversation history from HTTP API using session_id.

    Args:
        session_id: Session ID to retrieve conversations for
        limit: Maximum number of conversations to retrieve (default: 10)

    Returns:
        List of conversation dictionaries with role and content
    """
    try:
        logger.info(f"Fetching conversation history for session_id: {session_id}")

        # Build request payload
        payload = {
            "session_id": session_id,
            "action": "user_conversation",
            "role": "all",
            "limit": str(limit)
        }

        logger.info(f"📤 Sending request to conversation API: {CONVERSATION_API_URL}")
        logger.info(f"📤 Payload: {payload}")

        # Make HTTP request to conversation API with longer timeout
        async with httpx.AsyncClient(**_HTTP_CLIENT_KWARGS) as client:
            response = await client.post(
                CONVERSATION_API_URL,
                json=payload,
                headers={"Content-Type": "application/json"}
            )

            logger.info(f"📥 Received response: Status={response.status_code}")
            logger.info(f"📥 Response content: {response.text[:500]}...")  # First 500 chars

            response.raise_for_status()

            # Parse response
            data = response.json()
            logger.info(f"📥 Parsed JSON response type: {type(data)}")

            # Handle different response formats
            conversations = []

            if isinstance(data, list):
                # Direct list format
                conversations = data
            elif isinstance(data, dict):
                # Wrapped format: {"session_id": "...", "responses": [...]}
                if "responses" in data:
                    conversations = data["responses"]
                    logger.info(f"📥 Found {len(conversations)} conversations in 'responses' field")
                else:
                    logger.warning(f"Dict response but no 'responses' field. Keys: {list(data.keys())}")
                    return []
            else:
                logger.warning(f"Unexpected response format: {type(data)}")
                logger.info("📭 No conversation history found")
                logger.info("=" * 80)
                return []


            if not conversations:
                logger.info("📭 No conversations found")
                logger.info("=" * 80)
                return []

            logger.info(f"📚 Retrieved {len(conversations)} conversations from API (both user and assistant)")
            logger.info("=" * 80)

            # Log each conversation
            import json
            for i, conv in enumerate(conversations, 1):
                logger.info(f"Conversation {i}: {json.dumps(conv, indent=2)}")
                logger.info("-" * 80)

            return conversations

    except httpx.HTTPStatusError as e:
        logger.error(f"HTTP error fetching conversation history: {e.response.status_code} - {e.response.text}")
        return []
    except httpx.RequestError as e:
        logger.error(f"Request error fetching conversation history: {e}")
        return []
    except Exception as e:
        logger.error(f"Error fetching conversation history: {e}", exc_info=True)
        return []

