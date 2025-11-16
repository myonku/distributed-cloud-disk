from datetime import datetime
from typing import Any
from beanie import Document

class RequestAudit(Document):
    """HTTP/请求审计记录（非强一致）

    索引：
    - trace_id 唯一（避免重复写，可选）
    - route + method + ts 时间范围查询
    - user_id 过滤用户行为
    """
    trace_id: str
    route: str
    method: str
    status: int
    ts: datetime
    latency_ms: int | None = None
    user_id: str | None = None
    tenant_id: str | None = None
    session_id: str | None = None
    cred_level: int | None = None
    ip: str | None = None
    headers: dict[str, str] | None = None
    error: str | None = None
    extra: dict[str, Any] | None = None

    class Settings:
        name = "request_audit"
        indexes = [
            "trace_id",
            [("route", 1), ("method", 1), ("ts", -1)],
            [("user_id", 1), ("ts", -1)],
            [("tenant_id", 1), ("ts", -1)],
        ]

class SecurityAudit(Document):
    """安全相关审计（登录、权限变更、失败尝试等）"""
    event_type: str  # LOGIN_SUCCESS, LOGIN_FAILED, ROLE_CHANGED, etc.
    ts: datetime
    user_id: str | None = None
    tenant_id: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    session_id: str | None = None
    detail: dict[str, Any] | None = None
    severity: int | None = None  # 0=info,1=warn,2=high

    class Settings:
        name = "security_audit"
        indexes = [
            [("event_type", 1), ("ts", -1)],
            [("user_id", 1), ("ts", -1)],
            [("tenant_id", 1), ("ts", -1)],
        ]
