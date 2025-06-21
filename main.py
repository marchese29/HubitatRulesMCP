import asyncio
from contextlib import asynccontextmanager
import sys
import time

from fastapi import FastAPI
from fastmcp import Context, FastMCP
from sqlmodel import Session, SQLModel, create_engine, select
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
import uvicorn

from audit import service as audit_service_module
from audit.decorators import log_audit_event
from audit.service import AuditService
from hubitat import HubitatClient
from logic.rule_logic import RuleLogic
from logic.scene_logic import SceneLogic
from models.api import (
    DeviceStateRequirement,
    HubitatDeviceEvent,
    RuleInfo,
    Scene,
    SceneSetResponse,
    SceneWithStatus,
)
from models.audit import EventSubtype, EventType
from models.database import DBRule
from rules.engine import RuleEngine
from rules.handler import RuleHandler
from scenes.manager import SceneManager
from timing.timers import TimerService

# Common Resources
he_client = HubitatClient()
timer_service = TimerService()
rule_engine = RuleEngine(he_client, timer_service)
scene_manager = SceneManager(he_client)
rule_handler = RuleHandler(rule_engine, he_client, scene_manager)
rule_logic = RuleLogic(rule_handler)
scene_logic = SceneLogic(scene_manager)


web_app = FastAPI()


@web_app.get("/")
async def server_info(_: Request) -> PlainTextResponse:
    info = """Hubitat Rules MCP Server

This Model Context Protocol (MCP) server provides automation rule management and scene control for Hubitat home automation systems.

Features:
• Install and manage condition-based automation rules
• Install and manage scheduled automation rules
• Create and manage device scenes with state requirements
• Real-time device state monitoring and triggers
• Timer-based scheduling with cron support
• Python-based rule programming with full API access

Available Tools:
• install_rule - Create new automation rules (condition or scheduled)
• uninstall_rule - Remove existing automation rules
• get_rules - List rules with optional filtering and current status
• get_scenes - List scenes with optional filtering and current status
• create_scene - Create new scenes with device state requirements
• delete_scene - Remove scenes and get their definitions
• set_scene - Apply scenes by sending commands to devices

Available Resources:
• rulesengine://programming-guide - Comprehensive rule programming documentation

The server integrates with your Hubitat hub to provide powerful, flexible automation capabilities through Python scripting and scene management.
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

        # Create a HubitatDeviceEvent from the payload
        device_event = HubitatDeviceEvent(**payload)

        # Define callback for when processing completes
        async def _on_processing_complete(task):
            try:
                await task  # Wait for the task to complete and check for exceptions
                print(
                    f"Processed device event: device_id={device_event.device_id}, "
                    f"attribute={device_event.attribute}, value={device_event.value}"
                )
            except Exception as e:
                print(
                    f"Error processing device event: device_id={device_event.device_id}, "
                    f"attribute={device_event.attribute}, error={str(e)}",
                    file=sys.stderr,
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
        print(error_msg, file=sys.stderr)

        return JSONResponse({"success": False, "error": error_msg}, status_code=400)


@asynccontextmanager
async def lifespan(fastmcp: FastMCP):
    """Handle startup and shutdown for the MCP server"""
    print("Hubitat Rules MCP server starting up...")

    # Initialize and start audit service
    print("Starting audit service...")
    audit_service_module.audit_service = AuditService(fastmcp.db_engine)  # type: ignore[attr-defined]
    audit_service_module.audit_service.start()
    print("Audit service started")

    print("Initiating TimerService")
    timer_service.start()
    print("TimerService started")

    # Load existing rules from the database
    print("Re-installing rules from the database")
    # TODO: Move this logic into the rule_logic file
    count = 0
    with Session(fastmcp.db_engine) as session:  # type: ignore[attr-defined]
        for rule in session.exec(select(DBRule)):
            count += 1
            start_time = time.time()

            if rule.time_provider is not None:
                print(f"Installing scheduled rule '{rule.name}'")
                await rule_handler.install_scheduled_rule(rule, rule.name)
            else:
                print(f"Installing triggered rule '{rule.name}'")
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
        print(f"Re-installed {count} rules from the database")

    # Load existing scenes from the database
    print("Re-installing scenes from the database")
    scene_count = 0
    with Session(fastmcp.db_engine) as session:  # type: ignore[attr-defined]
        scene_count = await scene_logic.load_scenes_from_database(session)
    if scene_count > 0:
        print(f"Re-installed {scene_count} scenes from the database")

    # Launch the web server
    print("Starting webhook server")
    config = uvicorn.Config("main:web_app", host="0.0.0.0", port=8080)
    server = uvicorn.Server(config)
    web_app_task = asyncio.create_task(server.serve())
    print("Webhook server started")

    yield  # Server runs here

    # Shutdown code - runs when server stops
    print("Hubitat Rules MCP server shutting down...")
    try:
        web_app_task.cancel()
        await web_app_task

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
                        print(f"Uninstalled rule: {rule_name}")
                    else:
                        print(f"Rule {rule_name} not found in database during shutdown")
            except Exception as e:
                print(f"Error uninstalling rule {rule_name}: {e}")

        # Stop the timer service
        await timer_service.stop()
        print("Timer service stopped")

        # Stop the audit service
        if audit_service_module.audit_service:
            await audit_service_module.audit_service.stop()
            print("Audit service stopped")
    except Exception as e:
        print(f"Error during shutdown: {e}")


mcp = FastMCP(name="Hubitat Rules", lifespan=lifespan)
mcp.db_engine = create_engine("sqlite:///rulesdb.db")  # type: ignore[attr-defined]
SQLModel.metadata.create_all(mcp.db_engine)  # type: ignore[attr-defined]


@mcp.resource("rulesengine://programming-guide")
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
    import os

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


if __name__ == "__main__":
    try:
        mcp.run()
    except KeyboardInterrupt:
        print("\nShutdown completed gracefully.")
