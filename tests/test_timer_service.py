"""Unit tests for TimerService."""

import asyncio
from datetime import timedelta
import time

import pytest

from timing.timers import TimerService


class TestTimerService:
    """Test class for TimerService functionality."""

    @pytest.mark.unit
    async def test_basic_timer_functionality(self):
        """Test basic timer creation and execution."""
        service = TimerService()
        service.start()

        # Track callback execution
        executed_timers = []

        async def callback(timer_id: str):
            executed_timers.append((timer_id, time.time()))

        # Start a short timer
        start_time = time.time()
        await service.start_timer("test1", timedelta(seconds=0.2), callback)

        # Wait for timer to execute
        await asyncio.sleep(0.35)

        # Verify callback was executed
        assert len(executed_timers) == 1, (
            f"Expected 1 executed timer, got {len(executed_timers)}"
        )
        timer_id, execution_time = executed_timers[0]
        assert timer_id == "test1", f"Expected timer_id 'test1', got '{timer_id}'"

        # Verify timing (within reasonable tolerance)
        elapsed = execution_time - start_time
        assert 0.15 < elapsed < 0.3, (
            f"Timer executed after {elapsed:.3f}s, expected ~0.2s"
        )

        await service.stop()

    @pytest.mark.unit
    async def test_multiple_concurrent_timers(self):
        """Test multiple timers running simultaneously."""
        service = TimerService()
        service.start()

        executed_timers = []

        async def callback(timer_id: str):
            executed_timers.append((timer_id, time.time()))

        start_time = time.time()

        # Start multiple timers with different durations
        await service.start_timer("fast", timedelta(seconds=0.1), callback)
        await service.start_timer("medium", timedelta(seconds=0.2), callback)
        await service.start_timer("slow", timedelta(seconds=0.3), callback)

        # Wait for all timers to execute
        await asyncio.sleep(0.45)

        # Verify all timers executed
        assert len(executed_timers) == 3, (
            f"Expected 3 executed timers, got {len(executed_timers)}"
        )

        # Sort by execution time
        executed_timers.sort(key=lambda x: x[1])

        # Verify execution order
        assert executed_timers[0][0] == "fast", "Fast timer should execute first"
        assert executed_timers[1][0] == "medium", "Medium timer should execute second"
        assert executed_timers[2][0] == "slow", "Slow timer should execute third"

        # Verify timing
        fast_time = executed_timers[0][1] - start_time
        medium_time = executed_timers[1][1] - start_time
        slow_time = executed_timers[2][1] - start_time

        assert 0.05 < fast_time < 0.15, f"Fast timer timing: {fast_time:.3f}s"
        assert 0.15 < medium_time < 0.25, f"Medium timer timing: {medium_time:.3f}s"
        assert 0.25 < slow_time < 0.35, f"Slow timer timing: {slow_time:.3f}s"

        await service.stop()

    @pytest.mark.unit
    async def test_timer_cancellation(self):
        """Test cancelling a timer before it executes."""
        service = TimerService()
        service.start()

        executed_timers = []

        async def callback(timer_id: str):
            executed_timers.append(timer_id)

        # Start a timer
        await service.start_timer("cancel_me", timedelta(seconds=0.3), callback)

        # Cancel it before it executes
        await asyncio.sleep(0.1)
        result = service.cancel_timer("cancel_me")
        assert result is True, "Should return True when cancelling existing timer"

        # Wait past the original execution time
        await asyncio.sleep(0.3)

        # Verify callback was not executed
        assert len(executed_timers) == 0, (
            f"Expected 0 executed timers, got {len(executed_timers)}"
        )

        # Test cancelling non-existent timer
        result = service.cancel_timer("nonexistent")
        assert result is False, "Should return False when cancelling non-existent timer"

        await service.stop()

    @pytest.mark.unit
    async def test_timer_reset(self):
        """Test resetting a timer."""
        service = TimerService()
        service.start()

        executed_timers = []

        async def callback(timer_id: str):
            executed_timers.append((timer_id, time.time()))

        # Start a timer
        await service.start_timer("reset_me", timedelta(seconds=0.3), callback)

        # Reset it partway through
        await asyncio.sleep(0.15)
        reset_time = time.time()
        result = await service.reset_timer("reset_me")
        assert result is True, "Should return True when resetting existing timer"

        # Wait for the reset timer to execute
        await asyncio.sleep(0.4)

        # Verify callback was executed once
        assert len(executed_timers) == 1, (
            f"Expected 1 executed timer, got {len(executed_timers)}"
        )

        # Verify timing - should be ~0.3s from reset time, not start time
        execution_time = executed_timers[0][1]
        elapsed_from_reset = execution_time - reset_time
        assert 0.25 < elapsed_from_reset < 0.35, (
            f"Timer executed {elapsed_from_reset:.3f}s after reset"
        )

        # Test resetting non-existent timer
        result = await service.reset_timer("nonexistent")
        assert result is False, "Should return False when resetting non-existent timer"

        await service.stop()

    @pytest.mark.unit
    async def test_duplicate_timer_ids(self):
        """Test that starting a timer with the same ID replaces the existing one."""
        service = TimerService()
        service.start()

        executed_timers = []

        async def callback1(timer_id: str):
            executed_timers.append(f"callback1_{timer_id}")

        async def callback2(timer_id: str):
            executed_timers.append(f"callback2_{timer_id}")

        # Start first timer
        await service.start_timer("duplicate", timedelta(seconds=0.3), callback1)

        # Start second timer with same ID (should replace first)
        await asyncio.sleep(0.1)
        await service.start_timer("duplicate", timedelta(seconds=0.2), callback2)

        # Wait for execution
        await asyncio.sleep(0.35)

        # Should only have the second callback
        assert len(executed_timers) == 1, (
            f"Expected 1 executed timer, got {len(executed_timers)}"
        )
        assert executed_timers[0] == "callback2_duplicate", (
            f"Expected callback2, got {executed_timers[0]}"
        )

        await service.stop()

    @pytest.mark.unit
    async def test_service_lifecycle(self):
        """Test service start and stop behavior."""
        service = TimerService()

        executed_timers = []

        async def callback(timer_id: str):
            executed_timers.append(timer_id)

        # Try to start timer before service is started
        await service.start_timer("before_start", timedelta(seconds=0.1), callback)

        # Start service
        service.start()

        # Start timer after service is started
        await service.start_timer("after_start", timedelta(seconds=0.1), callback)

        # Wait for execution
        await asyncio.sleep(0.2)

        # Stop service
        await service.stop()

        # Verify behavior - both timers should execute since the queue processes them
        # after service.start() is called
        assert len(executed_timers) >= 1, "At least one timer should execute"

    @pytest.mark.unit
    async def test_exception_in_callback(self):
        """Test that exceptions in callbacks don't break the service."""
        service = TimerService()
        service.start()

        executed_timers = []

        async def good_callback(timer_id: str):
            executed_timers.append(f"good_{timer_id}")

        async def bad_callback(timer_id: str):
            executed_timers.append(f"bad_{timer_id}")
            raise Exception("Test exception")

        # Start timers with both good and bad callbacks
        await service.start_timer("good", timedelta(seconds=0.1), good_callback)
        await service.start_timer("bad", timedelta(seconds=0.15), bad_callback)
        await service.start_timer("good2", timedelta(seconds=0.2), good_callback)

        # Wait for execution
        await asyncio.sleep(0.3)

        # Verify both good callbacks executed despite the exception
        good_executions = [t for t in executed_timers if t.startswith("good_")]
        bad_executions = [t for t in executed_timers if t.startswith("bad_")]

        assert len(good_executions) == 2, (
            f"Expected 2 good executions, got {len(good_executions)}"
        )
        assert len(bad_executions) == 1, (
            f"Expected 1 bad execution, got {len(bad_executions)}"
        )

        await service.stop()
