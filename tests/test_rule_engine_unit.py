"""Unit tests for RuleEngine class - Milestone 1.

These tests focus on testing individual methods in isolation using mocks.
"""

import pytest
from unittest.mock import MagicMock

from rules.engine import RuleEngine, ConditionNotifier
from tests.test_conditions import (
    SimpleCondition,
    TimeoutCondition,
    ConditionWithSubconditions,
)
from tests.test_helpers import (
    create_mock_hubitat_client,
    create_mock_timer_service,
    assert_engine_state_clean,
    ConditionStateChecker,
)


class TestGetConditionState:
    """Test get_condition_state method."""

    def test_returns_true_for_true_condition(self, rule_engine):
        """Test that get_condition_state returns True for a condition that is True."""
        condition = SimpleCondition("test_condition")
        notifier = ConditionNotifier(condition)

        # Directly set internal state (bypassing normal initialization)
        rule_engine._conditions["test_condition"] = (notifier, True)

        result = rule_engine.get_condition_state(condition)
        assert result is True

    def test_returns_false_for_false_condition(self, rule_engine):
        """Test that get_condition_state returns False for a condition that is False."""
        condition = SimpleCondition("test_condition")
        notifier = ConditionNotifier(condition)

        # Directly set internal state
        rule_engine._conditions["test_condition"] = (notifier, False)

        result = rule_engine.get_condition_state(condition)
        assert result is False

    def test_raises_keyerror_for_nonexistent_condition(self, rule_engine):
        """Test that get_condition_state raises KeyError for non-existent condition."""
        condition = SimpleCondition("nonexistent")

        with pytest.raises(KeyError):
            rule_engine.get_condition_state(condition)


class TestRemoveCondition:
    """Test _remove_condition method."""

    def test_removes_condition_from_tracking(self, rule_engine, mock_timer_service):
        """Test that _remove_condition removes condition from internal tracking."""
        condition = SimpleCondition("test_condition", device_id=123)
        notifier = ConditionNotifier(condition)

        # Set up internal state as if condition was added
        rule_engine._conditions["test_condition"] = (notifier, False)
        rule_engine._device_to_conditions[123] = {"test_condition"}

        # Remove the condition
        rule_engine._remove_condition(condition)

        # Verify cleanup
        assert "test_condition" not in rule_engine._conditions
        assert 123 not in rule_engine._device_to_conditions

        # Verify timer cancellation was attempted
        assert mock_timer_service.was_cancelled("condition_timeout(test_condition)")
        assert mock_timer_service.was_cancelled("condition_duration(test_condition)")

    def test_removes_device_mapping_but_preserves_other_conditions(self, rule_engine):
        """Test that removing condition only removes its device mapping."""
        condition1 = SimpleCondition("condition1", device_id=123)
        condition2 = SimpleCondition("condition2", device_id=123)
        notifier1 = ConditionNotifier(condition1)
        notifier2 = ConditionNotifier(condition2)

        # Set up two conditions on same device
        rule_engine._conditions["condition1"] = (notifier1, False)
        rule_engine._conditions["condition2"] = (notifier2, True)
        rule_engine._device_to_conditions[123] = {"condition1", "condition2"}

        # Remove first condition
        rule_engine._remove_condition(condition1)

        # Verify only condition1 removed, condition2 remains
        assert "condition1" not in rule_engine._conditions
        assert "condition2" in rule_engine._conditions
        assert rule_engine._device_to_conditions[123] == {"condition2"}

    def test_removes_empty_device_mapping(self, rule_engine):
        """Test that device mapping is removed when last condition is removed."""
        condition = SimpleCondition("test_condition", device_id=123)
        notifier = ConditionNotifier(condition)

        # Set up condition with device mapping
        rule_engine._conditions["test_condition"] = (notifier, False)
        rule_engine._device_to_conditions[123] = {"test_condition"}

        # Remove condition
        rule_engine._remove_condition(condition)

        # Verify device mapping completely removed
        assert 123 not in rule_engine._device_to_conditions

    def test_removes_condition_dependencies(self, rule_engine):
        """Test that condition dependencies are cleaned up."""
        condition = SimpleCondition("test_condition")
        notifier = ConditionNotifier(condition)

        # Set up condition with dependencies
        rule_engine._conditions["test_condition"] = (notifier, False)
        rule_engine._condition_deps["test_condition"] = {"parent1", "parent2"}

        # Remove condition
        rule_engine._remove_condition(condition)

        # Verify dependency cleanup
        assert "test_condition" not in rule_engine._condition_deps

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
        rule_engine._conditions["child1"] = (notifier_child1, False)
        rule_engine._conditions["child2"] = (notifier_child2, False)
        rule_engine._conditions["parent"] = (notifier_parent, False)
        rule_engine._device_to_conditions[123] = {"child1"}
        rule_engine._device_to_conditions[456] = {"child2"}

        # Remove parent
        rule_engine._remove_condition(parent)

        # Verify all conditions removed
        assert "parent" not in rule_engine._conditions
        assert "child1" not in rule_engine._conditions
        assert "child2" not in rule_engine._conditions
        assert_engine_state_clean(rule_engine)


