import logging
import httpx

from config import get_settings
from openai import AzureOpenAI, AsyncAzureOpenAI
from langchain_openai import AzureChatOpenAI

settings = get_settings()

_HTTP_CLIENT_KWARGS = {"verify": False, "timeout": 30.0}  # noqa: S501

class LLMClient:
    """Class for interacting with Azure OpenAI API to generate embeddings and chat completions."""

    def __init__(self, api_key=None, endpoint=None, embedding_model=None, chat_model=None):
        """
        Initialize the LLM client with Azure OpenAI credentials.

        Args:
            api_key: Azure OpenAI API key (defaults to config setting)
            endpoint: Azure OpenAI endpoint (defaults to config setting)
            embedding_model: Model to use for embeddings (defaults to config setting)
            chat_model: Model to use for chat completions (defaults to config setting)
        """
        self.api_key = api_key or settings.AZURE_OPENAI_API_KEY
        self.endpoint = endpoint or settings.AZURE_OPENAI_ENDPOINT
        self.embedding_model = embedding_model or settings.AZURE_EMBEDDING_MODEL
        self.chat_model = chat_model or settings.AZURE_OPENAI_MODEL
        self.logger = logging.getLogger(__name__)
        self.client = self._initialize_client()
        self._async_client = None
        self._chat_client = None

    def _initialize_client(self):
        """Initialize and return the Azure OpenAI client."""
        # HTTP headers with API key
        headers = {
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
            "WM_LLM_GW.USER_TYPE": "NO_END_USER",
            "WM_LLM_GW.USER_NAME": "NO_END_USER"
        }

        # Initialize HTTP client with SSL verification disabled
        http_client = httpx.Client(
            **_HTTP_CLIENT_KWARGS,
            headers=headers,
        )

        # Initialize and return the Azure OpenAI client
        return AzureOpenAI(
            api_key=self.api_key,
            http_client=http_client,
            azure_endpoint=self.endpoint,
            api_version=settings.AZURE_OPENAI_API_VERSION,
        )

    @property
    def async_client(self) -> AsyncAzureOpenAI:
        """Get async Azure OpenAI client for direct API calls."""
        if self._async_client is None:
            headers = {
                "X-Api-Key": self.api_key,
                "Content-Type": "application/json",
                "WM_LLM_GW.USER_TYPE": "NO_END_USER",
                "WM_LLM_GW.USER_NAME": "NO_END_USER",
            }

            http_client = httpx.AsyncClient(
                **_HTTP_CLIENT_KWARGS,
                headers=headers,
            )

            self._async_client = AsyncAzureOpenAI(
                api_key=self.api_key,
                http_client=http_client,
                azure_endpoint=self.endpoint,
                api_version=settings.AZURE_OPENAI_API_VERSION,
            )
        return self._async_client

    @property
    def chat(self) -> AzureChatOpenAI:
        """Get LangChain AzureChatOpenAI client for agent usage."""
        if self._chat_client is None:
            # HTTP headers with API key
            headers = {
                "X-Api-Key": self.api_key,
                "Content-Type": "application/json",
                "WM_LLM_GW.USER_TYPE": "NO_END_USER",
                "WM_LLM_GW.USER_NAME": "NO_END_USER",
            }

            # Create HTTP client with SSL verification disabled
            http_client = httpx.AsyncClient(
                **_HTTP_CLIENT_KWARGS,
                headers=headers,
            )

            self._chat_client = AzureChatOpenAI(
                azure_deployment=self.chat_model,
                azure_endpoint=self.endpoint,
                api_key=self.api_key,
                api_version=settings.AZURE_OPENAI_API_VERSION,
                temperature=0,
                http_async_client=http_client,
            )
        return self._chat_client

    @property
    def model(self) -> str:
        """Get the chat model name."""
        return self.chat_model

    def generate_embedding(self, queries):
        """
        Generate vector embeddings for a batch of queries using OpenAI API.

        Args:
            queries: List of text strings to generate embeddings for

        Returns:
            List of embedding vectors or empty list on error
        """
        try:
            response = self.client.embeddings.create(model=self.embedding_model, input=queries)
            return [item.embedding for item in response.data]
        except Exception as e:
            self.logger.error(f"Failed to generate embeddings: {e}")
            return []


# Create a default instance for backward compatibility
default_client = LLMClient()
generate_embedding = default_client.generate_embedding

# Create a global instance for use across the application
llm_client = default_client

