import asyncio as aio
from abc import ABC, abstractmethod
from collections import deque
from datetime import timedelta
from typing import Awaitable, Callable

from hubitat import HubitatClient
from models.api import HubitatDeviceEvent


class EngineCondition(ABC):
    """A condition that the engine is tracking."""

    @property
    @abstractmethod
    def identifier(self) -> str:
        """Unique identifier for the condition."""

    @property
    def device_ids(self) -> list[int]:
        """The list of device IDs that this condition relies on"""
        return []

    @property
    def subconditions(self) -> list["EngineCondition"]:
        """Sub-conditions of this condition"""
        return []

    @property
    def timeout(self) -> timedelta | None:
        """Timeout for the condition."""
        return None

    @property
    def duration(self) -> timedelta | None:
        """Duration for the condition."""
        return None

    def on_device_event(self, event: HubitatDeviceEvent):
        """Invoked when an event occurs for a relevant device."""

    def on_condition_event(self, condition: "EngineCondition", triggered: bool):
        """Invoked when a subcondition changes state"""

    @abstractmethod
    def initialize(
        self, attrs: dict[int, dict[str, any]], conds: dict[str, bool]
    ) -> bool:
        """Invoked with the initial device attribute values and condition states.

        Returns true if the condition initializes to true"""

    @abstractmethod
    def evaluate(self) -> bool:
        """Evaluates if this condition is currently met"""


class ConditionNotifier:
    """Notifier for conditions."""

    def __init__(
        self,
        condition: EngineCondition,
        event: aio.Event | None = None,
        to_event: aio.Event | None = None,
    ):
        self._condition = condition
        self._event = event
        self._to_event = to_event

    @property
    def condition(self) -> EngineCondition:
        """Condition that triggered the event."""
        return self._condition

    def notify(self):
        """Notifies the condition."""
        if self._event is not None:
            self._event.set()

    def notify_timeout(self):
        """Notifies the condition of a timeout."""
        if self._to_event is not None:
            self._to_event.set()


