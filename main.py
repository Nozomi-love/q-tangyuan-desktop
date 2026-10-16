"""Run the Phase 1 desktop pet: python main.py."""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys

if sys.version_info < (3, 10):
    raise SystemExit("Q弹汤圆需要 Python 3.10 或更高版本。")

try:
    from PySide6.QtCore import QPointF, Qt, QTimer
    from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPainter, QPixmap
    from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon
except ModuleNotFoundError as error:
    if error.name and error.name.startswith("PySide6"):
        raise SystemExit(
            "缺少 PySide6。请在项目目录执行：\n"
            "  .\\.venv\\Scripts\\python.exe -m pip install -r requirements.txt\n"
            "然后执行：.\\.venv\\Scripts\\python.exe main.py"
        ) from error
    raise

from pet_engine import PetEngine, SkinRenderer, WorkArea
from pet_window import PetWindow
from save_manager import SaveDataError, SaveManager

PROJECT_ROOT = Path(__file__).resolve().parent


def create_tray_icon(renderer: SkinRenderer | None = None) -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(32.0, 59.0)
    painter.scale(0.43, 0.43)
    if renderer is not None and renderer.pixmaps:
        icon_engine = PetEngine(WorkArea(0, 0, 300, 300))
        renderer.paint(painter, icon_engine, QPointF(0, 0))
    else:
        SkinRenderer.paint_fallback(painter)
    painter.end()
    return QIcon(pixmap)


class PetApplication:
    """Own the overlay, shared menu, and tray for their entire lifetime."""

    def __init__(self, app: QApplication, save_path: Path | None = PROJECT_ROOT / "data" / "save_data.json") -> None:
        self.app = app
        self.save_manager = SaveManager(save_path) if save_path is not None else None
        self._restoring = True
        self._stopped = False
        self.window = PetWindow(PROJECT_ROOT / "assets" / "skins" / "default")
        self.icon = create_tray_icon(self.window.renderer)
        app.setWindowIcon(self.icon)
        self.window.setWindowIcon(self.icon)

        self.menu = QMenu(self.window)
        self.reset_action = QAction("重置回主屏幕右下角", self.menu)
        self.pin_action = QAction("固定当前位置（可拖动调整）", self.menu)
        self.pin_action.setCheckable(True)
        self.flat_action = QAction("切换测试饿扁状态", self.menu)
        self.flat_action.setCheckable(True)
        self.reload_action = QAction("重新加载表情 PNG", self.menu)
        self.quit_action = QAction("退出程序", self.menu)

        self.menu.addAction(self.reset_action)
        self.menu.addAction(self.pin_action)
        self.menu.addAction(self.flat_action)
        self.menu.addAction(self.reload_action)
        self.menu.addSeparator()
        self.menu.addAction(self.quit_action)

        self.reset_action.triggered.connect(self.window.reset_to_primary)
        self.pin_action.toggled.connect(self.window.set_pinned)
        self.window.pinned_changed.connect(self.pin_action.setChecked)
        self.window.position_changed.connect(self._save_position)
        self.flat_action.toggled.connect(self.window.set_test_flat)
        self.reload_action.triggered.connect(self._reload_skins)
        self.quit_action.triggered.connect(app.quit)
        self.window.context_menu_requested.connect(self.menu.popup)
        self.window.close_requested.connect(app.quit)

        self.tray = QSystemTrayIcon(self.icon, app)
        self.tray.setToolTip("Q弹汤圆 · 戳一戳，或拖起来轻轻抛下")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            logging.warning("系统托盘当前不可用；右键汤圆仍可重置、切换饿扁和退出。")

        self._restore_position()
        self._restoring = False
        app.aboutToQuit.connect(self.stop)
        self.window.show()

    def _restore_position(self) -> None:
        if self.save_manager is None:
            return
        try:
            self.window.restore_position(self.save_manager.load_window_state())
        except SaveDataError as error:
            logging.warning("无法恢复固定位置：%s", error)

    def _save_position(self) -> None:
        if self.save_manager is None or self._restoring or self._stopped:
            return
        try:
            self.save_manager.update_window(self.window.capture_position())
        except SaveDataError as error:
            logging.warning("固定位置尚未保存：%s", error)

    def _reload_skins(self) -> None:
        self.window.reload_skins()
        self.icon = create_tray_icon(self.window.renderer)
        self.app.setWindowIcon(self.icon)
        self.window.setWindowIcon(self.icon)
        self.tray.setIcon(self.icon)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.window.reset_to_primary()

    def stop(self) -> None:
        if self._stopped:
            return
        self._save_position()
        self._stopped = True
        self.window.stop()
        self.menu.hide()
        self.tray.hide()
        self.window.hide()


def main() -> int:
    parser = argparse.ArgumentParser(description="Q弹汤圆 · Phase 1")
    parser.add_argument("--smoke-test", action="store_true",
                        help="启动真实窗口与托盘，2 秒后输出诊断并自动退出")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    # Qt 6 already enables high DPI. Never multiply globalPosition or screen
    # geometry by devicePixelRatio; only painting uses the backing-store DPR.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Q弹汤圆")
    app.setOrganizationName("Q弹汤圆")
    app.setQuitOnLastWindowClosed(False)

    style_path = PROJECT_ROOT / "styles" / "theme.qss"
    if style_path.is_file():
        app.setStyleSheet(style_path.read_text(encoding="utf-8"))

    def report_exception(exc_type: type, value: BaseException, traceback: object) -> None:
        logging.critical("桌宠发生未处理异常", exc_info=(exc_type, value, traceback))
        app.exit(1)

    sys.excepthook = report_exception
    controller = PetApplication(app, save_path=None) if args.smoke_test else PetApplication(app)
    if args.smoke_test:
        def finish_smoke() -> None:
            window = controller.window
            area = window.engine.area
            diagnostics = {
                "platform": QGuiApplication.platformName(),
                "screens": len(QGuiApplication.screens()),
                "active_screen": window.active_screen.name(),
                "device_pixel_ratio": window.devicePixelRatioF(),
                "work_area": [area.left, area.top, area.width, area.height],
                "foot": [round(window.engine.x, 3), round(window.engine.y, 3)],
                "frames": window.frame_count,
                "loaded_png_states": sorted(state.value for state in window.renderer.pixmaps),
                "tray_available": QSystemTrayIcon.isSystemTrayAvailable(),
                "visible": window.isVisible(),
                "pinned": window.engine.pinned,
            }
            print("PHASE1_SMOKE_OK " + json.dumps(diagnostics, ensure_ascii=False), flush=True)
            app.quit()
        QTimer.singleShot(2000, finish_smoke)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
