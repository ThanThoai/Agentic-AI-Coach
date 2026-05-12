import logging

import structlog

_SECRET_KEYS = frozenset({
    "password", "passwd", "pwd", "token", "secret",
    "authorization", "cookie", "set-cookie", "api_key",
    "jwt", "hf_token", "openai_api_key", "access_token",
    "refresh_token", "anthropic_api_key", "database_url",
})


def _redact_secrets(logger, method, event_dict):
    """Strip well-known secret field names from every log line."""
    def _walk(obj):
        if isinstance(obj, dict):
            return {
                k: "***REDACTED***" if k.lower() in _SECRET_KEYS else _walk(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_walk(x) for x in obj]
        return obj
    return _walk(event_dict)


def setup_logging(log_level: str = "INFO") -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _redact_secrets,
    ]

    if log_level == "DEBUG":
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[*shared_processors, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(log_level)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
