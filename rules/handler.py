import asyncio as aio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timedelta
import inspect

from audit.decorators import audit_scope, log_audit_event
from hubitat import HubitatClient
from models.audit import EventSubtype, EventType
from models.database import DBRule
from rules.condition import AbstractCondition
from rules.engine import RuleEngine
from rules.interface import RuleUtilities
from scenes.manager import SceneManager

RuleTriggerProvider = Callable[[RuleUtilities], Awaitable[AbstractCondition]]
RuleRoutine = Callable[[RuleUtilities], Awaitable[None]]
TimerProvider = Callable[[], Awaitable[datetime]]


class RuleHandler:
    def __init__(
        self,
        rule_engine: RuleEngine,
        he_client: HubitatClient,
        scene_manager: SceneManager,
    ):
        self._rule_engine = rule_engine
        self._he_client = he_client
        self._scene_manager = scene_manager
        self._active_rules: dict[str, aio.Task] = {}

    @audit_scope(
        event_type=EventType.RULE_LIFECYCLE,
        end_event=EventSubtype.RULE_LOADED,
        error_event=EventSubtype.RULE_LOADED,
        rule_name="rule_name",
    )
    async def install_rule(self, rule: DBRule, rule_name: str):
        """Installs a rule that runs on a given trigger."""
        if rule.name in self._active_rules:
            raise ValueError(f"Rule '{rule.name}' already exists. Uninstall it first.")

        # TODO: Implement proper sandboxing/security for code execution
        # For now, execute directly in global namespace - THIS IS NOT SECURE

        try:
            # Create namespace and validate functions
            namespace = self._create_execution_namespace()

            # Execute and validate trigger provider
            if rule.trigger_code is None:
                raise ValueError("Rule trigger_code cannot be None")
            trigger_function = self._execute_and_validate_trigger_provider(
                rule.trigger_code, namespace
            )

            # Get the trigger condition by calling the function
            trigger_condition = await trigger_function(namespace["utils"])
            if not isinstance(trigger_condition, AbstractCondition):
                raise ValueError(
                    "get_trigger_condition must return an AbstractCondition"
                )

            # Execute and validate rule action
            rule_function = self._execute_and_validate_rule_action(
                rule.action_code, namespace
            )

            # Start the rule task
            task: aio.Task[None] = aio.create_task(
                self._run_rule_on_condition(
                    trigger_condition, rule_function, rule.name
                ),
                name=f"rule:{rule.name}",
            )
            self._active_rules[rule.name] = task

        except Exception as e:
            raise RuntimeError(f"Failed to install rule '{rule.name}': {e}") from e

    @audit_scope(
        event_type=EventType.RULE_LIFECYCLE,
        end_event=EventSubtype.RULE_LOADED,
        error_event=EventSubtype.RULE_LOADED,
        rule_name="rule_name",
    )
    async def install_scheduled_rule(self, rule: DBRule, rule_name: str):
        """Installs a rule that runs on a scheduled timer."""
        if rule.name in self._active_rules:
            raise ValueError(f"Rule '{rule.name}' already exists. Uninstall it first.")

        # TODO: Implement proper sandboxing/security for code execution
        # For now, execute directly in global namespace - THIS IS NOT SECURE

        try:
            # Create namespace and validate functions
            namespace = self._create_execution_namespace()

            # Execute and validate timer provider
            if rule.time_provider is None:
                raise ValueError("Rule time_provider cannot be None")
            timer_function = self._execute_and_validate_timer_provider(
                rule.time_provider, namespace
            )

            # Execute and validate rule action
            rule_function = self._execute_and_validate_rule_action(
                rule.action_code, namespace
            )

            # Start the scheduled rule task
            task: aio.Task[None] = aio.create_task(
                self._run_scheduled_rule(timer_function, rule_function, rule.name),
                name=f"scheduled_rule:{rule.name}",
            )
            self._active_rules[rule.name] = task

        except Exception as e:
            raise RuntimeError(
                f"Failed to install scheduled rule '{rule.name}': {e}"
            ) from e

    @audit_scope(
        event_type=EventType.RULE_LIFECYCLE,
        end_event=EventSubtype.RULE_DELETED,
        error_event=EventSubtype.RULE_DELETED,
        rule_name="rule_name",
    )
    async def uninstall_rule(self, rule: DBRule, rule_name: str):
        """Uninstall a rule"""
        if rule.name not in self._active_rules:
            raise ValueError(f"Rule '{rule.name}' does not exist")

        # Cancel the rule task
        task = self._active_rules[rule.name]
        task.cancel()

        with suppress(aio.CancelledError):
            await task

        # Remove from active rules
        del self._active_rules[rule.name]

    def get_active_rules(self) -> list[str]:
        """Get list of currently active rule names."""
        return list(self._active_rules.keys())

    def _create_execution_namespace(self) -> dict:
        """Create namespace for code execution with common utilities."""
        utils = RuleUtilities(self._rule_engine, self._he_client, self._scene_manager)
        return {
            "utils": utils,
            "timedelta": timedelta,
            "datetime": datetime,
        }

    def _validate_function_signature(
        self, func: Callable, name: str, expected_params: int
    ):
        """Generic function signature validation for async functions."""
        if not callable(func):
            raise ValueError(f"'{name}' must be a callable function")

        if not inspect.iscoroutinefunction(func):
            raise ValueError(f"'{name}' must be an async function")

        sig = inspect.signature(func)
        if len(sig.parameters) != expected_params:
            param_text = "parameter" if expected_params == 1 else "parameters"
            raise ValueError(
                f"'{name}' must accept exactly {expected_params} {param_text}"
            )

    def _execute_and_validate_rule_action(
        self, rule_code: str, namespace: dict
    ) -> RuleRoutine:
        """Execute rule code and validate rule_action function."""
        exec(rule_code, namespace)

        if "rule_action" not in namespace:
            raise ValueError("Rule code must define a 'rule_action' async function")

        rule_function: RuleRoutine = namespace["rule_action"]
        self._validate_function_signature(rule_function, "rule_action", 1)
        return rule_function

    def _execute_and_validate_timer_provider(
        self, timer_code: str, namespace: dict
    ) -> TimerProvider:
        """Execute timer code and validate get_next_time function."""
        exec(timer_code, namespace)

        if "get_next_time" not in namespace:
            raise ValueError("Timer code must define a 'get_next_time' function")

        timer_function: TimerProvider = namespace["get_next_time"]
        self._validate_function_signature(timer_function, "get_next_time", 0)
        return timer_function

    def _execute_and_validate_trigger_provider(
        self, trigger_code: str, namespace: dict
    ) -> RuleTriggerProvider:
        """Execute trigger code and validate get_trigger_condition function."""
        exec(trigger_code, namespace)

        if "get_trigger_condition" not in namespace:
            raise ValueError(
                "Trigger code must define a 'get_trigger_condition' function"
            )

        trigger_function: RuleTriggerProvider = namespace["get_trigger_condition"]
        self._validate_function_signature(trigger_function, "get_trigger_condition", 1)
        return trigger_function

    @audit_scope(rule_name="rule_name")
    async def _run_rule_on_condition(
        self, trigger: AbstractCondition, action: RuleRoutine, rule_name: str
    ):
        """Run a rule repeatedly when its trigger condition becomes true."""
        try:
            while True:
                # Wait for the condition to be true
                event = aio.Event()
                await self._rule_engine.add_condition(trigger, condition_event=event)
                await event.wait()

                # Log trigger fired
                await log_audit_event(
                    EventType.EXECUTION_LIFECYCLE,
                    EventSubtype.TRIGGER_FIRED,
                )

                # Remove the condition while running the rule
                await self._rule_engine.remove_condition(trigger)

                try:
                    # Log rule action start
                    await log_audit_event(
                        EventType.EXECUTION_LIFECYCLE,
                        EventSubtype.RULE_ACTION_STARTED,
                    )

                    # Run the rule
                    await action(
                        RuleUtilities(
                            self._rule_engine, self._he_client, self._scene_manager
                        )
                    )

                    # Log rule action completed
                    await log_audit_event(
                        EventType.EXECUTION_LIFECYCLE,
                        EventSubtype.RULE_ACTION_COMPLETED,
                        success=True,
                    )
                except Exception as e:
                    # Log rule action failed
                    await log_audit_event(
                        EventType.EXECUTION_LIFECYCLE,
                        EventSubtype.RULE_ACTION_FAILED,
                        success=False,
                        error_message=str(e),
                    )
                    print(f"Error executing rule: {e}")
        except aio.CancelledError:
            # Cleanup when rule is cancelled
            with suppress(Exception):
                await self._rule_engine.remove_condition(trigger)
            raise

    @audit_scope(rule_name="rule_name")
    async def _run_scheduled_rule(
        self, timer_provider: TimerProvider, action: RuleRoutine, rule_name: str
    ):
        """Run a rule repeatedly at scheduled times."""
        while (next_trigger := await timer_provider()) is not None:
            if next_trigger <= datetime.now():
                i = 0
                while next_trigger <= datetime.now() and i < 2:
                    i += 1
                    next_trigger = await timer_provider()
                if next_trigger <= datetime.now():
                    return

            # Wait until the trigger time then run the rule
            wait = next_trigger - datetime.now()
            await aio.sleep(wait.total_seconds())

            # Log trigger fired
            await log_audit_event(
                EventType.EXECUTION_LIFECYCLE,
                EventSubtype.TRIGGER_FIRED,
            )

            try:
                # Log rule action start
                await log_audit_event(
                    EventType.EXECUTION_LIFECYCLE,
                    EventSubtype.RULE_ACTION_STARTED,
                )

                await action(
                    RuleUtilities(
                        self._rule_engine, self._he_client, self._scene_manager
                    )
                )

                # Log rule action completed
                await log_audit_event(
                    EventType.EXECUTION_LIFECYCLE,
                    EventSubtype.RULE_ACTION_COMPLETED,
                    success=True,
                )
            except Exception as e:
                # Log rule action failed
                await log_audit_event(
                    EventType.EXECUTION_LIFECYCLE,
                    EventSubtype.RULE_ACTION_FAILED,
                    success=False,
                    error_message=str(e),
                )
                raise  # Re-raise to break the loop for scheduled rules
