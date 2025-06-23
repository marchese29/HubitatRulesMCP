"""Unit tests for RuleEngine class - Milestone 1.

These tests focus on testing individual methods in isolation using mocks.
"""

from unittest.mock import patch

from rules.engine import ConditionNotifier, ConditionState
from tests.test_conditions import (
    ConditionWithSubconditions,
    SimpleCondition,
)
from tests.test_helpers import (
    ConditionStateChecker,
    assert_engine_state_clean,
)


class TestGetConditionState:
    """Test get_condition_state method."""

    def test_returns_true_for_true_condition(self, rule_engine):
        """Test that get_condition_state returns True for a condition that is True."""
        condition = SimpleCondition("test_condition")
        notifier = ConditionNotifier(condition)

        # Directly set internal state (bypassing normal initialization)
        rule_engine._conditions[condition.instance_id] = (notifier, ConditionState.TRUE)

        result = rule_engine.get_condition_state(condition)
        assert result is True

    def test_returns_false_for_false_condition(self, rule_engine):
        """Test that get_condition_state returns False for a condition that is False."""
        condition = SimpleCondition("test_condition")
        notifier = ConditionNotifier(condition)

        # Directly set internal state
        rule_engine._conditions[condition.instance_id] = (
            notifier,
            ConditionState.FALSE,
        )

        result = rule_engine.get_condition_state(condition)
        assert result is False

    def test_returns_false_for_nonexistent_condition(self, rule_engine):
        """Test that get_condition_state returns False for non-existent condition."""
        condition = SimpleCondition("nonexistent")

        result = rule_engine.get_condition_state(condition)
        assert result is False


