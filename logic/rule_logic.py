from sqlmodel import Session, select

from models.api import RuleInfo
from models.database import DBRule
from rules.handler import RuleHandler
from util import transactional


class RuleLogic:
    def __init__(self, rule_handler: RuleHandler):
        self._rule_handler = rule_handler

    @transactional
    async def install_trigger_rule(
        self, session: Session, name: str, trigger_code: str, action_code: str
    ) -> DBRule:
        rule = DBRule(name=name, trigger_code=trigger_code, action_code=action_code)
        session.add(rule)
        self._rule_handler.install_rule(rule)
        return rule

    @transactional
    async def install_timer_rule(
        self, session: Session, name: str, time_provider: str, action_code: str
    ) -> DBRule:
        rule = DBRule(name=name, time_provider=time_provider, action_code=action_code)
        session.add(rule)
        await self._rule_handler.install_scheduled_rule(rule)
        return rule

    @transactional
    async def uninstall_rule(self, session: Session, name: str) -> DBRule:
        rule = session.exec(select(DBRule).where(DBRule.name == name)).one()
        session.delete(rule)
        await self._rule_handler.uninstall_rule(rule)
        return rule

    @transactional
    async def get_rules(
        self, session: Session, name: str | None = None, rule_type: str | None = None
    ) -> list[RuleInfo]:
        """Get rules with optional filtering.

        Args:
            name: Get specific rule by name
            rule_type: Filter by "condition" or "scheduled"

        Returns:
            List of rules with current status
        """
        # Build query based on filters
        query = select(DBRule)

        if name:
            query = query.where(DBRule.name == name)

        if rule_type:
            if rule_type == "scheduled":
                query = query.where(DBRule.time_provider.is_not(None))
            elif rule_type == "condition":
                query = query.where(DBRule.time_provider.is_(None))

        # Execute query and get results
        rules = session.exec(query).all()

        # Get active rule names for status checking
        active_rule_names = set(self._rule_handler.get_active_rules())

        # Convert to RuleInfo objects
        rule_infos = []
        for rule in rules:
            # Determine rule type
            if rule.time_provider is not None:
                current_rule_type = "scheduled"
                trigger_code = rule.time_provider
            else:
                current_rule_type = "condition"
                trigger_code = rule.trigger_code

            # Create RuleInfo object
            rule_info = RuleInfo(
                name=rule.name,
                rule_type=current_rule_type,
                trigger_code=trigger_code,
                action_code=rule.action_code,
                is_active=rule.name in active_rule_names,
            )
            rule_infos.append(rule_info)

        return rule_infos
