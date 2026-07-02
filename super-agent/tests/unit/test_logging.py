"""Unit tests for app.logging — setup_logging()."""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestSetupLogging:
    """Test setup_logging() configures the root logger correctly."""

    def setup_method(self):
        """Reset root logger before each test."""
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.WARNING)

    def test_returns_root_logger(self):
        from app.logging import setup_logging
        result = setup_logging()
        assert result is logging.getLogger()

    def test_sets_level_info(self):
        from app.logging import setup_logging
        setup_logging()
        assert logging.getLogger().level == logging.INFO

    def test_adds_stream_handler(self):
        from app.logging import setup_logging
        setup_logging()
        handlers = logging.getLogger().handlers
        assert len(handlers) == 1
        assert isinstance(handlers[0], logging.StreamHandler)

    def test_clears_existing_handlers(self):
        root = logging.getLogger()
        root.addHandler(logging.StreamHandler())
        root.addHandler(logging.StreamHandler())

        from app.logging import setup_logging
        setup_logging()
        # setup_logging clears all then adds exactly one StreamHandler
        stream_handlers = [h for h in root.handlers if type(h) is logging.StreamHandler]
        assert len(stream_handlers) == 1

    def test_handler_formatter_includes_filename(self):
        from app.logging import setup_logging
        setup_logging()
        formatter = logging.getLogger().handlers[0].formatter
        assert "%(filename)" in formatter._fmt

    def test_handler_formatter_includes_levelname(self):
        from app.logging import setup_logging
        setup_logging()
        formatter = logging.getLogger().handlers[0].formatter
        assert "%(levelname)" in formatter._fmt

    def test_handler_formatter_includes_lineno(self):
        from app.logging import setup_logging
        setup_logging()
        formatter = logging.getLogger().handlers[0].formatter
        assert "%(lineno)" in formatter._fmt

    def test_noisy_loggers_cleared(self):
        from app.logging import setup_logging, _NOISY_LOGGERS
        # Pre-add handlers to noisy loggers
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).addHandler(logging.StreamHandler())

        setup_logging()

        for name in _NOISY_LOGGERS:
            assert logging.getLogger(name).handlers == []

    def test_noisy_loggers_propagate(self):
        from app.logging import setup_logging, _NOISY_LOGGERS
        setup_logging()
        for name in _NOISY_LOGGERS:
            assert logging.getLogger(name).propagate is True

    def test_idempotent_on_repeated_calls(self):
        from app.logging import setup_logging
        setup_logging()
        setup_logging()
        # Should still have exactly one handler
        assert len(logging.getLogger().handlers) == 1