class TestRemoveCondition:
    """Test _remove_condition method."""

    def test_removes_condition_from_tracking(self, rule_engine, mock_timer_service):
        """Test that _remove_condition removes condition from internal tracking."""
        condition = SimpleCondition("test_condition", device_id=123)
        notifier = ConditionNotifier(condition)

        # Set up internal state as if condition was added
        rule_engine._conditions[condition.instance_id] = (
            notifier,
            ConditionState.FALSE,
        )
        rule_engine._device_to_conditions[123] = {condition.instance_id}

        # Remove the condition
        rule_engine._remove_condition(condition)

        # Verify cleanup
        assert condition.instance_id not in rule_engine._conditions
        assert 123 not in rule_engine._device_to_conditions

        # Verify timer cancellation was attempted
        assert mock_timer_service.was_cancelled(
            f"condition_timeout({condition.instance_id})"
        )
        assert mock_timer_service.was_cancelled(
            f"condition_duration({condition.instance_id})"
        )

    def test_removes_device_mapping_but_preserves_other_conditions(self, rule_engine):
        """Test that removing condition only removes its device mapping."""
        condition1 = SimpleCondition("condition1", device_id=123)
        condition2 = SimpleCondition("condition2", device_id=123)
        notifier1 = ConditionNotifier(condition1)
        notifier2 = ConditionNotifier(condition2)

        # Set up two conditions on same device
        rule_engine._conditions[condition1.instance_id] = (
            notifier1,
            ConditionState.FALSE,
        )
        rule_engine._conditions[condition2.instance_id] = (
            notifier2,
            ConditionState.TRUE,
        )
        rule_engine._device_to_conditions[123] = {
            condition1.instance_id,
            condition2.instance_id,
        }

        # Remove first condition
        rule_engine._remove_condition(condition1)

        # Verify only condition1 removed, condition2 remains
        assert condition1.instance_id not in rule_engine._conditions
        assert condition2.instance_id in rule_engine._conditions
        assert rule_engine._device_to_conditions[123] == {condition2.instance_id}

    def test_removes_empty_device_mapping(self, rule_engine):
        """Test that device mapping is removed when last condition is removed."""
        condition = SimpleCondition("test_condition", device_id=123)
        notifier = ConditionNotifier(condition)

        # Set up condition with device mapping
        rule_engine._conditions[condition.instance_id] = (
            notifier,
            ConditionState.FALSE,
        )
        rule_engine._device_to_conditions[123] = {condition.instance_id}

        # Remove condition
        rule_engine._remove_condition(condition)

        # Verify device mapping completely removed
        assert 123 not in rule_engine._device_to_conditions

    def test_removes_condition_dependencies(self, rule_engine):
        """Test that condition dependencies are cleaned up."""
        condition = SimpleCondition("test_condition")
        notifier = ConditionNotifier(condition)

        # Set up condition with dependencies
        rule_engine._conditions[condition.instance_id] = (
            notifier,
            ConditionState.FALSE,
        )
        rule_engine._condition_deps[condition.instance_id] = {"parent1", "parent2"}

        # Remove condition
        rule_engine._remove_condition(condition)

        # Verify dependency cleanup
        assert condition.instance_id not in rule_engine._condition_deps

    def test_handles_nonexistent_condition_gracefully(self, rule_engine):
        """Test that removing non-existent condition doesn't raise error."""
        condition = SimpleCondition("nonexistent")

        # Should not raise an exception
        rule_engine._remove_condition(condition)

        # Engine should remain clean
        assert_engine_state_clean(rule_engine)

    def test_removes_subconditions_recursively(self, rule_engine):
        """Test that subconditions are removed when parent is removed."""
        child1 = SimpleCondition("child1", device_id=123)
        child2 = SimpleCondition("child2", device_id=456)
        parent = ConditionWithSubconditions("parent", [child1, child2])

        notifier_child1 = ConditionNotifier(child1)
        notifier_child2 = ConditionNotifier(child2)
        notifier_parent = ConditionNotifier(parent)

        # Set up parent and children in engine
        rule_engine._conditions[child1.instance_id] = (
            notifier_child1,
            ConditionState.FALSE,
        )
        rule_engine._conditions[child2.instance_id] = (
            notifier_child2,
            ConditionState.FALSE,
        )
        rule_engine._conditions[parent.instance_id] = (
            notifier_parent,
            ConditionState.FALSE,
        )
        rule_engine._device_to_conditions[123] = {child1.instance_id}
        rule_engine._device_to_conditions[456] = {child2.instance_id}

        # Remove parent
        rule_engine._remove_condition(parent)

        # Verify all conditions removed
        assert parent.instance_id not in rule_engine._conditions
        assert child1.instance_id not in rule_engine._conditions
        assert child2.instance_id not in rule_engine._conditions
        assert_engine_state_clean(rule_engine)


