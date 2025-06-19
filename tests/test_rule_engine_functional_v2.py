"""
Functional tests for RuleEngine - Using Correct API

These tests focus on realistic workflows and end-to-end behavior of the RuleEngine,
using the actual engine API with asyncio.Event-based notifications and proper
auto-removal behavior.
"""

import asyncio
from datetime import timedelta

import pytest


from .test_conditions import (
    AlwaysFalseCondition,
    AlwaysTrueCondition,
    SimpleCondition,
    TimeoutCondition,
)
from .test_helpers import create_device_event


class TestSimpleConditionScenarios:
    """Test basic condition scenarios with device events."""

    async def test_add_condition_trigger_event_verify_fires(
        self, rule_engine_with_device_attrs
    ):
        """Test: Add condition, trigger device event, verify condition fires"""
        engine = rule_engine_with_device_attrs

        # Create a condition that fires when device 123 switch is "on"
        condition = SimpleCondition(
            "switch_on", device_id=123, attribute="switch", expected_value="on"
        )

        # Add condition to engine with event notification
        condition_event = asyncio.Event()
        await engine.add_condition(condition, condition_event)

        # Verify condition starts in false state (device is currently "off")
        state = engine.get_condition_state(condition)
        assert state is False

        # Trigger device event that makes condition true
        event = create_device_event(123, "switch", "on")
        await engine.on_device_event(event)

        # Verify condition fired by waiting for event
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

        # Verify condition was auto-removed after firing
        with pytest.raises(KeyError):
            engine.get_condition_state(condition)

    async def test_multiple_independent_conditions_different_devices(
        self, rule_engine_with_device_attrs
    ):
        """Test: Multiple independent conditions on different devices"""
        engine = rule_engine_with_device_attrs

        # Create conditions for different devices
        condition1 = SimpleCondition(
            "dev123_switch", device_id=123, attribute="switch", expected_value="on"
        )
        condition2 = SimpleCondition(
            "dev456_motion", device_id=456, attribute="motion", expected_value="active"
        )

        condition1_event = asyncio.Event()
        condition2_event = asyncio.Event()

        # Add both conditions
        await engine.add_condition(condition1, condition1_event)
        await engine.add_condition(condition2, condition2_event)

        # Verify both start false
        assert engine.get_condition_state(condition1) is False
        assert engine.get_condition_state(condition2) is False

        # Trigger event for first device only
        event1 = create_device_event(123, "switch", "on")
        await engine.on_device_event(event1)

        # Verify only first condition fired
        fired1 = await asyncio.wait_for(condition1_event.wait(), timeout=0.1)
        assert fired1

        # Second condition should not have fired
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(condition2_event.wait(), timeout=0.01)

        # Verify first condition was auto-removed, second still exists
        with pytest.raises(KeyError):
            engine.get_condition_state(condition1)
        assert engine.get_condition_state(condition2) is False

        # Trigger event for second device
        event2 = create_device_event(456, "motion", "active")
        await engine.on_device_event(event2)

        # Verify second condition now fired
        fired2 = await asyncio.wait_for(condition2_event.wait(), timeout=0.1)
        assert fired2

        # Both conditions should now be auto-removed
        with pytest.raises(KeyError):
            engine.get_condition_state(condition2)

    async def test_multiple_conditions_same_device(self, rule_engine_with_device_attrs):
        """Test: Multiple conditions on same device"""
        engine = rule_engine_with_device_attrs

        # Create two conditions for same device, different attributes
        condition1 = SimpleCondition(
            "switch_on", device_id=123, attribute="switch", expected_value="on"
        )
        condition2 = SimpleCondition(
            "level_high", device_id=123, attribute="level", expected_value=75
        )

        condition1_event = asyncio.Event()
        condition2_event = asyncio.Event()

        # Add both conditions
        await engine.add_condition(condition1, condition1_event)
        await engine.add_condition(condition2, condition2_event)

        # Trigger switch event - should only affect switch condition
        switch_event = create_device_event(123, "switch", "on")
        await engine.on_device_event(switch_event)

        # Verify switch condition fired
        fired1 = await asyncio.wait_for(condition1_event.wait(), timeout=0.1)
        assert fired1

        # Level condition should not have fired
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(condition2_event.wait(), timeout=0.01)

        # Switch condition auto-removed, level condition still exists
        with pytest.raises(KeyError):
            engine.get_condition_state(condition1)
        assert engine.get_condition_state(condition2) is False

        # Trigger level event - should affect remaining condition
        level_event = create_device_event(123, "level", 75)
        await engine.on_device_event(level_event)

        # Verify level condition fired
        fired2 = await asyncio.wait_for(condition2_event.wait(), timeout=0.1)
        assert fired2

        # Level condition should now be auto-removed
        with pytest.raises(KeyError):
            engine.get_condition_state(condition2)

    async def test_condition_state_tracking_before_firing(
        self, rule_engine_with_device_attrs
    ):
        """Test: Condition state changes before final firing"""
        engine = rule_engine_with_device_attrs

        condition = SimpleCondition(
            "switch_on", device_id=123, attribute="switch", expected_value="on"
        )
        condition_event = asyncio.Event()

        await engine.add_condition(condition, condition_event)

        # Initial state should be false
        assert engine.get_condition_state(condition) is False

        # Make condition true then false again (without auto-removal)
        await engine.on_device_event(create_device_event(123, "switch", "on"))

        # Condition should have fired and been auto-removed
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

        with pytest.raises(KeyError):
            engine.get_condition_state(condition)


