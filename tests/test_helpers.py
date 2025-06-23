"""Helper functions and factories for RuleEngine testing."""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from hubitat import HubitatClient
from models.api import HubitatDeviceEvent
from rules.engine import ConditionState, RuleEngine
from tests.mock_timer_service import MockTimerService


def create_device_event(
    device_id: int | str, attribute: str, value: Any
) -> HubitatDeviceEvent:
    """Create a HubitatDeviceEvent for testing.

    Args:
        device_id: Device ID (will be converted to string)
        attribute: Attribute name (e.g., "switch", "contact", "temperature")
        value: Attribute value (e.g., "on", "off", "open", "closed", 75)

    Returns:
        HubitatDeviceEvent instance
    """
    return HubitatDeviceEvent(deviceId=str(device_id), name=attribute, value=value)


def create_mock_hubitat_client(
    device_attributes: dict[int, dict[str, Any]] | None = None,
) -> HubitatClient:
    """Create a mock HubitatClient for testing.

    Args:
        device_attributes: Dict mapping device_id -> {attribute: value}
                          If None, returns empty dict for all devices

    Returns:
        Mock HubitatClient with get_all_attributes configured
    """
    mock_client = MagicMock(spec=HubitatClient)

    if device_attributes is None:
        device_attributes = {}

    async def mock_get_all_attributes(device_id: int) -> dict[str, Any]:
        return device_attributes.get(device_id, {})

    mock_client.get_all_attributes = AsyncMock(side_effect=mock_get_all_attributes)
    return mock_client


def create_mock_timer_service() -> MockTimerService:
    """Create a fresh MockTimerService for testing.

    Returns:
        MockTimerService instance
    """
    return MockTimerService()


class AsyncEventTracker:
    """Helper for tracking async events in tests."""

    def __init__(self):
        self.events: list[dict[str, Any]] = []
        self.event_occurred = asyncio.Event()

    def record_event(self, event_name: str, **kwargs):
        """Record an event with optional data."""
        self.events.append({"event": event_name, "data": kwargs})
        self.event_occurred.set()

    async def wait_for_event(self, timeout: float = 1.0) -> bool:
        """Wait for any event to occur.

        Args:
            timeout: Max time to wait in seconds

        Returns:
            True if event occurred, False if timeout
        """
        try:
            await asyncio.wait_for(self.event_occurred.wait(), timeout=timeout)
            return True
        except TimeoutError:
            return False

    def get_events(self) -> list[dict[str, Any]]:
        """Get all recorded events."""
        return self.events.copy()

    def clear(self):
        """Clear all recorded events and reset."""
        self.events.clear()
        self.event_occurred.clear()


class ConditionStateChecker:
    """Helper for verifying condition states in RuleEngine."""

    def __init__(self, engine: RuleEngine) -> None:
        self.engine = engine

    def verify_condition_exists(self, condition_instance_id: int) -> bool:
        """Check if condition is tracked by engine."""
        return condition_instance_id in self.engine._conditions

    def verify_condition_state(
        self, condition_instance_id: int, expected_state: bool
    ) -> bool:
        """Check if condition has expected state."""
        if condition_instance_id not in self.engine._conditions:
            return False
        # Convert boolean to ConditionState for comparison
        expected_enum_state = (
            ConditionState.TRUE if expected_state else ConditionState.FALSE
        )
        return self.engine._conditions[condition_instance_id][1] == expected_enum_state

    def verify_device_mapping(self, device_id: int, condition_instance_id: int) -> bool:
        """Check if device is mapped to condition."""
        if device_id not in self.engine._device_to_conditions:
            return False
        return condition_instance_id in self.engine._device_to_conditions[device_id]

    def verify_condition_dependency(
        self, parent_instance_id: int, child_instance_id: int
    ) -> bool:
        """Check if condition dependency exists."""
        if child_instance_id not in self.engine._condition_deps:
            return False
        dep_set = self.engine._condition_deps[child_instance_id]
        return bool(parent_instance_id in dep_set)

    def get_active_condition_count(self) -> int:
        """Get number of active conditions."""
        return len(self.engine._conditions)

    def get_device_mapping_count(self) -> int:
        """Get number of device mappings."""
        return len(self.engine._device_to_conditions)


def assert_engine_state_clean(engine):
    """Assert that engine has no active conditions or mappings."""
    assert len(engine._conditions) == 0, (
        f"Expected no conditions, found {len(engine._conditions)}"
    )
    assert len(engine._device_to_conditions) == 0, (
        f"Expected no device mappings, found {len(engine._device_to_conditions)}"
    )
    assert len(engine._condition_deps) == 0, (
        f"Expected no condition dependencies, found {len(engine._condition_deps)}"
    )


def assert_timer_state_clean(mock_timer: MockTimerService):
    """Assert that mock timer has no active timers."""
    assert mock_timer.get_active_timer_count() == 0, (
        f"Expected no active timers, found {mock_timer.get_active_timer_count()}"
    )
