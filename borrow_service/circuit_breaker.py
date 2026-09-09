"""Small thread-safe circuit breaker / 简单线程安全熔断器。"""

import time
from collections.abc import Callable
from enum import StrEnum
from threading import Lock


class CircuitState(StrEnum):
    """Describe breaker states / 描述熔断器状态。"""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Reject a call while the circuit is open / 熔断开启时拒绝调用。"""

    def __init__(self, retry_after_seconds: float) -> None:
        self.retry_after_seconds = max(0.0, retry_after_seconds)
        super().__init__("circuit is open")


class CircuitBreaker:
    """Open after consecutive failures and probe after recovery / 连续失败后熔断并在恢复期后探测。"""

    def __init__(
        self,
        failure_threshold: int = 3,
        recovery_timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be positive")
        if recovery_timeout_seconds < 0:
            raise ValueError("recovery_timeout_seconds cannot be negative")
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self._clock = clock
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at = 0.0
        self._probe_in_flight = False
        self._lock = Lock()

    @property
    def state(self) -> CircuitState:
        """Return the current state / 返回当前状态。"""
        with self._lock:
            return self._state

    def before_call(self) -> None:
        """Allow a call or reject it quickly / 允许调用或快速拒绝。"""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return

            elapsed = self._clock() - self._opened_at
            if self._state == CircuitState.OPEN and elapsed >= self.recovery_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                self._probe_in_flight = True
                return

            retry_after = self.recovery_timeout_seconds - elapsed
            raise CircuitOpenError(retry_after)

    def record_success(self) -> None:
        """Close the circuit after success / 成功后关闭熔断。"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._probe_in_flight = False

    def record_failure(self) -> None:
        """Count a failure and open when needed / 记录失败并在达到阈值时熔断。"""
        with self._lock:
            self._failure_count += 1
            if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                self._opened_at = self._clock()
            self._probe_in_flight = False
