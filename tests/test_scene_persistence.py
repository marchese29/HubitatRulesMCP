from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from hubitat import HubitatClient
from logic.scene_logic import SceneLogic
from models.api import DeviceStateRequirement, Scene
from models.database import DBScene
from scenes.manager import SceneManager


@pytest.fixture
def scene_logic():
    """Create a scene logic instance for testing."""
    mock_client = HubitatClient()
    scene_manager = SceneManager(mock_client)
    return SceneLogic(scene_manager)


@pytest.fixture
def sample_scene():
    """Create a sample scene for testing."""
    return Scene(
        name="test_scene",
        description="Test scene for persistence",
        device_states=[
            DeviceStateRequirement(
                device_id=123,
                attribute="switch",
                value="on",
                command="on",
                arguments=[],
            ),
            DeviceStateRequirement(
                device_id=456,
                attribute="level",
                value=75,
                command="setLevel",
                arguments=[75],
            ),
        ],
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class TestScenePersistence:
    """Test scene persistence functionality."""

    async def test_create_scene_persists_to_database(
        self, scene_logic, sample_scene, db_session, db_engine
    ):
        """Test that creating a scene saves it to the database."""
        # Mock the FastMCP context to provide our test database engine
        mock_context = MagicMock()
        mock_context.fastmcp.db_engine = db_engine

        with patch("util.get_context", return_value=mock_context):
            # Create the scene
            await scene_logic.create_scene("test_scene", sample_scene)

            # Verify we can query it from database
            saved_scene = db_session.get(DBScene, "test_scene")
            assert saved_scene is not None
            assert saved_scene.name == "test_scene"
            assert saved_scene.description == "Test scene for persistence"
            assert saved_scene.device_states_json is not None

    async def test_delete_scene_removes_from_database(
        self, scene_logic, sample_scene, db_session, db_engine
    ):
        """Test that deleting a scene removes it from the database."""
        # Mock the FastMCP context to provide our test database engine
        mock_context = MagicMock()
        mock_context.fastmcp.db_engine = db_engine

        with patch("util.get_context", return_value=mock_context):
            # Create the scene first
            await scene_logic.create_scene("test_scene", sample_scene)

            # Verify it exists
            saved_scene = db_session.get(DBScene, "test_scene")
            assert saved_scene is not None

            # Delete the scene
            await scene_logic.delete_scene("test_scene")

            # Force a commit and refresh the session to see the changes
            db_session.commit()

            # Verify it's gone from database (query again to be sure)
            saved_scene_after_delete = db_session.get(DBScene, "test_scene")
            assert saved_scene_after_delete is None

    async def test_get_scenes_from_database(
        self, scene_logic, sample_scene, db_session, db_engine
    ):
        """Test that we can retrieve scenes from the database."""
        # Mock the FastMCP context to provide our test database engine
        mock_context = MagicMock()
        mock_context.fastmcp.db_engine = db_engine

        with patch("util.get_context", return_value=mock_context):
            # Create the scene
            await scene_logic.create_scene("test_scene", sample_scene)

            # Get scenes from database
            scenes = await scene_logic.get_scenes()
            assert len(scenes) == 1

            retrieved_scene = scenes[0]
            assert retrieved_scene.name == "test_scene"
            assert retrieved_scene.description == "Test scene for persistence"
            assert len(retrieved_scene.device_states) == 2

            # Verify device states were correctly deserialized
            device_state_1 = retrieved_scene.device_states[0]
            assert device_state_1.device_id == 123
            assert device_state_1.attribute == "switch"
            assert device_state_1.value == "on"
            assert device_state_1.command == "on"

    async def test_get_scenes_by_name_filter(
        self, scene_logic, sample_scene, db_session, db_engine
    ):
        """Test filtering scenes by name."""
        # Mock the FastMCP context to provide our test database engine
        mock_context = MagicMock()
        mock_context.fastmcp.db_engine = db_engine

        with patch("util.get_context", return_value=mock_context):
            # Create two scenes
            await scene_logic.create_scene("scene1", sample_scene)

            scene2 = Scene(
                name="scene2",
                description="Second scene",
                device_states=[],
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            await scene_logic.create_scene("scene2", scene2)

            # Get specific scene by name
            scenes = await scene_logic.get_scenes(name="scene1")
            assert len(scenes) == 1
            assert scenes[0].name == "scene1"

    async def test_get_scenes_by_device_filter(
        self, scene_logic, sample_scene, db_session, db_engine
    ):
        """Test filtering scenes by device ID."""
        # Mock the FastMCP context to provide our test database engine
        mock_context = MagicMock()
        mock_context.fastmcp.db_engine = db_engine

        with patch("util.get_context", return_value=mock_context):
            # Create scene with device 123
            await scene_logic.create_scene("scene_with_123", sample_scene)

            # Create scene without device 123
            scene_without_123 = Scene(
                name="scene_without_123",
                description="Scene without device 123",
                device_states=[
                    DeviceStateRequirement(
                        device_id=789,
                        attribute="switch",
                        value="off",
                        command="off",
                        arguments=[],
                    )
                ],
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )
            await scene_logic.create_scene("scene_without_123", scene_without_123)

            # Filter by device 123
            scenes = await scene_logic.get_scenes(device_id=123)
            assert len(scenes) == 1
            assert scenes[0].name == "scene_with_123"

    async def test_load_scenes_from_database(
        self, scene_logic, sample_scene, db_session
    ):
        """Test loading scenes from database into memory."""
        # Create scene directly in database (bypassing scene_manager)
        import json

        from models.database import DBScene

        device_states_json = json.dumps(
            [req.model_dump() for req in sample_scene.device_states]
        )
        db_scene = DBScene(
            name="direct_db_scene",
            description="Scene created directly in DB",
            device_states_json=device_states_json,
            created_at=sample_scene.created_at,
            updated_at=sample_scene.updated_at,
        )
        db_session.add(db_scene)
        db_session.commit()

        # Load scenes from database
        count = await scene_logic.load_scenes_from_database(db_session)
        assert count == 1

    async def test_scene_json_serialization_roundtrip(
        self, scene_logic, db_session, db_engine
    ):
        """Test that complex device states are correctly serialized and deserialized."""
        # Mock the FastMCP context to provide our test database engine
        mock_context = MagicMock()
        mock_context.fastmcp.db_engine = db_engine

        with patch("util.get_context", return_value=mock_context):
            # Create scene with complex device states
            complex_scene = Scene(
                name="complex_scene",
                description="Scene with complex device states",
                device_states=[
                    DeviceStateRequirement(
                        device_id=100,
                        attribute="color",
                        value={"hue": 120, "saturation": 100, "level": 75},
                        command="setColor",
                        arguments=[{"hue": 120, "saturation": 100, "level": 75}],
                    ),
                    DeviceStateRequirement(
                        device_id=200,
                        attribute="multiValue",
                        value=[1, 2, 3],
                        command="setMultiple",
                        arguments=[1, 2, 3],
                    ),
                ],
                created_at=datetime.now(),
                updated_at=datetime.now(),
            )

            # Create and retrieve the scene
            await scene_logic.create_scene("complex_scene", complex_scene)
            scenes = await scene_logic.get_scenes(name="complex_scene")

            assert len(scenes) == 1
            retrieved_scene = scenes[0]

            # Verify complex data was preserved
            color_state = retrieved_scene.device_states[0]
            assert color_state.device_id == 100
            assert color_state.value == {"hue": 120, "saturation": 100, "level": 75}
            assert color_state.arguments == [
                {"hue": 120, "saturation": 100, "level": 75}
            ]

            multi_state = retrieved_scene.device_states[1]
            assert multi_state.device_id == 200
            assert multi_state.value == [1, 2, 3]
            assert multi_state.arguments == [1, 2, 3]
