from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from msgspec import Struct

class BackendSessionCache(Struct, frozen=True):
    id: str
    user_id: str | None
    backend: str
    client_pub_eph: str
    server_pub_eph: str
    device_printer: str
    key_fpr: str
    claims_hash: str  # 对绑定的基础 claims (user_id, roles, tenant, cred_level) 做哈希
    cred_level: int
    roles: str  # 逗号分隔
    tenant_id: str | None
    established_at: float
    claims_refreshed_at: float
    expires_at: float


class ChunkReceipt(BaseModel):
    """存储块收据模型"""
    model_config = ConfigDict(from_attributes=True, strict=True)
    chunk_id: str
    upload_session_id: UUID
    index: int
    size: int
    checksum: str | None = None
    stored_at: datetime
    node_id: str


class ChunkStatus(BaseModel):
    """存储块状态模型"""
    model_config = ConfigDict(from_attributes=True, strict=True)
    chunk_id: str
    exists: bool
    node_id: str
    last_verified_at: datetime | None = None
