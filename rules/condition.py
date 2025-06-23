from datetime import timedelta
from typing import Any, override

from models.api import HubitatDeviceEvent
from rules.engine import EngineCondition


class AbstractCondition(EngineCondition):
    def __init__(self):
        super().__init__()

    def __bool__(self) -> bool:
        raise NotImplementedError("Use utils.check(<condition>) to evaluate conditions")

    @property
    @override
    def timeout(self) -> timedelta | None:
        return getattr(self, "_timeout", None)

    @timeout.setter
    def timeout(self, value: timedelta):
        self._timeout = value

    @property
    @override
    def duration(self) -> timedelta | None:
        return getattr(self, "_duration", None)

    @duration.setter
    def duration(self, value: timedelta):
        self._duration = value


class AttributeChangeCondition(AbstractCondition):
    def __init__(self, device_id: int, attr_name: str):
        super().__init__()
        self._device_id = device_id
        self._attr_name = attr_name
        self._prev_value = None
        self._curr_value = None

    @property
    @override
    def identifier(self) -> str:
        return f"attribute_change(he_dev({self._device_id}:{self._attr_name}))"

    @property
    @override
    def device_ids(self) -> list[int]:
        return [self._device_id]

    @override
    def on_device_event(self, event: HubitatDeviceEvent):
        if event.device_id == self._device_id and event.attribute == self._attr_name:
            self._prev_value = self._curr_value
            self._curr_value = event.value

    @override
    def initialize(
        self, attrs: dict[int, dict[str, Any]], conds: dict[str, bool]
    ) -> bool:
        self._prev_value = attrs[self._device_id][self._attr_name]
        self._curr_value = self._prev_value
        return False

    @override
    def evaluate(self) -> bool:
        return bool(self._prev_value != self._curr_value)


class BooleanCondition(AbstractCondition):
    def __init__(self, *conditions: AbstractCondition, operator: str):
        super().__init__()
        self._conditions: dict[str, tuple[AbstractCondition, bool]] = {}
        for condition in conditions:
            self._conditions[condition.identifier] = (condition, False)
        if operator == "not" and len(self._conditions) != 1:
            raise ValueError("Boolean operator 'not' requires exactly one subcondition")
        self._operator = operator

    @property
    @override
    def identifier(self) -> str:
        inner = f" {self._operator} ".join(self._conditions.keys())
        return f"({inner})"

    @property
    @override
    def subconditions(self) -> list[EngineCondition]:
        return [c for (c, _) in self._conditions.values()]

    @override
    def initialize(
        self, attrs: dict[int, dict[str, Any]], conds: dict[str, bool]
    ) -> bool:
        for condition_id, state in conds.items():
            self._conditions[condition_id] = (
                self._conditions[condition_id][0],
                state,
            )
        return self.evaluate()

    @override
    def evaluate(self) -> bool:
        match self._operator:
            case "and":
                return all(state for (_, state) in self._conditions.values())
            case "or":
                return any(state for (_, state) in self._conditions.values())
            case "not":
                return not [state for (_, state) in self._conditions.values()][0]
            case _:
                raise ValueError(f"Unknown operator: {self._operator}")


class DynamicDeviceAttributeCondition(AbstractCondition):
    """A condition for the comparison of a device attribute against another one"""

    def __init__(self, first: tuple[int, str], operator: str, second: tuple[int, str]):
        super().__init__()
        self._left_device_id, self._left_attr_name = first
        self._right_device_id, self._right_attr_name = second
        self._operator = operator
        self._left_value: Any | None = None
        self._right_value: Any | None = None

    @override
    @property
    def identifier(self) -> str:
        return (
            f"device_condition(he_dev({self._left_device_id}:{self._left_attr_name}) "
            f"{self._operator} he_dev({self._right_device_id}:{self._right_attr_name}))"
        )

    @override
    @property
    def device_ids(self) -> list[int]:
        return [self._left_device_id, self._right_device_id]

    @override
    def on_device_event(self, event: HubitatDeviceEvent):
        if (
            int(event.device_id) == self._left_device_id
            and event.attribute == self._left_attr_name
        ):
            self._left_value = event.value
        elif (
            int(event.device_id) == self._right_device_id
            and event.attribute == self._right_attr_name
        ):
            self._right_value = event.value

    @override
    def initialize(
        self, attrs: dict[int, dict[str, Any]], conds: dict[str, bool]
    ) -> bool:
        self._left_value = attrs[self._left_device_id][self._left_attr_name]
        self._right_value = attrs[self._right_device_id][self._right_attr_name]
        return self.evaluate()

    @override
    def evaluate(self) -> bool:
        match self._operator:
            case "=":
                return bool(self._left_value == self._right_value)
            case "!=":
                return bool(self._left_value != self._right_value)
            case ">":
                # Handle None values - ordering comparisons with None are undefined
                if self._left_value is not None and self._right_value is not None:
                    return bool(self._left_value > self._right_value)
                return False
            case ">=":
                # Handle None values - ordering comparisons with None are undefined
                if self._left_value is not None and self._right_value is not None:
                    return bool(self._left_value >= self._right_value)
                return False
            case "<":
                # Handle None values - ordering comparisons with None are undefined
                if self._left_value is not None and self._right_value is not None:
                    return bool(self._left_value < self._right_value)
                return False
            case "<=":
                # Handle None values - ordering comparisons with None are undefined
                if self._left_value is not None and self._right_value is not None:
                    return bool(self._left_value <= self._right_value)
                return False
            case _:
                raise ValueError(f"Unknown operator: {self._operator}")


