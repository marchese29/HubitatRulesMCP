"""
Tests for the duration condition state management fix.

These tests verify that conditions with durations properly use the DURATION_PENDING
state to prevent dependent conditions from triggering prematurely.
"""

import asyncio
from datetime import timedelta

import pytest

from .test_conditions import DurationCondition, ParentCondition, SimpleCondition
from .test_helpers import create_device_event


class TestDurationConditionStateFix:
    """Test the fix for duration condition state management."""

    async def test_duration_condition_propagates_to_parent_when_complete(
        self, rule_engine_with_device_attrs, mock_timer_service
    ):
        """Test: Duration condition properly propagates state to parent when duration completes."""
        engine = rule_engine_with_device_attrs

        # Create child condition with duration and parent that depends on it (require_all=False for OR logic)
        child = DurationCondition(
            "child_with_duration",
            duration_time=timedelta(seconds=1),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )
        parent = ParentCondition("parent_depends_on_child", [child], require_all=False)

        child_event = asyncio.Event()
        parent_event = asyncio.Event()

        # Add both conditions
        await engine.add_condition(child, child_event)
        await engine.add_condition(parent, parent_event)

        # Both should start false
        assert engine.get_condition_state(child) is False
        assert engine.get_condition_state(parent) is False

        # Trigger child's device event to make it true
        event = create_device_event(123, "switch", "on")
        await engine.on_device_event(event)

        # Child should now be in DURATION_PENDING state but get_condition_state should return False
        # to prevent parent from triggering prematurely
        assert engine.get_condition_state(child) is False
        assert engine.get_condition_state(parent) is False

        # Verify child condition should NOT have fired yet
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(child_event.wait(), timeout=0.01)

        # Verify parent condition should NOT have fired yet
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(parent_event.wait(), timeout=0.01)

        # Manually trigger the duration timer to complete
        duration_timer_id = f"condition_duration({child.instance_id})"
        await mock_timer_service.trigger_timer(duration_timer_id)

        # Now child should fire
        fired = await asyncio.wait_for(child_event.wait(), timeout=0.1)
        assert fired

        # IMPORTANT: Parent should now fire too because child became TRUE and propagated state
        parent_fired = await asyncio.wait_for(parent_event.wait(), timeout=0.1)
        assert parent_fired

        # Both conditions should be auto-removed after firing (no dependents)
        # Verify condition was removed from internal tracking
        with pytest.raises(KeyError):
            engine._conditions[child.instance_id]

        # Verify graceful handling
        assert engine.get_condition_state(child) is False
        # Verify condition was removed from internal tracking
        with pytest.raises(KeyError):
            engine._conditions[parent.instance_id]

        # Verify graceful handling
        assert engine.get_condition_state(parent) is False

    async def test_multiple_duration_conditions_with_or_dependencies(
        self, rule_engine_with_device_attrs, mock_timer_service
    ):
        """Test: Multiple duration conditions with OR logic (any child can trigger parent)."""
        engine = rule_engine_with_device_attrs

        # Create multiple children with durations
        child1 = DurationCondition(
            "child1_duration",
            duration_time=timedelta(seconds=1),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )
        child2 = DurationCondition(
            "child2_duration",
            duration_time=timedelta(seconds=2),
            device_id=456,
            attribute="motion",
            expected_value="active",
        )

        # Parent depends on ANY child (require_all=False for OR logic)
        parent = ParentCondition(
            "parent_either_child", [child1, child2], require_all=False
        )

        parent_event = asyncio.Event()

        # Add only parent - children will be automatically added as subconditions
        await engine.add_condition(parent, parent_event)

        # All should start false
        assert engine.get_condition_state(child1) is False
        assert engine.get_condition_state(child2) is False
        assert engine.get_condition_state(parent) is False

        # Trigger child1's device event
        event1 = create_device_event(123, "switch", "on")
        await engine.on_device_event(event1)

        # Child1 should be DURATION_PENDING but still report False
        assert engine.get_condition_state(child1) is False
        assert engine.get_condition_state(child2) is False
        assert engine.get_condition_state(parent) is False

        # Trigger child2's device event
        event2 = create_device_event(456, "motion", "active")
        await engine.on_device_event(event2)

        # Both children should be DURATION_PENDING but still report False
        assert engine.get_condition_state(child1) is False
        assert engine.get_condition_state(child2) is False
        assert engine.get_condition_state(parent) is False

        # Complete child1's duration first
        await mock_timer_service.trigger_timer(
            f"condition_duration({child1.instance_id})"
        )

        # Parent should fire because child1 became TRUE (OR logic - any child triggers parent)
        parent_fired = await asyncio.wait_for(parent_event.wait(), timeout=0.1)
        assert parent_fired

        # Parent and all subconditions should be auto-removed after firing
        # Verify condition was removed from internal tracking
        with pytest.raises(KeyError):
            engine._conditions[child1.instance_id]

        # Verify graceful handling
        assert engine.get_condition_state(child1) is False
        # Verify condition was removed from internal tracking
        with pytest.raises(KeyError):
            engine._conditions[child2.instance_id]

        # Verify graceful handling
        assert engine.get_condition_state(child2) is False
        # Verify condition was removed from internal tracking
        with pytest.raises(KeyError):
            engine._conditions[parent.instance_id]

        # Verify graceful handling
        assert engine.get_condition_state(parent) is False

    async def test_duration_cancelled_when_condition_becomes_false(
        self, rule_engine_with_device_attrs, mock_timer_service
    ):
        """Test: Duration timer is cancelled when condition becomes false."""
        engine = rule_engine_with_device_attrs

        condition = DurationCondition(
            "duration_cancel_test",
            duration_time=timedelta(seconds=1),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )
        condition_event = asyncio.Event()

        await engine.add_condition(condition, condition_event)

        # Should start false
        assert engine.get_condition_state(condition) is False

        # Make condition true to start duration
        event_on = create_device_event(123, "switch", "on")
        await engine.on_device_event(event_on)

        # Should be DURATION_PENDING but report False
        assert engine.get_condition_state(condition) is False

        # Verify duration timer is active
        duration_timer_id = f"condition_duration({condition.instance_id})"
        assert mock_timer_service.has_timer(duration_timer_id)

        # Make condition false before duration expires
        event_off = create_device_event(123, "switch", "off")
        await engine.on_device_event(event_off)

        # Condition should be false and duration timer should be cancelled
        assert engine.get_condition_state(condition) is False
        assert mock_timer_service.was_cancelled(duration_timer_id)

        # Condition should not fire
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(condition_event.wait(), timeout=0.01)

    async def test_condition_state_querying_during_duration_pending(
        self, rule_engine_with_device_attrs
    ):
        """Test: get_condition_state returns appropriate values for each state."""
        engine = rule_engine_with_device_attrs

        # Test condition without duration
        simple_condition = SimpleCondition(
            "simple_no_duration",
            device_id=123,
            attribute="switch",
            expected_value="on",
        )

        # Test condition with duration
        duration_condition = DurationCondition(
            "with_duration",
            duration_time=timedelta(seconds=1),
            device_id=456,
            attribute="motion",
            expected_value="active",
        )

        simple_event = asyncio.Event()
        duration_event = asyncio.Event()

        await engine.add_condition(simple_condition, simple_event)
        await engine.add_condition(duration_condition, duration_event)

        # Both start FALSE -> should return False
        assert engine.get_condition_state(simple_condition) is False
        assert engine.get_condition_state(duration_condition) is False

        # Make simple condition true (no duration) -> should return True
        simple_event_trigger = create_device_event(123, "switch", "on")
        await engine.on_device_event(simple_event_trigger)

        # Simple condition should fire immediately and be removed
        fired = await asyncio.wait_for(simple_event.wait(), timeout=0.1)
        assert fired

        # Verify condition was removed from internal tracking
        with pytest.raises(KeyError):
            engine._conditions[simple_condition.instance_id]

        # Verify graceful handling
        assert engine.get_condition_state(simple_condition) is False

        # Make duration condition true -> should be DURATION_PENDING but return False
        duration_event_trigger = create_device_event(456, "motion", "active")
        await engine.on_device_event(duration_event_trigger)

        # Should be DURATION_PENDING but get_condition_state should return False
        assert engine.get_condition_state(duration_condition) is False

        # Condition should not have fired yet
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(duration_event.wait(), timeout=0.01)

    async def test_condition_starts_true_with_duration(
        self, rule_engine, mock_he_client, mock_timer_service
    ):
        """Test: Condition that initializes as true but has duration."""
        engine = rule_engine

        # Set up device state - device starts with switch=on
        device_attrs = {"switch": "on"}
        bulk_attrs = {123: device_attrs}

        from unittest.mock import AsyncMock

        mock_he_client.get_bulk_attributes = AsyncMock(return_value=bulk_attrs)

        # Create condition that will be true initially and has duration
        condition = DurationCondition(
            "starts_true_with_duration",
            duration_time=timedelta(seconds=1),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )
        condition_event = asyncio.Event()

        # Add condition - should start in DURATION_PENDING state
        await engine.add_condition(condition, condition_event)

        # Should be DURATION_PENDING but report False to dependencies
        assert engine.get_condition_state(condition) is False

        # Should not have fired immediately
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(condition_event.wait(), timeout=0.01)

        # Verify duration timer was started for initially true condition
        duration_timer_id = f"condition_duration({condition.instance_id})"
        assert mock_timer_service.has_timer(duration_timer_id)

        # Complete the duration
        await mock_timer_service.trigger_timer(duration_timer_id)

        # Now condition should fire
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

        # Should be auto-removed
        # Verify condition was removed from internal tracking
        with pytest.raises(KeyError):
            engine._conditions[condition.instance_id]

        # Verify graceful handling
        assert engine.get_condition_state(condition) is False

    async def test_duration_condition_with_parent_full_workflow(
        self, rule_engine_with_device_attrs, mock_timer_service
    ):
        """Test: Full workflow - duration condition with parent dependency, verifying state propagation."""
        engine = rule_engine_with_device_attrs

        # Create child with duration and parent that depends on it (require_all=False for OR logic)
        child = DurationCondition(
            "child_workflow",
            duration_time=timedelta(seconds=1),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )
        parent = ParentCondition("parent_workflow", [child], require_all=False)

        child_event = asyncio.Event()
        parent_event = asyncio.Event()

        await engine.add_condition(child, child_event)
        await engine.add_condition(parent, parent_event)

        # Phase 1: Both start false
        assert engine.get_condition_state(child) is False
        assert engine.get_condition_state(parent) is False

        # Phase 2: Child becomes true but is DURATION_PENDING
        event = create_device_event(123, "switch", "on")
        await engine.on_device_event(event)

        # Child should be DURATION_PENDING but report False to parent (prevents premature triggering)
        assert engine.get_condition_state(child) is False
        assert engine.get_condition_state(parent) is False

        # Neither should have fired yet
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(child_event.wait(), timeout=0.01)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(parent_event.wait(), timeout=0.01)

        # Phase 3: Duration completes - this should propagate state to parent
        duration_timer_id = f"condition_duration({child.instance_id})"
        await mock_timer_service.trigger_timer(duration_timer_id)

        # Child should fire
        fired = await asyncio.wait_for(child_event.wait(), timeout=0.1)
        assert fired

        # CRITICAL: Parent should ALSO fire because child became TRUE and propagated state
        parent_fired = await asyncio.wait_for(parent_event.wait(), timeout=0.1)
        assert parent_fired

        # Both should be auto-removed after firing (no dependents)
        # Verify condition was removed from internal tracking
        with pytest.raises(KeyError):
            engine._conditions[child.instance_id]

        # Verify graceful handling
        assert engine.get_condition_state(child) is False
        # Verify condition was removed from internal tracking
        with pytest.raises(KeyError):
            engine._conditions[parent.instance_id]

        # Verify graceful handling
        assert engine.get_condition_state(parent) is False
