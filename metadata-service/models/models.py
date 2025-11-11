from typing import Literal
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from uuid import UUID
from msgspec import Struct


class HandshakeTicket(Struct, frozen=True):
    """网关分发的会话票据"""

    id: str
    gateway_session_id: str
    backend_target: str
    user_id: str | None
    nonce: str
    created_at: float
    expires_at: float


class BackendSessionCache(Struct, frozen=True):
    """后端会话缓存"""

    id: str
    user_id: str | None
    backend: Literal["metadata"]
    client_pub_eph_b64: str  # 客户端临时公钥（Base64）
    server_pub_b64: str  # 服务器（静态）公钥（Base64 或指纹）
    shared_secret_fpr: str  # 指纹（便于审计）
    verified: bool  # 是否已完成 confirm
    # 授权绑定（按需刷新）
    claims_hash: str
    cred_level: int
    roles: str  # 逗号分隔，复杂时可换 JSON 字符串
    tenant_id: str | None  # 绑定的租户 ID（多租户场景）
    established_at: float
    claims_refreshed_at: float
    expires_at: float


class TemporaryHandshake(Struct, frozen=True):
    """
    临时握手模型：用于 init 和 confirm 之间的短期状态，存 Redis
    不存任何对称密钥与服务端临时私钥
    """

    id: str  # backendSessionId (UUID)
    backend: Literal["metadata"]  # 当前服务标识
    user_id: str | None  # 绑定的用户（可能为空）
    client_pub_eph_b64: str  # 客户端临时公钥（Base64 原始 X25519 公钥）
    server_pub_b64: str  # 服务器（静态）公钥（Base64 或指纹字符串）
    server_nonce_b64: str  # 服务端随机数（Base64）
    created_at: float  # epoch 秒
    expires_at: float  # 过期（用于整体 TTL）
    verify_deadline_at: float  # confirm 最晚时间（秒级）


class UploadSessionCache(Struct, frozen=True):
    """上传会话缓存模型"""

    id: str
    owner_id: str
    file_name: str
    size: int
    chunk_size: int
    state: Literal["init", "receiving", "committing", "done"]
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
