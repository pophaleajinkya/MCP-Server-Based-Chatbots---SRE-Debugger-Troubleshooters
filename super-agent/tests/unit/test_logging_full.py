"""
Comprehensive unit tests for app.logging — setup_logging function.
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from app.logging import setup_logging


class TestSetupLogging:

    def test_returns_root_logger(self):
        logger = setup_logging()
        assert logger is logging.getLogger()

    def test_sets_info_level(self):
        logger = setup_logging()
        assert logger.level == logging.INFO

    def test_has_exactly_one_handler(self):
        logger = setup_logging()
        assert len(logger.handlers) == 1

    def test_handler_is_stream_handler(self):
        logger = setup_logging()
        assert isinstance(logger.handlers[0], logging.StreamHandler)

    def test_formatter_includes_filename(self):
        logger = setup_logging()
        fmt = logger.handlers[0].formatter._fmt
        assert "filename" in fmt

    def test_formatter_includes_levelname(self):
        logger = setup_logging()
        fmt = logger.handlers[0].formatter._fmt
        assert "levelname" in fmt

    def test_formatter_includes_lineno(self):
        logger = setup_logging()
        fmt = logger.handlers[0].formatter._fmt
        assert "lineno" in fmt

    def test_formatter_includes_asctime(self):
        logger = setup_logging()
        fmt = logger.handlers[0].formatter._fmt
        assert "asctime" in fmt

    def test_idempotent_on_repeated_calls(self):
        setup_logging()
        logger = setup_logging()
        assert len(logger.handlers) == 1

    def test_noisy_loggers_cleared(self):
        setup_logging()
        noisy = ["LiteLLM", "uvicorn", "uvicorn.error", "uvicorn.access"]
        for name in noisy:
            lg = logging.getLogger(name)
            assert lg.handlers == []

    def test_noisy_loggers_propagate(self):
        setup_logging()
        for name in ["LiteLLM", "uvicorn"]:
            lg = logging.getLogger(name)
            assert lg.propagate is True

    def test_stream_handler_output(self):
        """Verify actual log output is produced correctly."""
        logger = setup_logging()
        # Create a test handler to capture output
        import io
        buf = io.StringIO()
        test_handler = logging.StreamHandler(buf)
        test_handler.setFormatter(logger.handlers[0].formatter)
        logger.addHandler(test_handler)
        try:
            logger.info("test log message")
            output = buf.getvalue()
            assert "test log message" in output
            assert "INFO" in output
        finally:
            logger.removeHandler(test_handler)