class TestPropagateStateUpdate:
    """Test _propagate_state_update method."""

    def test_updates_single_condition_state(self, rule_engine):
        """Test that state update changes condition state."""
        condition = SimpleCondition("test_condition")
        condition.set_state(True)  # Set condition to evaluate to True
        notifier = ConditionNotifier(condition)

        # Set up condition with initial False state
        rule_engine._conditions["test_condition"] = (notifier, False)

        # Propagate state update
        touched = rule_engine._propagate_state_update([notifier])

        # Verify state was updated
        assert rule_engine._conditions["test_condition"][1] is True
        assert len(touched) == 1
        assert touched[0] == notifier

    def test_no_update_when_state_unchanged(self, rule_engine):
        """Test that no update occurs when condition state hasn't changed."""
        condition = SimpleCondition("test_condition")
        condition.set_state(False)  # Keep condition False
        notifier = ConditionNotifier(condition)

        # Set up condition with False state
        rule_engine._conditions["test_condition"] = (notifier, False)

        # Propagate state update
        touched = rule_engine._propagate_state_update([notifier])

        # Verify state unchanged but condition was still touched
        assert rule_engine._conditions["test_condition"][1] is False
        assert len(touched) == 1

    def test_propagates_to_dependent_conditions(self, rule_engine):
        """Test that state changes propagate to dependent conditions."""
        child = SimpleCondition("child")
        child.set_state(True)
        parent = SimpleCondition("parent")

        child_notifier = ConditionNotifier(child)
        parent_notifier = ConditionNotifier(parent)

        # Set up child and parent conditions
        rule_engine._conditions["child"] = (child_notifier, False)
        rule_engine._conditions["parent"] = (parent_notifier, False)
        rule_engine._condition_deps["child"] = {"parent"}

        # Mock parent's on_condition_event method
        parent.on_condition_event = MagicMock()

        # Propagate child state update
        touched = rule_engine._propagate_state_update([child_notifier])

        # Verify parent was notified of child state change
        parent.on_condition_event.assert_called_once_with(child, True)

        # Verify both conditions were touched
        touched_ids = {notifier.condition.identifier for notifier in touched}
        assert "child" in touched_ids
        assert "parent" in touched_ids

    def test_handles_missing_dependent_condition(self, rule_engine):
        """Test that missing dependent conditions don't cause errors."""
        condition = SimpleCondition("test_condition")
        condition.set_state(True)
        notifier = ConditionNotifier(condition)

        # Set up condition with dependency to non-existent condition
        rule_engine._conditions["test_condition"] = (notifier, False)
        rule_engine._condition_deps["test_condition"] = {"nonexistent"}

        # Should not raise an exception
        touched = rule_engine._propagate_state_update([notifier])

        # Should still process the original condition
        assert len(touched) == 1
        assert touched[0] == notifier

    def test_handles_multiple_initial_conditions(self, rule_engine):
        """Test that multiple conditions can be updated simultaneously."""
        condition1 = SimpleCondition("condition1")
        condition2 = SimpleCondition("condition2")
        condition1.set_state(True)
        condition2.set_state(True)

        notifier1 = ConditionNotifier(condition1)
        notifier2 = ConditionNotifier(condition2)

        # Set up both conditions
        rule_engine._conditions["condition1"] = (notifier1, False)
        rule_engine._conditions["condition2"] = (notifier2, False)

        # Propagate updates for both
        touched = rule_engine._propagate_state_update([notifier1, notifier2])

        # Verify both were updated
        assert rule_engine._conditions["condition1"][1] is True
        assert rule_engine._conditions["condition2"][1] is True
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
        rule_engine._conditions["test"] = (notifier, True)
        rule_engine._device_to_conditions[123] = {"test"}

        # Verify checker detects state
        assert checker.get_active_condition_count() == 1
        assert checker.get_device_mapping_count() == 1
        assert checker.verify_condition_exists("test")
        assert checker.verify_condition_state("test", True)
        assert checker.verify_device_mapping(123, "test")
