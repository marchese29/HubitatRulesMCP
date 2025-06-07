"""Test script to verify device caching functionality."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

from hubitat import HubitatClient, HubitatDevice
from rules.interface import Device


async def test_device_caching():
    """Test that device is fetched only once and cached properly."""

    # Create a mock HubitatClient
    mock_client = MagicMock(spec=HubitatClient)

    # Create a mock device that will be returned by the client
    mock_hubitat_device = HubitatDevice(
        id=123,
        name="Test Device",
        attributes={"temperature", "humidity", "switch"},
        commands={"on", "off", "refresh"},
    )

    # Set up the mock to return our device
    mock_client.device_by_id = AsyncMock(return_value=mock_hubitat_device)

    # Create a Device instance
    device = Device(device_id=123, he_client=mock_client)

    # Access different attributes - this should trigger device fetching
    temp_attr = device.temperature
    print(f"Got temperature attribute: {temp_attr}")

    # Access a command - this should use the cached device
    on_cmd = device.on
    print(f"Got on command: {on_cmd}")

    # Access another attribute - this should also use the cached device
    switch_attr = device.switch
    print(f"Got switch attribute: {switch_attr}")

    # Verify that device_by_id was called only once
    mock_client.device_by_id.assert_called_once_with(123)
    print("✓ Device was fetched exactly once and cached properly!")

    # Test accessing non-existent attribute
    try:
        invalid_attr = device.nonexistent
        print("ERROR: Should have raised AttributeError")
    except AttributeError as e:
        print(f"✓ Correctly raised AttributeError: {e}")

    # Verify device_by_id was still called only once even after the error
    mock_client.device_by_id.assert_called_once_with(123)
    print("✓ Device cache was used even when accessing invalid attributes!")


if __name__ == "__main__":
    asyncio.run(test_device_caching())
