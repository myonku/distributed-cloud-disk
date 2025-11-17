import asyncio
import time
from msgspec import json
from models.models import ServiceInstance, ServiceSnapshot
from repositories.etcd_client import (
    EtcdAsyncClient,
    build_service_key,
    build_prefix,
    encode_instance,
    decode_instance,
)


class ServiceRegistrar:
    """
    实例注册 + 续租
    """

    def __init__(self, etcd: EtcdAsyncClient):
        self.etcd = etcd
        self._stop = asyncio.Event()
        self._keepalive_task: asyncio.Task | None = None

    async def register(self, instance: ServiceInstance, ttl: int = 15):
        """将服务注册到etcd"""
        assert self.etcd.namespace
        key = build_service_key(self.etcd.namespace, instance.name, instance.id)
        await self.etcd.put_with_lease(key, encode_instance(instance), ttl)
        # 启动 keepalive
        if self._keepalive_task is None or self._keepalive_task.done():
            self._keepalive_task = asyncio.create_task(
                self.etcd.keepalive_forever(ttl, self._stop)
            )

    async def unregister(self, instance: ServiceInstance):
        """从etcd清除注册信息"""
        assert self.etcd.namespace
        key = build_service_key(self.etcd.namespace, instance.name, instance.id)
        await self.etcd.delete(key)
        self._stop.set()
        if self._keepalive_task:
            await asyncio.sleep(0)  # 让任务有机会退出


class LocalRegistry:
    """
    本地只读缓存：维护某服务下的实例列表与修订号
    """

    def __init__(self, etcd: EtcdAsyncClient):
        self.etcd = etcd
        self._snapshots: dict[str, ServiceSnapshot] = {}
        self._watch_tasks: dict[str, asyncio.Task] = {}

    async def prime_and_watch(self, service_name: str):
        """预加载并启动监听指定服务的实例变更"""
        # 初始加载
        assert self.etcd.namespace
        prefix = build_prefix(self.etcd.namespace, service_name)
        # 使用带 revision 的加载，避免加载与 watch 间的竞态窗口
        rev, kvs = await self.etcd.get_prefix_with_revision(prefix)
        instances: list[ServiceInstance] = []
        for _, v in kvs:
            try:
                instances.append(decode_instance(v))
            except Exception:
                continue
        self._snapshots[service_name] = ServiceSnapshot(
            name=service_name, instances=instances, revision=rev
        )
        # 启动 watch
        stop_event = asyncio.Event()
        task = asyncio.create_task(
            self._watch_loop(service_name, prefix, stop_event, rev)
        )
        self._watch_tasks[service_name] = task

    async def _watch_loop(
        self, service_name: str, prefix: str, stop_event: asyncio.Event, base_rev: int
    ):
        """监听指定服务的实例变更并更新本地缓存"""

        async def on_event(key: str, val: bytes | None):
            snap = self._snapshots.get(service_name)
            current = list(snap.instances) if snap else []
            # 更新本地列表
            if val is None:
                # delete
                assert self.etcd.namespace
                current = [
                    i
                    for i in current
                    if build_service_key(self.etcd.namespace, i.name, i.id) != key
                ]
            else:
                try:
                    inst = decode_instance(val)
                    # upsert
                    current = [i for i in current if i.id != inst.id]
                    current.append(inst)
                except Exception:
                    pass
            self._snapshots[service_name] = ServiceSnapshot(
                name=service_name, instances=current, revision=int(time.time())
            )

        # 从 base_rev + 1 开始监听新增/变更
        start_rev = base_rev + 1 if base_rev > 0 else 0
        await self.etcd.watch_prefix(
            prefix, on_event, stop_event, start_revision=start_rev
        )

    def get_instances(self, service_name: str) -> list[ServiceInstance]:
        """获取指定服务的实例列表"""
        snap = self._snapshots.get(service_name)
        return list(snap.instances) if snap else []

    def get_snapshot(self, service_name: str) -> ServiceSnapshot | None:
        """获取指定服务的本地快照"""
        return self._snapshots.get(service_name)
