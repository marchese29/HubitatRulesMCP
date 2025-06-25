# Hubitat Rules MCP Server

A powerful Model Context Protocol (MCP) server that provides automation rule management and scene control for Hubitat home automation systems. This server enables you to create sophisticated Python-based automation rules and manage device scenes through a standardized MCP interface.

## Features

- **🤖 Intelligent Rule Engine**: Create condition-based and scheduled automation rules using Python
- **🎬 Scene Management**: Define and control coordinated device states and scenes
- **⚡ Real-time Processing**: Webhook endpoint for immediate device event processing
- **🔄 Persistent Storage**: SQLite database for rule and scene persistence across restarts
- **📅 Flexible Scheduling**: Timer-based automation with cron-like capabilities
- **🔌 MCP Integration**: Standard Model Context Protocol interface for AI assistant integration
- **📚 Comprehensive Documentation**: Built-in programming guide and examples
- **📊 Audit & Analytics** *(Optional)*: Advanced audit logging and AI-powered rule execution analysis

## Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   MCP Client    │◄──►│  FastMCP Server  │◄──►│  Hubitat Hub    │
│  (AI Assistant) │    │                  │    │                 │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                              │
                              ▼
                       ┌──────────────────┐
                       │   Rules Engine   │
                       │                  │
                       │ ┌──────────────┐ │
                       │ │ Condition    │ │
                       │ │ Rules        │ │
                       │ └──────────────┘ │
                       │ ┌──────────────┐ │
                       │ │ Scheduled    │ │
                       │ │ Rules        │ │
                       │ └──────────────┘ │
                       │ ┌──────────────┐ │
                       │ │ Scene        │ │
                       │ │ Manager      │ │
                       │ └──────────────┘ │
                       └──────────────────┘
                              │
                              ▼
                       ┌──────────────────┐
                       │ SQLite Database  │
                       │ (Rules & Scenes) │
                       └──────────────────┘
```

## Installation

### Prerequisites

- Python 3.12 or higher
- [uv](https://docs.astral.sh/uv/) package manager
- Hubitat Elevation hub with Maker API enabled

### Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd HubitatRulesMCP
   ```

2. **Install dependencies**:
   ```bash
   uv sync
   ```

3. **Configure environment variables**:
   Create a `.env` file or set the following environment variables:
   ```bash
   export HE_ADDRESS="192.168.1.100"        # Your Hubitat hub IP address
   export HE_APP_ID="123"                   # Maker API app ID from Hubitat
   export HE_ACCESS_TOKEN="your-token-here" # Access token from Maker API
   ```

4. **Start the server**:
   ```bash
   # Standard mode
   uv run fastmcp run main.py
   
   # With audit tools enabled
   uv run python main.py --audit-tools
   # or
   uv run python main.py -a
   ```

### Hubitat Configuration

1. **Enable Maker API**:
   - Go to Apps → Add Built-In App → Maker API
   - Select devices you want to control
   - Note the App ID and generate an access token

2. **Configure webhook (optional for real-time events)**:
   - In Maker API settings, set webhook URL to: `http://your-server:8080/he_event`
   - This enables real-time device event processing for faster rule triggers

## Rule Programming

### Condition-Based Rules

Rules that execute when device conditions become true:

```python
# Trigger code - must return AbstractCondition
async def get_trigger_condition(utils):
    motion = utils.device(123)
    await motion.load()
    return motion.motion == "active"

# Action code - executed when trigger fires
async def rule_action(utils):
    lights = utils.device(456)
    await lights.load()
    await lights.on()
    await utils.wait(timedelta(minutes=5))
    await lights.off()
```

### Scheduled Rules

Rules that execute at specific times:

```python
# Timer code - must return datetime
async def get_next_time():
    now = datetime.now()
    next_run = now.replace(hour=6, minute=0, second=0, microsecond=0)
    if next_run <= now:
        next_run += timedelta(days=1)
    return next_run

# Action code - executed at scheduled time
async def rule_action(utils):
    scene = utils.scene("morning_routine")
    await scene.enable()
```

### Available Utilities

The `utils` object provides:

- **Device Control**: `utils.device(id)` - Access device attributes and commands
- **Scene Control**: `utils.scene(name)` - Control and check scene status
- **Conditions**: `utils.all_of()`, `utils.any_of()`, `utils.is_not()` - Boolean logic
- **Timing**: `utils.wait()`, `utils.wait_until()`, `utils.wait_for()` - Delays and waits
- **Monitoring**: `utils.on_change()`, `utils.check()` - Attribute monitoring

## Audit Tools (Optional)

The server includes optional audit tools that provide advanced monitoring and analysis capabilities for your automation rules. These tools are only available when the server is started with the `--audit-tools` or `-a` flag.

### Enabling Audit Tools

```bash
# Start server with audit tools enabled
uv run python main.py --audit-tools
# or
uv run python main.py -a
```

### Available Audit Tools

#### `query_audit_logs`
Query and filter audit logs with pagination support:

```python
# Query all audit logs
logs = await query_audit_logs()

# Filter by specific rule
logs = await query_audit_logs(rule_name="motion_lights")

# Filter by event type and date range
logs = await query_audit_logs(
    event_type="execution_lifecycle",
    start_date="2024-01-01T00:00:00",
    end_date="2024-01-31T23:59:59",
    page=1,
    page_size=100
)
```

