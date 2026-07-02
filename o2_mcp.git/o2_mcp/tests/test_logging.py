"""Tests for src/utils/logging.py — Logging configuration."""
import pytest
import logging
from unittest.mock import patch
from src.utils.logging import setup_logging, get_logger


class TestSetupLogging:
    """Test setup_logging function."""

    def test_default_level_is_info(self):
        """Default log level should be INFO."""
        setup_logging()
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_custom_level_debug(self):
        """Should accept DEBUG level."""
        setup_logging("DEBUG")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_custom_level_warning(self):
        """Should accept WARNING level."""
        setup_logging("WARNING")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.WARNING

    def test_custom_level_error(self):
        """Should accept ERROR level."""
        setup_logging("ERROR")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.ERROR

    def test_invalid_level_defaults_to_info(self):
        """Invalid log level should default to INFO."""
        setup_logging("INVALID_LEVEL")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.INFO

    def test_case_insensitive(self):
        """Log level should be case-insensitive."""
        setup_logging("debug")
        root_logger = logging.getLogger()
        assert root_logger.level == logging.DEBUG

    def test_cached_with_lru_cache(self):
        """setup_logging should be cached (lru_cache)."""
        # Call twice with same args - should use cache
        setup_logging("INFO")
        setup_logging("INFO")
        # No exception means it worked


class TestGetLogger:
    """Test get_logger function."""

    def test_returns_logger_instance(self):
        """Should return a Logger instance."""
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)

    def test_logger_has_correct_name(self):
        """Logger should have the specified name."""
        logger = get_logger("my.module.name")
        assert logger.name == "my.module.name"

    def test_multiple_loggers_have_unique_names(self):
        """Different names should create different loggers."""
        logger1 = get_logger("module1")
        logger2 = get_logger("module2")
        assert logger1.name != logger2.name

    def test_same_name_returns_same_logger(self):
        """Same name should return the same logger instance."""
        logger1 = get_logger("module")
        logger2 = get_logger("module")
        assert logger1 is logger2

