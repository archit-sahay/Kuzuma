import time
from collections import defaultdict


class RateLimiter:
    """Sliding window rate limiter. Lightweight, no dependencies."""

    def __init__(self, max_requests=5, window_seconds=60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps = defaultdict(list)  # key -> [timestamps]

    def is_allowed(self, key: str) -> bool:
        now = time.time()
        cutoff = now - self.window

        # Remove old timestamps
        self._timestamps[key] = [t for t in self._timestamps[key] if t > cutoff]

        if len(self._timestamps[key]) >= self.max_requests:
            return False

        self._timestamps[key].append(now)
        return True

    def cleanup(self, key: str):
        self._timestamps.pop(key, None)


# Shared instance: 5 messages per 60 seconds per user
rate_limiter = RateLimiter(max_requests=5, window_seconds=60)
