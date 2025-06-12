from sqlmodel import Session, select

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
        rule = DBRule(name, trigger_code, action_code)
        session.add(rule)
        self._rule_handler.install_rule(rule)
        return rule

    @transactional
    async def install_timer_rule(
        self, session: Session, name: str, time_provider: str, action_code: str
    ) -> DBRule:
        rule = DBRule(name, time_provider, action_code)
        session.add(rule)
        await self._rule_handler.install_scheduled_rule(rule)
        return rule

    @transactional
    async def uninstall_rule(self, session: Session, name: str) -> DBRule:
        rule = session.exec(select(DBRule).where(DBRule.name == name)).one()
        session.delete(rule)
        await self._rule_handler.uninstall_rule(rule)
        return rule
