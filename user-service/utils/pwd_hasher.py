import argon2
from argon2 import Type


class PasswordHasher:
    def __init__(self, time_cost=2, memory_cost=512 * 1024, parallelism=2):
        """
        初始化 Argon2 哈希器

        :param time_cost: 时间成本（迭代次数）
        :param memory_cost: 内存成本（KB）
        :param parallelism: 并行度
        """
        self.time_cost = time_cost
        self.memory_cost = memory_cost
        self.parallelism = parallelism

        self.hasher = argon2.PasswordHasher(
            time_cost=time_cost,
            memory_cost=memory_cost,
            parallelism=parallelism,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )

    def hash_password(self, password) -> str:
        """
        哈希密码
        """
        if not password:
            raise ValueError("Password cannot be empty")

        return self.hasher.hash(password)

    def verify_password(self, hashed_password, password) -> bool:
        """
        验证密码
        """
        if not hashed_password or not password:
            return False

        try:
            return self.hasher.verify(hashed_password, password)
        except (
            argon2.exceptions.VerifyMismatchError,
            argon2.exceptions.InvalidHashError,
            argon2.exceptions.VerificationError,
        ):
            return False

    def needs_rehash(self, hashed_password) -> bool:
        """
        检查哈希是否需要重新计算（参数变更时）
        """
        return self.hasher.check_needs_rehash(hashed_password)
