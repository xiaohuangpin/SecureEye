"""业务控制器：封装账号、模型配置读写、检测与导出。

配置持久化由 SQLite（db.Store）承担，api_key 以 AES-256-GCM 加密存储。
所有耗时操作（scrypt 派生、建客户端、网络、写文件）均为 async，由 qasync
事件循环驱动；重建客户端时关闭旧 AsyncOpenAI 连接池，避免内存/句柄累积。
"""
import asyncio
import logging
import os
from collections.abc import Callable

from PIL import Image

from core.agent import MultClient
from db.store import Store
from export.export_docx import export_to_excel, export_to_word
from gui.common import open_file_with_default_app, to_data_uri

logger = logging.getLogger(__name__)


class AppController:
    API_TIMEOUT = 6.0   # 连通性校验最长等待（秒），避免保存时长时间无响应
    CLOSE_TIMEOUT = 2.0

    def __init__(self, store: Store) -> None:
        self.store = store
        self.data_key: bytes | None = None
        self.config: dict | None = None
        self.client: MultClient | None = None
        self.last_results: list[dict] = []

    # ------------------------------------------------------------------ #
    # 账号 / 会话密钥
    # ------------------------------------------------------------------ #
    def has_account(self) -> bool:
        return self.store.account_exists()

    async def register(self, email: str, password: str) -> None:
        """首次启动：创建账号并取得会话密钥 data_key（scrypt 在线程中执行）。"""
        self.data_key = await asyncio.to_thread(self.store.register, email, password)
        await self._load_config()

    async def login(self) -> None:
        """后续启动：自动解锁取出 data_key，无需输入密码。"""
        self.data_key = await asyncio.to_thread(self.store.unlock)
        await self._load_config()

    async def _load_config(self) -> None:
        config = (
            await asyncio.to_thread(self.store.load_config, self.data_key)
            if self.data_key
            else None
        )
        await self._swap_client(await asyncio.to_thread(self._build_client, config))
        self.config = config

    @staticmethod
    def _build_client(config: dict | None) -> MultClient | None:
        if not config:
            return None
        try:
            return MultClient(
                config["api_key"],
                config["base_url"],
                config["model"],
                config.get("system_prompt") or None,
                font_size=config.get("font_size", MultClient.DEFAULT_FONT_SIZE),
            )
        except Exception as e:
            logger.error(f"模型客户端创建失败: {e}")
            return None

    @staticmethod
    async def _close_client(client: MultClient) -> None:
        try:
            await asyncio.wait_for(client.client.close(), timeout=AppController.CLOSE_TIMEOUT)
        except Exception as e:
            logger.warning(f"释放模型客户端失败: {e}")

    async def _swap_client(self, new: MultClient | None) -> None:
        if self.client is not None and self.client is not new:
            await self._close_client(self.client)
        self.client = new

    @property
    def config_valid(self) -> bool:
        return self.client is not None and bool(self.config)

    # ------------------------------------------------------------------ #
    # 配置
    # ------------------------------------------------------------------ #
    def _endpoint_changed(self, api_key: str, base_url: str, model: str) -> bool:
        """连接参数是否与当前配置不同（仅此时才需联网校验，改字体/开关可秒存）"""
        old = self.config or {}
        return (old.get("api_key"), old.get("base_url"), old.get("model")) != (api_key, base_url, model)

    async def save_config(
        self,
        api_key: str,
        base_url: str,
        model: str,
        is_label: bool = False,
        font_size: int = MultClient.DEFAULT_FONT_SIZE,
    ) -> dict:
        api_key, base_url, model = api_key.strip(), base_url.strip(), model.strip()
        if not (api_key and base_url and model):
            return {"success": False, "message": "API Key、Base URL 和 Model 均为必填项"}
        if self.data_key is None:
            return {"success": False, "message": "会话未解锁，请先完成账号验证"}

        config = {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "is_label": bool(is_label),
            "font_size": MultClient.clamp_font_size(font_size),  # 限幅后入库，与客户端一致
            "system_prompt": (self.config or {}).get("system_prompt", ""),  # 提示词由专页维护，此处沿用
        }
        # 建客户端（含字体/连接池）放工作线程，不冻结 UI
        client = await asyncio.to_thread(self._build_client, config)
        if client is None:
            return {"success": False, "message": "模型客户端创建失败，请检查参数"}

        if self._endpoint_changed(api_key, base_url, model):
            try:
                alive = await asyncio.wait_for(client.test_api(), timeout=self.API_TIMEOUT)
            except Exception as e:  # 含 TimeoutError
                logger.warning(f"API 连通校验异常: {e}")
                alive = False
            if not alive:
                await self._close_client(client)
                logger.error("API 连通性校验失败，配置未保存")
                return {"success": False, "message": "无法连接模型服务，请检查 api_key 或 base_url"}

        try:
            await asyncio.to_thread(
                self.store.save_config, self.data_key, api_key, base_url, model,
                config["is_label"], config["font_size"],
            )
        except Exception as e:
            await self._close_client(client)
            logger.exception(f"配置写入失败: {e}")
            return {"success": False, "message": f"配置保存失败: {e}"}

        self.config = config
        await self._swap_client(client)
        logger.info(f"配置保存成功，当前模型: {model}")
        return {"success": True, "message": "配置保存成功！"}

    # ------------------------------------------------------------------ #
    # 系统提示词（可编辑段，固定 JSON 输出模板由 core.agent 自动拼接）
    # ------------------------------------------------------------------ #
    @staticmethod
    def default_prompt() -> str:
        return MultClient.DEFAULT_PROMPT_BODY

    async def save_prompt(self, prompt: str) -> dict:
        prompt = prompt.strip()
        if not prompt:
            return {"success": False, "message": "系统提示词不能为空"}
        if self.config is None:
            return {"success": False, "message": "请先完成模型配置"}
        if self.client is None:
            return {"success": False, "message": "会话未解锁，请先完成账号验证"}

        try:
            await asyncio.to_thread(self.store.save_prompt, prompt)
        except Exception as e:
            logger.exception(f"系统提示词写入失败: {e}")
            return {"success": False, "message": f"保存失败: {e}"}

        self.config["system_prompt"] = prompt
        await self._swap_client(await asyncio.to_thread(self._build_client, self.config))  # 新提示词即时生效
        logger.info("系统提示词已保存")
        return {"success": True, "message": "系统提示词已保存！"}

    # ------------------------------------------------------------------ #
    # 检测
    # ------------------------------------------------------------------ #
    async def detect(self, img_list: list[str], is_label: bool | None = None) -> dict:
        if self.client is None:
            return {"success": False, "message": "未检测到有效的模型配置，请先配置模型参数", "data": []}
        img_list = [p for p in img_list if p and os.path.exists(p)]
        if not img_list:
            return {"success": False, "message": "没有可用的图片，请重新选择", "data": []}

        if is_label is None:
            is_label = bool((self.config or {}).get("is_label"))

        self.last_results = []  # 先释放上一轮结果（大 data URI 字符串）
        try:
            results = await self.client.batch_infer(img_list, is_label)
            for item in results:  # 统一转 data URI
                image = item.get("image")
                # 只有标注模式是 PIL（需真编码）才值得走线程；已编码的 base64 只加前缀
                if isinstance(image, Image.Image):
                    image = await asyncio.to_thread(to_data_uri, image)
                else:
                    image = to_data_uri(image)
                item["image"] = image
        except Exception as e:
            logger.exception(f"检测失败: {e}")
            return {"success": False, "message": f"检测失败: {e}", "data": []}

        self.last_results = results
        logger.info(f"检测完成，共 {len(results)} 张图片")
        return {"success": True, "message": f"检测完成，共 {len(results)} 张图片", "data": results}

    # ------------------------------------------------------------------ #
    # 导出
    # ------------------------------------------------------------------ #
    def _export(self, exporter: Callable[[list[dict]], str]) -> dict:
        data = self.last_results
        if not data:
            return {"success": False, "message": "没有可导出的检测结果，请先执行检测"}
        try:
            output_path = str(exporter(data))
        except Exception as e:
            logger.exception(f"导出失败: {e}")
            return {"success": False, "message": f"导出失败: {e}"}
        logger.info(f"报告已生成: {output_path}")
        open_file_with_default_app(output_path)
        return {"success": True, "message": "导出成功", "path": output_path}

    def export_word(self) -> dict:
        return self._export(export_to_word)

    def export_excel(self) -> dict:
        return self._export(export_to_excel)

    # ------------------------------------------------------------------ #
    # 资源释放
    # ------------------------------------------------------------------ #
    async def aclose(self) -> None:
        self.last_results = []
        if self.client is not None:
            await self._close_client(self.client)
            self.client = None
        self.store.close()
