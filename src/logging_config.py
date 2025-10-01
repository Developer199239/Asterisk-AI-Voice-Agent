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
    # Prefer stdlib logger name injected by structlog.stdlib.add_logger_name
    component = event_dict.get('logger')
    if not component:
        # Fallbacks for various logger wrappers
        try:
            component = getattr(getattr(logger, 'logger', None), 'name', None) or getattr(logger, 'name')
        except Exception:
            component = 'unknown'
    event_dict['component'] = component
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

    # Determine when to render tracebacks
    # Default policy: only show stack traces when LOG_LEVEL=debug
    log_level_upper = log_level.upper() if isinstance(log_level, str) else str(log_level)
    tb_mode = os.getenv("LOG_SHOW_TRACEBACKS", "auto").strip().lower()  # auto|always|never
    if tb_mode == "always":
        show_tracebacks = True
    elif tb_mode == "never":
        show_tracebacks = False
    else:
        show_tracebacks = (log_level_upper == "DEBUG")

    def suppress_exc_info_if_disabled(logger, method_name, event_dict):
        """Remove exc_info from event when tracebacks are disabled by policy."""
        if not show_tracebacks and event_dict.get("exc_info"):
            event_dict.pop("exc_info", None)
        return event_dict

    # Derive numeric level for stdlib root logger
    try:
        level_value = getattr(logging, log_level_upper, logging.INFO) if isinstance(log_level, str) else int(log_level)
    except Exception:
        level_value = logging.INFO

    # Configure structlog to integrate with stdlib logging
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            add_service_context,
            add_correlation_id,
            suppress_exc_info_if_disabled,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=structlog.threadlocal.wrap_dict(dict),
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Choose final renderer
    renderer = structlog_dev.ConsoleRenderer(colors=log_color) if log_format == "console" else structlog.processors.JSONRenderer()

    # Stdlib ProcessorFormatter for both structlog and foreign loggers
    processor_formatter = structlog.stdlib.ProcessorFormatter(
        processor=renderer,
        foreign_pre_chain=[
            structlog.stdlib.add_logger_name,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
        ],
    )

    # Set up root logger and handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(level_value)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(processor_formatter)
    root_logger.addHandler(console_handler)

    if log_to_file:
        file_handler = RotatingFileHandler(
            log_file_path, maxBytes=10*1024*1024, backupCount=5
        )
        file_handler.setFormatter(processor_formatter)
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
