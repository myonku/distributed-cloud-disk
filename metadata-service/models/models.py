from typing import Literal
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
    key_fpr: str
    device_printer: str
    claims_hash: str  # 对绑定的基础 claims (user_id, roles, tenant, cred_level) 做哈希
    cred_level: int
    roles: str  # 逗号分隔
    tenant_id: str | None
    established_at: float
    claims_refreshed_at: float
    expires_at: float


class UploadSessionCache(Struct, frozen=True):
    """上传会话缓存模型"""
    id: str
    owner_id: str
    file_name: str
    size: int
    chunk_size: int
    state: Literal[
        "init", "receiving", "committing", "done"
    ]
    created_at: float
    expires_at: float


class File(BaseModel):
    """文件模型"""
    model_config = ConfigDict(from_attributes=True, strict=True)
    id: UUID
    owner_id: UUID
    logical_name: str
    size: int
    current_version_id: UUID | None = None
    status: str
    created_at: datetime
    updated_at: datetime


class FileVersion(BaseModel):
    """文件版本模型"""
    model_config = ConfigDict(from_attributes=True, strict=True)
    id: UUID
    file_id: UUID
    size: int
    chunk_count: int
    hash_root: str
    encryption_scheme: str
    created_at: datetime


class UploadSessionBusiness(BaseModel):
    """上传会话业务模型"""
    model_config = ConfigDict(from_attributes=True, strict=True)
    id: UUID
    owner_id: UUID
    file_name: str
    size: int
    chunk_size: int
    state: str
    created_at: datetime
    expires_at: datetime
