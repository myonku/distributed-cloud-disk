from datetime import datetime, timezone
from typing import Any

from models.audit_models import RequestAudit, SecurityAudit
from repositories.mongo_client import MongoDBClient, MongoBaseDAO

class AuditService:
    """审计服务：提供请求与安全事件的写入接口（非强一致）。

    建议通过 Kafka 异步消费写入；这里也支持直接调用快速落库。"""

    def __init__(self, mongo_client: MongoDBClient) -> None:
        if not mongo_client.is_initialized:
            raise RuntimeError("MongoClient 未初始化")
        self.mongo = mongo_client
        self.request_audit_dao = MongoBaseDAO[RequestAudit](RequestAudit)
        self.security_audit_dao = MongoBaseDAO[SecurityAudit](SecurityAudit)

    async def log_request(
        self,
        *,
        trace_id: str,
        route: str,
        method: str,
        status: int,
        latency_ms: int | None = None,
        user_id: str | None = None,
        tenant_id: str | None = None,
        session_id: str | None = None,
        cred_level: int | None = None,
        ip: str | None = None,
        headers: dict[str, str] | None = None,
        error: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> RequestAudit:
        """新增请求审计记录"""
        doc = RequestAudit(
            trace_id=trace_id,
            route=route,
            method=method,
            status=status,
            ts=datetime.now(timezone.utc),
            latency_ms=latency_ms,
            user_id=user_id,
            tenant_id=tenant_id,
            session_id=session_id,
            cred_level=cred_level,
            ip=ip,
            headers=headers,
            error=error,
            extra=extra,
        )
        return await self.request_audit_dao.create(doc)

    async def log_security(
        self,
        *,
        event_type: str,
        user_id: str | None = None,
        tenant_id: str | None = None,
        ip: str | None = None,
        user_agent: str | None = None,
        session_id: str | None = None,
        detail: dict[str, Any] | None = None,
        severity: int | None = None,
    ) -> SecurityAudit:
        """新增安全审计记录"""
        doc = SecurityAudit(
            event_type=event_type,
            ts=datetime.now(timezone.utc),
            user_id=user_id,
            tenant_id=tenant_id,
            ip=ip,
            user_agent=user_agent,
            session_id=session_id,
            detail=detail,
            severity=severity,
        )
        return await self.security_audit_dao.create(doc)
