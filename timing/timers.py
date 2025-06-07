import asyncio as aio
from asyncio import Queue, Task
from dataclasses import dataclass
from datetime import timedelta
from typing import Awaitable, Callable, Optional


@dataclass
class TimerRequest:
    """Represents a request to start a timer."""

    id: str
    duration: timedelta
    callback: Callable[[str], Awaitable[None]]


@dataclass
class Timer:
    """Represents a single timer with its properties and state."""

    id: str
    duration: timedelta
    callback: Callable[[str], Awaitable[None]]
    task: Task


class TimerService:
    """Manages multiple timers with unique IDs, durations, and callbacks."""

    def __init__(self):
        self._timers: dict[str, Timer] = {}
        self._queue: Queue[TimerRequest] = Queue()
        self._processor_task: Optional[Task] = None

    def start(self):
        """Start the timer service and its background processor.

        Returns:
            Task: The background task that can be awaited by the server process
        """
        if self._processor_task is None:
            self._processor_task = aio.create_task(self._process_queue())

    async def stop(self) -> None:
        """Stop the timer service and its background processor."""
        if self._processor_task is not None:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except aio.CancelledError:
                pass
            self._processor_task = None

    async def _process_queue(self) -> None:
        """Background task that processes timer requests from the queue."""
        while True:
            try:
                request = await self._queue.get()
                await self._start_timer_internal(request)
            except aio.CancelledError:
                break
            except Exception as e:
                print(f"Error processing timer request: {e}")

    async def _start_timer_internal(self, request: TimerRequest) -> None:
        """Internal method to start a timer with the given request."""
        if request.id in self._timers:
            self.cancel_timer(request.id)

        async def timer_task():
            try:
                await aio.sleep(request.duration.total_seconds())
                await request.callback(request.id)
            finally:
                if request.id in self._timers:
                    del self._timers[request.id]

        timer = Timer(
            id=request.id,
            duration=request.duration,
            callback=request.callback,
            task=aio.create_task(timer_task()),
        )
        self._timers[request.id] = timer

    async def start_timer(
        self,
        timer_id: str,
        duration: timedelta,
        callback: Callable[[str], Awaitable[None]],
    ) -> None:
        """Queue a request to start a new timer with the given ID, duration, and callback.

        Args:
            timer_id: Unique identifier for the timer
            duration: How long to wait before triggering the callback
            callback: Async function to call when the timer expires, taking the timer_id
                      as argument
        """
        request = TimerRequest(id=timer_id, duration=duration, callback=callback)
        await self._queue.put(request)

    def cancel_timer(self, timer_id: str) -> bool:
        """Cancel a timer by its ID.

        Args:
            timer_id: ID of the timer to cancel

        Returns:
            True if the timer was found and cancelled, False otherwise
        """
        if timer_id not in self._timers:
            return False

        timer = self._timers[timer_id]
        if not timer.task.done():
            timer.task.cancel()
        del self._timers[timer_id]
        return True

    async def reset_timer(self, timer_id: str) -> bool:
        """Reset a timer by cancelling it and starting it again with the same duration and
        callback.

        Args:
            timer_id: ID of the timer to reset

        Returns:
            True if the timer was found and reset, False otherwise
        """
        if timer_id not in self._timers:
            return False

        timer = self._timers[timer_id]
        if not timer.task.done():
            timer.task.cancel()

        # Queue a new timer with the same parameters
        await self.start_timer(timer_id, timer.duration, timer.callback)
        return True