class RuleEngine:
    """Engine for running rules."""

    def __init__(self, he_client: HubitatClient, timer_service):
        self._he_client = he_client
        self._timer_service = timer_service

        # ConditionId -> (Notifier, State)
        self._conditions: dict[str, tuple[ConditionNotifier, bool]] = {}

        # ConditionId -> set[DependentConditionId]
        self._condition_deps: dict[str, set[str]] = {}

        # DeviceId -> set[ConditionId]
        self._device_to_conditions: dict[int, set[str]] = {}

        # Protects the integrity of condition state
        self._engine_lock = aio.Lock()

    ####################
    # PUBLIC INTERFACE #
    ####################

    async def add_condition(
        self,
        condition: EngineCondition,
        condition_event: aio.Event | None = None,
        timeout_event: aio.Event | None = None,
    ):
        async with self._engine_lock:
            await self._add_condition(
                ConditionNotifier(condition, condition_event, timeout_event)
            )

    async def remove_condition(self, condition: EngineCondition):
        async with self._engine_lock:
            self._remove_condition(condition)

    def get_condition_state(self, condition: EngineCondition) -> bool:
        return self._conditions[condition.identifier][1]

    ############
    # REACTORS #
    ############

    async def on_device_event(self, event: HubitatDeviceEvent):
        device_id = int(event.device_id)

        # Find all conditions that care about this device
        if device_id in self._device_to_conditions:
            impacted_condition_ids = self._device_to_conditions[device_id]
            impacted = [
                self._conditions[cid][0]
                for cid in impacted_condition_ids
                if cid in self._conditions
            ]

            # Notify conditions of the device event
            for notifier in impacted:
                notifier.condition.on_device_event(event)

            await self._process_condition_change(impacted)

    def _on_condition_timeout(
        self, notifier: ConditionNotifier
    ) -> Callable[[str], Awaitable[None]]:
        """Handles a condition timeout"""

        async def _on_timeout(_timer_id: str):
            # We timed out, so stop waiting for the condition to become true
            await self.remove_condition(notifier.condition)
            notifier.notify_timeout()

        return _on_timeout

    #################
    # STATE UPDATES #
    #################

    def _propagate_state_update(
        self, notifiers: list[ConditionNotifier]
    ) -> list[ConditionNotifier]:
        """Propagates the state update to any dependent conditions

        Returns:
            List of conditions that were impacted by the state update
        """

        # We aren't de-duping on a visited set since we need all edges traversed
        work = deque(notifiers)
        touched_conditions: set[str] = set()
        while len(work) > 0:
            current = work.popleft()
            current_id = current.condition.identifier
            touched_conditions.add(current_id)
            current_state = self._conditions[current_id][1]
            new_state = current.condition.evaluate()

            # Update our tracking state if it has changed
            if new_state != current_state:
                self._conditions[current_id] = (current, new_state)

            # Process dependencies
            if current_id in self._condition_deps:
                for dep_cond_id in self._condition_deps[current_id]:
                    if dep_cond_id in self._conditions:
                        dep_cond = self._conditions[dep_cond_id][0].condition
                        dep_cond.on_condition_event(current.condition, new_state)
                        work.append(self._conditions[dep_cond_id][0])

        return [self._conditions[cid][0] for cid in touched_conditions]

    async def _process_condition_change(self, impacted: list[ConditionNotifier]):
        """Processes a condition change"""
        # Get a snapshot of our existing state so we can see what changed
        previous_state = {
            cid: self._conditions[cid][1] for cid in self._conditions.keys()
        }

        # Propagate the state change to transitively impacted conditions
        notifiers = self._propagate_state_update(impacted)

        for notifier in notifiers:
            curr = self._conditions[notifier.condition.identifier][1]
            prev = previous_state[notifier.condition.identifier]

            # When a condition becomes false, cancel the duration timer if it exists
            if (
                prev is True
                and curr is False
                and notifier.condition.duration is not None
            ):
                self._timer_service.cancel_timer(
                    f"condition_duration({notifier.condition.identifier})"
                )

            # When a condition with a duration becomes true, notify the event after the
            # condition remains true for the entire duration
            if (
                curr is True
                and prev is False
                and notifier.condition.duration is not None
            ):

                async def _notify_duration():
                    # When the duration timer expires remove the condition, cancel the
                    # timeout timer, and notify the event
                    await self.remove_condition(notifier.condition)
                    self._timer_service.cancel_timer(
                        f"condition_timeout({notifier.condition.identifier})"
                    )
                    notifier.notify()

                self._timer_service.start_timer(
                    f"condition_duration({notifier.condition.identifier})",
                    notifier.condition.duration,
                    _notify_duration,
                )
                return

            # When a condition becomes true, cancel the timeout timer if it exists then
            # notify the event
            if curr is True and prev is False:
                self._remove_condition(notifier.condition)
                self._timer_service.cancel_timer(
                    f"condition_timeout({notifier.condition.identifier})"
                )
                notifier.notify()

    ############
    # TRACKING #
    ############

    async def _add_condition(self, notifier: ConditionNotifier):
        condition = notifier.condition

        # Add device to condition mapping
        for device_id in condition.device_ids:
            if device_id not in self._device_to_conditions:
                self._device_to_conditions[device_id] = set()
            self._device_to_conditions[device_id].add(condition.identifier)

        # Initialize the subconditions
        init_cond_states = await self._initialize_sub_conditions(condition)

        # Fetch all attributes for all devices this condition cares about
        init_attrs: dict[int, dict[str, any]] = {}
        for device_id in condition.device_ids:
            init_attrs[device_id] = await self._he_client.get_all_attributes(device_id)

        # Initialize the condition
        state = condition.initialize(init_attrs, init_cond_states)
        self._conditions[condition.identifier] = (notifier, state)

        # Start timeout timer if condition has a timeout
        if condition.timeout is not None:
            await self._timer_service.start_timer(
                f"condition_timeout({condition.identifier})",
                condition.timeout,
                self._on_condition_timeout(notifier),
            )

        # Handle conditions that are immediately true
        if state is True:
            if condition.duration is not None:
                # Start duration timer if condition has a duration
                await self._timer_service.start_timer(
                    f"condition_duration({condition.identifier})",
                    condition.duration,
                    lambda _: notifier.notify(),
                )
            else:
                # Condition is immediately true and has no duration - fire immediately
                self._timer_service.cancel_timer(
                    f"condition_timeout({condition.identifier})"
                )
                self._remove_condition(condition)
                notifier.notify()

    def _remove_condition(self, condition: EngineCondition):
        # Cancel timeout timer if it exists
        self._timer_service.cancel_timer(f"condition_timeout({condition.identifier})")
        self._timer_service.cancel_timer(f"condition_duration({condition.identifier})")

        # Remove condition from tracking
        if condition.identifier in self._conditions:
            del self._conditions[condition.identifier]

            # Remove condition from device mapping
            for device_id in condition.device_ids:
                if device_id in self._device_to_conditions:
                    self._device_to_conditions[device_id].discard(condition.identifier)
                    # Clean up empty device entries
                    if len(self._device_to_conditions[device_id]) == 0:
                        del self._device_to_conditions[device_id]

            # Recursively remove conditions from dependencies
            if condition.identifier in self._condition_deps:
                del self._condition_deps[condition.identifier]
            for sub_condition in condition.subconditions:
                if sub_condition.identifier in self._conditions:
                    self._remove_condition(sub_condition)

    ##################
    # INITIALIZATION #
    ##################

    async def _initialize_sub_conditions(
        self, condition: EngineCondition
    ) -> dict[str, bool]:
        init_cond_states: dict[str, bool] = {}
        for sub_condition in condition.subconditions:
            if sub_condition.identifier not in self._conditions:
                if sub_condition.identifier not in self._condition_deps:
                    self._condition_deps[sub_condition.identifier] = set()
                self._condition_deps[sub_condition.identifier].add(condition.identifier)
                await self._add_condition(ConditionNotifier(sub_condition))  # RECURSION
            init_cond_states[sub_condition.identifier] = self._conditions[
                sub_condition.identifier
            ][1]
        return init_cond_states
