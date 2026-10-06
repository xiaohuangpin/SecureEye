"""首次启动的账号注册对话框（仅本地，用于加密模型配置）。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CaptionLabel,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    SimpleCardWidget,
    TitleLabel,
)

MIN_PWD_LEN = 6


class LoginDialog(QDialog):
    """采集邮箱 + 密码完成本地注册；确认返回 (email, password)，取消返回 None。"""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("账号设置")
        self.setFixedSize(420, 340)
        self._result: tuple[str, str] | None = None

        title = TitleLabel("设置账号", self)
        tip = BodyLabel("邮箱与密码用于在本机加密模型配置中的 API Key，仅需在首次启动设置。", self)
        tip.setWordWrap(True)

        self.email = LineEdit(self)
        self.email.setPlaceholderText("邮箱地址")
        self.pwd = PasswordLineEdit(self)
        self.pwd.setPlaceholderText(f"密码（至少 {MIN_PWD_LEN} 位）")

        self.error = CaptionLabel("", self)
        self.error.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.submit = PrimaryPushButton("创建并进入", self)

        card = SimpleCardWidget(self)
        form = QVBoxLayout(card)
        form.setContentsMargins(24, 20, 24, 20)
        form.setSpacing(14)
        form.addWidget(self.email)
        form.addWidget(self.pwd)
        form.addWidget(self.error)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(12)
        layout.addWidget(title)
        layout.addWidget(tip)
        layout.addSpacing(6)
        layout.addWidget(card)
        layout.addWidget(self.submit)

        self.submit.clicked.connect(self._on_submit)

    def _on_submit(self) -> None:
        email, pwd = self.email.text().strip(), self.pwd.text()
        if "@" not in email or not email.replace("@", "").strip():
            return self._show_error("请输入有效的邮箱地址")
        if len(pwd) < MIN_PWD_LEN:
            return self._show_error(f"密码至少 {MIN_PWD_LEN} 位")
        self._result = (email, pwd)
        self.accept()

    def _show_error(self, msg: str) -> None:
        self.error.setText(msg)
        self.error.setStyleSheet("color: #e81123;")

    def run(self) -> tuple[str, str] | None:
        """模态显示；确认返回 (email, password)，取消返回 None。"""
        return self._result if self.exec() == QDialog.DialogCode.Accepted else None