class TestPropagateStateUpdate:
    """Test _propagate_state_update method."""

    async def test_updates_single_condition_state(self, rule_engine):
        """Test that state update changes condition state."""
        condition = SimpleCondition("test_condition")
        condition.set_state(True)  # Set condition to evaluate to True
        notifier = ConditionNotifier(condition)

        # Set up condition with initial False state
        rule_engine._conditions[condition.instance_id] = (
            notifier,
            ConditionState.FALSE,
        )

        # Propagate state update
        touched = await rule_engine._propagate_state_update([notifier])

        # Verify state was updated
        assert rule_engine._conditions[condition.instance_id][1] == ConditionState.TRUE
        assert len(touched) == 1
        assert touched[0] == notifier

    async def test_no_update_when_state_unchanged(self, rule_engine):
        """Test that no update occurs when condition state hasn't changed."""
        condition = SimpleCondition("test_condition")
        condition.set_state(False)  # Keep condition False
        notifier = ConditionNotifier(condition)

        # Set up condition with False state
        rule_engine._conditions[condition.instance_id] = (
            notifier,
            ConditionState.FALSE,
        )

        # Propagate state update
        touched = await rule_engine._propagate_state_update([notifier])

        # Verify state unchanged but condition was still touched
        assert rule_engine._conditions[condition.instance_id][1] == ConditionState.FALSE
        assert len(touched) == 1

    async def test_propagates_to_dependent_conditions(self, rule_engine):
        """Test that state changes propagate to dependent conditions."""
        child = SimpleCondition("child")
        child.set_state(True)
        parent = SimpleCondition("parent")

        child_notifier = ConditionNotifier(child)
        parent_notifier = ConditionNotifier(parent)

        # Set up child and parent conditions
        rule_engine._conditions[child.instance_id] = (
            child_notifier,
            ConditionState.FALSE,
        )
        rule_engine._conditions[parent.instance_id] = (
            parent_notifier,
            ConditionState.FALSE,
        )
        rule_engine._condition_deps[child.instance_id] = {parent.instance_id}

        # Mock parent's on_condition_event method
        with patch.object(parent, "on_condition_event") as mock_on_event:
            # Propagate child state update
            touched = await rule_engine._propagate_state_update([child_notifier])

            # Verify parent was notified of child state change
            mock_on_event.assert_called_once_with(child, True)

        # Verify both conditions were touched
        touched_ids = {notifier.condition.identifier for notifier in touched}
        assert "child" in touched_ids
        assert "parent" in touched_ids

    async def test_handles_missing_dependent_condition(self, rule_engine):
        """Test that missing dependent conditions don't cause errors."""
        condition = SimpleCondition("test_condition")
        condition.set_state(True)
        notifier = ConditionNotifier(condition)

        # Set up condition with dependency to non-existent condition
        rule_engine._conditions[condition.instance_id] = (
            notifier,
            ConditionState.FALSE,
        )
        rule_engine._condition_deps[condition.instance_id] = {"nonexistent"}

        # Should not raise an exception
        touched = await rule_engine._propagate_state_update([notifier])

        # Should still process the original condition
        assert len(touched) == 1
        assert touched[0] == notifier

    async def test_handles_multiple_initial_conditions(self, rule_engine):
        """Test that multiple conditions can be updated simultaneously."""
        condition1 = SimpleCondition("condition1")
        condition2 = SimpleCondition("condition2")
        condition1.set_state(True)
        condition2.set_state(True)

        notifier1 = ConditionNotifier(condition1)
        notifier2 = ConditionNotifier(condition2)

        # Set up both conditions
        rule_engine._conditions[condition1.instance_id] = (
            notifier1,
            ConditionState.FALSE,
        )
        rule_engine._conditions[condition2.instance_id] = (
            notifier2,
            ConditionState.FALSE,
        )

        # Propagate updates for both
        touched = await rule_engine._propagate_state_update([notifier1, notifier2])

        # Verify both were updated
        assert rule_engine._conditions[condition1.instance_id][1] == ConditionState.TRUE
        assert rule_engine._conditions[condition2.instance_id][1] == ConditionState.TRUE
        assert len(touched) == 2


class TestBasicEngineState:
    """Test basic engine state management."""

    def test_engine_initializes_empty(self, rule_engine):
        """Test that new engine has empty state."""
        assert_engine_state_clean(rule_engine)

    def test_engine_state_checker_works(self, rule_engine):
        """Test that ConditionStateChecker helper works correctly."""
        checker = ConditionStateChecker(rule_engine)

        # Initially empty
        assert checker.get_active_condition_count() == 0
        assert checker.get_device_mapping_count() == 0

        # Add some state
        condition = SimpleCondition("test", device_id=123)
        notifier = ConditionNotifier(condition)
        rule_engine._conditions[condition.instance_id] = (notifier, ConditionState.TRUE)
        rule_engine._device_to_conditions[123] = {condition.instance_id}

        # Verify checker detects state
        assert checker.get_active_condition_count() == 1
        assert checker.get_device_mapping_count() == 1
        assert checker.verify_condition_exists(condition.instance_id)
        assert checker.verify_condition_state(condition.instance_id, True)
        assert checker.verify_device_mapping(123, condition.instance_id)
