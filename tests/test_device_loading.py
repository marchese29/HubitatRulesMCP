"""Unit tests for device loading functionality."""

import pytest

from hubitat import HubitatClient
from rules.interface import Device


class TestDeviceLoading:
    """Test class for device loading functionality."""

    @pytest.mark.unit
    async def test_device_loading_before_load_fails(self, mock_hubitat_client):
        """Test that accessing attributes before loading raises RuntimeError."""
        device = Device(device_id=64, he_client=mock_hubitat_client)

        # Test accessing attribute before loading should fail
        with pytest.raises(
            RuntimeError, match="Device .* is not loaded. Call load\\(\\) first"
        ):
            _ = device.temperature

    @pytest.mark.unit
    async def test_device_loading_success(
        self, mock_hubitat_client, mock_hubitat_device
    ):
        """Test successful device loading and subsequent attribute access."""
        device = Device(device_id=64, he_client=mock_hubitat_client)

        # Load the device
        loaded_device = await device.load()
        assert loaded_device is device, "load() should return the same device instance"

        # Test accessing attributes after loading
        door_attr = device.door
        assert door_attr is not None, (
            "Should be able to access door attribute after loading"
        )

        contact_attr = device.contact
        assert contact_attr is not None, (
            "Should be able to access contact attribute after loading"
        )

        # Test accessing commands after loading
        open_command = device.open
        assert open_command is not None, (
            "Should be able to access open command after loading"
        )

        close_command = device.close
        assert close_command is not None, (
            "Should be able to access close command after loading"
        )

        # Verify device was fetched once during load
        mock_hubitat_client.device_by_id.assert_called_once_with(64)

    @pytest.mark.unit
    async def test_device_loading_multiple_loads(
        self, mock_hubitat_client, mock_hubitat_device
    ):
        """Test that multiple load calls work correctly."""
        device = Device(device_id=64, he_client=mock_hubitat_client)

        # Load the device multiple times
        result1 = await device.load()
        result2 = await device.load()
        result3 = await device.load()

        # Verify all loads return the same device instance
        assert result1 is device
        assert result2 is device
        assert result3 is device

        # Verify device_by_id was called for each load (current behavior)
        assert mock_hubitat_client.device_by_id.call_count == 3
        for call in mock_hubitat_client.device_by_id.call_args_list:
            assert call == ((64,),)
