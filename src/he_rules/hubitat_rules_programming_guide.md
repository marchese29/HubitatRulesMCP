# Hubitat Rules Engine Programming Guide

## Overview

The Hubitat Rules Engine is a powerful automation system that allows you to create sophisticated home automation rules using Python code. This guide focuses on the rules engine architecture, programming patterns, and API for writing effective automation rules.

## Architecture

The rules engine supports two fundamental rule types:

- **Condition-Based Rules**: Execute when device conditions become true (trigger-based)
- **Scheduled Rules**: Execute at specific times determined by timer functions

### Core Components

- **RuleHandler**: Main interface for installing/uninstalling rules
- **RuleEngine**: Core engine monitoring conditions and managing execution  
- **RuleUtilities**: Helper utilities available in rule code
- **Device**: Interface for interacting with Hubitat devices
- **Conditions**: Various condition types for monitoring and logic

## Rule Installation

Rules are installed using the MCP server's `install_rule` tool:

```python
# Condition-based rule
{
    "name": "rule_name",
    "rule_type": "condition", 
    "trigger_code": "async def get_trigger_condition(utils): ...",
    "action_code": "async def rule_action(utils): ..."
}

# Scheduled rule
{
    "name": "rule_name",
    "rule_type": "scheduled",
    "trigger_code": "async def get_next_time(): ...", 
    "action_code": "async def rule_action(utils): ..."
}
```

## Condition-Based Rules

### Trigger Code Structure

Trigger code must define an async `get_trigger_condition(utils)` function that returns an `AbstractCondition` object.

**Available in trigger code namespace:**
- `utils`: RuleUtilities instance
- `timedelta`: For time duration calculations  
- `datetime`: For date/time operations

**Basic Pattern:**
```python
async def get_trigger_condition(utils):
    device = utils.device(device_id)
    await device.load()
    return device.attribute_name == "value"
```

### Device Interaction Patterns

**Loading and Accessing Devices:**
```python
async def get_trigger_condition(utils):
    # Get device reference and load its capabilities
    device = utils.device(123)
    await device.load()  # Required before accessing attributes/commands
    
    # Access attributes (defined by Hubitat device capabilities)
    return device.some_attribute == "expected_value"
```

**Attribute Comparisons:**
```python
async def get_trigger_condition(utils):
    sensor = utils.device(123)
    await sensor.load()
    
    # All comparison operators return AbstractCondition objects
    return sensor.temperature > 75        # Greater than
    # return sensor.battery <= 20         # Less than or equal  
    # return sensor.switch == "on"        # Equality
    # return sensor.contact != "closed"   # Inequality
```

**Device-to-Device Comparisons:**
```python
async def get_trigger_condition(utils):
    device1 = utils.device(123)
    device2 = utils.device(124)
    await device1.load()
    await device2.load()
    
    # Compare attributes between devices
    return device1.temperature > device2.temperature
```

### Boolean Logic Conditions

**AND Logic (all conditions must be true):**
```python
async def get_trigger_condition(utils):
    device1 = utils.device(123)
    device2 = utils.device(124)
    await device1.load()
    await device2.load()
    
    return utils.all_of(
        device1.motion == "active",
        device2.illuminance < 50
    )
```

**OR Logic (any condition must be true):**
```python
async def get_trigger_condition(utils):
    door = utils.device(123)
    window = utils.device(124)
    await door.load()
    await window.load()
    
    return utils.any_of(
        door.contact == "open",
        window.contact == "open"
    )
```

**Negation Logic:**
```python
async def get_trigger_condition(utils):
    presence = utils.device(123)
    await presence.load()
    
    return utils.is_not(presence.presence == "present")
```

**Complex Combinations:**
```python
async def get_trigger_condition(utils):
    motion = utils.device(123)
    door = utils.device(124)  
    mode = utils.device(125)
    await motion.load()
    await door.load()
    await mode.load()
    
    # Motion AND (door open OR night mode)
    return utils.all_of(
        motion.motion == "active",
        utils.any_of(
            door.contact == "open",
            mode.mode == "Night"
        )
    )
```

