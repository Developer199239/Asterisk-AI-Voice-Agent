import pytest
import asyncio
from unittest.mock import MagicMock

from shared.circuit_breaker import CircuitBreaker, CircuitBreakerError

@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures():
    """Test that the circuit breaker opens after the configured number of failures."""
    # Arrange
    breaker = CircuitBreaker(fail_max=2, reset_timeout=10)
    failing_func = MagicMock()
    failing_func.side_effect = ValueError("Failure")

    # Act & Assert
    with pytest.raises(ValueError):
        breaker.call(failing_func)
    with pytest.raises(ValueError):
        breaker.call(failing_func)
    
    assert breaker.state == "open"

    with pytest.raises(CircuitBreakerError):
        breaker.call(failing_func)

    assert failing_func.call_count == 2
