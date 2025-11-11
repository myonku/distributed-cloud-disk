import hashlib, random
from models.models import ServiceInstance


def pick_round_robin(
    instances: list[ServiceInstance], counter: int = 0
) -> ServiceInstance | None:
    """轮询选择实例"""
    if not instances:
        return None
    return instances[counter % len(instances)]


def pick_least_weighted_latency(
    instances: list[ServiceInstance], latency_map: dict[str, float]
) -> ServiceInstance | None:
    """选择加权延迟最低的实例"""
    if not instances:
        return None
    ranked = sorted(
        instances, key=lambda i: (latency_map.get(i.id, 100.0) / max(i.weight, 1))
    )
    return ranked[0]


def pick_hash_affinity(
    instances: list[ServiceInstance], affinity_key: str
) -> ServiceInstance | None:
    """基于一致性哈希选择实例"""
    if not instances:
        return None
    h = hashlib.sha256(affinity_key.encode()).digest()
    idx = int.from_bytes(h[:4], "big") % len(instances)
    return instances[idx]


def filter_by_tags(
    instances: list[ServiceInstance], require_tags: list[str]
) -> list[ServiceInstance]:
    """根据标签过滤实例"""
    if not require_tags:
        return instances
    req = set(require_tags)
    return [i for i in instances if req.issubset(set(i.tags))]


def random_weighted(instances: list[ServiceInstance]) -> ServiceInstance | None:
    """基于权重随机选择实例"""
    if not instances:
        return None
    total = sum(max(i.weight, 1) for i in instances)
    r = random.uniform(0, total)
    upto = 0
    for i in instances:
        w = max(i.weight, 1)
        if upto + w >= r:
            return i
        upto += w
    return instances[-1]
