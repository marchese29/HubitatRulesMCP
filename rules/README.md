# Hubitat Rules Engine

A powerful, flexible rules engine for Hubitat home automation that supports both condition-based and scheduled rule execution.

## Overview

The rules engine allows you to create automation rules using Python code that gets executed when certain conditions are met or at scheduled times. The system provides two types of rules:

- **Condition-Based Rules**: Execute when device conditions become true (e.g., "when motion is detected")
- **Scheduled Rules**: Execute at specific times determined by timer functions (e.g., "every day at 6 AM")

## Architecture

- **RuleHandler**: Main interface for installing/uninstalling rules
- **RuleEngine**: Core engine that monitors conditions and manages rule execution
- **RuleUtilities**: Helper utilities available in rule code for device control and condition checking
- **Conditions**: Various condition types for device attribute monitoring and boolean logic

## Quick Start

### Condition-Based Rule Example

```python
from rules.handler import RuleHandler

# Create rule handler
handler = RuleHandler(rule_engine, hubitat_client)

# Trigger: Motion sensor detects motion
trigger_code = """
async def get_trigger_condition(utils):
    motion_sensor = utils.device(123)
    await motion_sensor.load()
    return motion_sensor.motion == "active"
"""

# Action: Turn on lights for 5 minutes
rule_code = """
async def rule_action(utils):
    lights = utils.device(456)
    await lights.load()
    await lights.turn_on()
    await utils.wait(timedelta(minutes=5))
    await lights.turn_off()
"""

# Install the rule
await handler.install_rule("motion_lights", trigger_code, rule_code)
```

### Scheduled Rule Example

```python
# Timer: Every day at 6:00 AM
timer_code = """
async def get_next_time():
    now = datetime.now()
    next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run
"""

# Action: Turn on morning lights
rule_code = """
async def rule_action(utils):
    lights = utils.device(789)
    await lights.load()
    await lights.turn_on()
"""

# Install the scheduled rule
await handler.install_scheduled_rule("morning_lights", timer_code, rule_code)
```

## Rule Types

### Condition-Based Rules

Condition-based rules monitor device states and execute when specified conditions become true.

#### Trigger Code Requirements:
- Must define a `get_trigger_condition(utils)` function
- Function must return an `AbstractCondition` object
- Has access to `utils` (RuleUtilities), `timedelta`, and `datetime`
- Uses device attribute comparisons and boolean logic

#### Available Condition Types:

**Device Attribute Conditions:**
```python
# Single device attribute comparison
device = utils.device(123)
await device.load()
device.switch == "on"
device.temperature > 75
device.battery < 20
```

**Boolean Logic:**
```python
# Multiple conditions with AND logic
device1 = utils.device(123)
device2 = utils.device(124)
await device1.load()
await device2.load()

utils.all_of(
    device1.switch == "on",
    device2.temperature > 70
)

# Multiple conditions with OR logic  
utils.any_of(
    device1.motion == "active",
    device2.contact == "open"
)

# Negation
utils.is_not(device1.switch == "on")
```

**Attribute Change Detection:**
```python
# Trigger when any change occurs to an attribute
device = utils.device(123)
await device.load()
utils.on_change(device.temperature)
```

### Scheduled Rules

Scheduled rules execute at times determined by a timer provider function.

#### Timer Code Requirements:
- Must define an async `get_next_time()` function
- Function takes no parameters and returns a `datetime` object
- Has access to `datetime`, `timedelta`, and `utils`

#### Scheduling Patterns:

**Daily Schedule:**
```python
async def get_next_time():
    now = datetime.now()
    # Run at 6:30 AM every day
    next_run = now.replace(hour=6, minute=30, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run
```

**Weekly Schedule:**
```python
async def get_next_time():
    now = datetime.now()
    # Run every Monday at 9 AM
    days_until_monday = (7 - now.weekday()) % 7
    if days_until_monday == 0 and now.hour >= 9:
        days_until_monday = 7
    next_run = now.replace(hour=9, minute=0, second=0, microsecond=0)
    next_run += timedelta(days=days_until_monday)
    return next_run
```

