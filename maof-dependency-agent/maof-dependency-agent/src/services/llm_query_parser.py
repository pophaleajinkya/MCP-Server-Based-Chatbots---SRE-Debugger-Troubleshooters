"""LLM-based query parser using OpenAI."""
import logging
from typing import Dict, Optional
import json

from src.utils import llm_client

logger = logging.getLogger(__name__)


class LLMQueryParser:
    """Parse queries using LLM for intelligent parameter extraction."""

    def __init__(self):
        """Initialize LLM parser with shared LLM client."""
        self.client = llm_client.async_client
        self.model = llm_client.model

    async def parse_query(self, query: str, session_id: str) -> Dict[str, Optional[str]]:
        """
        Parse query using LLM to extract parameters.

        Args:
            query: Natural language or structured query
            session_id: Session ID for logging

        Returns:
            Dictionary with extracted parameters
        """
        logger.info(f"[{session_id}] Parsing query with LLM: {query[:100]}...")

        try:
            system_prompt = """You are a parameter extraction assistant for a dependency management system.

Extract the following parameters from user queries:
- app_name: The application or service name (e.g., "payment-service", "user-api", "checkout")
- namespace: The Kubernetes namespace or environment (e.g., "production", "prod", "staging", "dev")

Handle various formats:
1. Structured: "appName=checkout namespace=prod"
2. Context string: "--- Agent: DependencyAgent ---\\nDescription: ...\\nResponse: appName=X namespace=Y"
3. Natural language: "Get dependencies for payment-service in production"
4. Mixed formats

Be intelligent about extraction:
- Recognize common variations (prod/production, stg/staging, dev/development)
- Handle different naming conventions (appName, app_name, application, service)
- Extract from context even if not explicitly labeled
- Provide confidence score (0-1) and reasoning

Respond ONLY with valid JSON in this exact format:
{
  "app_name": "extracted-app-name",
  "namespace": "extracted-namespace",
  "confidence": 0.95,
  "reasoning": "brief explanation"
}

If you cannot find both parameters, set them to null and explain why in reasoning."""

            user_prompt = f"""Extract app_name and namespace from this query:

Query: {query}"""

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1  # Low temperature for consistent extraction
            )

            # Parse the JSON response
            content = response.choices[0].message.content
            extracted = json.loads(content)

            result = {
                "agent_name": None,
                "description": None,
                "response": query,
                "app_name": extracted.get("app_name"),
                "namespace": extracted.get("namespace"),
                "tool_name": "get_app_dependencies"
            }

            logger.info(
                f"[{session_id}] LLM extracted - appName: {result['app_name']}, "
                f"namespace: {result['namespace']}, "
                f"confidence: {extracted.get('confidence', 'N/A')}, "
                f"reasoning: {extracted.get('reasoning', 'N/A')}"
            )

            return result

        except Exception as e:
            logger.error(f"[{session_id}] LLM parsing failed: {e}")
            return {
                "agent_name": None,
                "description": None,
                "response": query,
                "app_name": None,
                "namespace": None,
                "tool_name": "get_app_dependencies"
            }

