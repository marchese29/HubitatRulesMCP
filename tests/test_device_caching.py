"""Unit tests for device caching functionality."""

import pytest

from rules.interface import Device


class TestDeviceCaching:
    """Test class for device caching functionality."""

    @pytest.mark.unit
    async def test_device_caching(self, mock_hubitat_client, mock_hubitat_device):
        """Test that device is fetched only once and cached properly."""
        # Create a Device instance
        device = Device(device_id=123, he_client=mock_hubitat_client)

        # Load the device first
        await device.load()

        # Access different attributes - this should use the cached device
        temp_attr = device.temperature
        assert temp_attr is not None

        # Access a command - this should use the cached device
        on_cmd = device.on
        assert on_cmd is not None

        # Access another attribute - this should also use the cached device
        switch_attr = device.switch
        assert switch_attr is not None

        # Verify that device_by_id was called only once (during load)
        mock_hubitat_client.device_by_id.assert_called_once_with(123)

    @pytest.mark.unit
    async def test_device_cache_with_invalid_attribute(self, mock_hubitat_client):
        """Test that accessing non-existent attributes raises AttributeError and still uses cache."""
        # Create a Device instance
        device = Device(device_id=123, he_client=mock_hubitat_client)

        # Load the device first
        await device.load()

        # Test accessing non-existent attribute
        with pytest.raises(
            AttributeError, match="Attribute or command 'nonexistent' not found"
        ):
            _ = device.nonexistent

        # Access a valid attribute - should use the same cached device
        switch_attr = device.switch
        assert switch_attr is not None

        # Verify device_by_id was called only once (during load)
        mock_hubitat_client.device_by_id.assert_called_once_with(123)

    @pytest.mark.unit
    async def test_multiple_device_instances_separate_caches(self, mock_hubitat_client):
        """Test that different device instances maintain separate caches."""
        # Create two different device instances
        device1 = Device(device_id=123, he_client=mock_hubitat_client)
        device2 = Device(device_id=456, he_client=mock_hubitat_client)

        # Load both devices
        await device1.load()
        await device2.load()

        # Access attributes on both devices
        _ = device1.temperature
        _ = device2.humidity

        # Verify each device was fetched separately (once during each load)
        expected_calls = [((123,),), ((456,),)]
        actual_calls = mock_hubitat_client.device_by_id.call_args_list
        assert len(actual_calls) == 2
        assert actual_calls[0] == expected_calls[0]
        assert actual_calls[1] == expected_calls[1]
