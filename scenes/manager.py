import asyncio
from typing import Optional

from hubitat import HubitatClient
from models.api import (
    Scene,
    SceneWithStatus,
    DeviceStateRequirement,
    CommandResult,
    SceneSetResponse,
)


class SceneManager:
    """Manager for creating, managing, setting, and tracking scenes."""

    def __init__(self, he_client: HubitatClient):
        self.he_client = he_client
        self._scenes: dict[str, Scene] = {}
        self._device_to_scenes: dict[int, set[str]] = {}

    # CRUD Operations
    async def create_scene(self, scene: Scene) -> Scene:
        """Create a new scene."""
        if scene.name in self._scenes:
            raise ValueError(f"Scene '{scene.name}' already exists")

        # Add to memory
        self._scenes[scene.name] = scene

        # Update device index
        for req in scene.device_states:
            if req.device_id not in self._device_to_scenes:
                self._device_to_scenes[req.device_id] = set()
            self._device_to_scenes[req.device_id].add(scene.name)

        return scene

    async def get_scenes(
        self,
        name: Optional[str] = None,
        device_id: Optional[int] = None,
    ) -> list[SceneWithStatus]:
        """Get scenes with optional filtering. Includes current set status."""
        # Filter scenes based on parameters
        scenes_to_return = []

        if name:
            # Get specific scene
            if name in self._scenes:
                scenes_to_return = [self._scenes[name]]
        elif device_id:
            # Get scenes involving specific device
            scene_names = self._device_to_scenes.get(device_id, set())
            scenes_to_return = [self._scenes[name] for name in scene_names]
        else:
            # Get all scenes
            scenes_to_return = list(self._scenes.values())

        # Convert to SceneWithStatus objects
        scenes_with_status = []

        if scenes_to_return:
            # Collect all unique device IDs across all scenes
            all_device_ids = set()
            for scene in scenes_to_return:
                for req in scene.device_states:
                    all_device_ids.add(req.device_id)

            # Batch fetch device states in parallel
            device_states = await self._batch_fetch_device_states(all_device_ids)

            # Check each scene using pre-fetched states
            for scene in scenes_to_return:
                is_set = self._is_scene_set_with_states(scene, device_states)
                scene_with_status = SceneWithStatus(
                    name=scene.name,
                    description=scene.description,
                    device_states=scene.device_states,
                    created_at=scene.created_at,
                    updated_at=scene.updated_at,
                    is_set=is_set,
                )
                scenes_with_status.append(scene_with_status)

        return scenes_with_status

    async def delete_scene(self, name: str) -> Scene:
        """Delete a scene and return its definition."""
        if name not in self._scenes:
            raise ValueError(f"Scene '{name}' not found")

        scene = self._scenes[name]

        # Remove from memory
        del self._scenes[name]

        # Update device index
        for req in scene.device_states:
            if req.device_id in self._device_to_scenes:
                self._device_to_scenes[req.device_id].discard(name)
                if not self._device_to_scenes[req.device_id]:
                    del self._device_to_scenes[req.device_id]

        return scene

    # Scene Operations
    async def set_scene(self, name: str) -> SceneSetResponse:
        """Apply a scene by sending commands to devices."""
        if name not in self._scenes:
            raise ValueError(f"Scene '{name}' not found")

        scene = self._scenes[name]
        failed_commands = []
        successful_count = 0

        # Send all commands in parallel
        tasks = []
        for req in scene.device_states:
            task = asyncio.create_task(self._send_command_safe(req))
            tasks.append((req, task))

        # Wait for all results and collect failures
        for req, task in tasks:
            try:
                await task
                successful_count += 1
            except Exception as e:
                failed_commands.append(
                    CommandResult(
                        device_id=req.device_id,
                        command=req.command,
                        arguments=req.arguments,
                        error=str(e),
                    )
                )

        total_commands = len(scene.device_states)
        success = len(failed_commands) == 0

        if success:
            message = f"Scene '{name}' applied successfully ({total_commands} commands)"
        else:
            message = f"Scene '{name}' applied with {len(failed_commands)} failures out of {total_commands} commands"

        return SceneSetResponse(
            success=success,
            scene_name=name,
            message=message,
            failed_commands=failed_commands,
        )

    def _is_scene_set_with_states(
        self, scene: Scene, device_states: dict[int, dict[str, any]]
    ) -> bool:
        """Internal method to check if scene is set using pre-fetched device states.

        Args:
            scene: The scene to check
            device_states: Dict mapping device_id to dict of attribute name->value

        Returns:
            True if all device states in scene match the provided values
        """
        for req in scene.device_states:
            current_attrs = device_states.get(req.device_id, {})
            if current_attrs.get(req.attribute) != req.value:
                return False
        return True

    async def is_scene_set(self, scene: Scene) -> bool:
        """Check if all device states in scene match current values."""
        # Collect unique device IDs needed for this scene
        device_ids = {req.device_id for req in scene.device_states}

        # Batch fetch device states in parallel
        device_states = await self._batch_fetch_device_states(device_ids)

        # Use internal method with fetched states
        return self._is_scene_set_with_states(scene, device_states)

    # Internal Methods
    async def _batch_fetch_device_states(
        self, device_ids: set[int]
    ) -> dict[int, dict[str, any]]:
        """Fetch device states for multiple devices in parallel.

        Args:
            device_ids: Set of device IDs to fetch states for

        Returns:
            Dict mapping device_id to dict of attribute name->value
        """
        if not device_ids:
            return {}

        # Create tasks for parallel fetching
        tasks = []
        device_id_list = list(device_ids)
        for device_id in device_id_list:
            task = asyncio.create_task(self.he_client.get_all_attributes(device_id))
            tasks.append(task)

        # Execute all fetches in parallel
        results = await asyncio.gather(*tasks)

        # Build result dictionary
        device_states = {}
        for device_id, attrs in zip(device_id_list, results):
            device_states[device_id] = attrs

        return device_states

    async def _send_command_safe(self, req: DeviceStateRequirement):
        """Send command and let exceptions bubble up for failure tracking."""
        arguments = req.arguments if req.arguments else None
        await self.he_client.send_command(req.device_id, req.command, arguments)
