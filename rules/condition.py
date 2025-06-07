from typing import override

from models.api import HubitatDeviceEvent
from rules.engine import EngineCondition


class BooleanCondition(EngineCondition):
    def __init__(self, *conditions: EngineCondition, operator: str):
        self._conditions: dict[str, tuple[EngineCondition, bool]] = {}
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
        self, attrs: dict[int, dict[str, any]], conds: dict[str, bool]
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
                return all([state for (_, state) in self._conditions.values()])
            case "or":
                return any([state for (_, state) in self._conditions.values()])
            case "not":
                return not [state for (_, state) in self._conditions.values()][0]
            case _:
                raise ValueError(f"Unknown operator: {self._operator}")


class DynamicDeviceAttributeCondition(EngineCondition):
    """A condition for the comparison of a device attribute against another one"""

    def __init__(self, first: tuple[int, str], operator: str, second: tuple[int, str]):
        self._left_device_id, self._left_attr_name = first
        self._right_device_id, self._right_attr_name = second
        self._operator = operator
        self._left_value = None
        self._right_value = None

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
        self, attrs: dict[int, dict[str, any]], conds: dict[str, bool]
    ) -> bool:
        self._left_value = attrs[self._left_device_id][self._left_attr_name]
        self._right_value = attrs[self._right_device_id][self._right_attr_name]
        return self.evaluate()

    @override
    def evaluate(self) -> bool:
        match self._operator:
            case "=":
                return self._left_value == self._right_value
            case "!=":
                return self._left_value != self._right_value
            case ">":
                return self._left_value > self._right_value
            case ">=":
                return self._left_value >= self._right_value
            case "<":
                return self._left_value < self._right_value
            case "<=":
                return self._left_value <= self._right_value
            case _:
                raise ValueError(f"Unknown operator: {self._operator}")


class StaticDeviceAttributeCondition(EngineCondition):
    """A condition for the comparison of a device attribute against a static value"""

    def __init__(self, device_id: int, attr_name: str, operator: str, value: any):
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

    def _cast_value(self, value: any) -> any:
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
        self, attrs: dict[int, dict[str, any]], conds: dict[str, bool]
    ) -> bool:
        self._device_value = self._cast_value(attrs[self._device_id][self._attr_name])
        return self.evaluate()

    @override
    def evaluate(self) -> bool:
        match self._operator:
            case "=":
                return self._device_value == self._value
            case "!=":
                return self._device_value != self._value
            case ">":
                return self._device_value > self._value
            case ">=":
                return self._device_value >= self._value
            case "<":
                return self._device_value < self._value
            case "<=":
                return self._device_value <= self._value
            case _:
                raise ValueError(f"Unknown operator: {self._operator}")
