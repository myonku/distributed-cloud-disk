import asyncio, time
from kafka.kafka_client import KafkaClient
from .repo import OutboxRepository


class OutboxDispatcher:
    """基于 Outbox 模式的异步消息派发器。"""
    def __init__(
        self,
        *,
        repo: OutboxRepository,
        kafka: KafkaClient,
        worker_id: str,
        batch_size: int = 100,
        poll_interval: float = 0.5,
        lock_ttl_sec: float = 60.0,
        max_attempts: int = 8,
        base_backoff: float = 1.0,
        max_backoff: float = 60.0,
    ) -> None:
        self.repo = repo
        self.kafka = kafka
        self.worker_id = worker_id
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.lock_ttl_sec = lock_ttl_sec
        self.max_attempts = max_attempts
        self.base_backoff = base_backoff
        self.max_backoff = max_backoff
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    def _backoff(self, attempts: int) -> float:
        delay = self.base_backoff * (2 ** (attempts - 1))
        return min(delay, self.max_backoff)

    async def start(self):
        if self._task:
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._stop.set()
        if self._task:
            try:
                await self._task
            except Exception:
                pass

    async def _run(self):
        prod = self.kafka.get_producer()
        while not self._stop.is_set():
            now = time.time()
            batch = await self.repo.lock_due(
                now_epoch=now,
                limit=self.batch_size,
                worker_id=self.worker_id,
                lock_ttl_sec=self.lock_ttl_sec,
            )
            if not batch:
                await asyncio.sleep(self.poll_interval)
                continue
            for rec in batch:
                try:
                    await prod.send_and_wait(
                        rec.topic,
                        value=rec.payload,
                        key=rec.key,
                        headers=[(k, v.encode()) for k, v in rec.headers.items()],
                    )
                    await self.repo.mark_sent(rec.id, sent_at=time.time())
                except Exception as e:
                    attempts = rec.attempts + 1
                    if attempts >= self.max_attempts:
                        await self.repo.mark_dead(rec.id, error=str(e))
                    else:
                        next_at = time.time() + self._backoff(attempts)
                        await self.repo.mark_failed(
                            rec.id,
                            error=str(e),
                            attempts=attempts,
                            next_attempt_at=next_at,
                        )
            # 循环继续
