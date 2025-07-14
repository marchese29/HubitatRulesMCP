from abc import ABC, abstractmethod
import asyncio as aio
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import timedelta
from enum import Enum
import logging
import time
from typing import Any

from ..audit.decorators import log_audit_event
from ..hubitat import HubitatClient
from ..models.api import HubitatDeviceEvent
from ..models.audit import EventSubtype, EventType

logger = logging.getLogger(__name__)


class ConditionState(Enum):
    """Represents the state of a condition in the engine."""

    FALSE = "false"
    DURATION_PENDING = "duration_pending"  # True but waiting for duration
    TRUE = "true"  # Actually fired/completed


class EngineCondition(ABC):
    """A condition that the engine is tracking."""

    def __init__(self):
        # Create unique instance ID using timestamp + object ID
        # This avoids any threading/async safety concerns
        self._instance_id = int(time.time_ns()) + id(self)

    @property
    def instance_id(self) -> int:
        """Unique instance identifier for this condition."""
        return self._instance_id

    @property
    @abstractmethod
    def identifier(self) -> str:
        """Human-readable identifier for the condition."""

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
        pass

    def on_condition_event(self, condition: "EngineCondition", triggered: bool):
        """Invoked when a subcondition changes state"""
        pass

    @abstractmethod
    def initialize(
        self, attrs: dict[int, dict[str, Any]], conds: dict[str, bool]
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

        # ConditionInstanceId -> (Notifier, State)
        self._conditions: dict[int, tuple[ConditionNotifier, ConditionState]] = {}

        # ConditionInstanceId -> set[DependentConditionInstanceId]
        self._condition_deps: dict[int, set[int]] = {}

        # DeviceId -> set[ConditionInstanceId]
        self._device_to_conditions: dict[int, set[int]] = {}

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
        """Get the boolean state of a condition.

        Returns False if condition doesn't exist (e.g., timed out).
        DURATION_PENDING conditions are treated as False to prevent
        dependent conditions from triggering prematurely.
        """
        try:
            state = self._conditions[condition.instance_id][1]
            return state == ConditionState.TRUE
        except KeyError:
            # Condition doesn't exist (likely timed out) - treat as FALSE
            logger.debug(
                "Condition %s not found in engine (likely timed out), returning False",
                condition.identifier,
            )
            return False

    ############
    # REACTORS #
    ############

    async def on_device_event(self, event: HubitatDeviceEvent):
        device_id = int(event.device_id)
        logger.info("Processing device event: %r", event)

        # Find all conditions that care about this device
        if device_id in self._device_to_conditions:
            impacted_condition_ids = self._device_to_conditions[device_id]
            impacted = [
                self._conditions[cid][0]
                for cid in impacted_condition_ids
                if cid in self._conditions
            ]
            logger.debug(
                "Device event %r wakes up conditions %s", event, impacted_condition_ids
            )

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
            await log_audit_event(
                EventType.EXECUTION_LIFECYCLE,
                EventSubtype.CONDITION_TIMEOUT,
                condition_id=notifier.condition.identifier,
            )
            logger.info("Condition %s timed out", notifier.condition.identifier)
            notifier.notify_timeout()

        return _on_timeout

    async def _handle_duration_completion(self, notifier: ConditionNotifier):
        """Handle completion of a duration timer for a condition."""
        condition = notifier.condition
        condition_id = condition.identifier  # For logging
        condition_instance_id = condition.instance_id  # For tracking

        # 1. Audit log showing the condition is now true
        assert condition.duration is not None
        logger.info(
            "Condition %s remained true for its duration of %f seconds",
            condition_id,
            condition.duration.total_seconds(),
        )
        await log_audit_event(
            EventType.EXECUTION_LIFECYCLE,
            EventSubtype.CONDITION_NOW_TRUE,
            condition_id=condition_id,
        )

        async with self._engine_lock:
            if condition_instance_id in self._conditions:
                current_notifier, current_state = self._conditions[
                    condition_instance_id
                ]
                if current_state == ConditionState.DURATION_PENDING:
                    # 2. Cancel timeout timer
                    logger.debug(
                        "Cancelling any timeouts on condition %s", condition_id
                    )
                    self._timer_service.cancel_timer(
                        f"condition_timeout({condition_instance_id})"
                    )

                    # 3. Update current state in the engine for the condition
                    self._conditions[condition_instance_id] = (
                        current_notifier,
                        ConditionState.TRUE,
                    )

                    # 4. Propagate to any conditions depending on the current one
                    logger.debug("Identifying dependents of condition %s", condition_id)
                    dependent_notifiers = []
                    if condition_instance_id in self._condition_deps:
                        for parent_id in self._condition_deps[condition_instance_id]:
                            if parent_id in self._conditions:
                                parent_notifier = self._conditions[parent_id][0]
                                dependent_notifiers.append(parent_notifier)

                                # Explicitly notify parent that child became TRUE
                                parent_notifier.condition.on_condition_event(
                                    condition, True
                                )

                    # Let the existing logic handle propagation and firing
                    if len(dependent_notifiers) > 0:
                        logger.debug(
                            "Propagating change in condition %s to its %d children",
                            condition_id,
                            len(dependent_notifiers),
                        )
                        await self._process_condition_change(dependent_notifiers)

                    # 5. If nobody depends on current condition, remove it
                    if not self._has_dependents(condition):
                        logger.debug(
                            "Condition %s has no dependents, removing it", condition_id
                        )
                        self._remove_condition(condition)

        # 6. Notify for the current condition
        logger.info("Notifying of condition %s state change", condition_id)
        notifier.notify()

    #################
    # STATE UPDATES #
    #################

    async def _propagate_state_update(
        self, notifiers: list[ConditionNotifier]
    ) -> list[ConditionNotifier]:
        """Propagates the state update to any dependent conditions

        Returns:
            List of conditions that were impacted by the state update
        """

        # We aren't de-duping on a visited set since we need all edges traversed
        work = deque(notifiers)
        touched_conditions: set[int] = set()
        while len(work) > 0:
            current = work.popleft()
            current_instance_id = current.condition.instance_id
            current_identifier = current.condition.identifier  # For logging
            touched_conditions.add(current_instance_id)
            current_state = self._conditions[current_instance_id][1]
            condition_evaluated = current.condition.evaluate()

            # Convert boolean evaluation to ConditionState
            # If condition has duration and evaluates to True, it should be DURATION_PENDING initially
            if condition_evaluated and current.condition.duration is not None:
                new_state = ConditionState.DURATION_PENDING
            elif condition_evaluated:
                new_state = ConditionState.TRUE
            else:
                new_state = ConditionState.FALSE

            # Update our tracking state if it has changed
            if new_state != current_state:
                self._conditions[current_instance_id] = (current, new_state)
                # Audit the state change
                await log_audit_event(
                    EventType.EXECUTION_LIFECYCLE,
                    EventSubtype.CONDITION_NOW_TRUE,
                    condition_id=current_identifier,
                    previous_state=current_state.value,
                    new_state=new_state.value,
                )

            # Process dependencies - notify parents when child condition changes
            # _condition_deps maps child_instance_id -> {parent_instance_id}, so when current_instance_id changes,
            # we need to notify all parents that depend on it
            if current_instance_id in self._condition_deps:
                for parent_id in self._condition_deps[current_instance_id]:
                    if parent_id in self._conditions:
                        parent_cond = self._conditions[parent_id][0].condition
                        # Only pass True if condition is actually TRUE (not DURATION_PENDING)
                        effective_state = new_state == ConditionState.TRUE
                        parent_cond.on_condition_event(
                            current.condition, effective_state
                        )
                        work.append(self._conditions[parent_id][0])

        return [self._conditions[cid][0] for cid in touched_conditions]

    async def _process_condition_change(self, impacted: list[ConditionNotifier]):
        """Processes a condition change"""
        # Get a snapshot of our existing state so we can see what changed
        previous_state = {cid: self._conditions[cid][1] for cid in self._conditions}

        # Propagate the state change to transitively impacted conditions
        notifiers = await self._propagate_state_update(impacted)

        for notifier in notifiers:
            await log_audit_event(
                EventType.EXECUTION_LIFECYCLE,
                EventSubtype.CONDITION_EVALUATED,
                condition_id=notifier.condition.identifier,
            )
            logger.debug(
                "Processing state update on condition %s", notifier.condition.identifier
            )

            # Check if condition still exists (might have been removed due to timeout/dependency)
            if notifier.condition.instance_id not in self._conditions:
                logger.debug(
                    "Condition %s no longer exists during processing, skipping",
                    notifier.condition.identifier,
                )
                continue

            curr = self._conditions[notifier.condition.instance_id][1]
            prev = previous_state[notifier.condition.instance_id]

            # When a condition becomes false, cancel the duration timer if it exists
            if (
                prev in (ConditionState.TRUE, ConditionState.DURATION_PENDING)
                and curr == ConditionState.FALSE
                and notifier.condition.duration is not None
            ):
                logger.debug(
                    "Condition %s became false before duration of %f seconds",
                    notifier.condition.identifier,
                    notifier.condition.duration.total_seconds(),
                )
                self._timer_service.cancel_timer(
                    f"condition_duration({notifier.condition.instance_id})"
                )

            # When a condition with a duration becomes DURATION_PENDING, start duration timer
            if (
                curr == ConditionState.DURATION_PENDING
                and prev == ConditionState.FALSE
                and notifier.condition.duration is not None
            ):

                def _make_notify_duration(captured_notifier: ConditionNotifier):
                    async def _notify_duration(_timer_id: str):
                        # When the duration timer expires, use shared completion logic
                        assert captured_notifier.condition.duration is not None
                        logger.info(
                            "Condition %s has been true for %f seconds, propagating state "
                            "and notifying",
                            captured_notifier.condition.identifier,
                            captured_notifier.condition.duration.total_seconds(),
                        )
                        await self._handle_duration_completion(captured_notifier)

                    return _notify_duration

                # Duration conditions are now properly handled with DURATION_PENDING state
                # to prevent dependent conditions from triggering prematurely
                logger.debug(
                    "Condition %s became true, waiting for duration of %f seconds before "
                    "activating",
                    notifier.condition.identifier,
                    notifier.condition.duration.total_seconds(),
                )
                await self._timer_service.start_timer(
                    f"condition_duration({notifier.condition.instance_id})",
                    notifier.condition.duration,
                    _make_notify_duration(notifier),
                )
                return

            # When a condition becomes TRUE (without duration), notify immediately
            if curr == ConditionState.TRUE and prev == ConditionState.FALSE:
                logger.info(
                    "Condition %s became true, notifying event loop",
                    notifier.condition.identifier,
                )
                self._remove_condition(notifier.condition)
                self._timer_service.cancel_timer(
                    f"condition_timeout({notifier.condition.instance_id})"
                )
                notifier.notify()

    ###################
    # HELPER METHODS  #
    ###################

    def _has_dependents(self, condition: EngineCondition) -> bool:
        """Check if any conditions depend on this condition."""
        condition_instance_id = condition.instance_id
        for dependent_set in self._condition_deps.values():
            if condition_instance_id in dependent_set:
                return True
        return False

    ############
    # TRACKING #
    ############

    async def _add_condition(self, notifier: ConditionNotifier):
        condition = notifier.condition
        logger.info("Adding condition %s to engine tracking", condition.identifier)
        if len(condition.device_ids) > 0:
            logger.debug(
                "Registering condition %s for tracking on devices: %s",
                condition.identifier,
                condition.device_ids,
            )

        # Add device to condition mapping
        for device_id in condition.device_ids:
            if device_id not in self._device_to_conditions:
                self._device_to_conditions[device_id] = set()
            self._device_to_conditions[device_id].add(condition.instance_id)

        # Initialize the subconditions
        if len(condition.subconditions) > 0:
            logger.debug(
                "Registering %i sub-conditions for condition: %s",
                len(condition.subconditions),
                condition.identifier,
            )
        init_cond_states = await self._initialize_sub_conditions(condition)

        # Fetch all attributes for all devices this condition cares about
        init_attrs = await self._he_client.get_bulk_attributes(condition.device_ids)

        # Initialize the condition
        initial_bool_state = condition.initialize(init_attrs, init_cond_states)

        # Convert boolean to ConditionState
        if initial_bool_state and condition.duration is not None:
            initial_state = ConditionState.DURATION_PENDING
        elif initial_bool_state:
            initial_state = ConditionState.TRUE
        else:
            initial_state = ConditionState.FALSE

        self._conditions[condition.instance_id] = (notifier, initial_state)

        # Start timeout timer if condition has a timeout
        if condition.timeout is not None:
            logger.debug(
                "Condition %s will timeout after %f seconds",
                condition.identifier,
                condition.timeout.total_seconds(),
            )
            await self._timer_service.start_timer(
                f"condition_timeout({condition.instance_id})",
                condition.timeout,
                self._on_condition_timeout(notifier),
            )

        # Handle conditions that are immediately true
        if initial_state == ConditionState.DURATION_PENDING:
            # Start duration timer if condition has a duration
            assert (
                condition.duration is not None
            )  # guaranteed by DURATION_PENDING state
            logger.debug(
                "Condition %s started true, waiting for duration of %f seconds",
                condition.identifier,
                condition.duration.total_seconds(),
            )

            # Create proper async callback for duration completion
            async def _notify_on_duration_complete(_timer_id: str):
                # Use shared duration completion logic
                await self._handle_duration_completion(notifier)

            await self._timer_service.start_timer(
                f"condition_duration({condition.instance_id})",
                condition.duration,
                _notify_on_duration_complete,
            )

        # Condition is done being initialized
        logger.info(
            "Condition %s initialized as %s", condition.identifier, initial_state
        )

    def _remove_condition(self, condition: EngineCondition):
        # Fixed: Now using instance_id for unique tracking instead of potentially colliding identifiers
        logger.info("Removing condition %s from engine tracking", condition.identifier)

        # Cancel timeout timer if it exists
        self._timer_service.cancel_timer(f"condition_timeout({condition.instance_id})")
        self._timer_service.cancel_timer(f"condition_duration({condition.instance_id})")

        # Remove condition from tracking
        if condition.instance_id in self._conditions:
            del self._conditions[condition.instance_id]

            # Remove condition from device mapping
            for device_id in condition.device_ids:
                if device_id in self._device_to_conditions:
                    self._device_to_conditions[device_id].discard(condition.instance_id)
                    # Clean up empty device entries
                    if len(self._device_to_conditions[device_id]) == 0:
                        del self._device_to_conditions[device_id]

            # Recursively remove conditions from dependencies
            if condition.instance_id in self._condition_deps:
                del self._condition_deps[condition.instance_id]
            for sub_condition in condition.subconditions:
                if sub_condition.instance_id in self._conditions:
                    logger.debug(
                        "Removing sub-condition %s of condition %s",
                        sub_condition.identifier,
                        condition.identifier,
                    )
                    self._remove_condition(sub_condition)

    ##################
    # INITIALIZATION #
    ##################

    async def _initialize_sub_conditions(
        self, condition: EngineCondition
    ) -> dict[str, bool]:
        init_cond_states: dict[str, bool] = {}
        for sub_condition in condition.subconditions:
            # Always establish dependency relationship
            if sub_condition.instance_id not in self._condition_deps:
                self._condition_deps[sub_condition.instance_id] = set()
            self._condition_deps[sub_condition.instance_id].add(condition.instance_id)

            # Add subcondition if it doesn't exist
            if sub_condition.instance_id not in self._conditions:
                await self._add_condition(ConditionNotifier(sub_condition))  # RECURSION

            # Convert ConditionState to boolean for API compatibility
            condition_state = self._conditions[sub_condition.instance_id][1]
            init_cond_states[sub_condition.identifier] = (
                condition_state == ConditionState.TRUE
            )
        return init_cond_states
