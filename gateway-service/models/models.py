from msgspec import Struct
from typing import Literal


class HandshakeTicket(Struct, frozen=True):
    """网关分发的会话票据"""

    id: str
    gateway_session_id: str
    backend_target: str
    user_id: str | None
    nonce: str
    created_at: float
    expires_at: float


class GatewaySession(Struct, frozen=True):
    """网关会话信息"""

    id: str  # UUID
    user_id: str | None
    device_fingerprint: str | None
    claims_hash: str | None  # 登录后身份摘要（user_id|roles|cred_level）
    cred_level_min: int  # 当前会话要求的最低凭证等级
    stage: Literal["pre_auth", "active", "revoked"]
    geo_hint: str | None  # 例如 "cn-sh" / "us-east"
    affinity_key: str | None  # 一致性哈希 key（常用 user_id）
    canary_group: str | None  # 灰度组
    risk_flags: str  # 逗号分隔 如 "ip_change,too_many_fail"
    recent_qps: int  # 简单速率信息（可用滑窗更新）
    burst_score: float  # 突发度评分
    created_at: float
    last_access_at: float
    expires_at: float


class RoutingDecision(Struct):
    """一次性握手票据中的路由决策信息"""

    request_id: str
    gateway_session_id: str
    backend_target: str
    selected_service_endpoint: str  # 实际访问入口（反向代理内部地址或外部 host）
    candidate_nodes: list[str]  # 可选节点列表（调试/诊断用）
    strategy_used: str  # round_robin / hash / weighted_latency / canary
    policy_trace: str  # 简单文本链路（匹配了哪些策略规则）
    decided_at: float


class ServiceInstance(Struct, frozen=True):
    """
    注册到 etcd 的实例信息（值）
    """

    id: str
    name: str
    endpoint: str  # http://host:port 或 grpc://host:port
    zone: str | None
    version: str | None
    weight: int  # 基础权重
    tags: list[str]  # ["primary","canary","bulk"]
    meta_json: str  # 复杂结构外部再解析
    heartbeat_at: float  # 最近心跳（监控）


class ServiceSnapshot(Struct, frozen=True):
    """
    从 etcd watch 得到的某服务的快照（缓存到内存，供路由使用）
    """

    name: str
    instances: list[ServiceInstance]
    revision: int
