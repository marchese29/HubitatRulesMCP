import asyncio
import contextlib
from contextlib import asynccontextmanager
from importlib import resources
import json
import logging
import logging.config
import os
from pathlib import Path
import sys
import time
from typing import Annotated

from fastapi import FastAPI
from fastmcp import Context, FastMCP
from pydantic import Field
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
import uvicorn
import yaml

from .audit import service as audit_service_module
from .audit.decorators import log_audit_event
from .audit.service import AuditService
from .hubitat import HubitatClient
from .logic.audit_logic import AuditLogic
from .logic.rule_logic import RuleLogic
from .logic.scene_logic import SceneLogic
from .models.api import (
    AuditLogQueryResponse,
    DeviceStateRequirement,
    HubitatDeviceEvent,
    PaginationInfo,
    RuleInfo,
    Scene,
    SceneSetResponse,
    SceneWithStatus,
)
from .models.audit import EventSubtype, EventType
from .models.database import DBRule
from .rules.engine import RuleEngine
from .rules.handler import RuleHandler
from .scenes.manager import SceneManager
from .timing.timers import TimerService

with resources.open_text(__package__, "log_config.yaml") as f:
    log_config = yaml.safe_load(f.read())
logging.config.dictConfig(log_config)

# Audit tools flag detection
AUDIT_TOOLS_ENABLED = "--audit-tools" in sys.argv or "-a" in sys.argv

# Common Resources
he_client = HubitatClient()
timer_service = TimerService()
rule_engine = RuleEngine(he_client, timer_service)
scene_manager = SceneManager(he_client)
rule_handler = RuleHandler(rule_engine, he_client, scene_manager)
rule_logic = RuleLogic(rule_handler)
scene_logic = SceneLogic(scene_manager)

# Conditional audit logic - only instantiate if audit tools are enabled
if AUDIT_TOOLS_ENABLED:
    audit_logic = AuditLogic()


web_app = FastAPI()
logger = logging.getLogger(__name__)


@web_app.get("/")
async def server_info(_: Request) -> PlainTextResponse:
    audit_status = "ENABLED" if AUDIT_TOOLS_ENABLED else "DISABLED"
    audit_tools_info = ""

    if AUDIT_TOOLS_ENABLED:
        audit_tools_info = """
• query_audit_logs - Query and filter audit logs with pagination
• get_rule_summary - AI-powered rule execution pattern analysis"""

    info = f"""Hubitat Rules MCP Server

This Model Context Protocol (MCP) server provides automation rule management and scene control for Hubitat home automation systems.

Features:
• Install and manage condition-based automation rules
• Install and manage scheduled automation rules
• Create and manage device scenes with state requirements
• Real-time device state monitoring and triggers
• Timer-based scheduling with cron support
• Python-based rule programming with full API access
• Comprehensive audit logging and analytics (Status: {audit_status})

Available Tools:
• install_rule - Create new automation rules (condition or scheduled)
• uninstall_rule - Remove existing automation rules
• get_rules - List rules with optional filtering and current status
• get_scenes - List scenes with optional filtering and current status
• create_scene - Create new scenes with device state requirements
• delete_scene - Remove scenes and get their definitions
• set_scene - Apply scenes by sending commands to devices{audit_tools_info}

Available Resources:
• rulesengine://programming-guide - Comprehensive rule programming documentation

The server integrates with your Hubitat hub to provide powerful, flexible automation capabilities through Python scripting and scene management.

Audit Tools: Use --audit-tools or -a flag when starting to enable advanced monitoring and AI-powered analysis tools.
"""
    return PlainTextResponse(info)


