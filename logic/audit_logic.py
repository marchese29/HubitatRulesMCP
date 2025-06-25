from datetime import datetime, timedelta
import json

from sqlalchemy import desc
from sqlmodel import Session, select

from models.api import AuditLogQueryResponse, PaginationInfo, RuleExecutionData
from models.audit import AuditLog, EventType
from util import transactional

# Template for rule execution analysis summary
RULE_EXECUTION_SUMMARY_TEMPLATE = """
Rule Execution Analysis Data:
- Date Range: {start_date} to {end_date}
- Total Executions: {total_executions}
- Successful: {successful_executions}
- Failed: {failed_executions}
- Rule Filter: {rule_name}

Recent Execution Details:
{execution_details}
"""


class AuditLogic:
    """Business logic for audit operations"""

    @transactional
    async def query_audit_logs(
        self,
        session: Session,
        event_type: str | None = None,
        event_subtype: str | None = None,
        rule_name: str | None = None,
        scene_name: str | None = None,
        device_id: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> AuditLogQueryResponse:
        """Query audit logs with filtering and pagination.

        Args:
            session: Database session
            event_type: Filter by event type
            event_subtype: Filter by event subtype
            rule_name: Filter by specific rule name
            scene_name: Filter by specific scene name
            device_id: Filter by device ID
            start_date: Start date filter (ISO format)
            end_date: End date filter (ISO format)
            page: Page number (starts at 1)
            page_size: Number of results per page

        Returns:
            AuditLogQueryResponse with audit log entries and pagination info
        """
        # Build query with filters
        query = select(AuditLog)

        # Apply filters
        if event_type:
            query = query.where(AuditLog.event_type == event_type)
        if event_subtype:
            query = query.where(AuditLog.event_subtype == event_subtype)
        if rule_name:
            query = query.where(AuditLog.rule_name == rule_name)
        if scene_name:
            query = query.where(AuditLog.scene_name == scene_name)
        if device_id:
            query = query.where(AuditLog.device_id == device_id)
        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            query = query.where(AuditLog.timestamp >= start_dt)
        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            query = query.where(AuditLog.timestamp <= end_dt)

        # Order by timestamp descending (most recent first)
        query = query.order_by(desc(AuditLog.timestamp))  # type: ignore[arg-type]

        # Count total records
        count_query = select(AuditLog.id).select_from(query.subquery())
        total_records = len(session.exec(count_query).all())

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size)

        # Execute query
        audit_logs = session.exec(query).all()

        # Build pagination info
        total_pages = (total_records + page_size - 1) // page_size
        pagination = PaginationInfo(
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            total_records=total_records,
            has_next=page < total_pages,
            has_prev=page > 1,
        )

        return AuditLogQueryResponse(
            data=[log.model_dump() for log in audit_logs],
            pagination=pagination,
        )

    @transactional
    async def get_rule_execution_data(
        self,
        session: Session,
        rule_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        include_successful: bool = True,
        include_failed: bool = True,
    ) -> RuleExecutionData:
        """Get rule execution data for analysis.

        Args:
            session: Database session
            rule_name: Specific rule to analyze
            start_date: Start date for analysis (ISO format)
            end_date: End date for analysis (ISO format)
            include_successful: Include successful executions
            include_failed: Include failed executions

        Returns:
            RuleExecutionData with formatted data and statistics
        """
        # Parse dates
        if start_date:
            start_dt = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
        else:
            start_dt = datetime.now() - timedelta(days=7)

        if end_date:
            end_dt = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
        else:
            end_dt = datetime.now()

        # Build query for rule execution events
        query = select(AuditLog).where(
            AuditLog.event_type == EventType.EXECUTION_LIFECYCLE,
            AuditLog.timestamp >= start_dt,
            AuditLog.timestamp <= end_dt,
        )

        # Filter by rule name if specified
        if rule_name:
            query = query.where(AuditLog.rule_name == rule_name)

        # Filter by success/failure
        if include_successful and include_failed:
            # Include both successful and failed
            pass  # No additional filter needed
        elif include_successful:
            query = query.where(AuditLog.success == True)  # noqa: E712
        elif include_failed:
            query = query.where(AuditLog.success == False)  # noqa: E712
        else:
            # Neither included - return empty result
            query = query.where(False)

        # Order by timestamp
        query = query.order_by(desc(AuditLog.timestamp))  # type: ignore[arg-type]

        # Execute query
        audit_logs = session.exec(query).all()

        total_executions = len(audit_logs)
        successful_executions = len([log for log in audit_logs if log.success])
        failed_executions = len([log for log in audit_logs if log.success == False])  # noqa: E712

        # Format audit data for LLM analysis (limit to first 100 for context size)
        formatted_data = []
        for log in audit_logs[:100]:
            entry = {
                "timestamp": log.timestamp.isoformat(),
                "rule_name": log.rule_name,
                "event_subtype": log.event_subtype,
                "success": log.success,
                "execution_time_ms": log.execution_time_ms,
                "error_message": log.error_message,
            }
            formatted_data.append(entry)

        return RuleExecutionData(
            formatted_data=formatted_data,
            total_executions=total_executions,
            successful_executions=successful_executions,
            failed_executions=failed_executions,
        )

    def format_rule_execution_summary(
        self,
        execution_data: RuleExecutionData,
        rule_name: str | None,
        start_date: str,
        end_date: str,
    ) -> str:
        """Format rule execution data for LLM analysis.

        Args:
            execution_data: Rule execution data from analysis
            rule_name: Rule name filter (if any)
            start_date: Analysis start date
            end_date: Analysis end date

        Returns:
            Formatted data summary for LLM analysis
        """
        return RULE_EXECUTION_SUMMARY_TEMPLATE.format(
            start_date=start_date,
            end_date=end_date,
            total_executions=execution_data.total_executions,
            successful_executions=execution_data.successful_executions,
            failed_executions=execution_data.failed_executions,
            rule_name=rule_name or "All rules",
            execution_details=json.dumps(execution_data.formatted_data, indent=2),
        )
