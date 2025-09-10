"""
Structured Logging Configuration

This module configures structured logging using the 'structlog' library.
It sets up processors for adding timestamps, log levels, correlation IDs,
and renders logs in JSON format.
"""

import logging
import sys
import contextvars
import uuid

import structlog
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

def configure_logging(log_level="INFO", log_to_file=False, log_file_path="service.log"):
    """
    Set up structured logging.
    """
    # Set up processors for structlog
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            # Add the processor to format exceptions
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=structlog.threadlocal.wrap_dict(dict),
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    # Set up root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Set up console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(message)s"))
    root_logger.addHandler(console_handler)

    if log_to_file:
        file_handler = RotatingFileHandler(
            log_file_path, maxBytes=10*1024*1024, backupCount=5
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger.addHandler(file_handler)

def get_logger(name: str):
    """Get a structlog logger."""
    return structlog.get_logger(name)
