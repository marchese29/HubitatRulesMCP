from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


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


class HubitatDeviceEvent(BaseModel):
    """Represents an event from a Hubitat device."""

    device_id: str = Field(alias="deviceId")
    attribute: str = Field(alias="name")
    value: Any | None


# Scene Models
class DeviceStateRequirement(BaseModel):
    """Defines both desired state and how to achieve it"""

    device_id: int
    attribute: str
    value: Any
    command: str
    arguments: list[Any] = []


class Scene(BaseModel):
    """Complete scene definition"""

    name: str
    description: str | None = None
    device_states: list[DeviceStateRequirement]
    created_at: datetime
    updated_at: datetime


class SceneWithStatus(BaseModel):
    """Scene information including current set status"""

    name: str
    description: str | None = None
    device_states: list[DeviceStateRequirement]
    created_at: datetime
    updated_at: datetime
    is_set: bool


class CommandResult(BaseModel):
    """Result of a failed command"""

    device_id: int
    command: str
    arguments: list[Any] = []
    error: str


class SceneSetResponse(BaseModel):
    """Response for set_scene operation - only includes failures"""

    success: bool
    scene_name: str
    message: str
    failed_commands: list[CommandResult]  # Only failed commands


# Rule Models
class RuleInfo(BaseModel):
    """Information about an automation rule"""

    name: str
    rule_type: str  # "condition" or "scheduled"
    trigger_code: str
    action_code: str
    is_active: bool