@web_app.post("/he_event")
async def receive_device_event(request: Request) -> JSONResponse:
    """Webhook endpoint to receive device events from Hubitat.

    This endpoint receives POST requests from Hubitat with device event data
    and forwards them to the rule engine for processing by active rules.

    Expected JSON payload:
    {
        "deviceId": "123",
        "name": "switch",
        "value": "on"
    }
    """
    try:
        # Parse the JSON payload from Hubitat
        payload = await request.json()
        logger.info(f"Received device event: {json.dumps(payload)}")

        # Create a HubitatDeviceEvent from the payload
        device_event = HubitatDeviceEvent(**payload["content"])

        # Define callback for when processing completes
        async def _on_processing_complete(task):
            try:
                await task  # Wait for the task to complete and check for exceptions
                logger.info(
                    f"Processed device event: device_id={device_event.device_id}, "
                    f"attribute={device_event.attribute}, value={device_event.value}"
                )
            except Exception as e:
                logger.error(
                    f"Error processing device event: device_id={device_event.device_id}, "
                    f"attribute={device_event.attribute}, error={str(e)}",
                )

        # Start device event processing as fire-and-forget
        processing_task = asyncio.create_task(rule_engine.on_device_event(device_event))

        # Add callback to log when processing completes
        processing_task.add_done_callback(
            lambda task: asyncio.create_task(_on_processing_complete(task))
        )

        # Return immediately without waiting for processing
        return JSONResponse(
            {
                "success": True,
                "message": "Device event received and queued for processing",
                "device_id": device_event.device_id,
                "attribute": device_event.attribute,
                "value": device_event.value,
            }
        )

    except Exception as e:
        error_msg = f"Error parsing device event: {str(e)}"
        logger.error(error_msg, exc_info=True)

        return JSONResponse({"success": False, "error": error_msg}, status_code=400)


@asynccontextmanager
async def lifespan(fastmcp: FastMCP):
    """Handle startup and shutdown for the MCP server"""
    lc_logger = logging.getLogger("lifecycle")
    lc_logger.debug("Hubitat Rules MCP server starting up...")

    # Initialize and start audit service
    lc_logger.debug("Starting audit service...")
    audit_service_module.audit_service = AuditService(fastmcp.db_engine)  # type: ignore[attr-defined]
    audit_service_module.audit_service.start()
    lc_logger.debug("Audit service started")

    lc_logger.debug("Initiating TimerService")
    timer_service.start()
    lc_logger.debug("TimerService started")

    # Load existing rules from the database
    lc_logger.debug("Re-installing rules from the database")
    # TODO: Move this logic into the rule_logic file
    count = 0
    with Session(fastmcp.db_engine) as session:  # type: ignore[attr-defined]
        for rule in session.exec(select(DBRule)):
            count += 1
            start_time = time.time()

            if rule.time_provider is not None:
                lc_logger.debug(f"Installing scheduled rule '{rule.name}'")
                await rule_handler.install_scheduled_rule(rule, rule.name)
            else:
                lc_logger.debug(f"Installing triggered rule '{rule.name}'")
                await rule_handler.install_rule(rule, rule.name)

            # Log rule loading to audit with timing
            execution_time = (time.time() - start_time) * 1000
            await log_audit_event(
                EventType.RULE_LIFECYCLE,
                EventSubtype.RULE_LOADED,
                rule_name=rule.name,
                execution_time_ms=execution_time,
                success=True,
            )
    if count > 0:
        lc_logger.debug(f"Re-installed {count} rules from the database")

    # Load existing scenes from the database
    lc_logger.debug("Re-installing scenes from the database")
    scene_count = 0
    with Session(fastmcp.db_engine) as session:  # type: ignore[attr-defined]
        scene_count = await scene_logic.load_scenes_from_database(session)
    if scene_count > 0:
        lc_logger.debug(f"Re-installed {scene_count} scenes from the database")

    # Launch the web server
    lc_logger.debug("Starting webhook server")
    config = uvicorn.Config("he_rules.server:web_app", host="0.0.0.0", port=8080)
    server = uvicorn.Server(config)
    web_app_task = asyncio.create_task(server.serve())
    lc_logger.debug("Webhook server started")

    lc_logger.info("Server initialization complete")
    yield  # Server runs here

    # Shutdown code - runs when server stops
    lc_logger.debug("Hubitat Rules MCP server shutting down...")
    try:
        web_app_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await web_app_task
        lc_logger.debug("Webhook server turned off")

        # Cancel all active rules first
        for rule_name in rule_handler.get_active_rules():
            try:
                # Note, this leaves the rule in the database so it can be loaded again on
                # startup
                # We need to get the DBRule object from the database first
                with Session(fastmcp.db_engine) as session:  # type: ignore[attr-defined]
                    db_rule: DBRule | None = session.exec(
                        select(DBRule).where(DBRule.name == rule_name)
                    ).first()
                    if db_rule:
                        await rule_handler.uninstall_rule(db_rule, rule_name)
                        lc_logger.debug(f"Uninstalled rule: {rule_name}")
                    else:
                        lc_logger.debug(
                            f"Rule {rule_name} not found in database during shutdown"
                        )
            except Exception as e:
                lc_logger.warning(
                    f"Error uninstalling rule {rule_name}: {e}", exc_info=True
                )

        # Stop the timer service and cancel all active timers
        with contextlib.suppress(asyncio.CancelledError):
            # Cancel all active timers first
            for timer_id in list(timer_service._timers.keys()):
                timer_service.cancel_timer(timer_id)
            # Then stop the service
            await timer_service.stop()
        lc_logger.debug("Timer service stopped")

        # Stop the audit service
        if audit_service_module.audit_service:
            with contextlib.suppress(asyncio.CancelledError):
                await audit_service_module.audit_service.stop()
            lc_logger.debug("Audit service stopped")

        # Cancel any remaining asyncio tasks to prevent hanging
        current_task = asyncio.current_task()
        pending_tasks = [
            task
            for task in asyncio.all_tasks()
            if not task.done() and task is not current_task
        ]

        if pending_tasks:
            lc_logger.debug(f"Cancelling {len(pending_tasks)} remaining tasks")
            for task in pending_tasks:
                task.cancel()

            # Wait briefly for tasks to finish cancelling
            await asyncio.gather(*pending_tasks, return_exceptions=True)

    except Exception as e:
        lc_logger.warning(f"Error during shutdown: {e}", exc_info=True)