class TestConditionLifecycle:
    """Test condition lifecycle management."""

    async def test_add_condition_with_initial_device_state_fetching(
        self, rule_engine, mock_he_client
    ):
        """Test: Add condition with initial device state fetching"""
        engine = rule_engine

        # Set up device state in mock - device 789 has switch=on initially
        device_attrs = {"switch": "on", "level": 25}
        bulk_attrs = {789: device_attrs}

        # Configure async mock properly
        from unittest.mock import AsyncMock

        mock_he_client.get_bulk_attributes = AsyncMock(return_value=bulk_attrs)

        # Create condition that should be true with current device state
        condition = SimpleCondition(
            "already_on", device_id=789, attribute="switch", expected_value="on"
        )
        condition_event = asyncio.Event()

        # Add condition - this should fetch initial state and immediately fire
        await engine.add_condition(condition, condition_event)

        # Verify device state was fetched using bulk method
        mock_he_client.get_bulk_attributes.assert_called_once_with([789])

        # Condition should have immediately fired and auto-removed
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

        with pytest.raises(KeyError):
            engine.get_condition_state(condition)

    async def test_remove_condition_manually_with_cleanup_verification(
        self, rule_engine_with_device_attrs
    ):
        """Test: Remove condition manually (cleanup verification)"""
        engine = rule_engine_with_device_attrs

        condition = SimpleCondition(
            "temp_condition", device_id=123, attribute="switch", expected_value="on"
        )
        condition_event = asyncio.Event()

        # Add condition
        await engine.add_condition(condition, condition_event)

        # Verify condition exists and is false
        assert engine.get_condition_state(condition) is False

        # Remove condition manually
        await engine.remove_condition(condition)

        # Verify condition no longer exists
        with pytest.raises(KeyError):
            engine.get_condition_state(condition)

        # Verify engine internal state is clean
        assert condition.identifier not in engine._conditions
        assert not any(
            condition.identifier in device_conditions
            for device_conditions in engine._device_to_conditions.values()
        )

    async def test_condition_auto_removes_when_fired(
        self, rule_engine_with_device_attrs
    ):
        """Test: Condition auto-removes itself when it fires"""
        engine = rule_engine_with_device_attrs

        condition = SimpleCondition(
            "auto_remove", device_id=123, attribute="switch", expected_value="on"
        )
        condition_event = asyncio.Event()

        # Add condition
        await engine.add_condition(condition, condition_event)

        # Verify condition exists and is false
        assert engine.get_condition_state(condition) is False

        # Trigger event that makes condition true
        event = create_device_event(123, "switch", "on")
        await engine.on_device_event(event)

        # Verify condition fired
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

        # Verify condition was auto-removed
        with pytest.raises(KeyError):
            engine.get_condition_state(condition)

    async def test_get_condition_state_for_active_vs_removed_conditions(
        self, rule_engine_with_device_attrs
    ):
        """Test: Get condition state for active vs removed conditions"""
        engine = rule_engine_with_device_attrs

        # Add two conditions
        condition1 = SimpleCondition(
            "active_condition", device_id=123, attribute="switch", expected_value="on"
        )
        condition2 = SimpleCondition(
            "removed_condition",
            device_id=456,
            attribute="motion",
            expected_value="active",
        )

        condition1_event = asyncio.Event()
        condition2_event = asyncio.Event()

        await engine.add_condition(condition1, condition1_event)
        await engine.add_condition(condition2, condition2_event)

        # Both should be active and return boolean states
        assert engine.get_condition_state(condition1) is False
        assert engine.get_condition_state(condition2) is False

        # Remove one condition manually
        await engine.remove_condition(condition2)

        # Active condition should still return boolean
        assert engine.get_condition_state(condition1) is False

        # Removed condition should raise KeyError
        with pytest.raises(KeyError):
            engine.get_condition_state(condition2)


