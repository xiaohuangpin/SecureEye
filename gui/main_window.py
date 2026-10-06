"""主窗口：FluentWindow 组装四个页面，并用 qasync 驱动异步业务。"""
import asyncio
import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QFileDialog
from qasync import asyncSlot
from qfluentwidgets import (
    FluentIcon,
    FluentWindow,
    InfoBar,
    InfoBarPosition,
)

from gui.common import BusyOverlay
from gui.controller import AppController
from gui.interfaces import ConfigInterface, HomeInterface, PromptInterface, ResultInterface
from gui.login_dialog import LoginDialog

logger = logging.getLogger(__name__)

IMAGE_FILTER = "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp);;所有文件 (*.*)"


class MainWindow(FluentWindow):
    def __init__(self, controller: AppController):
        super().__init__()
        self.controller = controller
        self._busy = False
        self._overlay = BusyOverlay(self)

        self.homeInterface = HomeInterface(self)
        self.configInterface = ConfigInterface(self)
        self.promptInterface = PromptInterface(self)
        self.resultInterface = ResultInterface(self)

        self.addSubInterface(self.homeInterface, FluentIcon.HOME, "首页")
        self.addSubInterface(self.configInterface, FluentIcon.SETTING, "模型配置")
        self.addSubInterface(self.promptInterface, FluentIcon.EDIT, "系统提示词")
        self.addSubInterface(self.resultInterface, FluentIcon.VIEW, "检测结果")

        self.homeInterface.configRequested.connect(lambda: self.switchTo(self.configInterface))
        self.homeInterface.detectRequested.connect(self._on_detect)
        self.configInterface.saveRequested.connect(self._on_save)
        self.promptInterface.saveRequested.connect(self._on_save_prompt)
        self.resultInterface.excelRequested.connect(self._on_export_excel)
        self.resultInterface.wordRequested.connect(self._on_export_word)

        self.resize(720, 560)
        self.setMinimumSize(560, 440)
        self.setWindowTitle("安全隐患智能排查")
        self.navigationInterface.setExpandWidth(200)

        # 窗口先显示，账号解锁/配置加载在事件循环内异步完成，UI 不卡顿
        QTimer.singleShot(0, self._bootstrap)

    # ------------------------------------------------------------------ #
    @asyncSlot()
    async def _bootstrap(self) -> None:
        """启动流程：首次注册（邮箱+密码）或自动解锁（免密），随后载入配置。"""
        if self.controller.has_account():
            self._overlay.start("正在验证账号…")
            try:
                await self.controller.login()
            finally:
                self._overlay.stop()
        else:
            creds = LoginDialog(self).run()
            if creds is None:  # 用户取消注册，退出应用
                self.close()
                return
            self._overlay.start("正在创建账号…")
            try:
                await self.controller.register(*creds)
            finally:
                self._overlay.stop()

        if self.controller.config_valid and self.controller.config:
            self.configInterface.set_config(self.controller.config)
            self.promptInterface.set_prompt(self.controller.config.get("system_prompt", ""))
        else:
            self.switchTo(self.configInterface)
            self._info("info", "请先完成模型配置", "提示")

    def _info(self, kind: str, content: str, title: str) -> None:
        fn = getattr(InfoBar, kind)
        fn(title=title, content=content, duration=2600, position=InfoBarPosition.TOP, parent=self)

    # ------------------------------------------------------------------ #
    @asyncSlot()
    async def _on_save(self) -> None:
        if self._busy:
            return
        self._busy = True
        api_key, base_url, model, is_label, font_size = self.configInterface.values()
        self.configInterface.saveBtn.setEnabled(False)
        self._overlay.start("正在校验并保存配置…")  # 包含网络探测，给明确反馈避免看似卡住
        try:
            res = await self.controller.save_config(api_key, base_url, model, is_label, font_size)
        finally:
            self._overlay.stop()
            self.configInterface.saveBtn.setEnabled(True)
            self._busy = False
        self._info("success" if res["success"] else "error", res["message"], "模型配置")
        if res["success"]:
            self.switchTo(self.homeInterface)

    @asyncSlot(str)
    async def _on_save_prompt(self, prompt: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.promptInterface.saveBtn.setEnabled(False)
        try:
            res = await self.controller.save_prompt(prompt)
        finally:
            self.promptInterface.saveBtn.setEnabled(True)
            self._busy = False
        self._info("success" if res["success"] else "error", res["message"], "系统提示词")
        if res["success"]:
            self.promptInterface.mark_saved()

    @asyncSlot()
    async def _on_detect(self) -> None:
        if self._busy:
            return
        if not self.controller.config_valid:
            self.switchTo(self.configInterface)
            self._info("info", "请先完成模型配置", "提示")
            return

        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择图片", "", IMAGE_FILTER
        )
        if not paths:
            self._info("info", "未选择任何图片", "提示")
            return

        self._busy = True
        self.homeInterface.detectBtn.setEnabled(False)
        self._overlay.start(f"正在检测 {len(paths)} 张图片…")
        try:
            res = await self.controller.detect(paths, self.configInterface.drawSwitch.isChecked())
        finally:
            self._overlay.stop()
            self.homeInterface.detectBtn.setEnabled(True)
            self._busy = False

        self._info("success" if res["success"] else "error", res["message"], "检测")
        if res["success"]:
            self.resultInterface.render(res["data"])
            self.switchTo(self.resultInterface)

    # ------------------------------------------------------------------ #
    @asyncSlot()
    async def _on_export(self, exporter) -> None:
        if self._busy:
            return
        self._busy = True
        self._overlay.start("正在导出…")
        try:
            res = await asyncio.to_thread(exporter)  # 写 docx/xlsx 耗时，不阻塞 UI
        finally:
            self._overlay.stop()
            self._busy = False
        msg = "导出成功，正在打开文件" if res["success"] else res["message"]
        self._info("success" if res["success"] else "error", msg, "导出")

    def _on_export_excel(self) -> None:
        self._on_export(self.controller.export_excel)

    def _on_export_word(self) -> None:
        self._on_export(self.controller.export_word)

    # ------------------------------------------------------------------ #
    def closeEvent(self, event) -> None:  # noqa: N802
        """退出前立即释放大对象（结果卡片 / data URI），异步收尾见 main_GUI。"""
        self.resultInterface.render([])
        self.controller.last_results = []
        super().closeEvent(event)
