"""
Structured Logging Configuration

This module configures structured logging using the 'structlog' library.
It sets up processors for adding timestamps, log levels, correlation IDs,
and renders logs in JSON (default) or colorized console format based on env.
"""

import os
import logging
import sys
import contextvars
import uuid

import structlog
from structlog import dev as structlog_dev
from logging.handlers import RotatingFileHandler

# Context variable for correlation ID
correlation_id_var = contextvars.ContextVar('correlation_id', default=None)

def get_correlation_id():
    """Get the current correlation ID."""
    return correlation_id_var.get()

def set_correlation_id(value=None):
    """Set the correlation ID."""
    if value is None:
        value = str(uuid.uuid4())
    correlation_id_var.set(value)

def add_correlation_id(logger, method_name, event_dict):
    """Add correlation ID to the log record."""
    correlation_id = get_correlation_id()
    if correlation_id:
        event_dict['correlation_id'] = correlation_id
    return event_dict

def add_service_context(logger, method_name, event_dict):
    """Add service context to the log record."""
    event_dict['service'] = 'ai-engine'
    # Handle different logger types that may not have a 'name' attribute
    try:
        event_dict['component'] = logger.name
    except AttributeError:
        event_dict['component'] = 'unknown'
    return event_dict

def configure_logging(log_level="INFO", log_to_file=False, log_file_path="service.log", service_name="ai-engine"):
    """
    Set up structured logging with enhanced context for troubleshooting.

    Environment overrides (optional):
      - LOG_LEVEL: debug|info|warning|error|critical (default: INFO)
      - LOG_FORMAT: json|console (default: json)
      - LOG_COLOR:  0|1 (console only; default: 1)
      - LOG_TO_FILE: 0|1 (default: 0)
      - LOG_FILE_PATH: path (default: service.log)
    """
    # Read env overrides
    env_level = os.getenv("LOG_LEVEL")
    if env_level:
        log_level = env_level.upper()
    try:
        log_to_file = bool(int(os.getenv("LOG_TO_FILE", "0"))) if os.getenv("LOG_TO_FILE") is not None else log_to_file
    except Exception:
        pass
    log_file_path = os.getenv("LOG_FILE_PATH", log_file_path)
    log_format = os.getenv("LOG_FORMAT", "json").strip().lower()
    log_color = os.getenv("LOG_COLOR", "1").strip() not in ("0", "false", "False")

    # Set up processors for structlog
    processors = [
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        # Add service name and correlation ID
        add_service_context,
        add_correlation_id,
        # Render exceptions
        structlog.processors.format_exc_info,
    ]

    if log_format == "console":
        processors.append(structlog_dev.ConsoleRenderer(colors=log_color))
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors,
        context_class=structlog.threadlocal.wrap_dict(dict),
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Set up console handler (structlog already renders the message)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(console_handler)

    if log_to_file:
        file_handler = RotatingFileHandler(
            log_file_path, maxBytes=10*1024*1024, backupCount=5
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger.addHandler(file_handler)

    # Reduce noisy third-party loggers
    try:
        logging.getLogger('websockets').setLevel(logging.WARNING)
        logging.getLogger('websockets.client').setLevel(logging.WARNING)
        logging.getLogger('websockets.protocol').setLevel(logging.WARNING)
        logging.getLogger('aiohttp').setLevel(logging.WARNING)
        logging.getLogger('asyncio').setLevel(logging.WARNING)
    except Exception:
        pass

def get_logger(name: str):
    """Get a structlog logger."""
    return structlog.get_logger(name)
