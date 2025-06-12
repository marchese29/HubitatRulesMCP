from sqlmodel import Field, SQLModel


class DBRule(SQLModel, table=True):
    """Represents a rule stored in the database"""

    name: str = Field(primary_key=True)
    time_provider: str | None = None
    trigger_code: str | None = None
    action_code: str