mcp = FastMCP(name="Hubitat Rules", lifespan=lifespan)
script_dir = Path(__file__).parent.absolute()
db_location = script_dir / "rules.db"
mcp.db_engine = create_engine(f"sqlite:///{db_location}")  # type: ignore[attr-defined]
SQLModel.metadata.create_all(mcp.db_engine)  # type: ignore[attr-defined]


# @mcp.resource("rulesengine://programming-guide")
@mcp.tool()
async def get_programming_guide() -> str:
    """Comprehensive programming guide for writing Hubitat automation rules.

    This resource provides detailed documentation on:
    - Rule architecture and concepts (condition-based vs scheduled rules)
    - Programming patterns and best practices
    - Complete API reference with examples
    - Device interaction patterns
    - Timing and condition handling
    - Common use cases and troubleshooting

    Essential context for LLMs to understand how to write effective
    Python automation rules using this Hubitat Rules MCP server.
    """
    try:
        # Get the directory where main.py is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        guide_path = os.path.join(script_dir, "hubitat_rules_programming_guide.md")

        with open(guide_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return (
            "Programming guide not found. Please ensure hubitat_rules_programming_guide.md exists "
            "in the same directory as main.py."
        )
    except Exception as e:
        return f"Error loading programming guide: {str(e)}"


@mcp.tool()
async def install_rule(
    name: str,
    rule_type: str,  # "condition" or "scheduled"
    trigger_code: str,
    action_code: str,
    ctx: Context,
) -> dict:
    """Install a new automation rule (either condition-based or scheduled).

    Args:
        name: Unique name for the rule
        rule_type: Either "condition" for trigger-based rules or "scheduled" for timer-based rules
        trigger_code: Python code defining the trigger condition or timer schedule
        action_code: Python code defining the rule action to execute

    Returns:
        Dict with success status, message, and current active rules
    """
    await ctx.info(f"Installing rule '{name}' of type '{rule_type}'")

    try:
        # Validate rule type
        if rule_type not in ["condition", "scheduled"]:
            error_msg = (
                f"Invalid rule_type '{rule_type}'. Must be 'condition' or 'scheduled'"
            )
            await ctx.error(error_msg)
            return {"success": False, "message": error_msg, "rule_name": name}

        # Install the appropriate rule type
        if rule_type == "condition":
            rule = await rule_logic.install_trigger_rule(
                name, trigger_code, action_code
            )
        else:  # scheduled
            rule = await rule_logic.install_timer_rule(
                name, time_provider=trigger_code, action_code=action_code
            )

        return {
            "success": True,
            "message": f"Rule '{name}' installed successfully",
            "rule": rule,
        }

    except ValueError as e:
        error_msg = f"Rule installation failed: {str(e)}"
        await ctx.error(error_msg)
        return {"success": False, "message": error_msg, "rule_name": name}
    except Exception as e:
        error_msg = f"Unexpected error installing rule '{name}': {str(e)}"
        await ctx.error(error_msg)
        return {"success": False, "message": error_msg, "rule_name": name}


@mcp.tool()
async def uninstall_rule(name: str, ctx: Context) -> dict:
    """Uninstall an existing automation rule.

    Args:
        name: Name of the rule to uninstall

    Returns:
        Dict with success status, message, and current active rules
    """
    await ctx.info(f"Uninstalling rule '{name}'")

    try:
        rule = await rule_logic.uninstall_rule(name)

        return {
            "success": True,
            "message": f"Rule '{name}' uninstalled successfully",
            "rule": rule,
        }

    except ValueError as e:
        error_msg = f"Rule uninstallation failed: {str(e)}"
        await ctx.warning(error_msg)
        return {"success": False, "message": error_msg, "rule_name": name}
    except Exception as e:
        error_msg = f"Unexpected error uninstalling rule '{name}': {str(e)}"
        await ctx.error(error_msg)
        return {"success": False, "message": error_msg, "rule_name": name}


@mcp.tool()
async def get_rules(
    ctx: Context,
    name: str | None = None,
    rule_type: str | None = None,
) -> list[RuleInfo]:
    """Get rules with optional filtering.

    Args:
        name: Get specific rule by name
        rule_type: Filter by "condition" or "scheduled"

    Returns:
        List of rules with current status
    """
    try:
        return await rule_logic.get_rules(name=name, rule_type=rule_type)
    except Exception as e:
        await ctx.error(f"Error getting rules: {str(e)}")
        return []


@mcp.tool()
async def get_scenes(
    ctx: Context,
    name: str | None = None,
    device_id: int | None = None,
) -> list[SceneWithStatus]:
    """Get scenes with optional filtering. Includes current set status.

    Args:
        name: Get specific scene by name
        device_id: Get all scenes that involve this device

    Returns:
        List of scenes with current status
    """
    try:
        return await scene_manager.get_scenes(name=name, device_id=device_id)
    except Exception as e:
        await ctx.error(f"Error getting scenes: {str(e)}")
        return []


@mcp.tool()
async def create_scene(
    name: str,
    device_states: list[DeviceStateRequirement],
    ctx: Context,
    description: str | None = None,
) -> SceneWithStatus:
    """Create a new scene with explicit device states and commands.

    Args:
        name: Unique name for the scene
        description: Optional description of the scene
        device_states: List of device state requirements with format:
                      [{"device_id": 123, "attribute": "switch", "value": "on", "command": "on", "arguments": []}]

    Returns:
        The created scene
    """
    try:
        from datetime import datetime

        scene = Scene(
            name=name,
            description=description,
            device_states=device_states,
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        # Use scene_logic to ensure persistence
        await scene_logic.create_scene(name, scene)

        # Get the created scene with current status
        scenes_with_status = await scene_manager.get_scenes(name=name)
        if not scenes_with_status:
            raise RuntimeError(f"Scene '{name}' was created but could not be retrieved")

        scene_with_status = scenes_with_status[0]

        await ctx.info(
            f"Created scene '{name}' with {len(device_states)} device states"
        )
        return scene_with_status

    except Exception as e:
        error_msg = f"Error creating scene '{name}': {str(e)}"
        await ctx.error(error_msg)
        raise RuntimeError(error_msg)


@mcp.tool()
async def delete_scene(name: str, ctx: Context) -> Scene:
    """Delete a scene and return its definition.

    Args:
        name: Name of the scene to delete

    Returns:
        The deleted scene information
    """
    try:
        # Get the scene data before deletion
        scenes = await scene_logic.get_scenes(name=name)
        if not scenes:
            raise ValueError(f"Scene '{name}' not found")

        scene_to_delete = scenes[0]

        # Use scene_logic to ensure persistence
        await scene_logic.delete_scene(name)

        await ctx.info(f"Deleted scene '{name}'")
        return scene_to_delete
    except Exception as e:
        error_msg = f"Error deleting scene '{name}': {str(e)}"
        await ctx.error(error_msg)
        raise RuntimeError(error_msg)


@mcp.tool()
async def set_scene(name: str, ctx: Context) -> SceneSetResponse:
    """Apply a scene by sending commands to devices.

    Args:
        name: Name of the scene to apply

    Returns:
        Result of scene application with any failed commands
    """
    try:
        response = await scene_manager.set_scene(name)

        # Log results
        if response.success:
            await ctx.info(f"Scene '{name}' applied successfully")
        else:
            await ctx.warning(
                f"Scene '{name}' applied with {len(response.failed_commands)} failures"
            )

        return response
    except Exception as e:
        error_msg = f"Error setting scene '{name}': {str(e)}"
        await ctx.error(error_msg)
        raise RuntimeError(error_msg)


# Conditional Audit Tools - only available with --audit-tools flag
if AUDIT_TOOLS_ENABLED:

    @mcp.tool()
    async def query_audit_logs(
        ctx: Context,
        event_type: str | None = None,
        event_subtype: str | None = None,
        rule_name: str | None = None,
        scene_name: str | None = None,
        device_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int = 1,
        page_size: Annotated[int, Field(ge=1, le=200)] = 50,
    ) -> AuditLogQueryResponse:
        """Query audit logs with filtering and pagination.

        Args:
            event_type: Filter by event type (e.g., 'rule_lifecycle', 'execution_lifecycle')
            event_subtype: Filter by event subtype (e.g., 'rule_created', 'condition_evaluated')
            rule_name: Filter by specific rule name
            scene_name: Filter by specific scene name
            device_id: Filter by device ID
            start_date: Start date filter (ISO format, e.g., '2024-01-01T00:00:00')
            end_date: End date filter (ISO format, e.g., '2024-01-31T23:59:59')
            page: Page number (starts at 1)
            page_size: Number of results per page (1-200)

        Returns:
            AuditLogQueryResponse with audit log entries and pagination info
        """
        await ctx.info(f"Querying audit logs - page {page}, size {page_size}")

        try:
            result = await audit_logic.query_audit_logs(
                event_type=event_type,
                event_subtype=event_subtype,
                rule_name=rule_name,
                scene_name=scene_name,
                device_id=device_id,
                start_date=start_date,
                end_date=end_date,
                page=page,
                page_size=page_size,
            )

            await ctx.info(
                f"Found {result.pagination.total_records} audit logs, returning page {page} "
                f"of {result.pagination.total_pages}"
            )

            return result

        except Exception as e:
            error_msg = f"Error querying audit logs: {str(e)}"
            await ctx.error(error_msg)
            return AuditLogQueryResponse(
                data=[],
                pagination=PaginationInfo(
                    page=page,
                    page_size=page_size,
                    total_pages=0,
                    total_records=0,
                    has_next=False,
                    has_prev=False,
                ),
            )


def main():
    mcp.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\nShutdown completed gracefully.")
