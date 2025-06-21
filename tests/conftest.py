"""Pytest configuration and shared fixtures."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

from audit import service as audit_service_module
from audit.service import AuditService
from hubitat import HubitatClient, HubitatDevice
from rules.engine import RuleEngine
from tests.test_helpers import create_mock_hubitat_client, create_mock_timer_service


@pytest.fixture
def mock_hubitat_device():
    """Create a mock HubitatDevice for testing."""
    device = HubitatDevice(
        id=123,
        name="Test Device",
        attributes={"temperature", "humidity", "switch", "door", "contact"},
        commands={"on", "off", "refresh", "open", "close"},
    )
    return device


@pytest.fixture
def mock_hubitat_client(mock_hubitat_device):
    """Create a mock HubitatClient for testing."""
    mock_client = MagicMock(spec=HubitatClient)
    mock_client.device_by_id = AsyncMock(return_value=mock_hubitat_device)
    return mock_client


@pytest.fixture
def device_64_mock():
    """Create a mock for device ID 64 used in integration tests."""
    return HubitatDevice(
        id=64,
        name="Test Door Sensor",
        attributes={"door", "contact", "temperature", "battery"},
        commands={"open", "close", "refresh"},
    )


# RuleEngine Testing Fixtures


@pytest.fixture
def mock_timer_service():
    """Create a fresh MockTimerService for each test."""
    return create_mock_timer_service()


@pytest.fixture
def mock_he_client():
    """Create a mock HubitatClient that returns empty attributes by default."""
    return create_mock_hubitat_client()


@pytest.fixture
def rule_engine(mock_he_client, mock_timer_service):
    """Create a RuleEngine instance with mocked dependencies."""
    return RuleEngine(mock_he_client, mock_timer_service)


@pytest.fixture
def rule_engine_with_device_attrs(mock_timer_service):
    """Create a RuleEngine with a client that has predefined device attributes.

    Device 123: {"switch": "off", "contact": "closed"}
    Device 456: {"switch": "on", "temperature": 72}
    """
    device_attrs = {
        123: {"switch": "off", "contact": "closed"},
        456: {"switch": "on", "temperature": 72},
    }
    client = create_mock_hubitat_client(device_attrs)
    return RuleEngine(client, mock_timer_service)


# Database Testing Fixtures


@pytest.fixture
def db_engine():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    """Create a database session for testing."""
    with Session(db_engine) as session:
        yield session


@pytest.fixture
async def audit_service(db_engine):
    """Create and start an audit service for testing."""
    # Set up the global audit service for testing
    service = AuditService(db_engine)
    audit_service_module.audit_service = service
    service.start()
    yield service
    await service.stop()
    audit_service_module.audit_service = None
