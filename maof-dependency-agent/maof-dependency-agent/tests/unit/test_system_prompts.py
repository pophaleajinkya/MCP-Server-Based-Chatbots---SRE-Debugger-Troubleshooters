"""Unit tests for src/prompts/system_prompts.py"""
import pytest
from src.prompts.system_prompts import PARAMETER_EXTRACTION_PROMPT


class TestParameterExtractionPrompt:
    """Tests for the PARAMETER_EXTRACTION_PROMPT constant."""

    def test_prompt_exists(self):
        """Test that the prompt constant exists."""
        assert PARAMETER_EXTRACTION_PROMPT is not None
        assert isinstance(PARAMETER_EXTRACTION_PROMPT, str)

    def test_prompt_is_not_empty(self):
        """Test that the prompt is not empty."""
        assert len(PARAMETER_EXTRACTION_PROMPT) > 0

    def test_prompt_contains_wcnp_instructions(self):
        """Test that prompt contains WCNP type instructions."""
        assert "WCNP" in PARAMETER_EXTRACTION_PROMPT
        assert "app_name" in PARAMETER_EXTRACTION_PROMPT
        assert "namespace" in PARAMETER_EXTRACTION_PROMPT

    def test_prompt_contains_oneops_instructions(self):
        """Test that prompt contains OneOps type instructions."""
        assert "OneOps" in PARAMETER_EXTRACTION_PROMPT
        assert "org" in PARAMETER_EXTRACTION_PROMPT
        assert "platform" in PARAMETER_EXTRACTION_PROMPT
        assert "assembly" in PARAMETER_EXTRACTION_PROMPT

    def test_prompt_contains_managed_service_instructions(self):
        """Test that prompt contains Managed Service instructions."""
        assert "Managed Service" in PARAMETER_EXTRACTION_PROMPT
        assert "cassandra" in PARAMETER_EXTRACTION_PROMPT
        assert "meghacache" in PARAMETER_EXTRACTION_PROMPT
        assert "cosmos" in PARAMETER_EXTRACTION_PROMPT
        assert "sqlserver" in PARAMETER_EXTRACTION_PROMPT

    def test_prompt_contains_cosmos_sql_params(self):
        """Test that prompt contains Cosmos/SQL parameters."""
        assert "resource_group" in PARAMETER_EXTRACTION_PROMPT
        assert "subscription_id" in PARAMETER_EXTRACTION_PROMPT
        assert "database_name" in PARAMETER_EXTRACTION_PROMPT

    def test_prompt_contains_direction_detection(self):
        """Test that prompt contains direction detection instructions."""
        assert "direction" in PARAMETER_EXTRACTION_PROMPT
        assert "upstream" in PARAMETER_EXTRACTION_PROMPT
        assert "downstream" in PARAMETER_EXTRACTION_PROMPT
        assert "both" in PARAMETER_EXTRACTION_PROMPT

    def test_prompt_contains_json_format(self):
        """Test that prompt specifies JSON response format."""
        assert "JSON" in PARAMETER_EXTRACTION_PROMPT
        assert "{" in PARAMETER_EXTRACTION_PROMPT
        assert "}" in PARAMETER_EXTRACTION_PROMPT

    def test_prompt_contains_type_detection_logic(self):
        """Test that prompt contains type detection logic."""
        assert "TYPE 1" in PARAMETER_EXTRACTION_PROMPT or "Type 1" in PARAMETER_EXTRACTION_PROMPT.lower()
        assert "TYPE 2" in PARAMETER_EXTRACTION_PROMPT or "Type 2" in PARAMETER_EXTRACTION_PROMPT.lower()
        assert "TYPE 3" in PARAMETER_EXTRACTION_PROMPT or "Type 3" in PARAMETER_EXTRACTION_PROMPT.lower()

    def test_prompt_contains_examples(self):
        """Test that prompt contains examples."""
        assert "EXAMPLES" in PARAMETER_EXTRACTION_PROMPT.upper() or "Example" in PARAMETER_EXTRACTION_PROMPT

    def test_prompt_contains_context_inference(self):
        """Test that prompt contains context inference instructions."""
        assert "conversation history" in PARAMETER_EXTRACTION_PROMPT.lower() or "context" in PARAMETER_EXTRACTION_PROMPT.lower()

    def test_prompt_field_rules(self):
        """Test that prompt contains field rules by type."""
        assert "null" in PARAMETER_EXTRACTION_PROMPT
        assert "query_type" in PARAMETER_EXTRACTION_PROMPT
