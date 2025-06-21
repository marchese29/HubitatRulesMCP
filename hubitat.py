from typing import Any

import httpx
from pydantic import BaseModel

from audit.decorators import audit_scope
from models.audit import EventSubtype, EventType
from util import env_var


class HubitatDevice(BaseModel):
    id: int
    name: str
    attributes: set[str]
    commands: set[str]
    current_attributes: dict[str, Any] = {}

    def has_attribute(self, attr: str) -> bool:
        return attr in self.attributes

    def has_command(self, command: str) -> bool:
        return command in self.commands

    def get_attribute_value(self, attr: str) -> Any:
        """Get the current value of an attribute."""
        return self.current_attributes.get(attr)


class HubitatClient:
    """Wrapper around Hubitat functionalities."""

    def __init__(self):
        """Initialize the Hubitat client with connection details."""
        self._address = (
            f"http://{env_var('HE_ADDRESS')}/apps/api/{env_var('HE_APP_ID')}"
        )
        self._token = env_var("HE_ACCESS_TOKEN")

    async def _make_request(self, url: str) -> httpx.Response:
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, params={"access_token": self._token})
            except httpx.HTTPStatusError as error:
                raise Exception(
                    f"HE Client returned '{error.response.status_code}' "
                    f"status: {error.response.text}"
                ) from error
            except Exception as error:
                print(f"HE Client returned error: {error}")
                raise

        if resp.status_code != 200:
            raise Exception(
                f"HE Client returned '{resp.status_code}' status: {resp.text}"
            )

        return resp

    @audit_scope(
        event_type=EventType.DEVICE_CONTROL,
        end_event=EventSubtype.DEVICE_COMMAND,
        error_event=EventSubtype.DEVICE_COMMAND,
        device_id="device_id",
        command="command",
    )
    async def send_command(
        self, device_id: int, command: str, arguments: list[Any] | None = None
    ):
        """Send a command with optional arguments to a device.

        Args:
            device_id: The ID of the device to send the command to
            command: The command to send
            arguments: Optional list of arguments for the command
        """
        url = f"{self._address}/devices/{device_id}/{command}"
        if arguments:
            url += f"/{','.join(str(arg) for arg in arguments)}"

        await self._make_request(url)

    async def device_by_id(self, device_id: int) -> HubitatDevice:
        """Loads the device with the given id

        Args:
            device_id: The ID of the device to retrieve
        Returns:
            Fetched device
        """
        url = f"{self._address}/devices/{device_id}"
        resp = await self._make_request(url)

        # Parse the JSON response
        data = resp.json()

        # Extract attribute names as strings
        attributes = set()
        for attr_data in data.get("attributes", []):
            attributes.add(attr_data["name"])

        # Convert commands to a set of strings
        commands = set(data.get("commands", []))

        # Create and return the HubitatDevice
        return HubitatDevice(
            id=int(data["id"]),
            name=data["name"],
            attributes=attributes,
            commands=commands,
        )

    async def get_all_attributes(self, device_id: int) -> dict[str, Any]:
        """Get all current attribute values for a device.

        Args:
            device_id: The ID of the device to retrieve attributes for
        Returns:
            Dict mapping attribute names to their current values
        """
        url = f"{self._address}/devices/{device_id}"
        resp = await self._make_request(url)
        data = resp.json()

        # Extract current attribute values
        attributes = {}
        for attr_data in data.get("attributes", []):
            attributes[attr_data["name"]] = attr_data["currentValue"]
        return attributes

    async def get_all_devices(self) -> list[HubitatDevice]:
        """Get all devices with their attributes and current values.

        Returns:
            List of HubitatDevice objects with current attribute values
        """
        url = f"{self._address}/devices/all"
        resp = await self._make_request(url)
        data = resp.json()

        # Convert to list of HubitatDevice objects
        devices = []
        for device_data in data:
            # Extract attribute names as strings
            attributes = set()
            current_attributes = {}
            for attr_data in device_data.get("attributes", []):
                attr_name = attr_data["name"]
                attributes.add(attr_name)
                current_attributes[attr_name] = attr_data["currentValue"]

            # Convert commands to a set of strings
            commands = set(device_data.get("commands", []))

            # Create HubitatDevice object
            device = HubitatDevice(
                id=int(device_data["id"]),
                name=device_data["name"],
                attributes=attributes,
                commands=commands,
                current_attributes=current_attributes,
            )
            devices.append(device)

        return devices

    async def get_bulk_attributes(
        self, device_ids: list[int]
    ) -> dict[int, dict[str, Any]]:
        """Get current attribute values for multiple devices efficiently.

        Args:
            device_ids: List of device IDs to retrieve attributes for
        Returns:
            Dict mapping device_id to dict of attribute name -> current value
        """
        if not device_ids:
            return {}

        # Get all devices data
        all_devices = await self.get_all_devices()
        devices_by_id = {device.id: device for device in all_devices}

        # Extract attributes for requested devices
        result = {}
        for device_id in device_ids:
            if device_id in devices_by_id:
                device = devices_by_id[device_id]
                result[device_id] = device.current_attributes
            else:
                # Device not found in bulk data, fallback to individual call
                result[device_id] = await self.get_all_attributes(device_id)

        return result
