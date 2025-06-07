from typing import Self

from hubitat import HubitatClient
from rules.condition import (
    DynamicDeviceAttributeCondition,
    StaticDeviceAttributeCondition,
)
from rules.engine import EngineCondition


class Attribute:
    """An attribute of a device."""

    def __init__(self, device_id: int, attr_name: str):
        self._device_id = device_id
        self._attr_name = attr_name

    def _compare(self, other: any, op: str) -> EngineCondition:
        """Helper method to handle all comparison operations.

        Args:
            other: Value to compare against
            op: Comparison operator to use
        Returns:
            Appropriate condition object for the comparison
        """
        if isinstance(other, Attribute):
            return DynamicDeviceAttributeCondition(
                (self._device_id, self._attr_name),
                op,
                (other._device_id, other._attr_name),
            )
        else:
            return StaticDeviceAttributeCondition(
                self._device_id, self._attr_name, op, other
            )

    def __gt__(self, other: any) -> EngineCondition:
        return self._compare(other, ">")

    def __ge__(self, other: any) -> EngineCondition:
        return self._compare(other, ">=")

    def __lt__(self, other: any) -> EngineCondition:
        return self._compare(other, "<")

    def __le__(self, other: any) -> EngineCondition:
        return self._compare(other, "<=")

    def __eq__(self, other: any) -> EngineCondition:
        return self._compare(other, "=")

    def __ne__(self, other: any) -> EngineCondition:
        return self._compare(other, "!=")


class Command:
    """A command to be sent to a device."""

    def __init__(self, he_client: HubitatClient, device_id: int, command: str):
        self._he_client = he_client
        self._device_id = device_id
        self._command = command

    async def __call__(self, *args: any, **_: any) -> None:
        await self._he_client.send_command(self._device_id, self._command, *args)


class Device:
    """A hubitat device."""

    def __init__(self, device_id: int, he_client: HubitatClient):
        self._device_id = device_id
        self._he_client = he_client
        self._he_device = None  # Cache for the fetched device
        self._loaded = False  # Track if device data has been loaded

    async def load(self) -> Self:
        """Load device data from the Hubitat API.

        Returns:
            Self for method chaining
        """
        self._he_device = await self._he_client.device_by_id(self._device_id)
        self._loaded = True
        return self

    def _check_loaded(self):
        """Check if device is loaded, raise error if not."""
        if not self._loaded:
            raise RuntimeError(
                f"Device {self._device_id} is not loaded. Call load() first."
            )

    def __getattr__(self, attr_name: str) -> Attribute | Command:
        self._check_loaded()

        if self._he_device.has_attribute(attr_name):
            return Attribute(self._device_id, attr_name)
        elif self._he_device.has_command(attr_name):
            return Command(self._he_client, self._device_id, attr_name)
        else:
            raise AttributeError(
                f"Attribute or command '{attr_name}' not found on device {self._device_id}"
            )
