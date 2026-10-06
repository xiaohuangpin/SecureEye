"""通用工具：镜像编解码、文件打开、加载遮罩。"""
import base64
import io
import logging
import os
import subprocess
import sys

from PIL import Image
from PySide6.QtCore import Qt, QEvent, QBuffer, QByteArray, QIODevice, QSize
from PySide6.QtGui import QColor, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout
from qfluentwidgets import IndeterminateProgressRing, SimpleCardWidget, StrongBodyLabel

from core.agent import MultClient

logger = logging.getLogger(__name__)


def open_file_with_default_app(file_path: str) -> bool:
    """用系统默认程序打开文件。"""
    if not file_path or not os.path.exists(file_path):
        logger.error(f"文件 {file_path} 不存在")
        return False
    try:
        if sys.platform == "win32":
            os.startfile(file_path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(
                ["open" if sys.platform == "darwin" else "xdg-open", file_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        return True
    except Exception as e:
        logger.exception(f"打开文件失败：{e}")
        return False


def to_data_uri(image: Image.Image | str) -> str:
    """把检测结果里的图像统一成 data URI 字符串（供展示与导出使用）。"""
    if isinstance(image, Image.Image):
        buf = io.BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=MultClient.JPEG_QUALITY)
        image = base64.b64encode(buf.getvalue()).decode()
    elif not isinstance(image, str):
        raise TypeError(f"不支持的图片数据类型: {type(image)}")
    return image if image.startswith("data:image") else f"data:image/jpeg;base64,{image}"


def _uri_bytes(uri: str) -> bytes:
    """data URI -> 原始图像字节。"""
    return base64.b64decode(uri.split(",", 1)[1]) if "," in uri else base64.b64decode(uri)


def pixmap_from_data_uri(uri: str) -> QPixmap:
    """data URI 字符串 -> QPixmap（全尺寸，供放大预览）。"""
    pixmap = QPixmap()
    pixmap.loadFromData(_uri_bytes(uri))
    return pixmap


def thumbnail_from_data_uri(uri: str, width: int = 280) -> QPixmap:
    """data URI -> 缩略图：先让 JPEG 解码器在 DCT 域预缩到 2 倍目标宽，再平滑缩放；
    避开整幅解码（实测 2048px 图 70ms/张 → 24ms/张，这些开销全在 GUI 线程）。"""
    data = QByteArray(_uri_bytes(uri))
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(buffer)
    src = reader.size()
    if src.width() > width * 2:  # 尺寸未知或小图不预缩
        reader.setScaledSize(QSize(width * 2, max(1, src.height() * width * 2 // src.width())))
    pixmap = QPixmap.fromImage(reader.read())
    buffer.close()
    if pixmap.width() > width:
        pixmap = pixmap.scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)
    return pixmap


class BusyOverlay(QWidget):
    """全窗口加载遮罩：半透暗纱帘 + 居中浮卡，阻塞交互。

    作为父窗口子控件覆盖整个客户区，随父窗口缩放自动重新居中；
    耗时任务请放工作线程/协程，事件循环保持转动，转圈动画才会刷新。
    """

    _DIM = QColor(0, 0, 0, 110)  # 约 43% 黑，明/暗主题下都能看出压暗效果

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(parent.rect())
        self.hide()
        parent.installEventFilter(self)  # 跟随父窗口尺寸变化

        # 不用 ElevatedCardWidget：阴影特效使每帧重绘成本翻倍，且鼠标掠过时会弹跳位
        self._card = SimpleCardWidget(self)
        box = QVBoxLayout(self._card)
        box.setContentsMargins(36, 28, 36, 28)
        box.setSpacing(16)
        # start=False：隐藏时不跑 60fps 动画帧，避免与检测线程抢 GIL
        self._ring = IndeterminateProgressRing(self._card, start=False)
        self._ring.setFixedSize(44, 44)
        self._label = StrongBodyLabel("正在处理，请稍候…", self._card)
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        box.addWidget(self._ring, 0, Qt.AlignmentFlag.AlignHCenter)
        box.addWidget(self._label, 0, Qt.AlignmentFlag.AlignHCenter)

    # ------------------------------------------------------------------ #
    def start(self, text: str = "正在处理，请稍候…") -> None:
        self._label.setText(text)
        if parent := self.parentWidget():
            self.setGeometry(parent.rect())
        self.show()
        self.raise_()
        self._ring.start()
        self.repaint()  # 同步画一帧：紧接着的同步代码也不会遮挡反馈

    def stop(self) -> None:
        self._ring.stop()
        self.hide()

    # ------------------------------------------------------------------ #
    def eventFilter(self, obj, event):
        if obj is self.parentWidget() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        card = self._card
        card.adjustSize()
        card.move((self.width() - card.width()) // 2, (self.height() - card.height()) // 2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), BusyOverlay._DIM)  # 压暗整页，突出居中浮卡

    def mousePressEvent(self, event):  # noqa: N802
        event.accept()  # 吞掉点击，阻断穿透到底下页面

    def mouseReleaseEvent(self, event):  # noqa: N802
        event.accept()
