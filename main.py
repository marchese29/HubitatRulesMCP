from contextlib import asynccontextmanager
from fastmcp import FastMCP, Context
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from hubitat import HubitatClient
from rules.engine import RuleEngine
from rules.handler import RuleHandler
from timing.timers import TimerService


# Common Resources
he_client = HubitatClient()
timer_service = TimerService()
rule_engine = RuleEngine(he_client, timer_service)
rule_handler = RuleHandler(rule_engine, he_client)


@asynccontextmanager
async def lifespan(app):
    """Handle startup and shutdown for the MCP server"""
    # Startup code - runs when server starts
    print("Hubitat Rules MCP server starting up...")
    timer_service.start()
    print("Timer service started")

    yield  # Server runs here

    # Shutdown code - runs when server stops
    print("Hubitat Rules MCP server shutting down...")
    try:
        # Cancel all active rules first
        for rule_name in rule_handler.get_active_rules():
            try:
                await rule_handler.uninstall_rule(rule_name)
                print(f"Uninstalled rule: {rule_name}")
            except Exception as e:
                print(f"Error uninstalling rule {rule_name}: {e}")

        # Stop the timer service
        await timer_service.stop()
        print("Timer service stopped")
    except Exception as e:
        print(f"Error during shutdown: {e}")


mcp = FastMCP(name="Hubitat Rules", lifespan=lifespan)


@mcp.custom_route("/", methods=["GET"])
async def hello_world(request: Request) -> PlainTextResponse:
    return PlainTextResponse("Hello, World!")


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
            await rule_handler.install_rule(name, trigger_code, action_code)
        else:  # scheduled
            await rule_handler.install_scheduled_rule(name, trigger_code, action_code)

        active_rules = rule_handler.get_active_rules()
        await ctx.info(
            f"Successfully installed rule '{name}'. Active rules: {len(active_rules)}"
        )

        return {
            "success": True,
            "message": f"Rule '{name}' installed successfully",
            "rule_name": name,
            "active_rules": active_rules,
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
        await rule_handler.uninstall_rule(name)
        active_rules = rule_handler.get_active_rules()
        await ctx.info(
            f"Successfully uninstalled rule '{name}'. Active rules: {len(active_rules)}"
        )

        return {
            "success": True,
            "message": f"Rule '{name}' uninstalled successfully",
            "rule_name": name,
            "active_rules": active_rules,
        }

    except ValueError as e:
        error_msg = f"Rule uninstallation failed: {str(e)}"
        await ctx.warning(error_msg)
        return {"success": False, "message": error_msg, "rule_name": name}
    except Exception as e:
        error_msg = f"Unexpected error uninstalling rule '{name}': {str(e)}"
        await ctx.error(error_msg)
        return {"success": False, "message": error_msg, "rule_name": name}


if __name__ == "__main__":
    try:
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8080)
    except KeyboardInterrupt:
        print("\nShutdown completed gracefully.")
