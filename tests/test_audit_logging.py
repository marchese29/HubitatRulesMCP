import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlmodel import Session, select

from audit.decorators import (
    audit_scope,
    audit_scope_context,
    log_audit_event,
)
from audit.service import AuditService
from hubitat import HubitatClient
from logic.rule_logic import RuleLogic
from models.api import DeviceStateRequirement, Scene
from models.audit import AuditLog, EventSubtype, EventType
from models.database import DBRule
from rules.handler import RuleHandler
from scenes.manager import SceneManager


@pytest.fixture
def mock_hubitat_client():
    """Create a mock Hubitat client"""
    client = MagicMock(spec=HubitatClient)
    client.send_command = AsyncMock()
    client.get_bulk_attributes = AsyncMock(return_value={})
    return client


@pytest.fixture
def mock_rule_handler():
    """Create a mock rule handler"""
    handler = MagicMock(spec=RuleHandler)
    handler.install_rule = AsyncMock()
    handler.install_scheduled_rule = AsyncMock()
    handler.uninstall_rule = AsyncMock()
    handler.get_active_rules = MagicMock(return_value=[])
    return handler


@pytest.fixture
def rule_logic(mock_rule_handler):
    """Create a rule logic instance with mocked dependencies"""
    return RuleLogic(mock_rule_handler)


@pytest.fixture
def scene_manager(mock_hubitat_client):
    """Create a scene manager with mocked dependencies"""
    return SceneManager(mock_hubitat_client)


class TestAuditService:
    """Test the audit service functionality"""

    async def test_log_event_creates_audit_entry(self, audit_service, db_engine):
        """Test that logging an event creates a database entry"""
        # Log an event
        await audit_service.log_event(
            EventType.RULE_LIFECYCLE,
            EventSubtype.RULE_CREATED,
            rule_name="test_rule",
            success=True,
            execution_time_ms=150.5,
        )

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        # Verify it was logged to database
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

            log = logs[0]
            assert log.event_type == EventType.RULE_LIFECYCLE
            assert log.event_subtype == EventSubtype.RULE_CREATED
            assert log.rule_name == "test_rule"
            assert log.success is True
            assert log.execution_time_ms == 150.5
            assert log.timestamp is not None

    async def test_log_event_with_all_fields(self, audit_service, db_engine):
        """Test logging an event with all possible fields"""
        await audit_service.log_event(
            EventType.DEVICE_CONTROL,
            EventSubtype.DEVICE_COMMAND,
            rule_name="device_rule",
            scene_name="test_scene",
            condition_id="cond_123",
            device_id=456,
            success=False,
            error_message="Device offline",
            execution_time_ms=75.2,
            context_data='{"command": "on", "args": []}',
        )

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        with Session(db_engine) as session:
            log = session.exec(select(AuditLog)).first()
            assert log.event_type == EventType.DEVICE_CONTROL
            assert log.event_subtype == EventSubtype.DEVICE_COMMAND
            assert log.rule_name == "device_rule"
            assert log.scene_name == "test_scene"
            assert log.condition_id == "cond_123"
            assert log.device_id == 456
            assert log.success is False
            assert log.error_message == "Device offline"
            assert log.execution_time_ms == 75.2
            assert log.context_data == '{"command": "on", "args": []}'


