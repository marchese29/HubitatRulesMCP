import asyncio
from contextlib import suppress
from datetime import datetime

from sqlalchemy import Engine
from sqlmodel import Session

from models.audit import AuditLog, EventSubtype, EventType


class AuditService:
    """Async audit service for non-blocking audit log writes"""

    def __init__(self, db_engine: Engine):
        self.db_engine: Engine = db_engine
        self.audit_queue: asyncio.Queue[AuditLog] = asyncio.Queue()
        self._writer_task: asyncio.Task[None] | None = None
        self._started: bool = False

    def start(self) -> None:
        """Start the audit writer task"""
        if self._writer_task is None:
            self._started = True
            self._writer_task = asyncio.create_task(self._audit_writer())

    async def stop(self):
        """Stop the audit writer task gracefully"""
        self._started = False
        if self._writer_task:
            self._writer_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._writer_task
            self._writer_task = None

    async def log_event(
        self, event_type: EventType, event_subtype: EventSubtype, **event_data
    ):
        """Non-blocking audit log entry creation"""
        try:
            # Handle context_data separately to avoid conflicts
            context_json = event_data.pop("context_data", None)

            audit_entry = AuditLog(
                timestamp=datetime.now(),
                event_type=event_type,
                event_subtype=event_subtype,
                context_data=context_json,
                **event_data,
            )

            # Non-blocking enqueue
            await self.audit_queue.put(audit_entry)

        except Exception as e:
            # Silently handle audit errors to avoid impacting main flow
            print(f"Failed to enqueue audit entry: {e}")

    async def _audit_writer(self):
        """Background task to write audit entries to database"""
        while self._started:
            try:
                # Wait for audit entry with timeout to allow graceful shutdown
                audit_entry = await asyncio.wait_for(
                    self.audit_queue.get(), timeout=1.0
                )

                # Write to database in separate session
                with Session(self.db_engine) as session:
                    session.add(audit_entry)
                    session.commit()

            except TimeoutError:
                # Continue loop to check _started flag
                continue
            except Exception as e:
                # Log but don't crash - audit failures shouldn't impact main app
                print(f"Audit write failed: {e}")


# Global audit service instance - will be initialized in main.py
audit_service: AuditService | None = None


def get_audit_service() -> AuditService:
    """Get the global audit service instance"""
    if audit_service is None:
        raise RuntimeError("Audit service not initialized")
    return audit_service
