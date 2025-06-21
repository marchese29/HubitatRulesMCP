"""Mock timer service for testing time-based functionality without real delays."""

from collections.abc import Awaitable, Callable
from datetime import timedelta


class MockTimerService:
    """Controllable timer service for testing.

    Allows instant triggering of timers without waiting for real time to pass.
    """

    def __init__(self) -> None:
        self.active_timers: dict[str, Callable[[str], Awaitable[None]]] = {}
        self.cancelled_timers: set[str] = set()
        self.timer_durations: dict[str, timedelta] = {}

    async def start_timer(
        self,
        timer_id: str,
        duration: timedelta,
        callback: Callable[[str], Awaitable[None]],
    ) -> None:
        """Store timer but don't actually wait for duration.

        Args:
            timer_id: Unique identifier for the timer
            duration: How long timer should run (stored for reference)
            callback: Async function to call when timer expires
        """
        self.active_timers[timer_id] = callback
        self.timer_durations[timer_id] = duration
        # Remove from cancelled set if it was previously cancelled
        self.cancelled_timers.discard(timer_id)

    def cancel_timer(self, timer_id: str) -> None:
        """Cancel a timer if it exists.

        Args:
            timer_id: Timer to cancel
        """
        if timer_id in self.active_timers:
            del self.active_timers[timer_id]
            if timer_id in self.timer_durations:
                del self.timer_durations[timer_id]
        self.cancelled_timers.add(timer_id)

    async def trigger_timer(self, timer_id: str) -> None:
        """Manually fire a timer for testing.

        Args:
            timer_id: Timer to trigger

        Raises:
            KeyError: If timer doesn't exist
        """
        if timer_id not in self.active_timers:
            raise KeyError(f"Timer {timer_id} not found in active timers")

        callback = self.active_timers[timer_id]
        # Remove timer before calling callback (simulates real timer behavior)
        del self.active_timers[timer_id]
        if timer_id in self.timer_durations:
            del self.timer_durations[timer_id]

        await callback(timer_id)

    def has_timer(self, timer_id: str) -> bool:
        """Check if timer is currently active.

        Args:
            timer_id: Timer to check

        Returns:
            True if timer is active, False otherwise
        """
        return timer_id in self.active_timers

    def was_cancelled(self, timer_id: str) -> bool:
        """Check if timer was cancelled.

        Args:
            timer_id: Timer to check

        Returns:
            True if timer was cancelled, False otherwise
        """
        return timer_id in self.cancelled_timers

    def get_timer_duration(self, timer_id: str) -> timedelta:
        """Get the duration of an active timer.

        Args:
            timer_id: Timer to check

        Returns:
            Duration of the timer

        Raises:
            KeyError: If timer doesn't exist
        """
        return self.timer_durations[timer_id]

    def get_active_timer_count(self) -> int:
        """Get number of active timers."""
        return len(self.active_timers)

    def clear_all(self) -> None:
        """Clear all timers and state (useful between tests)."""
        self.active_timers.clear()
        self.cancelled_timers.clear()
        self.timer_durations.clear()
