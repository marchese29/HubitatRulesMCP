import asyncio
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from functools import wraps
import inspect
import json
import time
from typing import Any, ParamSpec, TypeVar

from audit.service import get_audit_service
from models.audit import EventSubtype, EventType

# Type parameters for the audit_scope decorator
P = ParamSpec("P")
T = TypeVar("T")

# Database fields that are explicit columns in AuditLog table
AUDIT_SCOPE_FIELDS = {"rule_name", "scene_name", "condition_id", "device_id"}

# Context: tuple of dictionaries, each scope adds a new dict
audit_context: ContextVar[tuple[dict[str, Any], ...]] = ContextVar(
    "audit_context", default=()
)


def get_current_context() -> dict[str, Any]:
    """Get merged context from all dictionaries in tuple"""
    context_tuple = audit_context.get()
    merged = {}
    for context_dict in context_tuple:
        merged.update(context_dict)
    return merged


def audit_scope(
    *,
    # Lifecycle events (optional)
    event_type: EventType | None = None,
    start_event: EventSubtype | None = None,
    end_event: EventSubtype | None = None,
    error_event: EventSubtype | None = None,
    # Explicit scope fields (map to function args)
    rule_name: str | None = None,
    scene_name: str | None = None,
    condition_id: str | None = None,
    device_id: str | None = None,
    # Additional context (goes to context_data JSON)
    **additional_context,
) -> Callable[
    [Callable[P, Coroutine[Any, Any, T]]], Callable[P, Coroutine[Any, Any, T]]
]:
    """
    Decorator for audit scope management with optional lifecycle event logging.

    Args:
        event_type: EventType for lifecycle events (required if any lifecycle events specified)
        start_event: EventSubtype to log on function entry
        end_event: EventSubtype to log on successful function exit
        error_event: EventSubtype to log on function exception
        rule_name: Function argument name that provides rule_name context
        scene_name: Function argument name that provides scene_name context
        condition_id: Function argument name that provides condition_id context
        device_id: Function argument name that provides device_id context
        **additional_context: Additional context fields for context_data JSON
    """
    # Validate that event_type is provided if any lifecycle events are specified
    lifecycle_events = [start_event, end_event, error_event]
    if any(lifecycle_events) and event_type is None:
        raise ValueError("event_type is required when lifecycle events are specified")

    def decorator(
        func: Callable[P, Coroutine[Any, Any, T]],
    ) -> Callable[P, Coroutine[Any, Any, T]]:
        @wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            # Extract context from function arguments
            sig = inspect.signature(func)
            bound_args = sig.bind(*args, **kwargs)
            bound_args.apply_defaults()

            # Build new context from explicit scope fields
            new_context = {}
            scope_mappings = {
                "rule_name": rule_name,
                "scene_name": scene_name,
                "condition_id": condition_id,
                "device_id": device_id,
            }

            for context_key, arg_name in scope_mappings.items():
                if arg_name and arg_name in bound_args.arguments:
                    new_context[context_key] = bound_args.arguments[arg_name]

            # Add additional context to context_data
            if additional_context:
                context_data = {}
                for context_key, arg_name in additional_context.items():
                    if isinstance(arg_name, str) and arg_name in bound_args.arguments:
                        context_data[context_key] = bound_args.arguments[arg_name]
                    else:
                        # Direct value, not a function argument mapping
                        context_data[context_key] = arg_name

                if context_data:
                    new_context["context_data"] = json.dumps(context_data)

            # Push context onto tuple using token
            token = audit_context.set(audit_context.get() + (new_context,))

            try:
                start_time = time.time()

                # Try to get audit service, but don't fail if it's not available
                try:
                    audit_service = get_audit_service()
                except RuntimeError:
                    audit_service = None

                # Log start event if specified
                if audit_service and start_event and event_type:
                    await audit_service.log_event(
                        event_type,
                        start_event,
                        **get_current_context(),
                    )

                # Execute function (all functions using this decorator are async)
                function_result: T = await func(*args, **kwargs)

                # Log successful completion if end_event specified
                if audit_service and end_event and event_type:
                    execution_time = (time.time() - start_time) * 1000
                    await audit_service.log_event(
                        event_type,
                        end_event,
                        execution_time_ms=execution_time,
                        success=True,
                        **get_current_context(),
                    )
                return function_result

            except Exception as e:
                # Log failure if error_event specified
                if audit_service and error_event and event_type:
                    execution_time = (time.time() - start_time) * 1000
                    await audit_service.log_event(
                        event_type,
                        error_event,
                        execution_time_ms=execution_time,
                        error_message=str(e),
                        success=False,
                        **get_current_context(),
                    )
                raise
            finally:
                # Pop context using token
                audit_context.reset(token)

        # Since all audit_scope usages are on async functions, we only need the async wrapper
        return async_wrapper

    return decorator


