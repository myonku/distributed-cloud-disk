import os, base64, hmac, time
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives import serialization

HKDF_LEN = 64
INFO_MASTER = b"dcd:master"
INFO_C2S = b"dcd:c2s"
INFO_S2C = b"dcd:s2c"
LABEL_VERIFY = b"dcd:verify:"


def now_epoch() -> float:
    return time.time()


def _hkdf(
    ikm: bytes, info: bytes, length: int = 32, salt: bytes | None = None
) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(
        ikm
    )


def server_priv_from_service_bytes(raw: bytes) -> x25519.X25519PrivateKey:
    """
    若 ServerSecretKeyService 返回的是原始 32 字节私钥（X25519），直接构造；
    若返回 PEM，请先在调用处转换为 raw bytes 再传入。
    """
    return x25519.X25519PrivateKey.from_private_bytes(raw)


def derive_session_keys_static(
    client_pub_b64: str,
    server_priv_bytes: bytes | str,
    session_id: str,
    server_pub_b64: str | None = None,
) -> tuple[bytes, bytes, str]:
    """
    静态服务端私钥 + 客户端临时公钥 -> 预主密钥
    使用 session_id 作为 HKDF 的上下文绑定；
    返回 (c2s_key, s2c_key, fingerprint)
    """
    client_pub = base64.b64decode(client_pub_b64)
    # support raw 32-byte, PEM (str/bytes) or already an X25519PrivateKey
    if isinstance(server_priv_bytes, x25519.X25519PrivateKey):
        sp = server_priv_bytes
    else:
        sb = (
            server_priv_bytes.encode()
            if isinstance(server_priv_bytes, str)
            else server_priv_bytes
        )
        if isinstance(sb, (bytes, bytearray)):
            # raw 32-byte private key
            if len(sb) == 32:
                sp = server_priv_from_service_bytes(bytes(sb))
            # PEM encoded private key
            elif sb.strip().startswith(b"-----BEGIN"):
                priv = load_pem_private_key(sb, password=None)
                if isinstance(priv, x25519.X25519PrivateKey):
                    sp = priv
                else:
                    # try to extract raw bytes from supported key objects
                    raw = priv.private_bytes(
                        encoding=serialization.Encoding.Raw,
                        format=serialization.PrivateFormat.Raw,
                        encryption_algorithm=serialization.NoEncryption(),
                    )
                    sp = server_priv_from_service_bytes(raw)
            else:
                # maybe base64 of raw bytes
                try:
                    dec = base64.b64decode(sb)
                    if len(dec) == 32:
                        sp = server_priv_from_service_bytes(dec)
                    else:
                        raise ValueError(
                            "server_priv_bytes is not a valid X25519 private key"
                        )
                except Exception as e:
                    raise ValueError(
                        "server_priv_bytes is not a valid X25519 private key"
                    ) from e
        else:
            raise ValueError(
                "server_priv_bytes must be bytes, str, or X25519PrivateKey"
            )
    shared = sp.exchange(x25519.X25519PublicKey.from_public_bytes(client_pub))
    # master key 绑定上下文（避免不同会话复用）
    master = _hkdf(shared, info=INFO_MASTER + session_id.encode(), length=HKDF_LEN)
    c2s = _hkdf(master[:32], info=INFO_C2S, length=32)
    s2c = _hkdf(master[32:], info=INFO_S2C, length=32)
    # 简单指纹（审计）
    h = hashes.Hash(hashes.SHA256())
    h.update(shared[:16])
    h.update(session_id.encode())
    fpr = h.finalize().hex()[:32]
    return c2s, s2c, fpr


def compute_verify_hmac(c2s_key: bytes, s2c_key: bytes, server_nonce_b64: str) -> str:
    """计算HMAC"""
    server_nonce = base64.b64decode(server_nonce_b64)
    mac = hmac.new(c2s_key + s2c_key, LABEL_VERIFY + server_nonce, digestmod="sha256")
    return mac.hexdigest()


def aesgcm_encrypt(
    key: bytes, plaintext: bytes, aad: bytes | None = None
) -> tuple[str, str]:
    """对称加密"""
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext, aad)
    return base64.b64encode(nonce).decode(), base64.b64encode(ct).decode()


def aesgcm_decrypt(
    key: bytes, nonce_b64: str, ct_b64: str, aad: bytes | None = None
) -> bytes:
    """对称解密"""
    nonce = base64.b64decode(nonce_b64)
    ct = base64.b64decode(ct_b64)
    return AESGCM(key).decrypt(nonce, ct, aad)
