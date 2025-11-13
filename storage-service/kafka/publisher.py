from aiokafka.structs import RecordMetadata
from kafka.kafka_client import KafkaClient


class KafkaPublisher:
    """通用直接发送（非可靠）Publisher。"""

    def __init__(self, kc: KafkaClient) -> None:
        self._kc = kc

    async def publish(
        self,
        *,
        topic: str,
        value: bytes,
        key: bytes | None = None,
        headers: dict[str, str] | None = None,
        partition: int | None = None,
    ) -> RecordMetadata:
        """直接推送事件"""
        prod = self._kc.get_producer()
        md = await prod.send_and_wait(
            topic,
            value=value,
            key=key,
            partition=partition,
            headers=[(k, v.encode()) for k, v in (headers or {}).items()],
        )
        return md
