from datetime import datetime
from enum import Enum

from sqlalchemy import Column
from sqlalchemy import Enum as SQLEnum
from sqlmodel import Field, SQLModel


class EventType(str, Enum):
    """Main categories of audit events"""

    RULE_LIFECYCLE = "rule_lifecycle"
    EXECUTION_LIFECYCLE = "execution_lifecycle"
    DEVICE_CONTROL = "device_control"
    SCENE_LIFECYCLE = "scene_lifecycle"


class EventSubtype(str, Enum):
    """Specific audit event subtypes"""

    # Rule lifecycle events
    RULE_CREATED = "rule_created"
    RULE_LOADED = "rule_loaded"
    RULE_DELETED = "rule_deleted"

    # Execution lifecycle events
    CONDITION_NOW_TRUE = "condition_now_true"
    CONDITION_EVALUATED = "condition_evaluated"
    CONDITION_TIMEOUT = "condition_timeout"
    TRIGGER_FIRED = "trigger_fired"
    RULE_ACTION_STARTED = "rule_action_started"
    RULE_ACTION_COMPLETED = "rule_action_completed"
    RULE_ACTION_FAILED = "rule_action_failed"

    # Device control events
    DEVICE_COMMAND = "device_command"

    # Scene lifecycle events
    SCENE_CREATED = "scene_created"
    SCENE_DELETED = "scene_deleted"
    SCENE_APPLIED = "scene_applied"


class AuditLog(SQLModel, table=True):
    """Audit log entry for tracking rule engine events and execution flow"""

    id: int | None = Field(primary_key=True, default=None, nullable=False)
    timestamp: datetime = Field(default_factory=datetime.now)

    # Event categorization using enums
    event_type: EventType = Field(sa_column=Column(SQLEnum(EventType)))
    event_subtype: EventSubtype = Field(sa_column=Column(SQLEnum(EventSubtype)))

    # Context fields for filtering and debugging
    rule_name: str | None = Field(index=True, default=None)
    scene_name: str | None = Field(index=True, default=None)
    condition_id: str | None = Field(index=True, default=None)
    device_id: int | None = Field(index=True, default=None)

    # Execution results
    success: bool | None = None
    error_message: str | None = None
    execution_time_ms: float | None = None

    # Additional event-specific data as JSON
    context_data: str | None = None
