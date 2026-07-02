import logging

# Third-party loggers that install their own handlers with incompatible formats.
# Cleared here so all records propagate to the root logger with a unified format.
_NOISY_LOGGERS = ("LiteLLM", "uvicorn", "uvicorn.error", "uvicorn.access")


def setup_logging() -> logging.Logger:
    logger = logging.getLogger()
    logger.handlers.clear()
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(filename)-15s %(lineno)-8s %(levelname)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    for name in _NOISY_LOGGERS:
        _l = logging.getLogger(name)
        _l.handlers.clear()
        _l.propagate = True

    return logger
