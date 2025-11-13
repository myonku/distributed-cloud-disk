from abc import ABC, abstractmethod
from collections.abc import Sequence
from .models import OutboxRecord


class OutboxRepository(ABC):
    @abstractmethod
    async def insert(self, rec: OutboxRecord, *, tx=None) -> None: ...

    @abstractmethod
    async def lock_due(
        self,
        *,
        now_epoch: float,
        limit: int,
        worker_id: str,
        lock_ttl_sec: float,
    ) -> Sequence[OutboxRecord]: ...

    @abstractmethod
    async def mark_sent(self, rec_id: str, *, sent_at: float) -> None: ...

    @abstractmethod
    async def mark_failed(
        self, rec_id: str, *, error: str, attempts: int, next_attempt_at: float
    ) -> None: ...

    @abstractmethod
    async def mark_dead(self, rec_id: str, *, error: str) -> None: ...
