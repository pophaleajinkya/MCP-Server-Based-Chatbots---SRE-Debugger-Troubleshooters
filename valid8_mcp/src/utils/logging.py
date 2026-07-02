"""Centralized logging setup."""
from __future__ import annotations

import logging
import sys
from functools import lru_cache


@lru_cache(maxsize=1)
def setup_logging(level: str = "INFO") -> None:
    """Configure root logger. Call once at startup."""
    fmt = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        stream=sys.stdout,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
