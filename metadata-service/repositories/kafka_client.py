import asyncio
from collections.abc import Iterable
import logging
from typing import Any  # 新增

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from config import ProjectConfig

logger = logging.getLogger(__name__)


class KafkaClient:
    """基于 aiokafka 的最底层 Kafka 服务封装。

    目标：作为全局单例注册，暴露 start/stop、produce 和创建 consumer 的工厂。
    仅负责连接与基础操作，业务层再封装主题/序列化/错误处理。
    """

    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None
        self._started = False
        self._lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()

    async def start(self, cfg: ProjectConfig) -> None:
        """启动并连接到 Kafka（会创建并启动 producer）。"""
        self._cfg = cfg.kafka if cfg and getattr(cfg, "kafka", None) else None
        if not self._cfg:
            raise RuntimeError("Kafka config not provided")
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            bootstrap_list = self._cfg.BOOTSTRAP_SERVERS
            if not bootstrap_list:
                raise ValueError("Kafka bootstrap servers empty")
            kwargs = {}
            if self._cfg.CLIENT_ID:
                kwargs["client_id"] = self._cfg.CLIENT_ID

            # 安全/认证相关（如果配置了）
            if self._cfg.SECURITY_PROTOCOL:
                kwargs["security_protocol"] = self._cfg.SECURITY_PROTOCOL
            if self._cfg.SASL_MECHANISM:
                kwargs["sasl_mechanism"] = self._cfg.SASL_MECHANISM
            if self._cfg.SASL_USERNAME is not None:
                kwargs["sasl_plain_username"] = self._cfg.SASL_USERNAME
            if self._cfg.SASL_PASSWORD is not None:
                kwargs["sasl_plain_password"] = self._cfg.SASL_PASSWORD

            self._producer = AIOKafkaProducer(bootstrap_servers=",".join(bootstrap_list), **kwargs)
            try:
                await self._producer.start()
            except Exception:
                logger.exception("Failed to start Kafka producer")
                self._producer = None
                raise
            self._started = True
            logger.info("Kafka producer started")

    async def stop(self) -> None:
        """停止 producer（不关闭由 create_consumer 创建的 consumer，调用者应负责）。"""
        async with self._lock:
            if self._producer is not None:
                try:
                    await self._producer.stop()
                except Exception:
                    logger.exception("error stopping kafka producer")
                finally:
                    self._producer = None
                    self._started = False
                    logger.info("Kafka producer stopped")

    async def produce(self, topic: str, value: bytes, key: bytes | None = None, partition: int | None = None) -> None:
        """发送一条消息到指定 topic（会等待发送完成）。

        说明：value/key 都应为 bytes；上层可以负责 json 编码/压缩等。
        """
        assert self._cfg and self._started and self._producer, "Kafka producer not started"
        try:
            await self._producer.send_and_wait(topic, value, key=key, partition=partition)
        except Exception:
            logger.exception("Kafka produce failed topic=%s partition=%s", topic, partition)
            raise
    
    def get_producer(self) -> AIOKafkaProducer:
        """获取全局已启动的 AIOKafkaProducer 实例（由 KafkaClient 管理生命周期）。

        注意：
        - 下游不应调用 start()/stop()；仅调用 send()/send_and_wait() 发送消息即可。
        - 如需简单发送，优先使用 KafkaClient.produce()，以避免误操作生命周期。

        返回：
        - AIOKafkaProducer（已启动）
        """
        if not self._cfg:
            raise RuntimeError("Kafka config not provided")
        if not self._started or not self._producer:
            raise RuntimeError("Kafka producer not started")
        return self._producer

    def create_consumer(self, topics: Iterable[str], group_id: str | None = None, **kwargs) -> AIOKafkaConsumer:
        """创建一个 AIOKafkaConsumer 实例，返回后调用方负责 start()/stop()。

        示例：
            consumer = kafka_svc.create_consumer(["topic"], group_id="g")
            await consumer.start()
            try:
                async for msg in consumer:
                    ...
            finally:
                await consumer.stop()
        """
        if not self._cfg:
            raise RuntimeError("Kafka config not provided")
        topics = list(topics)
        if not topics:
            raise ValueError("topics must be non-empty")

        # 显式标注 Any，避免被推断为 dict[str, str]
        consumer_kwargs: dict[str, Any] = {"bootstrap_servers": ",".join(self._cfg.BOOTSTRAP_SERVERS)}
        if group_id:
            consumer_kwargs["group_id"] = group_id

        # 继承安全/认证相关配置
        if self._cfg.SECURITY_PROTOCOL:
            consumer_kwargs["security_protocol"] = self._cfg.SECURITY_PROTOCOL
        if self._cfg.SASL_MECHANISM:
            consumer_kwargs["sasl_mechanism"] = self._cfg.SASL_MECHANISM
        if self._cfg.SASL_USERNAME is not None:
            consumer_kwargs["sasl_plain_username"] = self._cfg.SASL_USERNAME
        if self._cfg.SASL_PASSWORD is not None:
            consumer_kwargs["sasl_plain_password"] = self._cfg.SASL_PASSWORD

        consumer_kwargs.update(kwargs)

        # 将字符串配置转换为正确类型，避免运行时报错
        INT_KEYS = {
            "fetch_max_wait_ms", "fetch_max_bytes", "fetch_min_bytes",
            "max_partition_fetch_bytes", "request_timeout_ms", "retry_backoff_ms",
            "auto_commit_interval_ms", "metadata_max_age_ms", "max_poll_interval_ms",
            "session_timeout_ms", "heartbeat_interval_ms", "consumer_timeout_ms",
            "connections_max_idle_ms", "max_poll_records",
        }
        BOOL_KEYS = {"enable_auto_commit", "check_crcs", "exclude_internal_topics"}

        for k in INT_KEYS:
            v = consumer_kwargs.get(k)
            if isinstance(v, str):
                try:
                    consumer_kwargs[k] = int(v)
                except ValueError as e:
                    raise ValueError(f"{k} must be int, got {v!r}") from e

        for k in BOOL_KEYS:
            v = consumer_kwargs.get(k)
            if isinstance(v, str):
                consumer_kwargs[k] = v.strip().lower() in {"1", "true", "yes", "on"}

        return AIOKafkaConsumer(*topics, **consumer_kwargs)
