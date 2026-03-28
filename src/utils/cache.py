import time
from src.logger import get_logger

log = get_logger(__name__)


class TTLCache:
    """Simple in-memory cache with per-key TTL. No dependencies needed."""

    def __init__(self):
        self._store = {}  # key -> (value, expires_at)

    def get(self, key):
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key, value, ttl_seconds):
        self._store[key] = (value, time.time() + ttl_seconds)

    def clear(self):
        self._store.clear()

    def cleanup(self):
        """Remove expired entries. Call periodically if needed."""
        now = time.time()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]


# Shared cache instance
cache = TTLCache()

# TTL presets (seconds)
TTL_SHORT = 600       # 10 min — Spotify tracks/artists/recent
TTL_MEDIUM = 1800     # 30 min — anime data, genres
TTL_LONG = 86400      # 24 hours — static data (experience, account age)
