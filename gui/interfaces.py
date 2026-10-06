"""四个功能页面：首页、模型配置、系统提示词、检测结果。"""
from PySide6.QtCore import Qt, QRect, QSize, Signal
from PySide6.QtGui import (
    QColor,
    QFontDatabase,
    QKeySequence,
    QPainter,
    QPalette,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    FluentIcon,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    SimpleCardWidget,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    SwitchButton,
    TitleLabel,
    isDarkTheme,
)

from core.agent import MultClient
from gui.common import pixmap_from_data_uri, thumbnail_from_data_uri


class ClickLabel(QLabel):
    """可点击的缩略图标签；仅持有缩略图 + data URI 引用（与 last_results 共享），
    全尺寸图像在点开预览时才即时解码，避免常驻内存。"""

    clicked = Signal(str)

    def __init__(self, uri: str, parent=None):
        super().__init__(parent)
        self._uri = uri
        self.setScaledContents(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._uri)
        super().mousePressEvent(event)


class _PreviewDialog(QDialog):
    """图片放大预览，点击任意处关闭。"""

    def __init__(self, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.setWindowTitle("图片预览")
        screen = QApplication.primaryScreen().availableGeometry().size()
        max_w, max_h = int(screen.width() * 0.85), int(screen.height() * 0.85)
        self._view = QLabel()
        self._view.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._view.setPixmap(
            pixmap.scaled(max_w, max_h, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self._view)
        self.resize(self._view.pixmap().size())


class HomeInterface(QWidget):
    configRequested = Signal()
    detectRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeInterface")

        logo = QLabel("🦺")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setStyleSheet("font-size: 64px;")

        title = TitleLabel("安全隐患智能排查", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle = BodyLabel("基于多模态大模型的工地违规作业识别", self)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.configBtn = PushButton("模型配置", self, FluentIcon.SETTING)
        self.detectBtn = PrimaryPushButton("安全隐患检测", self, FluentIcon.SEARCH)
        for btn in (self.configBtn, self.detectBtn):
            btn.setFixedWidth(240)
            btn.setMinimumHeight(42)

        btnRow = QVBoxLayout()
        btnRow.setSpacing(12)
        btnRow.addWidget(self.detectBtn, 0, Qt.AlignmentFlag.AlignHCenter)
        btnRow.addWidget(self.configBtn, 0, Qt.AlignmentFlag.AlignHCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 40, 40, 40)
        layout.addStretch(1)
        layout.addWidget(logo)
        layout.addWidget(title)
        layout.addWidget(subtitle, 0, Qt.AlignmentFlag.AlignCenter)
        layout.addSpacing(28)
        layout.addLayout(btnRow)
        layout.addStretch(2)

        self.configBtn.clicked.connect(self.configRequested)
        self.detectBtn.clicked.connect(self.detectRequested)


class ConfigInterface(QWidget):
    saveRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("configInterface")

        self.apiKey = PasswordLineEdit(self)
        self.apiKey.setPlaceholderText("请输入 API 密钥")
        self.baseUrl = LineEdit(self)
        self.baseUrl.setPlaceholderText("https://api.example.com/v1")
        self.model = LineEdit(self)
        self.model.setPlaceholderText("qwen-vl-max")
        self.drawSwitch = SwitchButton(self)
        self.drawSwitch.setChecked(True)
        self.fontSize = SpinBox(self)
        self.fontSize.setRange(MultClient.MIN_FONT_SIZE, MultClient.MAX_FONT_SIZE)
        self.fontSize.setSuffix(" px")
        self.fontSize.setValue(MultClient.DEFAULT_FONT_SIZE)
        self.fontSize.setMinimumWidth(110)
        # 不拉伸也不写死：跟随 sizeHint，兼顾高分屏下“NN px”不被裁切
        self.fontSize.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)

        card = SimpleCardWidget(self)
        form = QVBoxLayout(card)
        form.setSpacing(14)
        form.setContentsMargins(24, 20, 24, 20)
        form.addLayout(self._field("API Key", self.apiKey))
        form.addLayout(self._field("Base URL", self.baseUrl))
        form.addLayout(self._field("Model", self.model))
        form.addLayout(self._row("在图片中绘制检测框", self.drawSwitch))
        form.addLayout(self._row("标注字体大小", self.fontSize))

        self.saveBtn = PrimaryPushButton("保存配置", self, FluentIcon.SAVE)
        self.saveBtn.setMinimumHeight(40)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 30, 36, 30)
        layout.addWidget(SubtitleLabel("模型配置", self))
        # 强提醒：必须是支持图像输入的多模态模型，否则检测必然失败
        tip = StrongBodyLabel("需使用多模态大模型（支持图像输入），纯文本模型无法完成检测", self)
        font = tip.font()
        font.setBold(True)  # StrongBodyLabel 仅 600（Semibold），这里要真加粗
        tip.setFont(font)
        layout.addWidget(tip)
        layout.addSpacing(8)
        layout.addWidget(card)
        layout.addWidget(self.saveBtn)
        layout.addStretch(1)

        self.saveBtn.clicked.connect(self.saveRequested)

    @staticmethod
    def _field(name: str, widget: QWidget) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(6)
        box.addWidget(CaptionLabel(name))
        box.addWidget(widget)
        return box

    @staticmethod
    def _row(name: str, widget: QWidget) -> QHBoxLayout:
        """名称在左、控件在右的设置行（开关 / 数字输入等小控件）"""
        row = QHBoxLayout()
        row.addWidget(StrongBodyLabel(name))
        row.addStretch(1)
        row.addWidget(widget)
        return row

    def set_config(self, config: dict) -> None:
        self.apiKey.setText(config.get("api_key", ""))
        self.baseUrl.setText(config.get("base_url", ""))
        self.model.setText(config.get("model", ""))
        self.drawSwitch.setChecked(bool(config.get("is_label")))
        self.fontSize.setValue(MultClient.clamp_font_size(config.get("font_size")))

    def values(self) -> tuple[str, str, str, bool, int]:
        return (
            self.apiKey.text().strip(),
            self.baseUrl.text().strip(),
            self.model.text().strip(),
            self.drawSwitch.isChecked(),
            self.fontSize.value(),
        )


class LineNumberArea(QWidget):
    """编辑器左侧行号栏：绘制交给编辑器完成，保证与正文滚动严格对齐。"""

    def __init__(self, editor: "PromptEditor") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._editor.line_number_width(), 0)

    def paintEvent(self, event):  # noqa: N802
        self._editor.paint_line_numbers(event)