async def log_audit_event(
    event_type: EventType, event_subtype: EventSubtype, **context
):
    """
    Log an audit event with automatic context inheritance.

    Args:
        event_type: Category of event (EventType enum)
        event_subtype: Specific event subtype (EventSubtype enum)
        **context: Additional context data to include with the event
    """
    try:
        audit_service = get_audit_service()
        current_context = get_current_context()

        # Separate explicit DB fields from additional context
        explicit_fields = {}
        additional_data = {}

        # Merge current context first, then provided context
        merged_context = {**current_context, **context}

        # Extract explicit DB fields
        for key, value in merged_context.items():
            if key in AUDIT_SCOPE_FIELDS:
                explicit_fields[key] = value
            elif key != "context_data":  # Don't double-nest context_data
                additional_data[key] = value

        # Handle context_data JSON field
        final_context_data = None
        if "context_data" in merged_context:
            # If there's existing context_data from scope, parse it
            try:
                existing_data = json.loads(merged_context["context_data"])
                if isinstance(existing_data, dict):
                    additional_data.update(existing_data)
            except (json.JSONDecodeError, TypeError):
                pass

        # Add additional_data to context_data if any
        if additional_data:
            final_context_data = json.dumps(additional_data)

        await audit_service.log_event(
            event_type,
            event_subtype,
            context_data=final_context_data,
            **explicit_fields,
        )
    except Exception as e:
        print(f"Audit logging failed: {e}")


def log_audit_event_sync(event_type: EventType, event_subtype: EventSubtype, **context):
    """
    Synchronous version of log_audit_event for use in sync contexts.
    """

    async def log():
        await log_audit_event(event_type, event_subtype, **context)

    # Try to schedule the logging
    try:
        asyncio.create_task(log())
    except RuntimeError:
        # No event loop, run in new one
        asyncio.run(log())


class AuditScopeContext:
    """Async context manager for audit scope management"""

    def __init__(self, **context):
        self.context = context
        self.token = None

    async def __aenter__(self):
        # Build context with proper structure
        new_context = {}
        additional_data = {}

        # Separate explicit DB fields from additional context
        for key, value in self.context.items():
            if key in AUDIT_SCOPE_FIELDS:
                new_context[key] = value
            else:
                additional_data[key] = value

        # Add additional_data to context_data if any
        if additional_data:
            new_context["context_data"] = json.dumps(additional_data)

        # Push context onto tuple
        self.token = audit_context.set(audit_context.get() + (new_context,))
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            audit_context.reset(self.token)


def audit_scope_context(**context):
    """
    Create an async context manager for audit scope management.

    Args:
        **context: Context fields to add to audit scope

    Usage:
        async with audit_scope_context(rule_name="test_rule", sensor_type="motion"):
            await log_audit_event(EventType.EXECUTION_LIFECYCLE, EventSubtype.CONDITION_EVALUATED)
    """
    return AuditScopeContext(**context)
