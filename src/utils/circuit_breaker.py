import time
from src.logger import get_logger

log = get_logger(__name__)


class CircuitBreaker:
    """Opens after `threshold` consecutive failures; half-opens after `recovery_time`."""

    def __init__(self, threshold: int = 3, recovery_time: int = 60, name: str = "breaker"):
        self.threshold = threshold
        self.recovery_time = recovery_time
        self.name = name
        self.failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.time() - self.opened_at > self.recovery_time:
            return False  # half-open: allow probe
        return True

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.time()
            log.warning(f"Circuit breaker '{self.name}' opened after {self.failures} failures")

    def trip(self, recovery_seconds: int | None = None) -> None:
        """Force-open the breaker immediately. Use for non-recoverable errors
        where retrying without manual intervention is hopeless (e.g. revoked
        OAuth refresh tokens). Optionally override recovery_time for this trip."""
        self.failures = self.threshold
        self.opened_at = time.time()
        if recovery_seconds is not None:
            self.recovery_time = recovery_seconds
        log.warning(f"Circuit breaker '{self.name}' force-tripped (recovery in {self.recovery_time}s)")
