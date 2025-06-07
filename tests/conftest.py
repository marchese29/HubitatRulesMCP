"""Pytest configuration and shared fixtures."""

import pytest
from unittest.mock import AsyncMock, MagicMock

from hubitat import HubitatClient, HubitatDevice


@pytest.fixture
def mock_hubitat_device():
    """Create a mock HubitatDevice for testing."""
    device = HubitatDevice(
        id=123,
        name="Test Device",
        attributes={"temperature", "humidity", "switch", "door", "contact"},
        commands={"on", "off", "refresh", "open", "close"},
    )
    return device


@pytest.fixture
def mock_hubitat_client(mock_hubitat_device):
    """Create a mock HubitatClient for testing."""
    mock_client = MagicMock(spec=HubitatClient)
    mock_client.device_by_id = AsyncMock(return_value=mock_hubitat_device)
    return mock_client


@pytest.fixture
def device_64_mock():
    """Create a mock for device ID 64 used in integration tests."""
    return HubitatDevice(
        id=64,
        name="Test Door Sensor",
        attributes={"door", "contact", "temperature", "battery"},
        commands={"open", "close", "refresh"},
    )
