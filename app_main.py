import asyncio
import base64
import io
import json
import logging
import multiprocessing
import os
import sys
import threading
from collections.abc import Callable
from pathlib import Path
import webview
from PIL import Image
from core.agent import MultClient
from export.export_docx import export_to_word,export_to_excel

# nuitka --standalone --enable-plugin=anti-bloat --include-package-data=docx --include-data-dir=assets=assets --output-dir=dist --windows-icon-from-ico=logo.ico --windows-disable-console --output-dir=dist main_web.py
# pyinstaller --windowed --name secure --add-data "assets;assets" --add-data "model_config.json;." -i logo.ico main_web.py

logger: logging.Logger = logging.getLogger(__name__)


def get_resource_path(relative_path: str) -> str:
    """兼容 Nuitka / PyInstaller 打包后的资源路径。"""
    base_path:str = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def open_file_with_default_app(file_path: str) -> bool:
    """用系统默认程序打开文件。"""
    if not file_path or not os.path.exists(file_path):
        logger.error(f"文件 {file_path} 不存在")
        return False
    try:
        if sys.platform == "win32":
            os.startfile(file_path)  # type: ignore[attr-defined]
        else:
            import subprocess

            subprocess.Popen(
                ["open" if sys.platform == "darwin" else "xdg-open", file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as e:
        logger.exception(f"打开文件失败：{e}")
        return False


def to_bool(value) -> bool:
    """把 JS / JSON 传来的各种真假值统一成 bool。"""
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


class API:
    IMAGE_FILE_TYPES: tuple[str, ...] = (
        "图片文件 (*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tiff;*.webp)",
        "所有文件 (*.*)",
    )
    REQUIRED_FIELDS: tuple[str, ...] = ("api_key", "base_url", "model")
    CONFIG_FILE: str = "model_config.json"

    def __init__(self) -> None:
        self.config_path = Path(get_resource_path(self.CONFIG_FILE))
        self.window: webview.Window | None = None
        self._busy = False
        self._last_data: list[dict] = []
        self.config: dict | None = self._load_config()
        self.client: MultClient | None = self._build_client(self.config)

    # 窗口 / 配置基础
    def set_window(self, window: "webview.Window") -> None:
        self.window = window

    def _load_config(self) -> dict | None:
        if not self.config_path.exists():
            logger.warning(f"配置文件不存在: {self.config_path}")
            return None
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
        except Exception as e:
            logger.error(f"配置文件读取失败: {e}")
            return None

        if not self._is_valid(config):
            logger.warning("配置文件内容不合法，缺少必填字段")
            return None

        config["is_label"] = to_bool(config.get("is_label"))
        logger.info("配置文件加载成功")
        return config

    @classmethod
    def _is_valid(cls, config: dict | None) -> bool:
        if not isinstance(config, dict):
            return False
        return all(
            isinstance(config.get(field), str) and config[field].strip()
            for field in cls.REQUIRED_FIELDS
        )

    @staticmethod
    def _build_client(config: dict | None) -> MultClient | None:
        if not config:
            return None
        try:
            return MultClient(config["api_key"], config["base_url"], config["model"])
        except Exception as e:
            logger.error(f"模型客户端创建失败: {e}")
            return None

    def get_config_status(self) -> dict:
        if self.client is None or not self.config:
            return {"valid": False, "config": None}
        return {"valid": True, "config": self.config}


    def save_config(
        self,
        api_key: str,
        base_url: str,
        model: str,
        is_label: bool = False,
    ) -> dict:
        api_key, base_url, model = api_key.strip(), base_url.strip(), model.strip()

        if not (api_key and base_url and model):
            logger.warning("保存配置失败：存在未填写的必填项")
            return {"success": False, "message": "API Key、Base URL 和 Model 均为必填项"}

        config = {
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "is_label": to_bool(is_label),
        }

        
        client:MultClient = self._build_client(config)
        if client is None or not asyncio.run(client.test_api()):
            logger.error("API 连通性校验失败，配置未保存")
            return {"success": False, "message": "无效的 api_key 或 base_url，请检查后重试"}

        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=4)
        except Exception as e:
            logger.exception(f"配置写入失败: {e}")
            return {"success": False, "message": f"配置保存失败: {e}"}

        self.config, self.client = config, client
        logger.info(f"配置保存成功，当前模型: {model}")
        return {"success": True, "message": "配置保存成功！"}

    # ------------------------------------------------------------------ #
    # 接口 1：上传（选择）图片
    # ------------------------------------------------------------------ #
    def select_images(self) -> dict:
        if self.window is None:
            logger.error("窗口未就绪，无法打开文件选择框")
            return {"success": False, "message": "窗口未就绪", "paths": []}
        try:
            paths = self.window.create_file_dialog(
                webview.OPEN_DIALOG,
                allow_multiple=True,
                file_types=self.IMAGE_FILE_TYPES,
            )
            selected:list[str] = list(paths) if paths else []
            logger.info(f"已选择 {len(selected)} 张图片")
            return {"success": True, "paths": selected}
        except Exception as e:
            logger.exception(f"文件选择失败: {e}")
            return {"success": False, "message": f"文件选择失败: {e}", "paths": []}

    # ------------------------------------------------------------------ #
    # 接口 2：目标检测并生成结果
    # ------------------------------------------------------------------ #
    def _check_ready(self, img_list: list[str]) -> tuple[list[str], str | None]:
        if self.client is None:
            logger.warning("未检测到有效的模型配置")
            return [], "未检测到有效的模型配置，请先配置模型参数"
        img_list = [p for p in (img_list or []) if p and os.path.exists(p)]
        if not img_list:
            logger.warning("图片列表为空或路径均不存在")
            return [], "没有可用的图片，请重新选择"
        return img_list, None

    def _resolve_label(self, is_label: bool | None) -> bool:
        if is_label is None:
            return to_bool((self.config or {}).get("is_label"))
        return to_bool(is_label)

    def start_generation(self, img_list: list[str], is_label: bool | None = None) -> dict:
        img_list, error = self._check_ready(img_list)
        if error:
            return {"success": False, "message": error}

        if self._busy:
            logger.warning("已有任务正在执行，忽略本次请求")
            return {"success": False, "message": "已有任务正在执行，请稍候"}

        self._busy = True
        threading.Thread(
            target=self._run_task,
            args=(img_list, self._resolve_label(is_label)),
            daemon=True,
        ).start()
        logger.info(f"后台任务已启动，待处理图片 {len(img_list)} 张")
        return {"success": True, "message": "任务已启动"}

    def detect_images(self, img_list: list[str], is_label: bool | None = None) -> dict:
        img_list, error = self._check_ready(img_list)
        if error:
            return {"success": False, "message": error, "data": []}

        try:
            data = asyncio.run(self._detect(img_list, self._resolve_label(is_label)))
        except Exception as e:
            logger.exception(f"检测失败: {e}")
            return {"success": False, "message": f"检测失败: {e}", "data": []}

        logger.info(f"检测完成，共 {len(data)} 张图片")
        return {"success": True, "message": f"检测完成，共 {len(data)} 张图片", "data": data}

    @staticmethod
    def _to_data_uri(image: object) -> str:
        if isinstance(image, Image.Image):
            buf = io.BytesIO()
            image.convert("RGB").save(buf, format="JPEG", quality=95)
            image = base64.b64encode(buf.getvalue()).decode()
        elif not isinstance(image, str):
            raise TypeError(f"不支持的图片数据类型: {type(image)}")
        return image if image.startswith("data:image") else f"data:image/jpeg;base64,{image}"

    async def _detect(self, img_list: list[str], is_label: bool) -> list[dict]:
        """调用异步目标检测，返回 [{image, label}, ...]，image 统一为 data URI。"""
        results = await self.client.batch_infer(img_list, is_label)
        for item in results:
            item["image"] = self._to_data_uri(item.get("image"))
        return results

    def _run_task(self, img_list: list[str], is_label: bool) -> None:
        """后台线程：检测 -> 回调前端（结果由前端用 JSON 渲染）。"""
        self._js("window.taskStarted()")
        try:
            data = asyncio.run(self._detect(img_list, is_label))
            self._last_data = data
            logger.info(f"检测完成，共 {len(data)} 张图片")
            self._notify(True, f"检测完成，共处理 {len(data)} 张图片", data)
        except Exception as e:
            logger.exception(f"检测失败: {e}")
            self._notify(False, f"检测失败: {e}")
        finally:
            self._busy = False

    def _export(self, exporter: Callable[[list[dict]], str], data: list[dict] | None) -> dict:
        data = data or self._last_data
        if not data:
            logger.warning("导出失败：没有可导出的检测结果")
            return {"success": False, "message": "没有可导出的检测结果，请先执行检测"}

        try:
            output_path = str(exporter(data))
        except Exception as e:
            logger.exception(f"导出失败: {e}")
            return {"success": False, "message": f"导出失败: {e}"}

        logger.info(f"报告已生成: {output_path}")
        open_file_with_default_app(output_path)
        return {"success": True, "message": "导出成功", "path": output_path}

    def export_word(self, data: list[dict] | None = None) -> dict:
        return self._export(export_to_word, data)

    def export_excel(self, data: list[dict] | None = None) -> dict:
        return self._export(export_to_excel, data)

   
    def _js(self, script: str) -> None:
        if self.window is None:
            logger.warning("窗口未就绪，跳过 JS 调用")
            return
        try:
            self.window.evaluate_js(script)
        except Exception as e:
            logger.error(f"JS 调用失败: {e}")

    def _notify(self, success: bool, message: str, data: list[dict] | None = None) -> None:
        args = json.dumps([success, message, data or []], ensure_ascii=False)[1:-1]
        self._js(f"window.taskCompleted({args})")


def main() -> None:
    api = API()
    window = webview.create_window(
        "Model Configurator",
        url=get_resource_path("assets/index.html"),
        js_api=api,
        width=600,
        height=450,
        resizable=True,
        min_size=(480, 360),
        frameless=False,
        background_color="#f5f7fa",
    )
    api.set_window(window)
    logger.info("应用启动")
    webview.start(debug=True)
    logger.info("应用退出")


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