### Change Detection

**Attribute Change Triggers:**
```python
async def get_trigger_condition(utils):
    device = utils.device(123)
    await device.load()
    
    # Trigger whenever attribute changes from any previous value
    return utils.on_change(device.temperature)
```

### Scene Trigger Patterns

**Scene Becomes Set:**
```python
async def get_trigger_condition(utils):
    scene = utils.scene("evening_lights")
    
    # Trigger when scene becomes active (all device states match)
    return await scene.on_set()
```

**Scene State Changes:**
```python
async def get_trigger_condition(utils):
    scene = utils.scene("morning_routine")
    
    # Trigger on any scene state change (set ↔ not set)
    return await scene.on_change()
```

**Complex Scene Logic:**
```python
async def get_trigger_condition(utils):
    evening_scene = utils.scene("evening_lights")
    motion = utils.device(123)
    await motion.load()
    
    # Trigger when evening scene becomes set AND motion detected
    return utils.all_of(
        await evening_scene.on_set(),
        motion.motion == "active"
    )
```

## Scheduled Rules

### Timer Code Structure

Timer code must define an async `get_next_time()` function that returns a `datetime` object.

**Available in timer code namespace:**
- `datetime`: For date/time operations
- `timedelta`: For time calculations
- `utils`: RuleUtilities instance (if needed for dynamic scheduling)

### Scheduling Patterns

**Daily Schedule:**
```python
async def get_next_time():
    from datetime import datetime, timedelta
    now = datetime.now()
    next_run = now.replace(hour=6, minute=30, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run
```

**Weekly Schedule:**
```python
async def get_next_time():
    from datetime import datetime, timedelta
    now = datetime.now()
    
    # Run every Monday at 9:00 AM (Monday = 0)
    days_ahead = (0 - now.weekday()) % 7
    if days_ahead == 0:  # Today is Monday
        next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if next_run <= now:
            days_ahead = 7
    
    next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
    return next_run + timedelta(days=days_ahead)
```

**Custom Intervals:**
```python
async def get_next_time():
    from datetime import datetime, timedelta
    # Run every 30 minutes
    return datetime.now() + timedelta(minutes=30)
```

**Conditional Scheduling:**
```python
async def get_next_time():
    from datetime import datetime, timedelta
    now = datetime.now()
    
    # More frequent during day, less at night
    if 6 <= now.hour < 22:
        return now + timedelta(minutes=15) 
    else:
        return now + timedelta(hours=2)
```

## Rule Actions

All rules must define an async `rule_action(utils)` function that receives a `RuleUtilities` instance.

### Device Control Patterns

**Basic Device Commands:**
```python
async def rule_action(utils):
    device = utils.device(123)
    await device.load()  # Always load before use
    
    # Execute commands (available commands defined by Hubitat capabilities)
    await device.on()          # Turn on
    await device.off()         # Turn off
    await device.set_level(75) # Set dimmer level
    
    # Commands with multiple parameters
    await device.set_color(240, 100)  # Hue, saturation
```

**Reading Current Values:**
```python
async def rule_action(utils):
    sensor = utils.device(123)
    await sensor.load()
    
    # Get current attribute value directly
    current_temp = await sensor.temperature.fetch()
    current_switch_state = await sensor.switch.fetch()
    
    # Use values in logic
    if current_temp > 75:
        hvac = utils.device(456)
        await hvac.load()
        await hvac.cool()
```

**Multiple Device Control:**
```python
async def rule_action(utils):
    device_ids = [101, 102, 103]
    
    for device_id in device_ids:
        device = utils.device(device_id)
        await device.load()
        await device.on()
```

### Scene Control Patterns

**Basic Scene Operations:**
```python
async def rule_action(utils):
    scene = utils.scene("evening_lights")
    
    # Check if scene is currently active
    if not await scene.is_set:
        # Apply the scene
        response = await scene.enable()
        
        if response.success:
            print(f"Scene applied successfully")
        else:
            print(f"Scene failed with {len(response.failed_commands)} errors")
```

