from datetime import datetime

from sqlmodel import Field, SQLModel


class DBRule(SQLModel, table=True):
    """Represents a rule stored in the database"""

    name: str = Field(primary_key=True)
    time_provider: str | None = None
    trigger_code: str | None = None
    action_code: str


class DBScene(SQLModel, table=True):
    """Represents a scene stored in the database"""

    name: str = Field(primary_key=True)
    description: str | None = None
    device_states_json: str  # JSON serialized DeviceStateRequirement list
    created_at: datetime
    updated_at: datetime
