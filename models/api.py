from typing import Any

from pydantic import BaseModel


class HubitatDeviceResponse(BaseModel):
    """Full device response from /devices/all endpoint."""

    id: str  # Hubitat returns this as string
    name: str
    label: str
    type: str
    date: str | None = None  # API can return None for date
    model: str | None = None
    manufacturer: str | None = None
    capabilities: list[str]
    attributes: dict[str, Any] | None = None
    commands: list[dict[str, str]] | None = None
