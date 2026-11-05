"""RAM-only bounded LRU cache for deterministic query answers.

Zero disk writes, zero logging, zero telemetry.
"""

import asyncio
import hashlib
from collections import OrderedDict

from app.services.chat_models import ChatResponse


class ChatCache:
    """Thread-safe bounded in-memory LRU cache."""

    def __init__(self, maxsize: int = 256, dataset_version: str = "v1") -> None:
        self._maxsize = maxsize
        self._dataset_version = dataset_version
        self._cache: OrderedDict[str, ChatResponse] = OrderedDict()
        self._lock = asyncio.Lock()

    def hash_key(self, message: str) -> str:
        normalized = " ".join(message.strip().casefold().split())
        payload = f"{self._dataset_version}:{normalized}".encode()
        return hashlib.sha256(payload).hexdigest()

    async def get(self, message: str) -> ChatResponse | None:
        key = self.hash_key(message)
        async with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
            return None

    async def set(self, message: str, response: ChatResponse) -> None:
        if response.status not in ("VERIFIED", "NOT_FOUND"):
            return
        key = self.hash_key(message)
        async with self._lock:
            self._cache[key] = response
            self._cache.move_to_end(key)
            if len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()
