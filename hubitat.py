from typing import Any, Optional

import httpx

from util import env_var


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
        self, device_id: int, command: str, arguments: Optional[list[Any]] = None
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