class StaticDeviceAttributeCondition(AbstractCondition):
    """A condition for the comparison of a device attribute against a static value"""

    def __init__(self, device_id: int, attr_name: str, operator: str, value: Any):
        super().__init__()
        self._device_id = device_id
        self._attr_name = attr_name
        self._device_value = None
        self._value_type = type(value)
        self._operator = operator
        self._value = value

    @override
    @property
    def identifier(self) -> str:
        return (
            f"device_condition(he_dev({self._device_id}:{self._attr_name}) "
            f"{self._operator} {self._value})"
        )

    def _cast_value(self, value: Any) -> Any:
        """Cast the incoming value to match the model value type.

        Args:
            value: The value to cast

        Returns:
            The value cast to the appropriate type
        """
        if value is None:
            return None

        try:
            if isinstance(self._value_type, type(bool)):
                if isinstance(value, str):
                    return value.lower() in ("true", "1", "yes", "on", "active", "open")
                return bool(value)
            elif isinstance(self._value_type, type(int)):
                return int(value)
            elif isinstance(self._value_type, type(float)):
                return float(value)
            elif isinstance(self._value_type, type(str)):
                return str(value)
            return value
        except (ValueError, TypeError):
            return value

    @override
    @property
    def device_ids(self) -> list[int]:
        return [self._device_id]

    @override
    def on_device_event(self, event: HubitatDeviceEvent):
        # We already know the deviceId matches
        if event.attribute == self._attr_name:
            self._device_value = self._cast_value(event.value)

    @override
    def initialize(
        self, attrs: dict[int, dict[str, Any]], conds: dict[str, bool]
    ) -> bool:
        self._device_value = self._cast_value(attrs[self._device_id][self._attr_name])
        return self.evaluate()

    @override
    def evaluate(self) -> bool:
        match self._operator:
            case "=":
                return bool(self._device_value == self._value)
            case "!=":
                return bool(self._device_value != self._value)
            case ">":
                return bool(self._device_value > self._value)
            case ">=":
                return bool(self._device_value >= self._value)
            case "<":
                return bool(self._device_value < self._value)
            case "<=":
                return bool(self._device_value <= self._value)
            case _:
                raise ValueError(f"Unknown operator: {self._operator}")


class AlwaysFalseCondition(AbstractCondition):
    """A condition that is always false. Used for error cases."""

    def __init__(self, reason: str = "always_false"):
        super().__init__()
        self._reason = reason

    @property
    @override
    def identifier(self) -> str:
        return f"always_false({self._reason})"

    @property
    @override
    def device_ids(self) -> list[int]:
        return []  # No devices to monitor

    @override
    def on_device_event(self, event: HubitatDeviceEvent):
        pass  # Never changes state

    @override
    def initialize(
        self, attrs: dict[int, dict[str, Any]], conds: dict[str, bool]
    ) -> bool:
        return False  # Always false

    @override
    def evaluate(self) -> bool:
        return False  # Always false


class SceneChangeCondition(AbstractCondition):
    """A condition that triggers when a scene state changes (set ↔ not set)."""

    def __init__(self, scene_name: str, scene_condition: AbstractCondition):
        super().__init__()
        self._scene_name = scene_name
        self._scene_condition = scene_condition
        self._prev_state = False
        self._curr_state = False

    @property
    @override
    def identifier(self) -> str:
        return f"scene_change({self._scene_name})"

    @property
    @override
    def device_ids(self) -> list[int]:
        # Delegate to the wrapped scene condition
        return self._scene_condition.device_ids

    @property
    @override
    def subconditions(self) -> list[EngineCondition]:
        return [self._scene_condition]

    @override
    def on_device_event(self, event: HubitatDeviceEvent):
        # Let the wrapped condition handle the event
        self._scene_condition.on_device_event(event)

    @override
    def initialize(
        self, attrs: dict[int, dict[str, Any]], conds: dict[str, bool]
    ) -> bool:
        # Initialize the wrapped condition and get its initial state
        scene_state = self._scene_condition.initialize(attrs, conds)
        self._prev_state = scene_state
        self._curr_state = scene_state
        return False  # Never start as true for change detection

    @override
    def evaluate(self) -> bool:
        # Evaluate the wrapped scene condition
        new_state = self._scene_condition.evaluate()

        # Check for state change
        result = self._curr_state != new_state

        # Update state
        self._prev_state = self._curr_state
        self._curr_state = new_state

        return result