class TestDeviceEventProcessing:
    """Test device event processing behavior."""

    async def test_relevant_device_events_trigger_condition_evaluation(
        self, rule_engine_with_device_attrs
    ):
        """Test: Relevant device events trigger condition evaluation"""
        engine = rule_engine_with_device_attrs

        condition = SimpleCondition(
            "motion_active", device_id=123, attribute="motion", expected_value="active"
        )
        condition_event = asyncio.Event()

        await engine.add_condition(condition, condition_event)

        # Event for correct device and attribute should trigger evaluation
        relevant_event = create_device_event(123, "motion", "active")
        await engine.on_device_event(relevant_event)

        # Verify condition fired
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

    async def test_irrelevant_device_events_are_ignored(
        self, rule_engine_with_device_attrs
    ):
        """Test: Irrelevant device events are ignored"""
        engine = rule_engine_with_device_attrs

        condition = SimpleCondition(
            "motion_active", device_id=123, attribute="motion", expected_value="active"
        )
        condition_event = asyncio.Event()

        await engine.add_condition(condition, condition_event)

        # Event for wrong device should be ignored
        wrong_device_event = create_device_event(999, "motion", "active")
        await engine.on_device_event(wrong_device_event)

        # Event for wrong attribute should be ignored
        wrong_attribute_event = create_device_event(123, "switch", "on")
        await engine.on_device_event(wrong_attribute_event)

        # Condition should not have fired
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(condition_event.wait(), timeout=0.01)

        # Condition should still exist and be false
        assert engine.get_condition_state(condition) is False

    async def test_rapid_successive_events_on_same_device(
        self, rule_engine_with_device_attrs
    ):
        """Test: Rapid successive events on same device"""
        engine = rule_engine_with_device_attrs

        condition = SimpleCondition(
            "switch_on", device_id=123, attribute="switch", expected_value="on"
        )
        condition_event = asyncio.Event()

        await engine.add_condition(condition, condition_event)

        # Send rapid succession of events
        events = [
            create_device_event(123, "switch", "on"),  # Should fire condition
            # NOTE: Condition auto-removes after first firing, so subsequent events
            # will not affect it since it's no longer tracked
        ]

        # Process first event - should fire condition
        await engine.on_device_event(events[0])

        # Verify condition fired
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

        # Condition should be auto-removed
        with pytest.raises(KeyError):
            engine.get_condition_state(condition)

    async def test_events_for_non_tracked_devices_dont_affect_engine(
        self, rule_engine_with_device_attrs
    ):
        """Test: Events for non-tracked devices don't affect engine"""
        engine = rule_engine_with_device_attrs

        # Add condition for device 123
        condition = SimpleCondition(
            "tracked_device", device_id=123, attribute="switch", expected_value="on"
        )
        condition_event = asyncio.Event()

        await engine.add_condition(condition, condition_event)

        # Send events for completely different devices
        untracked_events = [
            create_device_event(999, "switch", "on"),
            create_device_event(888, "motion", "active"),
            create_device_event(777, "level", 75),
        ]

        for event in untracked_events:
            await engine.on_device_event(event)

        # Our condition should be unaffected
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(condition_event.wait(), timeout=0.01)

        assert engine.get_condition_state(condition) is False

        # Now send relevant event to verify engine still works
        relevant_event = create_device_event(123, "switch", "on")
        await engine.on_device_event(relevant_event)

        # Condition should now fire
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired


class TestTimeoutBehavior:
    """Test condition timeout behavior using mock timer service."""

    async def test_condition_with_timeout_fires_timeout_event(
        self, rule_engine_with_device_attrs, mock_timer_service
    ):
        """Test: Condition with timeout fires timeout event when timer expires"""
        engine = rule_engine_with_device_attrs

        condition = TimeoutCondition(
            "timeout_test",
            timeout_duration=timedelta(milliseconds=100),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )
        condition_event = asyncio.Event()
        timeout_event = asyncio.Event()

        await engine.add_condition(condition, condition_event, timeout_event)

        # Verify timeout timer was started
        assert mock_timer_service.get_active_timer_count() > 0

        # Trigger the timeout manually using mock timer
        timer_id = f"condition_timeout({condition.identifier})"
        await mock_timer_service.trigger_timer(timer_id)

        # Verify timeout event was fired
        fired = await asyncio.wait_for(timeout_event.wait(), timeout=0.1)
        assert fired

        # Condition should be auto-removed after timeout
        with pytest.raises(KeyError):
            engine.get_condition_state(condition)

    async def test_timeout_cancelled_when_condition_becomes_true(
        self, rule_engine_with_device_attrs, mock_timer_service
    ):
        """Test: Timeout timer is cancelled when condition becomes true"""
        engine = rule_engine_with_device_attrs

        condition = TimeoutCondition(
            "timeout_cancel_test",
            timeout_duration=timedelta(milliseconds=100),
            device_id=123,
            attribute="switch",
            expected_value="on",
        )
        condition_event = asyncio.Event()
        timeout_event = asyncio.Event()

        await engine.add_condition(condition, condition_event, timeout_event)

        # Verify timeout timer was started
        timer_count_before = mock_timer_service.get_active_timer_count()
        assert timer_count_before > 0

        # Make condition true before timeout
        event = create_device_event(123, "switch", "on")
        await engine.on_device_event(event)

        # Verify condition fired (not timeout)
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

        # Timeout should not have fired
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(timeout_event.wait(), timeout=0.01)

        # Timeout timer should be cancelled/cleaned up
        timer_count_after = mock_timer_service.get_active_timer_count()
        assert timer_count_after < timer_count_before