**Custom Interval:**
```python
async def get_next_time():
    # Run every 30 minutes
    now = datetime.now()
    return now + timedelta(minutes=30)
```

## Rule Actions

All rules must define a `rule_action` async function that accepts a single `utils` parameter.

### Available Utilities

The `utils` parameter provides access to:

**Device Control:**
```python
async def rule_action(utils):
    # Get device and load its capabilities
    device = utils.device(123)
    await device.load()
    
    # Call device commands
    await device.turn_on()
    await device.turn_off()
    await device.set_level(50)
    await device.set_color_temperature(3000)
```

**Scene Control:**
```python
async def rule_action(utils):
    # Get scene by name
    evening_scene = utils.scene("evening_lights")
    
    # Check if scene is currently active
    if not await evening_scene.is_set:
        # Apply the scene
        response = await evening_scene.enable()
        
        if response.success:
            print("Scene applied successfully")
        else:
            print(f"Scene failed: {response.message}")
```

**Timing and Delays:**
```python
async def rule_action(utils):
    # Wait for a specific duration
    await utils.wait(timedelta(minutes=5))
    await utils.wait(timedelta(seconds=30))
    
    # Wait until a specific time
    from datetime import time
    await utils.wait_until(time(6, 30))  # Wait until 6:30 AM
```

**Conditional Logic:**
```python
async def rule_action(utils):
    # Check conditions dynamically
    sensor = utils.device(123)
    await sensor.load()
    
    if await utils.check(sensor.temperature > 75):
        # Turn on AC
        ac = utils.device(456)
        await ac.load()
        await ac.turn_on()
```

**Wait for Conditions:**
```python
async def rule_action(utils):
    # Wait for a condition to become true
    door = utils.device(123)
    await door.load()
    
    # Wait up to 5 minutes for door to close
    door_closed = await utils.wait_for(
        door.contact == "closed",
        timeout=timedelta(minutes=5)
    )
    
    if door_closed:
        # Arm security system
        await utils.device(789).arm_away()
```

**Wait for Attribute Changes:**
```python
async def rule_action(utils):
    # Wait for temperature to change from current value
    sensor = utils.device(123)
    await sensor.load()
    
    changed = await utils.wait_for_change(
        sensor.temperature,
        timeout=timedelta(minutes=10)
    )
    
    if changed:
        print("Temperature changed!")
```

**Direct Value Access for Custom Logic:**
```python
async def rule_action(utils):
    # Store baseline value when rule starts
    sensor = utils.device(123)
    await sensor.load()
    baseline_temp = await sensor.temperature.fetch()
    
    # Later, check if temperature has changed from baseline
    await utils.wait(timedelta(minutes=30))
    current_temp = await sensor.temperature.fetch()
    
    if abs(current_temp - baseline_temp) > 5:
        # Temperature changed by more than 5 degrees
        print(f"Significant temperature change: {baseline_temp} -> {current_temp}")
```

## Code Examples

### Complex Trigger Examples

**Temperature Range with Time Restriction:**
```python
async def get_trigger_condition(utils):
    # Only trigger between 6 PM and 11 PM when temp drops below 68
    from datetime import datetime
    now = datetime.now()
    time_ok = 18 <= now.hour < 23

    temp_sensor = utils.device(123)
    await temp_sensor.load()

    if time_ok:
        return temp_sensor.temperature < 68
    else:
        # Return a condition that will never be true during non-allowed hours
        return temp_sensor.temperature < -999
```

**Multiple Device Coordination:**
```python
async def get_trigger_condition(utils):
    # Trigger when all lights are off and no motion detected
    light1 = utils.device(101)
    light2 = utils.device(102)
    motion = utils.device(103)

    await light1.load()
    await light2.load()
    await motion.load()

    return utils.all_of(
        light1.switch == "off",
        light2.switch == "off",
        motion.motion == "inactive"
    )
```

### Advanced Timer Examples

