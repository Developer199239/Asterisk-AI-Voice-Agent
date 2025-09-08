"""
Circuit Breaker Module

This module provides a circuit breaker implementation using the 'pybreaker' library
to prevent cascade failures in service-to-service communication.
"""

import pybreaker
import asyncio
from pybreaker import CircuitBreaker as PyCircuitBreaker, CircuitBreakerError
import logging
from functools import wraps

logger = logging.getLogger(__name__)


class CircuitBreaker:
    """A wrapper around pybreaker.CircuitBreaker."""

    def __init__(self, fail_max=5, reset_timeout=60, name=None):
        self._breaker = PyCircuitBreaker(fail_max=fail_max, reset_timeout=reset_timeout, name=name)

    def call(self, func, *args, **kwargs):
        """Execute a function within the circuit breaker."""
        return self._breaker.call(func, *args, **kwargs)

    async def call_async(self, func, *args, **kwargs):
        """
        Execute an async function within the circuit breaker, avoiding the
        problematic @gen.coroutine decorator in pybreaker.
        """
        if self._breaker.current_state == "open":
            raise CircuitBreakerError("Circuit Breaker is open")
        
        try:
            result = await func(*args, **kwargs)
            self._breaker.success()
            return result
        except Exception as e:
            self._breaker.fail()
            raise e

    def decorate(self, func):
        """Decorate a function with this circuit breaker."""
        return self._breaker.decorate(func)
        
    def decorate_async(self, func):
        """Decorate an async function with the circuit breaker."""
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await self.call_async(func, *args, **kwargs)
            except CircuitBreakerError as e:
                logger.error(f"Circuit breaker '{self._breaker.name}' is open: {e}")
                raise
        return async_wrapper

    @property
    def state(self):
        return self._breaker.current_state
