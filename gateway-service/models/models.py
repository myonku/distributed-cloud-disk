from msgspec import Struct
from typing import Literal


class TrustSnapshot(Struct, frozen=True):
    """
    网关侧的信任快照，仅用于网关中间件判定是否放行与策略决策。
    rv: 权限/角色版本号（角色、权限变更时递增）
    """

    user_id: str
    cred: Literal[0, 1, 2, 3]  # 0=匿名,1=登录,2=二次验证,3=管理员...
    roles_csv: str | None  # 角色集合快照（简单 CSV；复杂可换 JSON）
    rv: int  # 权限版本
    token_id: str | None  # 会话令牌/登录令牌的 jti（用于撤销/审计）
    exp: float  # 快照过期时刻（短 TTL，驱动刷新）
    tenant_id: str | None = None


class BackendBinding(Struct, frozen=True):
    """
    会话内的“客户端 -> 后端服务实例”的导向信息
    - stickiness: 绑定键（如 user_id）用于一致性路由
    """

    backend: Literal["user", "metadata", "storage"]
    selected_instance_id: str
    selected_endpoint: str  # http://host:port 或 grpc://...
    strategy_used: str  # round_robin/hash/latency/canary 等
    stickiness_key: str | None
    min_required_cred: int | None  # 此后端路径族的最低 cred 要求（可辅助快速拒绝）
    last_routed_at: float
    expires_at: float
    policy_trace: str | None = None  # 选择依据的简短说明（调试/审计）


class GatewaySession(Struct, frozen=True):
    """
    网关会话（只存信任/导向/风控，不存节点加密态）
    - 中间件在转发前先依据 trust 与路由策略判定
    - 节点加密握手请求在放行后透明转发
    """

    id: str  # UUID
    device_fingerprint: str | None
    trust: TrustSnapshot | None  # 已登录则存在；匿名访问时可为空
    cred_level_min: int  # 会话级最低 cred（策略可上调）
    stage: Literal["pre_auth", "active", "revoked"]
    risk_flags: str  # "ip_change,too_many_fail" 等
    recent_qps: int
    burst_score: float
    bindings: list[BackendBinding]  # 后端绑定表：按服务名记录最近的路由选择与粘性
    created_at: float
    last_access_at: float
    expires_at: float


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
