"""Run the desktop companion and shared growth model: python main.py."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
import logging
import math
from pathlib import Path
import sys
import time

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

from models import GameRules, PetData, PetModel
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
    """Coordinate model, windows and persistence using Qt signals."""

    def __init__(self, app: QApplication, save_path: Path | None = PROJECT_ROOT / "data" / "save_data.json",
                 accelerated: bool = False) -> None:
        self.app = app
        self.save_manager = SaveManager(save_path) if save_path is not None else None
        self._restoring = True
        self._stopped = False
        self._dirty = False
        self._save_blocked = False
        self._warned_save = False
        data, position = PetData(), {}
        if self.save_manager is not None:
            try:
                data, position = self.save_manager.load_all()
            except SaveDataError as error:
                self._save_blocked = True
                logging.warning("存档读取失败，本次只在内存体验，原文件保留：%s", error)
        self.model = PetModel(data, self._load_rules(accelerated))
        self.window = PetWindow(PROJECT_ROOT / "assets" / "skins" / "default")
        self.icon = create_tray_icon(self.window.renderer)
        app.setWindowIcon(self.icon)
        self.window.setWindowIcon(self.icon)
        self._build_menu()

        self.model.state_changed.connect(self._state_changed)
        self.model.starvation_changed.connect(self.window.set_starving)
        self.model.feedback.connect(self._feedback)
        self.model.upgraded.connect(self._upgraded)
        self.model.collectible_changed.connect(self._collectible_changed)
        self.model.fed.connect(self._fed)
        self.window.clicked.connect(self.model.poke)
        self.window.collectible_clicked.connect(self.model.claim_collectible)
        self.window.pinned_changed.connect(self.pin_action.setChecked)
        self.window.position_changed.connect(self._save_position)
        self.window.context_menu_requested.connect(self.menu.popup)
        self.window.close_requested.connect(app.quit)

        self.tray = QSystemTrayIcon(self.icon, app)
        self.tray.setToolTip("Q弹汤圆 · 右键喂食、摸头与查看状态")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            logging.warning("系统托盘当前不可用；右键汤圆仍可使用全部菜单。")

        self.window.restore_position(position)
        self.window.set_starving(self.model.starving)
        self.window.show_collectible(self.model.has_collectible)
        self._restoring = False
        self._dirty = True
        self._refresh_menu()
        self.tick_timer = QTimer(self.window)
        self.tick_timer.setInterval(1000)
        self.tick_timer.timeout.connect(self._tick)
        self._last_tick = time.monotonic()
        self.tick_timer.start()
        self.autosave_timer = QTimer(self.window)
        self.autosave_timer.setInterval(15000)
        self.autosave_timer.timeout.connect(self._save)
        self.autosave_timer.start()
        self.save_timer = QTimer(self.window)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(200)
        self.save_timer.timeout.connect(self._save)
        self.dev_action.setChecked(accelerated)
        app.aboutToQuit.connect(self.stop)
        self.window.show()
        self._save()
        if self._save_blocked:
            self.window.show_message("存档读取失败，原文件已保留；本次进度不写入。", "hungry")
        elif accelerated:
            self.window.show_message(f"🧪 加速：饥饿 {self.model.rules.hunger_seconds:g} 秒 -1，礼包 {self.model.rules.gift_seconds:g} 秒", "normal")

    @staticmethod
    def _load_rules(accelerated: bool) -> GameRules:
        try:
            return GameRules.from_catalog(PROJECT_ROOT / "config" / "catalog.json", accelerated)
        except (OSError, ValueError, TypeError, KeyError) as error:
            logging.warning("基础配置读取失败，使用内置数值：%s", error)
            return GameRules(hunger_seconds=2, gift_seconds=10, hungry_notice_seconds=8) if accelerated else GameRules()

    def _build_menu(self) -> None:
        self.menu = QMenu(self.window)
        self.level_info = self.menu.addAction("")
        self.hunger_info = self.menu.addAction("")
        self.coins_info = self.menu.addAction("")
        for action in (self.level_info, self.hunger_info, self.coins_info):
            action.setEnabled(False)
        self.menu.addSeparator()
        self.feed_action = self.menu.addAction("")
        self.pet_action = self.menu.addAction("")
        self.pin_action = self.menu.addAction("📌 固定当前位置（可拖动调整）")
        self.pin_action.setCheckable(True)
        self.dashboard_action = self.menu.addAction("🏠 打开主面板（Phase 3 启用）")
        self.menu.addSeparator()
        self.debug_menu = self.menu.addMenu("🧪 调试与外观")
        self.hunger_zero_action = self.debug_menu.addAction("[调试] 饥饿值归零")
        self.hunger_full_action = self.debug_menu.addAction("[调试] 饥饿值恢复满值")
        self.flat_action = self.debug_menu.addAction("手动测试饿扁（独立于真实饥饿）")
        self.flat_action.setCheckable(True)
        self.dev_action = self.debug_menu.addAction("开发测试加速模式")
        self.dev_action.setCheckable(True)
        self.gift_action = self.debug_menu.addAction("[调试] 立即生成拾币气泡")
        self.reset_action = self.menu.addAction("重置回主屏幕右下角")
        self.reload_action = self.debug_menu.addAction("重新加载表情 PNG")
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("❌ 退出程序")
        self.feed_action.triggered.connect(self.model.feed_sugar)
        self.pet_action.triggered.connect(self._pet_head)
        self.pin_action.toggled.connect(self.window.set_pinned)
        self.flat_action.toggled.connect(self.window.set_test_flat)
        self.dev_action.toggled.connect(self._set_accelerated)
        self.gift_action.triggered.connect(self.model.offer_collectible)
        self.hunger_zero_action.triggered.connect(lambda: self.model.set_hunger(0))
        self.hunger_full_action.triggered.connect(lambda: self.model.set_hunger(100))
        self.dashboard_action.triggered.connect(lambda: self.window.show_message("🏠 主面板将在 Phase 3 开放，现在可以右键喂食和摸头～"))
        self.reset_action.triggered.connect(self.window.reset_to_primary)
        self.reload_action.triggered.connect(self._reload_skins)
        self.quit_action.triggered.connect(self.app.quit)
        self.menu.aboutToShow.connect(self._refresh_menu)

    def _refresh_menu(self) -> None:
        data, rules = self.model.data, self.model.rules
        exp = "MAX" if data.affection_level == 30 else f"{data.affection_exp}/{self.model.exp_required}"
        self.level_info.setText(f"🍡 等级: Lv.{data.affection_level} (EXP: {exp})")
        self.hunger_info.setText(f"🍙 饥饿度: {data.hunger:g}/100" + (" · 饿扁啦" if self.model.starving else ""))
        self.coins_info.setText(f"🪙 糯米币: {data.coins}")
        self.feed_action.setText(f"🍬 快捷投喂白砂糖 (-{rules.sugar_cost}币, 饥饿+{rules.sugar_hunger:g}, 好感+{rules.sugar_exp})")
        self.feed_action.setEnabled(data.coins >= rules.sugar_cost)
        remaining = math.ceil(data.timers["pet_cooldown_remaining"])
        self.pet_action.setText("👋 摸摸头 (好感+3)" + (f" · 冷却 {remaining} 秒" if remaining else ""))
        self.pet_action.setEnabled(remaining == 0)
        self.gift_action.setEnabled(not self.model.has_collectible)

    def _state_changed(self, _state: dict) -> None:
        self._dirty = True
        self._refresh_menu()

    def _feedback(self, text: str, tone: str) -> None:
        self.window.show_message(text, tone)
        if hasattr(self, "save_timer"):
            self.save_timer.start()

    def _collectible_changed(self, available: bool) -> None:
        self.window.show_collectible(available)
        if hasattr(self, "save_timer"):
            self.save_timer.start()

    def _upgraded(self, level: int) -> None:
        self.window.engine.celebrate()
        self.window.show_message(f"🎉 好感度升至 Lv.{level}！奖励 30 糯米币", "level")

    def _fed(self) -> None:
        # Feeding also ends the cosmetic test, while true starvation is model-owned.
        self.flat_action.setChecked(False)
        self.window.engine.rebound()

    def _pet_head(self) -> None:
        if self.model.pet_head():
            self.window.engine.rebound()

    def _set_accelerated(self, enabled: bool) -> None:
        self.model.set_rules(self._load_rules(enabled))
        self._dirty = True
        self._refresh_menu()
        rules = self.model.rules
        self.window.show_message(f"{'🧪 加速已开启' if enabled else '正常计时'}：{rules.hunger_seconds:g} 秒掉饥饿 / {rules.gift_seconds:g} 秒礼包")

    def _tick(self) -> None:
        now = time.monotonic()
        delta, self._last_tick = now - self._last_tick, now
        # A long sleep/debugger pause does not become offline hunger or income.
        self.model.advance(delta if delta <= 5.0 else 1.0)

    def _save_position(self) -> None:
        self._dirty = True
        self._save()

    def _save(self) -> None:
        if self.save_manager is None or self._restoring or self._stopped or self._save_blocked or not self._dirty:
            return
        try:
            self.save_manager.update_game(self.model.snapshot(), self.window.capture_position())
            self._dirty = False
        except SaveDataError as error:
            logging.warning("本次进度尚未保存：%s", error)
            if not self._warned_save:
                self._warned_save = True
                self.window.show_message("存档写入受阻，原文件保留。请检查是否开了多个桌宠。", "hungry")

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
        self._save()
        self._stopped = True
        for timer in (self.tick_timer, self.autosave_timer, self.save_timer):
            timer.stop()
        self.window.stop()
        self.menu.hide()
        self.tray.hide()
        self.window.hide()


def main() -> int:
    parser = argparse.ArgumentParser(description="Q弹汤圆 · Phase 2")
    parser.add_argument("--smoke-test", action="store_true",
                        help="启动真实窗口与托盘，2 秒后输出诊断并自动退出")
    parser.add_argument("--dev-mode", action="store_true", help="开启养成计时加速：饥饿 2 秒、拾币 10 秒")
    parser.add_argument("--demo", action="store_true", help="创建独立演示存档，不影响正式玩家数据")
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
    save_path = PROJECT_ROOT / "data" / "save_data.json"
    if args.demo:
        save_path = PROJECT_ROOT / "tests" / "artifacts" / datetime.now().strftime("demo-%Y%m%d-%H%M%S-%f") / "save_data.json"
        print(f"演示存档：{save_path}", flush=True)
    controller = PetApplication(app, save_path=None if args.smoke_test else save_path, accelerated=args.dev_mode)
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
                "growth": controller.model.snapshot(),
            }
            print("PHASE2_SMOKE_OK " + json.dumps(diagnostics, ensure_ascii=False), flush=True)
            app.quit()
        QTimer.singleShot(2000, finish_smoke)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
