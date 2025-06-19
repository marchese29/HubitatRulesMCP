"""
Test that the bulk device optimization is working correctly.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from hubitat import HubitatClient


class TestBulkOptimization:
    """Test bulk device optimization functionality."""

    @pytest.fixture
    def mock_hubitat_client(self):
        """Create a mock HubitatClient with bulk optimization methods."""
        client = MagicMock(spec=HubitatClient)
        return client

    async def test_get_all_devices_returns_device_objects_with_attributes(
        self, mock_hubitat_client
    ):
        """Test that get_all_devices returns HubitatDevice objects with current attributes."""
        from hubitat import HubitatDevice

        # Mock the API response
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "id": "123",
                "name": "Living Room Switch",
                "attributes": [
                    {"name": "switch", "currentValue": "on"},
                    {"name": "level", "currentValue": 75},
                ],
                "commands": ["on", "off", "setLevel"],
            },
            {
                "id": "456",
                "name": "Motion Sensor",
                "attributes": [
                    {"name": "motion", "currentValue": "active"},
                    {"name": "battery", "currentValue": 85},
                ],
                "commands": [],
            },
        ]

        # Create real client for testing actual implementation
        client = HubitatClient()
        client._make_request = AsyncMock(return_value=mock_response)

        # Test get_all_devices
        devices = await client.get_all_devices()

        # Verify we got HubitatDevice objects
        assert len(devices) == 2
        assert all(isinstance(device, HubitatDevice) for device in devices)

        # Check first device
        device1 = devices[0]
        assert device1.id == 123
        assert device1.name == "Living Room Switch"
        assert "switch" in device1.attributes
        assert "level" in device1.attributes
        assert device1.current_attributes["switch"] == "on"
        assert device1.current_attributes["level"] == 75
        assert device1.get_attribute_value("switch") == "on"

        # Check second device
        device2 = devices[1]
        assert device2.id == 456
        assert device2.name == "Motion Sensor"
        assert "motion" in device2.attributes
        assert device2.current_attributes["motion"] == "active"
        assert device2.current_attributes["battery"] == 85

    async def test_get_bulk_attributes_efficiency(self, mock_hubitat_client):
        """Test that get_bulk_attributes uses bulk endpoint for efficiency."""
        # Mock the bulk API response
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "id": "123",
                "name": "Switch 1",
                "attributes": [
                    {"name": "switch", "currentValue": "on"},
                    {"name": "level", "currentValue": 50},
                ],
                "commands": ["on", "off"],
            },
            {
                "id": "456",
                "name": "Switch 2",
                "attributes": [
                    {"name": "switch", "currentValue": "off"},
                    {"name": "level", "currentValue": 0},
                ],
                "commands": ["on", "off"],
            },
        ]

        # Create real client for testing
        client = HubitatClient()
        client._make_request = AsyncMock(return_value=mock_response)

        # Test bulk attributes
        device_ids = [123, 456]
        result = await client.get_bulk_attributes(device_ids)

        # Verify we only made one API call (to /devices/all)
        assert client._make_request.call_count == 1
        call_url = client._make_request.call_args[0][0]
        assert "devices/all" in call_url

        # Verify results are correct
        assert len(result) == 2
        assert result[123]["switch"] == "on"
        assert result[123]["level"] == 50
        assert result[456]["switch"] == "off"
        assert result[456]["level"] == 0

    async def test_bulk_attributes_fallback_for_missing_devices(
        self, mock_hubitat_client
    ):
        """Test that get_bulk_attributes falls back to individual calls for missing devices."""
        # Mock bulk response missing one device
        mock_bulk_response = MagicMock()
        mock_bulk_response.json.return_value = [
            {
                "id": "123",
                "name": "Switch 1",
                "attributes": [{"name": "switch", "currentValue": "on"}],
                "commands": [],
            }
        ]

        # Mock individual device response
        mock_individual_response = MagicMock()
        mock_individual_response.json.return_value = {
            "id": "456",
            "name": "Switch 2",
            "attributes": [{"name": "switch", "currentValue": "off"}],
        }

        # Create real client
        client = HubitatClient()
        client._make_request = AsyncMock(
            side_effect=[mock_bulk_response, mock_individual_response]
        )

        # Test with device that's not in bulk response
        device_ids = [123, 456]  # 456 missing from bulk
        result = await client.get_bulk_attributes(device_ids)

        # Should have made 2 calls: bulk + individual fallback
        assert client._make_request.call_count == 2

        # Verify both devices returned
        assert len(result) == 2
        assert result[123]["switch"] == "on"
        assert result[456]["switch"] == "off"
