"""
Tests for graceful handling of timed-out conditions.

These tests verify that when conditions time out and are removed,
dependent conditions can still query their state without errors.
"""

import asyncio
from datetime import timedelta

import pytest

from .test_conditions import ParentCondition, SimpleCondition, TimeoutCondition
from .test_helpers import create_device_event


class TestTimeoutGracefulHandling:
    """Test graceful handling when conditions time out."""

    async def test_parent_gracefully_handles_child_timeout(
        self, rule_engine_with_device_attrs, mock_timer_service
    ):
        """Test: Parent condition gracefully handles when child subcondition times out."""
        engine = rule_engine_with_device_attrs

        # Create child condition with timeout
        child = TimeoutCondition(
            "child_with_timeout",
            timeout_duration=timedelta(seconds=1),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )

        # Create parent that depends on child (AND logic - requires all children true)
        parent = ParentCondition("parent_depends_on_child", [child], require_all=True)

        parent_event = asyncio.Event()

        # Add only parent - child will be automatically added as subcondition
        await engine.add_condition(parent, parent_event)

        # Both should start false
        assert engine.get_condition_state(child) is False
        assert engine.get_condition_state(parent) is False

        # Trigger child's timeout manually
        timeout_timer_id = f"condition_timeout({child.instance_id})"
        await mock_timer_service.trigger_timer(timeout_timer_id)

        # Child should be removed when it times out
        with pytest.raises(KeyError):
            engine._conditions[child.instance_id]

        # Parent should still exist (timeouts don't remove ancestors)
        assert parent.instance_id in engine._conditions

        # The key test: get_condition_state should gracefully return False for missing child
        assert engine.get_condition_state(child) is False
        # Parent should still be evaluable and return False (since child is missing/False)
        assert engine.get_condition_state(parent) is False

    async def test_direct_get_condition_state_on_timed_out_condition(
        self, rule_engine_with_device_attrs, mock_timer_service
    ):
        """Test: Direct get_condition_state call on timed-out condition returns False."""
        engine = rule_engine_with_device_attrs

        # Create condition with timeout
        condition = TimeoutCondition(
            "condition_with_timeout",
            timeout_duration=timedelta(seconds=1),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )

        timeout_event = asyncio.Event()

        await engine.add_condition(condition, timeout_event=timeout_event)

        # Should start false
        assert engine.get_condition_state(condition) is False

        # Trigger timeout
        timeout_timer_id = f"condition_timeout({condition.instance_id})"
        await mock_timer_service.trigger_timer(timeout_timer_id)

        # Timeout event should fire
        timeout_fired = await asyncio.wait_for(timeout_event.wait(), timeout=0.1)
        assert timeout_fired

        # Condition should be removed from engine
        with pytest.raises(KeyError):
            engine._conditions[condition.instance_id]

        # Direct call to get_condition_state should return False (not crash)
        result = engine.get_condition_state(condition)
        assert result is False

    async def test_parent_or_logic_with_one_child_timeout(
        self, rule_engine_with_device_attrs, mock_timer_service
    ):
        """Test: Parent with OR logic where one child times out but other remains."""
        engine = rule_engine_with_device_attrs

        # Create two children - one with timeout, one without
        child1 = TimeoutCondition(
            "child1_with_timeout",
            timeout_duration=timedelta(seconds=1),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )
        child2 = SimpleCondition(
            "child2_no_timeout",
            device_id=456,
            attribute="motion",
            expected_value="active",
        )

        # Parent with OR logic (require_all=False) - any child true makes parent true
        parent = ParentCondition("parent_or_logic", [child1, child2], require_all=False)

        parent_event = asyncio.Event()

        # Add only parent - children will be automatically added as subconditions
        await engine.add_condition(parent, parent_event)

        # All should start false
        assert engine.get_condition_state(child1) is False
        assert engine.get_condition_state(child2) is False
        assert engine.get_condition_state(parent) is False

        # Trigger child1's timeout
        timeout_timer_id = f"condition_timeout({child1.instance_id})"
        await mock_timer_service.trigger_timer(timeout_timer_id)

        # Child1 should be removed after timeout
        with pytest.raises(KeyError):
            engine._conditions[child1.instance_id]

        # Child2 and parent should still exist and be false
        assert engine.get_condition_state(child2) is False
        assert engine.get_condition_state(parent) is False

        # Now make child2 true - this should make parent true (OR logic)
        event2 = create_device_event(456, "motion", "active")
        await engine.on_device_event(event2)

        # Child2 should become true and fire (no timeout)
        # Parent should also fire because child2 is true (OR logic)
        parent_fired = await asyncio.wait_for(parent_event.wait(), timeout=0.1)
        assert parent_fired

        # Parent and child2 should be auto-removed after firing
        with pytest.raises(KeyError):
            engine._conditions[child2.instance_id]
        with pytest.raises(KeyError):
            engine._conditions[parent.instance_id]

        # But get_condition_state should gracefully handle missing conditions
        assert engine.get_condition_state(child2) is False
        assert engine.get_condition_state(parent) is False
