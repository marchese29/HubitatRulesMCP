from typing import Optional

import httpx
from pydantic import BaseModel

from util import env_var


class HubitatDevice(BaseModel):
    id: int
    name: str
    attributes: set[str]
    commands: set[str]

    def has_attribute(self, attr: str) -> bool:
        return attr in self.attributes

    def has_command(self, command: str) -> bool:
        return command in self.commands


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

    async def send_command(
        self, device_id: int, command: str, arguments: Optional[list[any]] = None
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

    async def get_all_attributes(self, device_id: int) -> dict[str, any]:
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
