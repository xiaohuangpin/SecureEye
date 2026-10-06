"""SecureEye GUI 启动入口（PySide6 + QFluentWidgets + qasync + SQLite）。

启动流程：
1. QApplication 创建后立即初始化 SQLite 连接与建表（不在使用时才建）。
2. 窗口显示后由 MainWindow._bootstrap 异步完成注册/自动解锁（scrypt 在工作线程）。
3. 退出时关闭 AsyncOpenAI 连接池与数据库连接，及时释放资源。
"""
import asyncio
import logging
import multiprocessing
import sys
from PySide6.QtWidgets import QApplication
from db.store import Store
from gui.controller import AppController
from gui.main_window import MainWindow
from qasync import QEventLoop
from qfluentwidgets import Theme, setTheme


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    app = QApplication(sys.argv)
    app.setApplicationName("SecureEye")
    setTheme(Theme.LIGHT)

    store = Store()  # 数据库连接在应用启动时即初始化
    controller = AppController(store)

    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(controller)
    window.show()

    try:
        loop.run_forever()
    finally:
        loop.run_until_complete(controller.aclose())  # 释放 HTTP 连接池与 DB 句柄
        loop.close()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()


