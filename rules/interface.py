import asyncio as aio
from datetime import datetime, time, timedelta
from typing import Self

from hubitat import HubitatClient
from rules.condition import (
    AbstractCondition,
    AlwaysFalseCondition,
    AttributeChangeCondition,
    BooleanCondition,
    DynamicDeviceAttributeCondition,
    SceneChangeCondition,
    StaticDeviceAttributeCondition,
)
from rules.engine import RuleEngine
from scenes.manager import SceneManager
from models.api import SceneSetResponse


class Attribute:
    """An attribute of a device."""

    def __init__(self, device_id: int, attr_name: str, he_client: HubitatClient):
        self._device_id = device_id
        self._attr_name = attr_name
        self._he_client = he_client

    async def fetch(self) -> any:
        """Fetch the current value of this attribute from Hubitat.

        Returns:
            The current value of the attribute
        """
        attributes = await self._he_client.get_all_attributes(self._device_id)
        return attributes.get(self._attr_name)

    def _compare(self, other: any, op: str) -> AbstractCondition:
        """Helper method to handle all comparison operations.

        Args:
            other: Value to compare against
            op: Comparison operator to use
        Returns:
            Appropriate condition object for the comparison
        """
        if isinstance(other, Attribute):
            return DynamicDeviceAttributeCondition(
                (self._device_id, self._attr_name),
                op,
                (other._device_id, other._attr_name),
            )
        else:
            return StaticDeviceAttributeCondition(
                self._device_id, self._attr_name, op, other
            )

    def __gt__(self, other: any) -> AbstractCondition:
        return self._compare(other, ">")

    def __ge__(self, other: any) -> AbstractCondition:
        return self._compare(other, ">=")

    def __lt__(self, other: any) -> AbstractCondition:
        return self._compare(other, "<")

    def __le__(self, other: any) -> AbstractCondition:
        return self._compare(other, "<=")

    def __eq__(self, other: any) -> AbstractCondition:
        return self._compare(other, "=")

    def __ne__(self, other: any) -> AbstractCondition:
        return self._compare(other, "!=")


class Command:
    """A command to be sent to a device."""

    def __init__(self, he_client: HubitatClient, device_id: int, command: str):
        self._he_client = he_client
        self._device_id = device_id
        self._command = command

    async def __call__(self, *args: any, **_: any) -> None:
        await self._he_client.send_command(self._device_id, self._command, *args)


class Device:
    """A hubitat device."""

    def __init__(self, device_id: int, he_client: HubitatClient):
        self._device_id = device_id
        self._he_client = he_client
        self._he_device = None  # Cache for the fetched device
        self._loaded = False  # Track if device data has been loaded

    async def load(self) -> Self:
        """Load device data from the Hubitat API.

        Returns:
            Self for method chaining
        """
        self._he_device = await self._he_client.device_by_id(self._device_id)
        self._loaded = True
        return self

    def _check_loaded(self):
        """Check if device is loaded, raise error if not."""
        if not self._loaded:
            raise RuntimeError(
                f"Device {self._device_id} is not loaded. Call load() first."
            )

    def __getattr__(self, attr_name: str) -> Attribute | Command:
        self._check_loaded()

        if self._he_device.has_attribute(attr_name):
            return Attribute(self._device_id, attr_name, self._he_client)
        elif self._he_device.has_command(attr_name):
            return Command(self._he_client, self._device_id, attr_name)
        else:
            raise AttributeError(
                f"Attribute or command '{attr_name}' not found on device {self._device_id}"
            )


class Scene:
    """A Hubitat scene."""

    def __init__(self, scene_name: str, scene_manager: SceneManager):
        self._scene_name = scene_name
        self._scene_manager = scene_manager

    @property
    async def is_set(self) -> bool:
        """Check if this scene is currently active.

        Returns:
            True if all device states in the scene match current values
        """
        scenes = await self._scene_manager.get_scenes(name=self._scene_name)
        if not scenes:
            raise ValueError(f"Scene '{self._scene_name}' not found")
        return scenes[0].is_set

    async def enable(self) -> SceneSetResponse:
        """Apply/activate this scene.

        Returns:
            SceneSetResponse with success status and any failed commands
        """
        return await self._scene_manager.set_scene(self._scene_name)

    async def on_set(self) -> AbstractCondition:
        """Return a condition that triggers when this scene becomes set.

        Returns:
            AbstractCondition that is true when all scene device states match
        """
        try:
            scenes = await self._scene_manager.get_scenes(name=self._scene_name)
            if not scenes:
                # Return a condition that's never true for missing scenes
                return AlwaysFalseCondition(f"scene_missing:{self._scene_name}")

            # Convert each device requirement to a condition
            device_conditions = []
            for req in scenes[0].device_states:
                condition = StaticDeviceAttributeCondition(
                    req.device_id, req.attribute, "=", req.value
                )
                device_conditions.append(condition)

            if not device_conditions:
                # Empty scene - return a condition that's always false
                return AlwaysFalseCondition(f"scene_empty:{self._scene_name}")

            # Scene is set when ALL conditions are true
            return BooleanCondition(*device_conditions, operator="and")

        except Exception as e:
            # Any error - return a condition that's never true
            return AlwaysFalseCondition(f"scene_error:{self._scene_name}:{str(e)}")

    async def on_change(self) -> AbstractCondition:
        """Return a condition that triggers when this scene state changes.

        Returns:
            AbstractCondition that triggers on any scene state change (set ↔ not set)
        """
        try:
            # Get the base scene condition (same as on_set)
            scene_condition = await self.on_set()

            # If the scene condition is AlwaysFalse, just return it directly
            if isinstance(scene_condition, AlwaysFalseCondition):
                return scene_condition

            # Wrap in change detection
            return SceneChangeCondition(self._scene_name, scene_condition)

        except Exception as e:
            # Any error - return a condition that's never true
            return AlwaysFalseCondition(
                f"scene_change_error:{self._scene_name}:{str(e)}"
            )


