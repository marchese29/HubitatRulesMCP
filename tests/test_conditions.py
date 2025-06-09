"""Test condition classes for RuleEngine testing."""

from datetime import timedelta
from typing import List, Dict, Any

from rules.engine import EngineCondition
from models.api import HubitatDeviceEvent


class SimpleCondition(EngineCondition):
    """Simple condition for testing basic functionality."""

    def __init__(
        self,
        identifier: str,
        device_id: int | None = None,
        attribute: str = "switch",
        expected_value: Any = "on",
        initial_state: bool = False,
    ):
        self._identifier = identifier
        self._device_id = device_id
        self._attribute = attribute
        self._expected_value = expected_value
        self._current_state = initial_state
        self._initial_state = initial_state

    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def device_ids(self) -> List[int]:
        return [self._device_id] if self._device_id is not None else []

    def initialize(
        self, attrs: Dict[int, Dict[str, Any]], conds: Dict[str, bool]
    ) -> bool:
        """Initialize condition based on current device attributes."""
        if self._device_id is not None and self._device_id in attrs:
            device_attrs = attrs[self._device_id]
            if self._attribute in device_attrs:
                self._current_state = (
                    device_attrs[self._attribute] == self._expected_value
                )
            else:
                self._current_state = self._initial_state
        else:
            self._current_state = self._initial_state
        return self._current_state

    def evaluate(self) -> bool:
        """Return current state."""
        return self._current_state

    def on_device_event(self, event: HubitatDeviceEvent):
        """Update state based on device event."""
        if (
            self._device_id is not None
            and int(event.device_id) == self._device_id
            and event.attribute == self._attribute
        ):
            self._current_state = event.value == self._expected_value

    def set_state(self, state: bool):
        """Manually set state for testing."""
        self._current_state = state


class TimeoutCondition(SimpleCondition):
    """Condition with timeout for testing timeout behavior."""

    def __init__(
        self,
        identifier: str,
        timeout_duration: timedelta,
        device_id: int | None = None,
        **kwargs,
    ):
        super().__init__(identifier, device_id, **kwargs)
        self._timeout_duration = timeout_duration

    @property
    def timeout(self) -> timedelta:
        return self._timeout_duration


class DurationCondition(SimpleCondition):
    """Condition with duration for testing duration behavior."""

    def __init__(
        self,
        identifier: str,
        duration_time: timedelta,
        device_id: int | None = None,
        **kwargs,
    ):
        super().__init__(identifier, device_id, **kwargs)
        self._duration_time = duration_time

    @property
    def duration(self) -> timedelta:
        return self._duration_time


class TimeoutDurationCondition(SimpleCondition):
    """Condition with both timeout and duration."""

    def __init__(
        self,
        identifier: str,
        timeout_duration: timedelta,
        duration_time: timedelta,
        device_id: int | None = None,
        **kwargs,
    ):
        super().__init__(identifier, device_id, **kwargs)
        self._timeout_duration = timeout_duration
        self._duration_time = duration_time

    @property
    def timeout(self) -> timedelta:
        return self._timeout_duration

    @property
    def duration(self) -> timedelta:
        return self._duration_time


class ParentCondition(EngineCondition):
    """Condition that depends on subconditions for testing dependencies."""

    def __init__(
        self,
        identifier: str,
        child_conditions: List[EngineCondition],
        require_all: bool = True,
    ):
        self._identifier = identifier
        self._child_conditions = child_conditions
        self._require_all = require_all
        self._child_states: Dict[str, bool] = {}

    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def subconditions(self) -> List[EngineCondition]:
        return self._child_conditions

    def initialize(
        self, attrs: Dict[int, Dict[str, Any]], conds: Dict[str, bool]
    ) -> bool:
        """Initialize based on child condition states."""
        self._child_states = {cid: state for cid, state in conds.items()}
        return self.evaluate()

    def evaluate(self) -> bool:
        """Evaluate based on child condition states."""
        if not self._child_conditions:
            return False

        child_states = [
            self._child_states.get(child.identifier, False)
            for child in self._child_conditions
        ]

        if self._require_all:
            return all(child_states)
        else:
            return any(child_states)

    def on_condition_event(self, condition: EngineCondition, triggered: bool):
        """Update child state when subcondition changes."""
        self._child_states[condition.identifier] = triggered


class AlwaysTrueCondition(EngineCondition):
    """Condition that is always true for testing immediate triggers."""

    def __init__(self, identifier: str):
        self._identifier = identifier

    @property
    def identifier(self) -> str:
        return self._identifier

    def initialize(
        self, attrs: Dict[int, Dict[str, Any]], conds: Dict[str, bool]
    ) -> bool:
        return True

    def evaluate(self) -> bool:
        return True


class AlwaysFalseCondition(EngineCondition):
    """Condition that is always false for testing timeout scenarios."""

    def __init__(self, identifier: str):
        self._identifier = identifier

    @property
    def identifier(self) -> str:
        return self._identifier

    def initialize(
        self, attrs: Dict[int, Dict[str, Any]], conds: Dict[str, bool]
    ) -> bool:
        return False

    def evaluate(self) -> bool:
        return False


class ExceptionCondition(EngineCondition):
    """Condition that raises exceptions for testing error handling."""

    def __init__(self, identifier: str, exception_on_evaluate: bool = True):
        self._identifier = identifier
        self._exception_on_evaluate = exception_on_evaluate

    @property
    def identifier(self) -> str:
        return self._identifier

    def initialize(
        self, attrs: Dict[int, Dict[str, Any]], conds: Dict[str, bool]
    ) -> bool:
        if not self._exception_on_evaluate:
            raise RuntimeError("Exception during initialization")
        return False

    def evaluate(self) -> bool:
        if self._exception_on_evaluate:
            raise RuntimeError("Exception during evaluation")
        return False


class ConditionWithSubconditions(EngineCondition):
    """Condition that has subconditions for testing recursive removal."""

    def __init__(self, identifier: str, subconditions: List[EngineCondition] = None):
        self._identifier = identifier
        self._subconditions = subconditions or []

    @property
    def identifier(self) -> str:
        return self._identifier

    @property
    def subconditions(self) -> List[EngineCondition]:
        return self._subconditions

    def initialize(
        self, attrs: Dict[int, Dict[str, Any]], conds: Dict[str, bool]
    ) -> bool:
        return False

    def evaluate(self) -> bool:
        return False
