import json

from sqlmodel import Session, select

from audit.decorators import audit_scope
from models.api import DeviceStateRequirement, Scene
from models.audit import EventSubtype, EventType
from models.database import DBScene
from scenes.manager import SceneManager
from util import transactional


class SceneLogic:
    def __init__(self, scene_manager: SceneManager):
        self._scene_manager = scene_manager

    @transactional
    @audit_scope(
        event_type=EventType.SCENE_LIFECYCLE,
        end_event=EventSubtype.SCENE_CREATED,
        error_event=EventSubtype.SCENE_CREATED,
        scene_name="name",
    )
    async def create_scene(self, session: Session, name: str, scene: Scene) -> DBScene:
        """Create a new scene and save it to the database."""
        # Serialize device states to JSON
        device_states_json = json.dumps(
            [req.model_dump() for req in scene.device_states]
        )

        # Create database record
        db_scene = DBScene(
            name=name,
            description=scene.description,
            device_states_json=device_states_json,
            created_at=scene.created_at,
            updated_at=scene.updated_at,
        )
        session.add(db_scene)

        # Create in memory
        await self._scene_manager.create_scene(name, scene)

        return db_scene

    @transactional
    @audit_scope(
        event_type=EventType.SCENE_LIFECYCLE,
        end_event=EventSubtype.SCENE_DELETED,
        error_event=EventSubtype.SCENE_DELETED,
        scene_name="name",
    )
    async def delete_scene(self, session: Session, name: str) -> DBScene:
        """Delete a scene from both database and memory."""
        # Get the scene from database first
        db_scene = session.exec(select(DBScene).where(DBScene.name == name)).one()

        # Delete from database
        session.delete(db_scene)

        # Delete from memory
        await self._scene_manager.delete_scene(name)

        return db_scene

    @transactional
    async def get_scenes(
        self, session: Session, /, name: str | None = None, device_id: int | None = None
    ) -> list[Scene]:
        """Get scenes from database with optional filtering."""
        # Build query based on filters
        query = select(DBScene)

        if name:
            query = query.where(DBScene.name == name)

        # Execute query and get results
        db_scenes = session.exec(query).all()

        # Convert to Scene objects
        scenes = []
        for db_scene in db_scenes:
            # Deserialize device states from JSON
            device_states_data = json.loads(db_scene.device_states_json)
            device_states = [
                DeviceStateRequirement.model_validate(req_data)
                for req_data in device_states_data
            ]

            # Filter by device_id if specified
            if device_id and not any(
                req.device_id == device_id for req in device_states
            ):
                continue

            scene = Scene(
                name=db_scene.name,
                description=db_scene.description,
                device_states=device_states,
                created_at=db_scene.created_at,
                updated_at=db_scene.updated_at,
            )
            scenes.append(scene)

        return scenes

    async def load_scenes_from_database(self, session: Session) -> int:
        """Load all scenes from database into memory. Returns count of loaded scenes."""
        db_scenes = session.exec(select(DBScene)).all()

        count = 0
        for db_scene in db_scenes:
            # Deserialize device states from JSON
            device_states_data = json.loads(db_scene.device_states_json)
            device_states = [
                DeviceStateRequirement.model_validate(req_data)
                for req_data in device_states_data
            ]

            scene = Scene(
                name=db_scene.name,
                description=db_scene.description,
                device_states=device_states,
                created_at=db_scene.created_at,
                updated_at=db_scene.updated_at,
            )

            # Load into memory (bypass audit logging during startup)
            await self._scene_manager.create_scene(db_scene.name, scene)
            count += 1

        return count