class RuleUtilities:
    """Utilities for building rules."""

    def __init__(
        self, engine: RuleEngine, he_client: HubitatClient, scene_manager: SceneManager
    ):
        self._engine = engine
        self._he_client = he_client
        self._scene_manager = scene_manager

    def device(self, device_id: int) -> Device:
        """Get a device by its id."""
        return Device(device_id, self._he_client)

    def scene(self, scene_name: str) -> Scene:
        """Get a scene by its name."""
        return Scene(scene_name, self._scene_manager)

    def all_of(self, *conditions: AbstractCondition) -> AbstractCondition:
        """Condition that checks if all subconditions are true."""
        return BooleanCondition(*conditions, operator="and")

    def any_of(self, *conditions: AbstractCondition) -> AbstractCondition:
        """Condition that checks if any subcondition is true."""
        return BooleanCondition(*conditions, operator="or")

    def is_not(self, condition: AbstractCondition) -> AbstractCondition:
        """Condition that checks if a subcondition is false."""
        return BooleanCondition(condition, operator="not")

    def on_change(self, attr: Attribute) -> AbstractCondition:
        """Create a condition that triggers when an attribute changes.

        This is for use in trigger code to create conditions.
        For waiting in action code, use wait_for_change() instead.

        Args:
            attr: The device attribute to monitor for changes

        Returns:
            AttributeChangeCondition that can be used in trigger code
        """
        return AttributeChangeCondition(attr._device_id, attr._attr_name)

    async def wait(self, for_time: timedelta):
        """Wait for a period of time.

        Args:
            for_time: The amount of time to wait for
        """
        await aio.sleep(for_time.total_seconds())

    async def wait_for(
        self,
        condition: AbstractCondition,
        timeout: timedelta | None = None,
        for_duration: timedelta | None = None,
    ) -> bool:
        """Wait for a condition to be true.

        Args:
            condition: The condition to wait for.
            timeout: The timeout for the condition to be true.
            for_duration: How long the condition must be true for (default is immediate)
        Returns:
            True if the condition is true after waiting, False if otherwise
        """
        if timeout is not None and for_duration is not None and timeout <= for_duration:
            raise ValueError("Timeout must be longer than duration")

        if for_duration is not None:
            condition.duration = for_duration

        return await self._wait_for_condition(condition, timeout)

    async def wait_for_change(
        self,
        attr: Attribute,
        timeout: timedelta | None = None,
    ) -> bool:
        """Wait for an attribute to change.

        Args:
            attr: The attribute to wait for.
            timeout: The timeout for the attribute to change.

        Returns:
            True if the attribute changed, False if otherwise (timeout)
        """
        condition = AttributeChangeCondition(attr._device_id, attr._attr_name)
        return await self.wait_for(condition, timeout)

    async def wait_until(self, t: time):
        """Wait until a given time.

        Args:
            t: The time to wait until.
        """
        now = datetime.now()
        target_time = datetime.combine(now.date(), t)
        if target_time < now:
            target_time = datetime.combine(now.date().replace(day=now.day + 1), t)
        wait_time = target_time - now
        await aio.sleep(wait_time.total_seconds())

    async def check(self, condition: AbstractCondition) -> bool:
        """Check if a condition is true.

        Args:
            condition: The condition to check.

        Returns:
            True if the condition is true, False otherwise
        """
        await self._engine.add_condition(condition)
        result = self._engine.get_condition_state(condition)
        self._engine.remove_condition(condition)
        return result

    async def _wait_for_condition(
        self,
        condition: AbstractCondition,
        timeout: timedelta | None = None,
    ) -> bool:
        """Internal helper to wait for a condition with optional timeout.

        Args:
            condition: The condition to wait for
            timeout: Optional timeout for the condition

        Returns:
            True if the condition was met, False if timed out
        """
        event = aio.Event()
        timeout_event = None
        if timeout is not None:
            timeout_event = aio.Event()
            condition.timeout = timeout

        await self._engine.add_condition(
            condition, condition_event=event, timeout_event=timeout_event
        )

        # Wait for the condition to become true or for timeout
        if timeout_event is not None:
            tasks = [
                aio.create_task(event.wait(), name="condition"),
                aio.create_task(timeout_event.wait(), name="timeout"),
            ]
            done, pending = await aio.wait(tasks, return_when=aio.FIRST_COMPLETED)
            # Cancel any pending tasks
            for task in pending:
                task.cancel()

            # Remove the condition from tracking
            self._engine.remove_condition(condition)

            # Check which task completed
            completed_task = done.pop()
            return completed_task.get_name() != "timeout"
        else:
            await event.wait()
            # Remove the condition from tracking
            self._engine.remove_condition(condition)
            return True