class TestAuditDecorators:
    """Test the audit decorators functionality"""

    async def test_audit_decorator_logs_success(self, audit_service, db_engine):
        """Test that the audit scope decorator logs successful operations"""

        @audit_scope(
            event_type=EventType.RULE_LIFECYCLE,
            end_event=EventSubtype.RULE_CREATED,
            rule_name="name",
        )
        async def test_function(name: str):
            return f"Success: {name}"

        # Call the decorated function
        result = await test_function("test_rule")
        assert result == "Success: test_rule"

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        # Verify audit log was created
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

            log = logs[0]
            assert log.event_type == EventType.RULE_LIFECYCLE
            assert log.event_subtype == EventSubtype.RULE_CREATED
            assert log.rule_name == "test_rule"
            assert log.success is True
            assert log.error_message is None
            assert log.execution_time_ms > 0

    async def test_audit_decorator_logs_failure(self, audit_service, db_engine):
        """Test that the audit scope decorator logs failed operations"""

        @audit_scope(
            event_type=EventType.SCENE_LIFECYCLE,
            error_event=EventSubtype.SCENE_DELETED,
            scene_name="name",
        )
        async def test_function(name: str):
            raise ValueError(f"Failed to delete {name}")

        # Call the decorated function and expect it to fail
        with pytest.raises(ValueError, match="Failed to delete test_scene"):
            await test_function("test_scene")

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        # Verify audit log was created with failure information
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

            log = logs[0]
            assert log.event_type == EventType.SCENE_LIFECYCLE
            assert log.event_subtype == EventSubtype.SCENE_DELETED
            assert log.scene_name == "test_scene"
            assert log.success is False
            assert "Failed to delete test_scene" in log.error_message
            assert log.execution_time_ms > 0


class TestRuleLogicAuditIntegration:
    """Test audit logging integration with rule logic"""

    async def test_install_trigger_rule_audit_logging(
        self, rule_logic, audit_service, db_engine, db_session
    ):
        """Test that installing a trigger rule creates audit logs"""

        # Mock the FastMCP context to provide our test database engine
        mock_context = MagicMock()
        mock_context.fastmcp.db_engine = db_engine

        with patch("util.get_context", return_value=mock_context):
            # Install a trigger rule - this should complete successfully
            await rule_logic.install_trigger_rule(
                "test_trigger", "device.switch == 'on'", "print('triggered')"
            )

            # Wait a moment for the async writer to process
            await asyncio.sleep(0.1)

            # Verify audit log was created
            with Session(db_engine) as session:
                logs = session.exec(select(AuditLog)).all()
                assert len(logs) == 1

                log = logs[0]
                assert log.event_type == EventType.RULE_LIFECYCLE
                assert log.event_subtype == EventSubtype.RULE_CREATED
                assert log.rule_name == "test_trigger"
                assert log.success is True

    async def test_install_timer_rule_audit_logging(
        self, rule_logic, audit_service, db_engine, db_session
    ):
        """Test that installing a timer rule creates audit logs"""

        # Mock the FastMCP context to provide our test database engine
        mock_context = MagicMock()
        mock_context.fastmcp.db_engine = db_engine

        with patch("util.get_context", return_value=mock_context):
            # Install a timer rule - this should complete successfully
            await rule_logic.install_timer_rule(
                "test_timer", "0 */5 * * * *", "print('timer triggered')"
            )

            # Wait a moment for the async writer to process
            await asyncio.sleep(0.1)

            # Verify audit log was created
            with Session(db_engine) as session:
                logs = session.exec(select(AuditLog)).all()
                assert len(logs) == 1

                log = logs[0]
                assert log.event_type == EventType.RULE_LIFECYCLE
                assert log.event_subtype == EventSubtype.RULE_CREATED
                assert log.rule_name == "test_timer"
                assert log.success is True

    async def test_uninstall_rule_audit_logging(
        self, rule_logic, audit_service, db_engine, db_session
    ):
        """Test that uninstalling a rule creates audit logs"""

        # Mock the FastMCP context to provide our test database engine
        mock_context = MagicMock()
        mock_context.fastmcp.db_engine = db_engine

        with patch("util.get_context", return_value=mock_context):
            # First install a rule
            rule = DBRule(
                name="test_rule",
                trigger_code="device.switch == 'on'",
                action_code="print('test')",
            )
            db_session.add(rule)
            db_session.commit()

            # Then uninstall it
            deleted_rule = await rule_logic.uninstall_rule("test_rule")
            assert deleted_rule.name == "test_rule"

            # Wait a moment for the async writer to process
            await asyncio.sleep(0.1)

            # Verify audit log was created
            with Session(db_engine) as session:
                logs = session.exec(select(AuditLog)).all()
                assert len(logs) == 1

                log = logs[0]
                assert log.event_type == EventType.RULE_LIFECYCLE
                assert log.event_subtype == EventSubtype.RULE_DELETED
                assert log.rule_name == "test_rule"
                assert log.success is True