class PromptEditor(QPlainTextEdit):
    """VSCode 风格纯文本编辑器：行号 + 当前行高亮 + 等宽字体 + 自动缩进。"""

    GUTTER_PAD = 10
    HL_COLOR = QColor(0, 120, 212, 28)  # 当前行淡蓝底纹（半透明叠加，不改字形颜色）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._lines = LineNumberArea(self)

        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(11)
        self.setFont(font)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))  # Tab ≈ 4 空格
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        dark = isDarkTheme()  # 原生 QPlainTextEdit 不跟随 Fluent 主题，显式给一套调色板
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor(43, 43, 43) if dark else QColor(255, 255, 255))
        palette.setColor(QPalette.ColorRole.Text, QColor(220, 220, 220) if dark else QColor(32, 32, 32))
        palette.setColor(QPalette.ColorRole.Window, QColor(32, 32, 32) if dark else QColor(250, 250, 250))
        self.setPalette(palette)
        self._lines.setPalette(palette)

        self.cursorPositionChanged.connect(self._repaint_state)
        self.blockCountChanged.connect(lambda _: self._sync_gutter())
        self.updateRequest.connect(self._on_update_request)
        self._sync_gutter()

    # ------------------------------------------------------------------ #
    def line_number_width(self) -> int:
        digits = max(2, len(str(self.blockCount())))
        return self.GUTTER_PAD * 2 + digits * self.fontMetrics().horizontalAdvance("9")

    def _sync_gutter(self) -> None:
        width = self.line_number_width()
        if self.viewportMargins().left() != width:
            self.setViewportMargins(width, 0, 0, 0)
        self._lines.update()

    def _on_update_request(self, rect, dy) -> None:
        if dy:  # 正文滚动：行号整体搬移，避免重算
            self._lines.scroll(0, dy)
        else:
            self._lines.update(0, rect.y(), self._lines.width(), rect.height())
            if rect.contains(self.viewport().rect()):
                self._sync_gutter()

    def _repaint_state(self) -> None:
        self.viewport().update()
        self._lines.update()

    # ------------------------------------------------------------------ #
    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        area = self.rect()
        self._lines.setGeometry(QRect(area.topLeft(), QSize(self.line_number_width(), area.height())))

    def paint_line_numbers(self, event) -> None:
        with QPainter(self._lines) as painter:  # 显式收尾，避免绘制中切换主题时 painter 泄漏
            painter.fillRect(event.rect(), self.palette().color(QPalette.ColorRole.Window))
            metrics = self.fontMetrics()
            block = self.firstVisibleBlock()
            number = block.blockNumber()
            top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
            bottom = top + round(self.blockBoundingRect(block).height())
            current = self.textCursor().blockNumber()
            while block.isValid() and top <= event.rect().bottom():
                if block.isVisible() and bottom >= event.rect().top():
                    role = (QPalette.ColorRole.Highlight if number == current
                            else QPalette.ColorRole.PlaceholderText)
                    painter.setPen(self.palette().color(role))
                    painter.drawText(0, top, self._lines.width() - self.GUTTER_PAD,
                                     metrics.height(), Qt.AlignmentFlag.AlignRight, str(number + 1))
                block = block.next()
                top = bottom
                bottom = top + round(self.blockBoundingRect(block).height())
                number += 1

    def paintEvent(self, event):  # noqa: N802
        super().paintEvent(event)  # 先正常绘制，再叠一层当前行底纹（避开重绘开销）
        if self.isReadOnly():
            return
        band = self.cursorRect()
        band.setLeft(0)
        band.setWidth(self.viewport().width())
        with QPainter(self.viewport()) as painter:
            painter.fillRect(band, self.HL_COLOR)

    def keyPressEvent(self, event):  # noqa: N802
        """回车保持上一行缩进，多行提示词排版不跑位"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not event.modifiers():
            text = self.textCursor().block().text()
            indent = text[: len(text) - len(text.lstrip())]
            super().keyPressEvent(event)
            if indent:
                self.insertPlainText(indent)
            return
        super().keyPressEvent(event)


class PromptInterface(QWidget):
    """系统提示词：可编辑段用 VSCode 风编辑器编写，固定输出模板由 core 追加、界面不展示。"""

    saveRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("promptInterface")
        self._saved = ""

        self.editor = PromptEditor(self)
        self.editor.setPlaceholderText("在此编写角色设定与重点识别行为…")
        self.editor.setPlainText(MultClient.DEFAULT_PROMPT_BODY)

        card = SimpleCardWidget(self)
        box = QVBoxLayout(card)
        box.setContentsMargins(6, 6, 6, 6)
        box.addWidget(self.editor)

        self.saveBtn = PrimaryPushButton("保存提示词", self, FluentIcon.SAVE)
        self.resetBtn = PushButton("恢复默认", self, FluentIcon.SYNC)
        self.statusLabel = CaptionLabel("", self)

        for sequence, slot in ((QKeySequence.StandardKey.Save, self._emit_save),
                               ("Ctrl+Shift+D", self._reset)):
            shortcut = QShortcut(sequence, self)
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)

        row = QHBoxLayout()
        row.addWidget(self.statusLabel)
        row.addStretch(1)
        row.addWidget(self.resetBtn)
        row.addWidget(self.saveBtn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.addWidget(SubtitleLabel("系统提示词", self))
        layout.addWidget(CaptionLabel(
            "只需编写角色与识别重点；结构化输出模板由程序固定追加，保证结果可解析", self))
        layout.addSpacing(6)
        layout.addWidget(card, 1)
        layout.addSpacing(6)
        layout.addLayout(row)

        self.saveBtn.clicked.connect(self._emit_save)
        self.resetBtn.clicked.connect(self._reset)
        self.editor.textChanged.connect(self._refresh_status)
        self.mark_saved()

    # ------------------------------------------------------------------ #
    def _emit_save(self) -> None:
        self.saveRequested.emit(self.editor.toPlainText())

    def _reset(self) -> None:
        self.editor.setPlainText(MultClient.DEFAULT_PROMPT_BODY)

    def _refresh_status(self) -> None:
        text = self.editor.toPlainText()
        state = "● 未保存" if text.strip() != self._saved else "✓ 已保存"
        self.statusLabel.setText(
            f"{state}　{self.editor.blockCount()} 行 · {len(text)} 字　"
            "Ctrl+S 保存 · Ctrl+Shift+D 恢复默认")

    def set_prompt(self, prompt: str) -> None:
        self.editor.setPlainText(prompt or MultClient.DEFAULT_PROMPT_BODY)
        self.mark_saved()

    def mark_saved(self) -> None:
        """写入成功后刷新“已保存”状态"""
        self._saved = self.editor.toPlainText().strip()
        self._refresh_status()


class ResultInterface(QWidget):
    excelRequested = Signal()
    wordRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("resultInterface")

        self.countLabel = CaptionLabel("", self)
        self.excelBtn = PushButton("导出 Excel", self, FluentIcon.DOCUMENT)
        self.wordBtn = PushButton("导出 Word", self, FluentIcon.SAVE)
        for btn in (self.excelBtn, self.wordBtn):
            btn.setEnabled(False)

        header = QHBoxLayout()
        header.addWidget(SubtitleLabel("安全隐患表", self))
        header.addStretch(1)
        header.addWidget(self.countLabel)
        header.addWidget(self.excelBtn)
        header.addWidget(self.wordBtn)

        self._container = QWidget()
        self._list = QVBoxLayout(self._container)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(12)
        self._list.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(self._container)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 24, 36, 24)
        layout.addLayout(header)
        layout.addSpacing(8)
        layout.addWidget(scroll)

        self.excelBtn.clicked.connect(self.excelRequested)
        self.wordBtn.clicked.connect(self.wordRequested)
        self.render([])

    def render(self, results: list[dict]) -> None:
        """重建结果卡片列表。"""
        while self._list.count() > 1:  # 保留末尾 stretch
            item = self._list.takeAt(0)
            if widget := item.widget():
                for label in widget.findChildren(QLabel):  # 先释放图像再销毁
                    label.setPixmap(QPixmap())
                widget.deleteLater()

        self.countLabel.setText(f"共 {len(results)} 张" if results else "")
        has = bool(results)
        self.excelBtn.setEnabled(has)
        self.wordBtn.setEnabled(has)

        if not has:
            self._list.insertWidget(0, BodyLabel("暂无检测结果", self))
            return

        for i, item in enumerate(results):
            self._list.insertWidget(i, self._build_card(item["image"], item.get("label", "")))

    def _build_card(self, uri: str, label: str) -> SimpleCardWidget:
        card = SimpleCardWidget(self._container)
        row = QHBoxLayout(card)
        row.setContentsMargins(14, 14, 14, 14)
        row.setSpacing(16)

        thumb = ClickLabel(uri, card)
        thumb.setPixmap(thumbnail_from_data_uri(uri))  # 只保留缩略图，全尺寸解码即刻释放
        thumb.clicked.connect(self._preview)
        row.addWidget(thumb, 0, Qt.AlignmentFlag.AlignTop)

        text = BodyLabel((label or "").strip() or "✅ 未发现隐患", card)
        text.setWordWrap(True)
        text.setAlignment(Qt.AlignmentFlag.AlignTop)
        row.addWidget(text, 1)
        return card

    def _preview(self, uri: str) -> None:
        """点开才解码全尺寸图，关闭立即释放。"""
        dialog = _PreviewDialog(pixmap_from_data_uri(uri), self.window())
        dialog.exec()
        dialog._view.clear()  # 释放大尺寸预览图，不等 GC
        dialog.deleteLater()