**Sunset-Based Schedule (Approximation):**
```python
async def get_next_time():
    import math
    now = datetime.now()
    
    # Simple sunset approximation (6 PM +/- 2 hours seasonally)
    day_of_year = now.timetuple().tm_yday
    sunset_offset = math.sin(2 * math.pi * (day_of_year - 81) / 365) * 2
    sunset_hour = 18 + sunset_offset
    
    next_run = now.replace(
        hour=int(sunset_hour), 
        minute=int((sunset_hour % 1) * 60),
        second=0, 
        microsecond=0
    )
    
    if next_run <= now:
        next_run += timedelta(days=1)
    
    return next_run
```

**Business Days Only:**
```python
async def get_next_time():
    now = datetime.now()
    next_run = now.replace(hour=7, minute=0, second=0, microsecond=0)
    
    # If past 7 AM today, start with tomorrow
    if next_run <= now:
        next_run += timedelta(days=1)
    
    # Skip weekends (Monday=0, Sunday=6)
    while next_run.weekday() >= 5:  # Saturday or Sunday
        next_run += timedelta(days=1)
    
    return next_run
```

### Complex Rule Actions

**Sequential Device Control:**
```python
async def rule_action(utils):
    # Turn on devices in sequence with delays
    devices = [101, 102, 103, 104]
    
    for device_id in devices:
        device = utils.device(device_id)
        await device.load()
        await device.turn_on()
        await utils.wait(timedelta(seconds=2))
```

**Conditional Automation:**
```python
async def rule_action(utils):
    # Check time of day and adjust behavior
    from datetime import datetime
    now = datetime.now()
    
    lights = utils.device(123)
    await lights.load()
    
    if 6 <= now.hour < 22:  # Daytime
        await lights.set_level(75)
    else:  # Nighttime
        await lights.set_level(25)
    
    await lights.turn_on()
```

## API Reference

### RuleHandler

```python
class RuleHandler:
    async def install_rule(name: str, trigger_provider_code: str, rule_code: str)
    async def install_scheduled_rule(name: str, timer_provider_code: str, rule_code: str)
    async def uninstall_rule(rule_name: str)
    def get_active_rules() -> list[str]
```

### RuleUtilities

```python
class RuleUtilities:
    def device(device_id: int) -> Device
    def all_of(*conditions) -> AbstractCondition
    def any_of(*conditions) -> AbstractCondition
    def is_not(condition) -> AbstractCondition
    def on_change(attr) -> AbstractCondition
    
    async def wait(for_time: timedelta)
    async def wait_for(condition, timeout=None, for_duration=None) -> bool
    async def wait_for_change(attr, timeout=None) -> bool
    async def wait_until(time)
    async def check(condition) -> bool
```

### Device

```python
class Device:
    async def load() -> Device
    # Dynamic attributes and commands based on device capabilities
    # Examples: .switch, .level, .temperature, .turn_on(), .set_level(), etc.
```

### Attribute

```python
class Attribute:
    async def fetch() -> any
    # Comparison operators return AbstractCondition objects
    # Examples: attr == "value", attr > 75, attr != "off"
```

### Available in Code Namespace

**Trigger/Timer Code:**
- `utils`: RuleUtilities instance
- `timedelta`: For time durations
- `datetime`: For timer code only

**Rule Action Code:**
- `utils`: RuleUtilities instance (passed as parameter)

## Security and Limitations

⚠️ **Security Warning**: The current implementation uses `eval()` and `exec()` without sandboxing. This means rule code has access to the full Python environment. Only install rules from trusted sources.

### Current Limitations:
- No code sandboxing or security restrictions
- No resource limits on rule execution
- Limited error handling in rule code
- No persistent rule storage (rules are lost on restart)

### Best Practices:
- Always use `await device.load()` before accessing device attributes
- Handle device command failures gracefully
- Use timeouts for condition waits to avoid infinite blocking
- Keep rule actions simple and focused
- Test rule code thoroughly before installation

## Troubleshooting

**Rule Not Triggering:**
- Verify trigger code returns an AbstractCondition
- Check that device IDs are correct
- Ensure device attributes exist and are spelled correctly

**Scheduled Rule Not Running:**
- Verify timer function returns future datetime objects
- Check that `get_next_time()` function is defined correctly
- Ensure datetime calculations account for edge cases

**Rule Action Errors:**
- Always `await device.load()` before using device methods
- Check that device commands exist for the device type
- Use try/catch blocks for error handling in complex rule actions
