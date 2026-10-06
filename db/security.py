"""安全模块：scrypt 密钥派生与 AES-256-GCM 加解密（纯静态类，无全局变量）。"""
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Crypto:
    """密钥派生与加解密工具。

    注意：_SCRYPT 参数与 AESGCM 编码格式（nonce(12) ‖ 密文 ‖ tag(16)）与既有
    secureeye.db 数据绑定，改动会导致旧库无法解密，请勿随意调整。
    """

    _KEY_LEN = 32
    _SALT_LEN = 16
    _NONCE_LEN = 12
    _SCRYPT = dict(n=2**14, r=8, p=1, dklen=32, maxmem=64 * 1024 * 1024)

    @staticmethod
    def new_salt() -> bytes:
        return os.urandom(Crypto._SALT_LEN)

    @staticmethod
    def new_key() -> bytes:
        """AES-256 密钥（32 字节）。"""
        return os.urandom(Crypto._KEY_LEN)

    @staticmethod
    def derive(secret: str, salt: bytes) -> bytes:
        """由口令/标识派生 32 字节密钥（scrypt，CPU 密集，耗时操作请放工作线程）。"""
        return hashlib.scrypt(secret.encode("utf-8"), salt=salt, **Crypto._SCRYPT)

    @staticmethod
    def encrypt(key: bytes, data: bytes) -> bytes:
        """AES-256-GCM，返回 nonce(12) ‖ 密文 ‖ tag(16)。"""
        nonce = os.urandom(Crypto._NONCE_LEN)
        return nonce + AESGCM(key).encrypt(nonce, data, None)

    @staticmethod
    def decrypt(key: bytes, blob: bytes) -> bytes:
        """解密；密钥不符会抛 InvalidTag。"""
        return AESGCM(key).decrypt(blob[: Crypto._NONCE_LEN], blob[Crypto._NONCE_LEN :], None)