#### `get_rule_summary`
AI-powered analysis of rule execution patterns and performance:

```python
# Analyze all rules from the last 7 days
summary = await get_rule_summary()

# Analyze specific rule with custom date range
summary = await get_rule_summary(
    rule_name="motion_lights",
    start_date="2024-01-01T00:00:00",
    end_date="2024-01-31T23:59:59"
)

# Focus only on failed executions
summary = await get_rule_summary(
    include_successful=False,
    include_failed=True
)
```

### What Gets Audited

The audit system automatically logs:

- **Rule Lifecycle Events**: Installation, uninstallation, loading
- **Rule Execution**: Success/failure, execution time, error details
- **Condition Evaluations**: When conditions are checked and their results
- **Scene Operations**: Scene creation, deletion, activation
- **Device Commands**: Commands sent to devices with results

### Analysis Features

The AI-powered `get_rule_summary` tool provides:

- **Performance Analysis**: Execution time trends and optimization suggestions
- **Error Pattern Detection**: Common failure modes and troubleshooting advice
- **Usage Statistics**: Frequency analysis and activity patterns
- **Actionable Recommendations**: Specific suggestions for improving reliability

### Audit Data Structure

Audit logs include:
- **Timestamp**: When the event occurred
- **Event Type**: Category of event (rule_lifecycle, execution_lifecycle, etc.)
- **Event Subtype**: Specific event (rule_created, condition_evaluated, etc.)
- **Success Status**: Whether the operation succeeded
- **Execution Time**: How long the operation took (when applicable)
- **Context**: Rule name, scene name, device ID, etc.
- **Error Details**: Full error messages for failed operations

## Development

### Running Tests

```bash
# Run all tests
uv run --group test pytest

# Run specific test categories
uv run --group test pytest -m unit        # Unit tests only
uv run --group test pytest -m integration # Integration tests only

# Run with verbose output
uv run --group test pytest -v
```

### Project Structure

```
├── main.py                 # FastMCP server and main entry point
├── hubitat.py             # Hubitat REST API client
├── models/                # Data models and schemas
│   ├── api.py            # API request/response models
│   └── database.py       # Database models
├── rules/                # Rules engine core
│   ├── engine.py         # Rule execution engine
│   ├── handler.py        # Rule installation/management
│   ├── condition.py      # Condition system
│   └── interface.py      # Device/scene interfaces
├── logic/                # Business logic layer
│   └── rule_logic.py     # High-level rule operations
├── timing/               # Timer and scheduling
│   └── timers.py         # Timer service implementation
├── scenes/               # Scene management
│   └── manager.py        # Scene operations
├── tests/                # Test suite
└── hubitat_rules_programming_guide.md  # Comprehensive documentation
```

### Adding New Features

1. **New Rule Conditions**: Extend `AbstractCondition` in `rules/condition.py`
2. **Device Capabilities**: Add support in `rules/interface.py`
3. **Timer Patterns**: Enhance `timing/timers.py`
4. **Scene Operations**: Extend `scenes/manager.py`

### Debugging

If you have trouble seeing command output:
```bash
uv run fastmcp run --transport streamable-http --host 0.0.0.0 --port 8080
```

## Security Considerations

⚠️ **Important Security Warning**: The current implementation uses `eval()` and `exec()` for rule code execution without sandboxing. This provides full Python environment access.

### Security Best Practices:
- Only install rules from trusted sources
- Review all rule code before installation
- Run the server in an isolated environment
- Consider network restrictions for the server
- Monitor rule execution for unexpected behavior

### Current Limitations:
- No code sandboxing or security restrictions
- No resource limits on rule execution
- Rule code has full Python environment access

## API Reference

### HTTP Endpoints

- `GET /` - Server information and feature overview
- `POST /he_event` - Webhook endpoint for Hubitat device events

### MCP Tools

#### Core Tools

| Tool | Description | Parameters |
|------|-------------|------------|
| `install_rule` | Install automation rule | `name`, `rule_type`, `trigger_code`, `action_code` |
| `uninstall_rule` | Remove automation rule | `name` |
| `get_rules` | List rules with filtering | `name?`, `rule_type?` |
| `create_scene` | Create device scene | `name`, `device_states`, `description?` |
| `delete_scene` | Remove scene | `name` |
| `get_scenes` | List scenes with status | `name?`, `device_id?` |
| `set_scene` | Apply/activate scene | `name` |

#### Audit Tools (with --audit-tools flag)

| Tool | Description | Parameters |
|------|-------------|------------|
| `query_audit_logs` | Query audit logs with filtering | `event_type?`, `event_subtype?`, `rule_name?`, `scene_name?`, `device_id?`, `start_date?`, `end_date?`, `page?`, `page_size?` |
| `get_rule_summary` | AI-powered rule execution analysis | `rule_name?`, `start_date?`, `end_date?`, `include_successful?`, `include_failed?` |

### MCP Resources

| Resource | Description |
|----------|-------------|
| `rulesengine://programming-guide` | Comprehensive rule programming documentation |
