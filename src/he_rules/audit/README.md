# Audit Module

## Philosophy

The audit module implements a **non-blocking, context-aware audit logging system** designed with the following core principles:

### 1. **Never Impact Main Application Performance**
- Audit logging uses an **async background queue** to avoid blocking rule execution
- Failed audit operations are **silently handled** and never crash the main application
- The audit service can be **completely disabled** without affecting functionality

### 2. **Rich Context Tracking**
- Uses Python's `ContextVar` to automatically track **hierarchical context** across function calls
- Context flows naturally through the call stack (rule → condition → device command)
- Provides **automatic timing** and **success/failure tracking**

### 3. **Structured Event Categorization**
- Events are categorized using **strict enums** for consistency
- **Event types** provide high-level categorization (rule_lifecycle, device_control, etc.)
- **Event subtypes** provide specific detail (rule_created, device_command, etc.)

### 4. **Developer-Friendly Design**
- **Decorator-based** - just add `@audit_event()` to functions you want to track
- **Zero-configuration** - works out of the box with sensible defaults
- **Graceful degradation** - works even if audit service isn't initialized

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   @audit_event  │───▶│   AuditService   │───▶│   SQLite DB     │
│   (Decorator)   │    │   (Async Queue)  │    │   (Background)  │
└─────────────────┘    └──────────────────┘    └─────────────────┘
         │                       │
         ▼                       ▼
┌─────────────────┐    ┌──────────────────┐
│  ContextVar     │    │  Background      │
│  (Call Stack)   │    │  Writer Task     │
└─────────────────┘    └──────────────────┘
```

## Components

### `service.py` - Core Audit Service
- **AuditService**: Async service with background writer task
- **Global instance**: Managed in main.py for application lifecycle
- **Queue-based**: Non-blocking audit log queuing

### `decorators.py` - Developer Interface
- **@audit_event()**: Primary decorator for automatic audit logging
- **Context management**: Hierarchical context tracking using ContextVar
- **Timing**: Automatic execution time measurement
- **Error handling**: Logs both success and failure cases

### `models/audit.py` - Data Model
- **EventType**: High-level event categories
- **EventSubtype**: Specific event types
- **AuditLog**: SQLModel for database storage with proper indexing

## Usage

### Basic Decorator Usage

```python
from audit.decorators import audit_event
from models.audit import EventType, EventSubtype

@audit_event(
    EventType.DEVICE_CONTROL, 
    EventSubtype.DEVICE_COMMAND,
    device_id="device_id",  # Map context_key to function argument
    rule_name="rule_name"
)
async def send_device_command(device_id: int, command: str, rule_name: str):
    # Your function implementation
    pass
```

### Direct Logging

```python
from audit.decorators import audit_simple_event
from models.audit import EventType, EventSubtype

# Async context
await audit_simple_event(
    EventType.RULE_LIFECYCLE,
    EventSubtype.RULE_CREATED,
    rule_name="my_rule",
    custom_data="additional info"
)

# Sync context
audit_simple_event_sync(
    EventType.SCENE_LIFECYCLE,
    EventSubtype.SCENE_APPLIED,
    scene_name="evening_mode"
)
```

### Context Inheritance

Context automatically flows through function calls:

```python
@audit_event(EventType.RULE_LIFECYCLE, EventSubtype.RULE_ACTION_STARTED, rule_name="rule")
async def execute_rule(rule: str):
    await evaluate_condition()  # Inherits rule_name context
    
@audit_event(EventType.EXECUTION_LIFECYCLE, EventSubtype.CONDITION_EVALUATED)
async def evaluate_condition():
    # This function automatically has access to rule_name from parent context
    pass
```

## Event Types & Subtypes

### RULE_LIFECYCLE
- `RULE_CREATED`: New rule registered
- `RULE_LOADED`: Rule loaded into engine
- `RULE_DELETED`: Rule removed
- `RULE_ACTION_STARTED`: Rule execution began
- `RULE_ACTION_COMPLETED`: Rule execution finished successfully
- `RULE_ACTION_FAILED`: Rule execution failed

### EXECUTION_LIFECYCLE
- `CONDITION_EVALUATED`: Rule condition checked
- `TRIGGER_FIRED`: Rule trigger activated

### DEVICE_CONTROL
- `DEVICE_COMMAND`: Command sent to device

### SCENE_LIFECYCLE
- `SCENE_CREATED`: New scene defined
- `SCENE_DELETED`: Scene removed
- `SCENE_APPLIED`: Scene activated

## Database Schema

```sql
CREATE TABLE auditlog (
    id INTEGER PRIMARY KEY,
    timestamp DATETIME,
    event_type VARCHAR,       -- EventType enum
    event_subtype VARCHAR,    -- EventSubtype enum
    rule_name VARCHAR,        -- Indexed for filtering
    scene_name VARCHAR,       -- Indexed for filtering  
    condition_id VARCHAR,     -- Indexed for filtering
    device_id INTEGER,        -- Indexed for filtering
    success BOOLEAN,          -- Execution result
    error_message TEXT,       -- Error details if failed
    execution_time_ms FLOAT,  -- Performance timing
    context_data TEXT         -- Additional JSON data
);
```

## Initialization

The audit service is initialized in `main.py`:

```python
from audit.service import AuditService, audit_service

# Initialize global audit service
audit_service = AuditService(db_engine)
audit_service.start()

# Graceful shutdown
await audit_service.stop()
```

## Performance Characteristics

- **Memory**: Minimal - uses async queue, not persistent buffers
- **CPU**: Negligible - background writes only
- **I/O**: Non-blocking - never blocks main thread
- **Storage**: Efficient - indexed SQLite with JSON for flexible data

## Error Handling

The audit system is designed to **never fail the main application**:

- Missing audit service → Functions work normally
- Database write failures → Logged but ignored
- Queue full → Entries dropped silently
- Context errors → Gracefully handled

## Future Considerations

This audit system is designed to support the upcoming "flag-enabled audit tooling" TODO item, allowing selective audit logging based on configuration flags while maintaining the same simple decorator interface.