class TestSceneManagerAuditIntegration:
    """Test audit logging integration with scene manager"""

    async def test_create_scene_audit_logging(
        self, scene_manager, audit_service, db_engine
    ):
        """Test that creating a scene creates audit logs"""

        scene = Scene(
            name="test_scene",
            description="Test scene",
            device_states=[
                DeviceStateRequirement(
                    device_id=123,
                    attribute="switch",
                    value="on",
                    command="on",
                    arguments=[],
                )
            ],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )

        created_scene = await scene_manager.create_scene("test_scene", scene)
        assert created_scene.name == "test_scene"

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        # Verify audit log was created
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

            log = logs[0]
            assert log.event_type == EventType.SCENE_LIFECYCLE
            assert log.event_subtype == EventSubtype.SCENE_CREATED
            assert log.scene_name == "test_scene"
            assert log.success is True

    async def test_delete_scene_audit_logging(
        self, scene_manager, audit_service, db_engine
    ):
        """Test that deleting a scene creates audit logs"""

        # First create a scene
        scene = Scene(
            name="test_scene",
            description="Test scene",
            device_states=[],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await scene_manager.create_scene("test_scene", scene)

        # Then delete it
        deleted_scene = await scene_manager.delete_scene("test_scene")
        assert deleted_scene.name == "test_scene"

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        # Verify audit logs were created (both create and delete)
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 2

            # Check delete log (most recent)
            delete_log = logs[1]
            assert delete_log.event_type == EventType.SCENE_LIFECYCLE
            assert delete_log.event_subtype == EventSubtype.SCENE_DELETED
            assert delete_log.scene_name == "test_scene"
            assert delete_log.success is True

    async def test_set_scene_audit_logging(
        self, scene_manager, audit_service, db_engine
    ):
        """Test that setting a scene creates audit logs"""

        # Create a scene with device states
        scene = Scene(
            name="test_scene",
            description="Test scene",
            device_states=[
                DeviceStateRequirement(
                    device_id=123,
                    attribute="switch",
                    value="on",
                    command="on",
                    arguments=[],
                )
            ],
            created_at=datetime.now(),
            updated_at=datetime.now(),
        )
        await scene_manager.create_scene("test_scene", scene)

        # Set the scene
        response = await scene_manager.set_scene("test_scene")
        assert response.success is True

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        # Verify audit logs were created (both create and apply)
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 2

            # Check apply log (most recent)
            apply_log = logs[1]
            assert apply_log.event_type == EventType.SCENE_LIFECYCLE
            assert apply_log.event_subtype == EventSubtype.SCENE_APPLIED
            assert apply_log.scene_name == "test_scene"
            assert apply_log.success is True


class TestHubitatClientAuditIntegration:
    """Test audit logging integration with Hubitat client"""

    async def test_send_command_audit_logging(
        self, mock_hubitat_client, audit_service, db_engine
    ):
        """Test that sending device commands creates audit logs"""

        # We need to create a real HubitatClient instance with audit decorator
        # but mock the actual HTTP call
        from hubitat import HubitatClient

        client = HubitatClient()
        # Mock the _make_request method to avoid actual HTTP calls
        client._make_request = AsyncMock()

        # Send a command
        await client.send_command(123, "on", [])

        # Verify the HTTP request was called
        client._make_request.assert_called_once()

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        # Verify audit log was created
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

            log = logs[0]
            assert log.event_type == EventType.DEVICE_CONTROL
            assert log.event_subtype == EventSubtype.DEVICE_COMMAND
            assert log.device_id == 123
            assert log.success is True


class TestAuditServiceLifecycle:
    """Test audit service start/stop lifecycle"""

    async def test_audit_service_start_stop(self, db_engine):
        """Test that audit service starts and stops properly"""

        service = AuditService(db_engine)

        # Service should not be started initially
        assert not service._started

        # Start the service
        service.start()
        assert service._started

        # Log an event to verify it's working
        await service.log_event(
            EventType.RULE_LIFECYCLE, EventSubtype.RULE_CREATED, rule_name="test"
        )

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        # Stop the service
        await service.stop()
        assert not service._started

        # Verify the event was logged
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

    async def test_audit_service_multiple_events(self, audit_service, db_engine):
        """Test logging multiple events in sequence"""

        events = [
            (EventType.RULE_LIFECYCLE, EventSubtype.RULE_CREATED, "rule1"),
            (EventType.RULE_LIFECYCLE, EventSubtype.RULE_CREATED, "rule2"),
            (EventType.SCENE_LIFECYCLE, EventSubtype.SCENE_CREATED, None),
            (EventType.DEVICE_CONTROL, EventSubtype.DEVICE_COMMAND, None),
        ]

        for event_type, event_subtype, rule_name in events:
            await audit_service.log_event(
                event_type,
                event_subtype,
                rule_name=rule_name,
                scene_name="test_scene"
                if event_type == EventType.SCENE_LIFECYCLE
                else None,
                device_id=123 if event_type == EventType.DEVICE_CONTROL else None,
            )

        # Wait a moment for the async writer to process
        await asyncio.sleep(0.1)

        # Verify all events were logged
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 4

            # Verify each event type
            rule_logs = [
                log for log in logs if log.event_type == EventType.RULE_LIFECYCLE
            ]
            scene_logs = [
                log for log in logs if log.event_type == EventType.SCENE_LIFECYCLE
            ]
            device_logs = [
                log for log in logs if log.event_type == EventType.DEVICE_CONTROL
            ]

            assert len(rule_logs) == 2
            assert len(scene_logs) == 1
            assert len(device_logs) == 1

            assert rule_logs[0].rule_name in ["rule1", "rule2"]
            assert scene_logs[0].scene_name == "test_scene"
            assert device_logs[0].device_id == 123


class TestNewAuditScope:
    """Test the new @audit_scope decorator functionality"""

    async def test_audit_scope_context_only(self, audit_service, db_engine):
        """Test audit scope for context management without lifecycle events"""

        @audit_scope(rule_name="name", device_id="device_id", command_type="command")
        async def test_function(name: str, device_id: int, command: str):
            # Log an event within the scope
            await log_audit_event(
                EventType.DEVICE_CONTROL, EventSubtype.DEVICE_COMMAND, result="success"
            )
            return f"Command {command} sent to device {device_id}"

        result = await test_function("test_rule", 123, "on")
        assert result == "Command on sent to device 123"

        # Wait for async writer
        await asyncio.sleep(0.1)

        # Verify only the manual event was logged (no lifecycle events)
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

            log = logs[0]
            assert log.event_type == EventType.DEVICE_CONTROL
            assert log.event_subtype == EventSubtype.DEVICE_COMMAND
            assert log.rule_name == "test_rule"
            assert log.device_id == 123


class TestRuleLifecycleAuditIntegration:
    """Test rule lifecycle audit logging integration"""

    async def test_rule_installation_audit_logging(self, audit_service, db_engine):
        """Test that rule installation creates proper audit logs"""

        # Create mock rule handler that accepts the new signature
        from unittest.mock import MagicMock

        @audit_scope(
            event_type=EventType.RULE_LIFECYCLE,
            end_event=EventSubtype.RULE_LOADED,
            error_event=EventSubtype.RULE_LOADED,
            rule_name="rule_name",
        )
        async def mock_install_rule(rule, rule_name: str):
            # Simulate successful rule installation
            return f"Rule {rule_name} installed"

        result = await mock_install_rule(MagicMock(), "test_rule")
        assert result == "Rule test_rule installed"

        # Wait for async writer
        await asyncio.sleep(0.1)

        # Verify audit log was created
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

            log = logs[0]
            assert log.event_type == EventType.RULE_LIFECYCLE
            assert log.event_subtype == EventSubtype.RULE_LOADED
            assert log.rule_name == "test_rule"
            assert log.success is True
            assert log.execution_time_ms > 0

    async def test_rule_execution_context_inheritance(self, audit_service, db_engine):
        """Test that rule execution context is inherited by device operations"""

        # Simulate rule execution with device commands
        @audit_scope(rule_name="rule_name")
        async def mock_rule_execution(rule_name: str):
            # Log rule action started
            await log_audit_event(
                EventType.EXECUTION_LIFECYCLE,
                EventSubtype.RULE_ACTION_STARTED,
            )

            # Simulate device command within rule (inherits rule context)
            @audit_scope(device_id="device_id", command="command")
            async def device_command(device_id: int, command: str):
                await log_audit_event(
                    EventType.DEVICE_CONTROL,
                    EventSubtype.DEVICE_COMMAND,
                    success=True,
                )
                return f"Device {device_id} command {command} executed"

            # Execute device command within rule context
            result = await device_command(123, "on")

            # Log rule action completed
            await log_audit_event(
                EventType.EXECUTION_LIFECYCLE,
                EventSubtype.RULE_ACTION_COMPLETED,
                success=True,
            )

            return result

        result = await mock_rule_execution("bedroom_lights")
        assert result == "Device 123 command on executed"

        # Wait for async writer
        await asyncio.sleep(0.1)

        # Should have 3 events: rule start, device command, rule complete
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 3

            # All events should have the rule name from the parent context
            for log in logs:
                assert log.rule_name == "bedroom_lights"

            # Check specific events
            rule_start = logs[0]
            assert rule_start.event_subtype == EventSubtype.RULE_ACTION_STARTED

            device_cmd = logs[1]
            assert device_cmd.event_subtype == EventSubtype.DEVICE_COMMAND
            assert device_cmd.device_id == 123

            rule_complete = logs[2]
            assert rule_complete.event_subtype == EventSubtype.RULE_ACTION_COMPLETED
            # success=True is passed as kwargs, so it goes into context_data
            import json

            context_data = json.loads(rule_complete.context_data)
            assert context_data["success"] is True

    async def test_rule_execution_with_scene_operations(self, audit_service, db_engine):
        """Test rule execution context inheritance with scene operations"""

        @audit_scope(rule_name="rule_name")
        async def mock_rule_with_scene(rule_name: str):
            # Log trigger fired
            await log_audit_event(
                EventType.EXECUTION_LIFECYCLE,
                EventSubtype.TRIGGER_FIRED,
            )

            # Simulate scene operation within rule
            @audit_scope(scene_name="scene_name")
            async def scene_operation(scene_name: str):
                await log_audit_event(
                    EventType.SCENE_LIFECYCLE,
                    EventSubtype.SCENE_APPLIED,
                    success=True,
                )
                return f"Scene {scene_name} applied"

            scene_result = await scene_operation("evening_lights")

            return f"Rule {rule_name} executed: {scene_result}"

        result = await mock_rule_with_scene("evening_automation")
        assert (
            result == "Rule evening_automation executed: Scene evening_lights applied"
        )

        # Wait for async writer
        await asyncio.sleep(0.1)

        # Should have 2 events: trigger fired, scene applied
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 2

            trigger_log = logs[0]
            assert trigger_log.event_subtype == EventSubtype.TRIGGER_FIRED
            assert trigger_log.rule_name == "evening_automation"

            scene_log = logs[1]
            assert scene_log.event_subtype == EventSubtype.SCENE_APPLIED
            assert (
                scene_log.rule_name == "evening_automation"
            )  # Inherited from rule context
            assert scene_log.scene_name == "evening_lights"

    async def test_audit_scope_with_lifecycle_events(self, audit_service, db_engine):
        """Test audit scope with lifecycle event logging"""

        @audit_scope(
            event_type=EventType.EXECUTION_LIFECYCLE,
            start_event=EventSubtype.RULE_ACTION_STARTED,
            end_event=EventSubtype.RULE_ACTION_COMPLETED,
            error_event=EventSubtype.RULE_ACTION_FAILED,
            rule_name="name",
            priority="high",
        )
        async def test_function(name: str):
            # Manual event within scope
            await log_audit_event(
                EventType.EXECUTION_LIFECYCLE,
                EventSubtype.CONDITION_EVALUATED,
                result=True,
            )
            return f"Rule {name} executed"

        result = await test_function("test_rule")
        assert result == "Rule test_rule executed"

        # Wait for async writer
        await asyncio.sleep(0.1)

        # Should have 3 events: start, manual, end
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 3

            # Check start event
            start_log = logs[0]
            assert start_log.event_subtype == EventSubtype.RULE_ACTION_STARTED
            assert start_log.rule_name == "test_rule"

            # Check manual event
            manual_log = logs[1]
            assert manual_log.event_subtype == EventSubtype.CONDITION_EVALUATED
            assert manual_log.rule_name == "test_rule"

            # Check end event
            end_log = logs[2]
            assert end_log.event_subtype == EventSubtype.RULE_ACTION_COMPLETED
            assert end_log.rule_name == "test_rule"
            assert end_log.success is True
            assert end_log.execution_time_ms > 0

    async def test_audit_scope_error_logging(self, audit_service, db_engine):
        """Test audit scope error event logging"""

        @audit_scope(
            event_type=EventType.EXECUTION_LIFECYCLE,
            start_event=EventSubtype.RULE_ACTION_STARTED,
            error_event=EventSubtype.RULE_ACTION_FAILED,
            rule_name="name",
        )
        async def test_function(name: str):
            raise ValueError(f"Rule {name} failed")

        with pytest.raises(ValueError, match="Rule test_rule failed"):
            await test_function("test_rule")

        # Wait for async writer
        await asyncio.sleep(0.1)

        # Should have 2 events: start, error
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 2

            # Check start event
            start_log = logs[0]
            assert start_log.event_subtype == EventSubtype.RULE_ACTION_STARTED

            # Check error event
            error_log = logs[1]
            assert error_log.event_subtype == EventSubtype.RULE_ACTION_FAILED
            assert error_log.rule_name == "test_rule"
            assert error_log.success is False
            assert "Rule test_rule failed" in error_log.error_message


class TestContextInheritance:
    """Test context inheritance between nested audit scopes"""

    async def test_nested_scope_inheritance(self, audit_service, db_engine):
        """Test that nested scopes inherit context from parent scopes"""

        @audit_scope(rule_name="name")
        async def parent_function(name: str):
            # This scope contributes rule_name
            return await child_function("motion_sensor_1")

        @audit_scope(condition_id="condition_id", sensor_type="motion")
        async def child_function(condition_id: str):
            # This scope adds condition_id and sensor_type
            await log_audit_event(
                EventType.EXECUTION_LIFECYCLE,
                EventSubtype.CONDITION_EVALUATED,
                result=True,
                sensor_value=85,
            )
            return "condition evaluated"

        result = await parent_function("test_rule")
        assert result == "condition evaluated"

        # Wait for async writer
        await asyncio.sleep(0.1)

        # Check that the logged event has context from both scopes
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

            log = logs[0]
            assert log.event_type == EventType.EXECUTION_LIFECYCLE
            assert log.event_subtype == EventSubtype.CONDITION_EVALUATED
            assert log.rule_name == "test_rule"  # From parent scope
            assert log.condition_id == "motion_sensor_1"  # From child scope

            # Check context_data contains additional fields
            import json

            context_data = json.loads(log.context_data)
            assert context_data["result"] is True
            assert context_data["sensor_value"] == 85
            assert context_data["sensor_type"] == "motion"

    async def test_context_manager_inheritance(self, audit_service, db_engine):
        """Test context inheritance with audit_scope_context manager"""

        @audit_scope(rule_name="name")
        async def test_function(name: str):
            # Use context manager to add more context
            async with audit_scope_context(
                condition_id="motion_1", sensor_location="hallway"
            ):
                await log_audit_event(
                    EventType.EXECUTION_LIFECYCLE,
                    EventSubtype.CONDITION_EVALUATED,
                    sensor_triggered=True,
                )
            return "done"

        result = await test_function("test_rule")
        assert result == "done"

        # Wait for async writer
        await asyncio.sleep(0.1)

        with Session(db_engine) as session:
            log = session.exec(select(AuditLog)).first()
            assert log.rule_name == "test_rule"  # From decorator scope
            assert log.condition_id == "motion_1"  # From context manager

            import json

            context_data = json.loads(log.context_data)
            assert context_data["sensor_triggered"] is True
            assert context_data["sensor_location"] == "hallway"


class TestConditionEvaluatedEvent:
    """Test the new CONDITION_EVALUATED event subtype"""

    async def test_condition_evaluated_logging(self, audit_service, db_engine):
        """Test logging CONDITION_EVALUATED events"""

        async def evaluate_condition(rule_name: str, condition_id: str):
            async with audit_scope_context(
                rule_name=rule_name, condition_id=condition_id
            ):
                # Simulate condition evaluation
                await log_audit_event(
                    EventType.EXECUTION_LIFECYCLE,
                    EventSubtype.CONDITION_EVALUATED,
                    result=True,
                    sensor_value=75,
                    threshold=70,
                    evaluation_time_ms=12.5,
                )
                return True

        result = await evaluate_condition("bedroom_lights", "motion_sensor_1")
        assert result is True

        # Wait for async writer
        await asyncio.sleep(0.1)

        with Session(db_engine) as session:
            log = session.exec(select(AuditLog)).first()
            assert log.event_type == EventType.EXECUTION_LIFECYCLE
            assert log.event_subtype == EventSubtype.CONDITION_EVALUATED
            assert log.rule_name == "bedroom_lights"
            assert log.condition_id == "motion_sensor_1"

            import json

            context_data = json.loads(log.context_data)
            assert context_data["result"] is True
            assert context_data["sensor_value"] == 75
            assert context_data["threshold"] == 70
            assert context_data["evaluation_time_ms"] == 12.5

    async def test_multiple_condition_evaluations(self, audit_service, db_engine):
        """Test logging multiple condition evaluations within a rule execution"""

        @audit_scope(rule_name="name")
        async def execute_rule(name: str):
            # Evaluate multiple conditions
            conditions = [
                ("motion_sensor_1", True, 85),
                ("light_sensor_1", False, 45),
                ("door_sensor_1", True, 1),
            ]

            for condition_id, result, sensor_value in conditions:
                async with audit_scope_context(condition_id=condition_id):
                    await log_audit_event(
                        EventType.EXECUTION_LIFECYCLE,
                        EventSubtype.CONDITION_EVALUATED,
                        result=result,
                        sensor_value=sensor_value,
                    )

            return "rule executed"

        result = await execute_rule("complex_rule")
        assert result == "rule executed"

        # Wait for async writer
        await asyncio.sleep(0.1)

        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 3

            # All should be condition evaluated events with same rule name
            for log in logs:
                assert log.event_type == EventType.EXECUTION_LIFECYCLE
                assert log.event_subtype == EventSubtype.CONDITION_EVALUATED
                assert log.rule_name == "complex_rule"

            # Check specific condition results
            condition_ids = [log.condition_id for log in logs]
            assert "motion_sensor_1" in condition_ids
            assert "light_sensor_1" in condition_ids
            assert "door_sensor_1" in condition_ids


class TestAuditScopeValidation:
    """Test validation and error handling for audit scope"""

    def test_lifecycle_events_require_event_type(self):
        """Test that lifecycle events require event_type parameter"""

        with pytest.raises(
            ValueError,
            match="event_type is required when lifecycle events are specified",
        ):

            @audit_scope(start_event=EventSubtype.RULE_ACTION_STARTED)
            async def test_function():
                pass

    async def test_scope_without_lifecycle_events(self, audit_service, db_engine):
        """Test that scope works fine without any lifecycle events"""

        @audit_scope(rule_name="name", device_id="device_id")
        async def test_function(name: str, device_id: int):
            await log_audit_event(EventType.DEVICE_CONTROL, EventSubtype.DEVICE_COMMAND)
            return "success"

        result = await test_function("test_rule", 123)
        assert result == "success"

        # Wait for async writer
        await asyncio.sleep(0.1)

        # Should only have the manually logged event
        with Session(db_engine) as session:
            logs = session.exec(select(AuditLog)).all()
            assert len(logs) == 1

            log = logs[0]
            assert log.event_subtype == EventSubtype.DEVICE_COMMAND
            assert log.rule_name == "test_rule"
            assert log.device_id == 123
