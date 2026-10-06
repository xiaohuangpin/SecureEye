"""数据访问层：账号注册 / 自动登录 / 加密模型配置读写。

安全模型（免登录）：
- 首次注册生成随机 32 字节 data_key（AES-256-GCM 密钥），加密 api_key。
- data_key 用 derive(email, key_salt) 得到的 wrap_key 加密后存库。
- 之后启动：凭库中 email 重算 wrap_key，解出 data_key，自动登录。

耗时点仅在 scrypt 派生（约百毫秒），由上层通过 asyncio.to_thread 调用本模块，
避免阻塞 UI。
"""
from __future__ import annotations

from pathlib import Path

from db.database import Database
from db.security import Crypto


class Store:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db = Database(db_path)

    def close(self) -> None:
        self.db.close()

    # ------------------------------------------------------------------ #
    # 账号
    # ------------------------------------------------------------------ #
    def account_exists(self) -> bool:
        return self.db.query_one("SELECT 1 FROM accounts LIMIT 1") is not None

    def register(self, email: str, password: str) -> bytes:
        """创建唯一账号，生成并返回 data_key（内存态会话密钥）。"""
        email = email.strip().lower()
        if self.account_exists():
            raise ValueError("账号已存在")

        pwd_salt, key_salt = Crypto.new_salt(), Crypto.new_salt()
        data_key = Crypto.new_key()
        self.db.execute(
            "INSERT INTO accounts (email, pwd_salt, pwd_hash, key_salt, data_key_enc) "
            "VALUES (?, ?, ?, ?, ?)",
            (email, pwd_salt, Crypto.derive(password, pwd_salt), key_salt,
             Crypto.encrypt(Crypto.derive(email, key_salt), data_key)),
        )
        return data_key

    def unlock(self) -> bytes | None:
        """自动登录：由库中 email 还原 wrap_key 并解出 data_key；无账号返回 None。"""
        row = self.db.query_one("SELECT email, key_salt, data_key_enc FROM accounts LIMIT 1")
        if row is None:
            return None
        return Crypto.decrypt(Crypto.derive(row["email"], bytes(row["key_salt"])),
                              bytes(row["data_key_enc"]))

    # ------------------------------------------------------------------ #
    # 模型配置
    # ------------------------------------------------------------------ #
    def save_config(
        self,
        data_key: bytes,
        api_key: str,
        base_url: str,
        model: str,
        is_label: bool,
        font_size: int = 14,
    ) -> None:
        account_id = self.db.query_one("SELECT id FROM accounts LIMIT 1")["id"]
        self.db.execute(
            """
            INSERT INTO model_config (account_id, base_url, model, api_key_enc, is_label, font_size, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))
            ON CONFLICT(account_id) DO UPDATE SET
                base_url = excluded.base_url,
                model = excluded.model,
                api_key_enc = excluded.api_key_enc,
                is_label = excluded.is_label,
                font_size = excluded.font_size,
                updated_at = excluded.updated_at
            """,
            (account_id, base_url, model,
             Crypto.encrypt(data_key, api_key.encode("utf-8")), int(bool(is_label)), int(font_size)),
        )

    def load_config(self, data_key: bytes) -> dict | None:
        row = self.db.query_one(
            "SELECT base_url, model, api_key_enc, is_label, system_prompt, font_size FROM model_config "
            "WHERE account_id = (SELECT id FROM accounts LIMIT 1)"
        )
        if row is None:
            return None
        return {
            "api_key": Crypto.decrypt(data_key, bytes(row["api_key_enc"])).decode("utf-8"),
            "base_url": row["base_url"],
            "model": row["model"],
            "is_label": bool(row["is_label"]),
            "system_prompt": row["system_prompt"] or "",
            "font_size": int(row["font_size"] or 14),
        }

    def save_prompt(self, prompt: str) -> None:
        """仅更新可编辑提示词段（非敏感数据，明文存储），不影响模型配置其余字段。"""
        self.db.execute(
            "UPDATE model_config SET system_prompt = ?, updated_at = datetime('now','localtime') "
            "WHERE account_id = (SELECT id FROM accounts LIMIT 1)",
            (prompt,),
        )
