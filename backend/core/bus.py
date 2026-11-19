"""
High-speed asynchronous event bus for sub-5ms pipeline routing.
Routes ticks, liquidations, news, derivatives metrics, and AI alerts across services.
"""

import asyncio
from collections import defaultdict
from typing import Any, Callable, Coroutine, Dict, List


EventHandler = Callable[[Dict[str, Any]], Coroutine[Any, Any, None]]


class AsyncEventBus:
    """Zero-overhead in-memory pub/sub event bus using asyncio queues & callbacks."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, List[EventHandler]] = defaultdict(list)
        self._queue: asyncio.Queue[tuple[str, Dict[str, Any]]] = asyncio.Queue(maxsize=10000)
        self._running: bool = False
        self._worker_task: asyncio.Task[None] | None = None
        self.events_processed: int = 0

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Subscribe an async coroutine handler to a topic."""
        if handler not in self._subscribers[topic]:
            self._subscribers[topic].append(handler)

    def publish_nowait(self, topic: str, payload: Dict[str, Any]) -> None:
        """Non-blocking publish to the hot-path event queue."""
        try:
            self._queue.put_nowait((topic, payload))
        except asyncio.QueueFull:
            # Drop oldest item if backpressure hits max limit to preserve sub-5ms latency
            try:
                self._queue.get_nowait()
                self._queue.put_nowait((topic, payload))
            except asyncio.QueueEmpty:
                pass

    async def publish(self, topic: str, payload: Dict[str, Any]) -> None:
        """Async publish to the event queue."""
        self.publish_nowait(topic, payload)

    async def start(self) -> None:
        """Start the background event dispatcher loop."""
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._dispatch_loop())

    async def stop(self) -> None:
        """Gracefully stop the dispatcher loop."""
        self._running = False
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def _dispatch_loop(self) -> None:
        while self._running:
            try:
                topic, payload = await self._queue.get()
                self.events_processed += 1
                handlers = self._subscribers.get(topic, [])
                wildcard_handlers = self._subscribers.get("*", [])
                for handler in handlers + wildcard_handlers:
                    try:
                        asyncio.create_task(handler(payload))
                    except Exception:
                        pass
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.001)


# Global singleton event bus
bus = AsyncEventBus()