class TestImmediateConditions:
    """Test conditions that are immediately true when added."""

    async def test_condition_immediately_true_when_added(
        self, rule_engine_with_device_attrs
    ):
        """Test: Condition that is immediately true when added"""
        engine = rule_engine_with_device_attrs

        # Use AlwaysTrueCondition for immediate firing
        condition = AlwaysTrueCondition("immediate_true")
        condition_event = asyncio.Event()

        # Add condition - should immediately fire and auto-remove
        await engine.add_condition(condition, condition_event)

        # Verify condition fired immediately
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

        # Condition should be auto-removed
        with pytest.raises(KeyError):
            engine.get_condition_state(condition)

    async def test_condition_never_becomes_true(self, rule_engine_with_device_attrs):
        """Test: Condition that never becomes true (stays in engine until manually removed)"""
        engine = rule_engine_with_device_attrs

        condition = AlwaysFalseCondition("always_false")
        condition_event = asyncio.Event()

        await engine.add_condition(condition, condition_event)

        # Condition should exist and be false
        assert engine.get_condition_state(condition) is False

        # Send various events - condition should never fire
        events = [
            create_device_event(123, "switch", "on"),
            create_device_event(456, "motion", "active"),
        ]

        for event in events:
            await engine.on_device_event(event)

        # Condition should still not have fired
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(condition_event.wait(), timeout=0.01)

        # Condition should still exist
        assert engine.get_condition_state(condition) is False

        # Clean up manually
        await engine.remove_condition(condition)


class TestEngineResourceManagement:
    """Test engine resource cleanup and management."""

    async def test_engine_state_clean_after_condition_auto_removal(
        self, rule_engine_with_device_attrs
    ):
        """Test: Engine internal state is clean after condition auto-removal"""
        engine = rule_engine_with_device_attrs

        condition = SimpleCondition(
            "cleanup_test", device_id=123, attribute="switch", expected_value="on"
        )
        condition_event = asyncio.Event()

        # Capture initial state
        initial_condition_count = len(engine._conditions)
        initial_device_mapping_count = len(engine._device_to_conditions)

        # Add condition
        await engine.add_condition(condition, condition_event)

        # Verify condition was added
        assert len(engine._conditions) == initial_condition_count + 1
        assert 123 in engine._device_to_conditions

        # Trigger condition to auto-remove
        event = create_device_event(123, "switch", "on")
        await engine.on_device_event(event)

        # Wait for condition to fire
        fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
        assert fired

        # Verify engine state is clean
        assert len(engine._conditions) == initial_condition_count

        # Device mapping should be clean if no other conditions track device 123
        if not any(
            condition_id
            for condition_set in engine._device_to_conditions.values()
            for condition_id in condition_set
        ):
            assert len(engine._device_to_conditions) == initial_device_mapping_count

    async def test_multiple_conditions_cleanup_independently(
        self, rule_engine_with_device_attrs
    ):
        """Test: Multiple conditions clean up independently when they fire"""
        engine = rule_engine_with_device_attrs

        # Create multiple conditions
        conditions = [
            SimpleCondition(
                f"condition_{i}",
                device_id=100 + i,
                attribute="switch",
                expected_value="on",
            )
            for i in range(3)
        ]
        events = [asyncio.Event() for _ in conditions]

        # Add all conditions
        for condition, event in zip(conditions, events):
            await engine.add_condition(condition, event)

        # Verify all conditions exist
        for condition in conditions:
            assert engine.get_condition_state(condition) is False

        # Fire conditions one by one
        for i, (condition, condition_event) in enumerate(zip(conditions, events)):
            # Trigger this specific condition
            device_event = create_device_event(100 + i, "switch", "on")
            await engine.on_device_event(device_event)

            # Verify this condition fired
            fired = await asyncio.wait_for(condition_event.wait(), timeout=0.1)
            assert fired

            # This condition should be removed
            with pytest.raises(KeyError):
                engine.get_condition_state(condition)

            # Other conditions should still exist
            for j, other_condition in enumerate(conditions):
                if i != j and j > i:  # Only check conditions that haven't fired yet
                    assert engine.get_condition_state(other_condition) is False