**Conditional Scene Management:**
```python
async def rule_action(utils):
    # Check current scene status before acting
    morning_scene = utils.scene("morning_routine")
    evening_scene = utils.scene("evening_lights")
    
    if await morning_scene.is_set:
        # Switch from morning to evening
        await evening_scene.enable()
    elif not await evening_scene.is_set:
        # No scene active, enable evening
        await evening_scene.enable()
```

**Scene-Based Automation:**
```python
async def rule_action(utils):
    from datetime import datetime
    now = datetime.now()
    
    if 6 <= now.hour < 12:
        scene = utils.scene("morning_routine")
    elif 12 <= now.hour < 18:
        scene = utils.scene("day_lights")
    else:
        scene = utils.scene("evening_lights")
    
    if not await scene.is_set:
        await scene.enable()
```

### Timing Operations

**Simple Delays:**
```python
async def rule_action(utils):
    device = utils.device(123)
    await device.load()
    
    await device.on()
    await utils.wait(timedelta(minutes=5))  # Wait 5 minutes
    await device.off()
```

**Wait Until Specific Time:**
```python
async def rule_action(utils):
    from datetime import time
    
    # Wait until 6:30 AM
    await utils.wait_until(time(6, 30))
    
    device = utils.device(123)
    await device.load()
    await device.on()
```

### Waiting for Conditions

**Wait for Device State:**
```python
async def rule_action(utils):
    door = utils.device(123)
    await door.load()
    
    # Wait up to 5 minutes for door to close
    door_closed = await utils.wait_for(
        door.contact == "closed",
        timeout=timedelta(minutes=5)
    )
    
    if door_closed:
        # Door closed successfully
        security = utils.device(456)
        await security.load()
        await security.arm_away()
    else:
        # Timeout - door still open
        pass  # Handle timeout case
```

**Wait for Condition Duration:**
```python
async def rule_action(utils):
    motion = utils.device(123)
    await motion.load()
    
    # Wait for motion to be inactive for 10 minutes (with 15 min timeout)
    no_motion = await utils.wait_for(
        motion.motion == "inactive",
        timeout=timedelta(minutes=15),
        for_duration=timedelta(minutes=10)
    )
    
    if no_motion:
        lights = utils.device(456)
        await lights.load()
        await lights.off()
```

**Wait for Attribute Changes:**
```python
async def rule_action(utils):
    sensor = utils.device(123)
    await sensor.load()
    
    # Wait for temperature to change (any change)
    temp_changed = await utils.wait_for_change(
        sensor.temperature,
        timeout=timedelta(minutes=30)
    )
    
    if temp_changed:
        new_temp = await sensor.temperature.fetch()
        # React to temperature change
```

**Check Conditions Immediately:**
```python
async def rule_action(utils):
    sensor = utils.device(123)
    await sensor.load()
    
    # Check condition right now (non-blocking)
    is_hot = await utils.check(sensor.temperature > 75)
    
    if is_hot:
        fan = utils.device(456)
        await fan.load()
        await fan.on()
```

### Conditional Logic in Actions

**Time-Based Behavior:**
```python
async def rule_action(utils):
    from datetime import datetime
    now = datetime.now()
    
    device = utils.device(123)
    await device.load()
    
    if 6 <= now.hour < 22:  # Daytime
        await device.set_level(100)
    else:  # Nighttime
        await device.set_level(25)
    
    await device.on()
```

## API Reference

### RuleUtilities Methods

**Device Access:**
- `device(device_id: int) -> Device` - Get device interface

**Scene Access:**
- `scene(scene_name: str) -> Scene` - Get scene interface

**Condition Builders:**
- `all_of(*conditions) -> AbstractCondition` - AND logic
- `any_of(*conditions) -> AbstractCondition` - OR logic
- `is_not(condition) -> AbstractCondition` - NOT logic  
- `on_change(attr) -> AbstractCondition` - Change detection for triggers

**Timing:**
- `wait(for_time: timedelta)` - Sleep for duration
- `wait_until(time)` - Wait until specific time
- `wait_for(condition, timeout=None, for_duration=None) -> bool` - Wait for condition
- `wait_for_change(attr, timeout=None) -> bool` - Wait for attribute change
- `check(condition) -> bool` - Evaluate condition immediately

### Device Interface

**Loading:**
- `load() -> Device` - Load device capabilities (required before use)

**Dynamic Attributes and Commands:**
Device attributes and commands are determined by Hubitat device capabilities. The rules engine provides a dynamic interface - after loading a device, you can access any attribute or command supported by that device type in Hubitat.

**Common Attribute Patterns:**
- Attributes return `Attribute` objects that support comparisons
- Use `await attribute.fetch()` to get current value directly
- Comparisons (`==`, `!=`, `>`, `<`, etc.) return `AbstractCondition` objects

**Common Command Patterns:**
- Commands are async functions: `await device.command_name(args)`
- Available commands depend on device capabilities in Hubitat
- Common commands: `on()`, `off()`, `set_level(value)`, `refresh()`

### Attribute Interface

**Value Access:**
- `fetch() -> any` - Get current attribute value directly

**Comparisons (return AbstractCondition):**
- `== value`, `!= value` - Equality/inequality
- `> value`, `>= value`, `< value`, `<= value` - Numeric comparisons

### Scene Interface

**Scene Status:**
- `is_set -> bool` - Check if scene is currently active (async property)

**Scene Control:**
- `enable() -> SceneSetResponse` - Apply/activate the scene

**Usage Pattern:**
```python
scene = utils.scene("scene_name")
if not await scene.is_set:
    response = await scene.enable()
    if response.success:
        print("Scene applied successfully")
    else:
        print(f"Scene failed: {response.message}")
```

## Example: Complete Motion Light Rule

**Condition-Based Rule:**
```python
# Trigger: Motion detected AND low light
async def get_trigger_condition(utils):
    motion = utils.device(123)
    lux_sensor = utils.device(124)
    await motion.load()
    await lux_sensor.load()
    
    return utils.all_of(
        motion.motion == "active",
        lux_sensor.illuminance < 50
    )

# Action: Turn on light, wait for no motion, then turn off
async def rule_action(utils):
    light = utils.device(456)
    motion = utils.device(123)
    await light.load()
    await motion.load()
    
    # Turn on light
    await light.on()
    
    # Wait for motion to stop
    await utils.wait_for(
        motion.motion == "inactive",
        timeout=timedelta(minutes=30)
    )
    
    # Wait additional 5 minutes then turn off
    await utils.wait(timedelta(minutes=5))
    await light.off()
```

## Best Practices

### Device Loading
- Always call `await device.load()` before accessing attributes or commands
- Load devices once at the beginning of functions when possible
- Handle loading failures gracefully for robust rules

### Error Handling  
- Use try/catch blocks for device operations that might fail
- Don't let one device failure break entire rule execution
- Implement timeouts for all waiting operations

### Performance
- Minimize API calls by caching values with `fetch()` when appropriate
- Use timeouts for condition waits to prevent infinite blocking
- Keep trigger conditions simple for fast evaluation

### Rule Design
- Keep rule actions focused and avoid overly complex logic
- Use descriptive rule names that indicate purpose
- Test edge cases like device unavailability or timeouts

## Troubleshooting

### Rule Not Triggering
- Verify trigger code returns `AbstractCondition` object
- Check device IDs exist and are correct
- Ensure attribute names match device capabilities
- Test conditions using `utils.check()` for debugging

### Scheduled Rule Not Running
- Verify `get_next_time()` returns future `datetime` objects
- Check timezone handling for specific times
- Ensure datetime calculations handle edge cases properly

### Rule Action Errors
- Always `await device.load()` before using device methods  
- Verify device supports the commands you're calling
- Check attribute names are spelled correctly
- Use timeouts for condition waits to avoid infinite blocking

### Device Communication Issues
- Confirm device IDs match Hubitat device IDs exactly
- Verify devices are online and responding in Hubitat
- Check network connectivity between MCP server and Hubitat hub

This guide provides the foundation for creating automation rules using the Hubitat Rules Engine. The actual device attributes and commands available depend on your specific Hubitat devices and their capabilities.
