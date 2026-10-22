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

from dashboard import DashboardWindow
from illustrated_assets import IconAtlas, plain_text
from models import GameRules, PetData, PetModel
from pet_engine import PetEngine, SkinRenderer, WorkArea
from pet_window import PetWindow, ProceduralAudio
from save_manager import SaveDataError, SaveManager, SkinManager, SkinImportError
from release_support import APP_VERSION, BackupManager, SingleInstance, player_paths

PROJECT_ROOT = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parent)
WINDOWS_APP_ID = "Nozomi.QTangyuan.Desktop"


def configure_windows_identity() -> bool:
    """Give the Python-hosted window its own taskbar group before creating Qt."""
    if sys.platform != "win32":
        return False
    import ctypes
    try:
        set_id = ctypes.WinDLL("shell32", use_last_error=True).SetCurrentProcessExplicitAppUserModelID
        set_id.argtypes = [ctypes.c_wchar_p]
        set_id.restype = ctypes.c_long
        result = set_id(WINDOWS_APP_ID)
        if result < 0:
            raise OSError(f"SetCurrentProcessExplicitAppUserModelID: {result:#x}")
        return True
    except (OSError, AttributeError) as error:
        logging.warning("Windows任务栏身份设置失败，仍可继续运行：%s", error)
        return False



def create_tray_icon(renderer: SkinRenderer | None = None) -> QIcon:
    # Stable product identity: shortcut, window, taskbar and tray share the ICO.
    icon_path = PROJECT_ROOT / "assets" / "icons" / "tangyuan.ico"
    if icon_path.is_file():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            return icon
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
                 accelerated: bool = False, skins_root: Path | None = None,
                 dev_mode: bool | None = None) -> None:
        self.app = app
        self.dev_mode = accelerated if dev_mode is None else dev_mode
        self.skin_manager = SkinManager(skins_root or PROJECT_ROOT / "assets" / "skins")
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
        self.audio = ProceduralAudio(PROJECT_ROOT / "assets" / "sounds", data.muted, self.window)
        self._skin_restore_warning = ""
        if data.selected_skin_id != "default":
            restored = self.skin_manager.resolve(data.selected_skin_id)
            if restored.name != data.selected_skin_id or not self.window.set_skin(restored):
                self._skin_restore_warning = "原自定义皮肤暂时无法读取，先用白汤圆陪伴你；原选择和素材保留。"
        self.window.engine.skin_scale=self.model.skin_config()["scale_multiplier"]
        self.window.set_accessories(self.model.effective_accessories())
        self.icon = create_tray_icon(self.window.renderer)
        app.setWindowIcon(self.icon)
        self.window.setWindowIcon(self.icon)
        self.ui_icons = IconAtlas()
        self._build_menu()
        self.dashboard = DashboardWindow(self.model, self.window.engine, lambda: self.window.renderer)
        self.dashboard.setWindowIcon(self.icon)
        self.dashboard.set_phase4_context(self.skin_manager.list_skins(), self.dev_mode)
        self._connect_dashboard()
        self._preview_id=None
        self.dashboard.data_directory_label.setText("数据目录："+str(save_path.parent) + "\n本地皮肤："+str(self.skin_manager.root) if save_path else "本次仅内存体验，不写入玩家进度。")
        self.window.dialogue_shown.connect(self.dashboard.room.show_message)
        self.dashboard.room.sound_requested.connect(self.audio.play)
        self.model.gains_received.connect(self._gains_received)
        self.model.interaction_started.connect(self._interaction_started)
        self.window.drag_started.connect(self.dashboard.room.interact)

        self.model.state_changed.connect(self._state_changed)
        self.model.starvation_changed.connect(self.window.set_starving)
        self.model.feedback.connect(self._feedback)
        self.model.upgraded.connect(self._upgraded)
        self.model.collectible_changed.connect(self._collectible_changed)
        self.model.fed.connect(self._fed)
        self.model.gifted.connect(self.window.engine.rebound)
        self.model.presentation_requested.connect(
            lambda event: self.window.engine.enjoy_interaction(event.get("duration", 2.5)))
        self.model.buff_changed.connect(self.window.set_buff)
        self.model.achievement_unlocked.connect(self._achievement_unlocked)
        self.model.dizzy_requested.connect(self._dizzy)
        self.model.appearance_changed.connect(self.window.set_accessories)
        self.model.perks_unlocked.connect(self._perks_unlocked)
        self.window.trick_finished.connect(self.model.finish_trick)
        self.window.trick_finished.connect(self.dashboard.room.finish_trick)
        self.window.clicked.connect(self.model.poke)
        self.window.dashboard_requested.connect(self.dashboard.summon)
        self.window.drag_started.connect(lambda: self.window.show_message(self.model.dialogue("drag"), "interaction"))
        self.window.drag_landed.connect(self.model.record_drop)
        self.window.shaken.connect(self.model.record_shake)
        interactions = self.model.catalog.interactions
        self.window.shake_min_speed = interactions["shake_min_speed"]
        self.window.shake_distance = interactions["shake_distance"]
        self.window.shake_reversals = interactions["shake_reversals"]
        self.window.collectible_clicked.connect(self.model.claim_collectible)
        self.window.pinned_changed.connect(self.pin_action.setChecked)
        self.window.position_changed.connect(self._save_position)
        self.window.context_menu_requested.connect(self.menu.popup)
        self.window.close_requested.connect(app.quit)

        self.tray = QSystemTrayIcon(self.icon, app)
        self.tray.setToolTip("Q弹汤圆 · 双击回小窝，右键快捷互动")
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        else:
            logging.warning("系统托盘当前不可用；右键汤圆仍可使用全部菜单。")

        self.window.restore_position(position)
        self.window.set_starving(self.model.starving)
        self.window.set_buff(self.model.buff_view())
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
        self._sync_settings()
        app.aboutToQuit.connect(self.stop)
        self.window.set_overlay_visible(self.model.data.overlay_visible)
        self.overlay_action.setChecked(self.model.data.overlay_visible)
        self.dashboard.summon()
        self._save()
        for achievement in self.model.initial_achievements:
            self._achievement_unlocked(achievement)
        if self._save_blocked:
            self.window.show_message("存档读取失败，原文件已保留；本次进度不写入。", "hungry")
        elif self._skin_restore_warning:
            self.window.show_message(self._skin_restore_warning, "special")
        elif accelerated:
            self.window.show_message(f" 加速：饥饿 {self.model.rules.hunger_seconds:g} 秒 -1，礼包 {self.model.rules.gift_seconds:g} 秒自动入账", "normal")

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
        self.pin_action = self.menu.addAction(" 固定当前位置（可拖动调整）")
        self.pin_action.setCheckable(True)
        self.dashboard_action = self.menu.addAction(" 打开汤圆小窝")
        self.overlay_action = self.menu.addAction(" 显示桌面悬浮窗")
        self.mute_action = self.menu.addAction("静音")
        self.mute_action.setCheckable(True); self.mute_action.toggled.connect(self.model.set_muted)
        self.mute_action.setIcon(self.ui_icons.icon("music_box"))
        self.overlay_action.setCheckable(True)
        self.overlay_action.toggled.connect(self.model.set_overlay_visible)
        self.trick_menu = self.menu.addMenu(" 表演特技")
        self.trick_actions = {}
        for trick_id in self.model.trick_cooldowns:
            action = self.trick_menu.addAction(self.model.trick_name(trick_id))
            action.triggered.connect(lambda checked=False, tid=trick_id: self._perform_trick(tid))
            self.trick_actions[trick_id] = action
        self.menu.addSeparator()
        self.debug_menu = self.menu.addMenu(" 调试与外观")
        self.debug_menu.menuAction().setVisible(self.dev_mode)
        self.hunger_zero_action = self.debug_menu.addAction("[调试] 饥饿值归零")
        self.hunger_full_action = self.debug_menu.addAction("[调试] 饥饿值恢复满值")
        self.flat_action = self.debug_menu.addAction("手动测试饿扁（独立于真实饥饿）")
        self.flat_action.setCheckable(True)
        self.dev_action = self.debug_menu.addAction("开发测试加速模式")
        self.dev_action.setCheckable(True)
        self.gift_action = self.debug_menu.addAction("[调试] 立即结算在线糯米币")
        self.reset_action = self.menu.addAction("重置回主屏幕右下角")
        self.reload_action = self.debug_menu.addAction("重新加载当前皮肤")
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction(" 退出程序")
        self.feed_action.triggered.connect(self.model.feed_sugar)
        self.pet_action.triggered.connect(self._pet_head)
        self.pin_action.toggled.connect(self.window.set_pinned)
        self.flat_action.toggled.connect(self.window.set_test_flat)
        self.dev_action.toggled.connect(self._set_accelerated)
        self.gift_action.triggered.connect(self.model.offer_collectible)
        self.hunger_zero_action.triggered.connect(lambda: self.model.set_hunger(0))
        self.hunger_full_action.triggered.connect(lambda: self.model.set_hunger(100))
        self.dashboard_action.triggered.connect(lambda: self.dashboard.summon())
        self.reset_action.triggered.connect(self.window.reset_to_primary)
        self.reload_action.triggered.connect(self._reload_skins)
        self.quit_action.triggered.connect(self.app.quit)
        for action, icon_id in ((self.feed_action, "sugar"), (self.pet_action, "sprout"),
            (self.pin_action, "desktop"), (self.dashboard_action, "home"), (self.overlay_action, "desktop"),
            (self.reset_action, "home"), (self.reload_action, "dress"), (self.quit_action, "remove"),
            (self.level_info, "avatar"), (self.hunger_info, "water"), (self.coins_info, "coin")):
            action.setIcon(self.ui_icons.icon(icon_id))
        for key, action in self.trick_actions.items():
            action.setIcon(self.ui_icons.icon(key))
        self.menu.aboutToShow.connect(self._refresh_menu)

    def _connect_dashboard(self) -> None:
        self.dashboard.rename_requested.connect(self.model.rename_pet)
        self.dashboard.overlay_requested.connect(self.model.set_overlay_visible)
        self.dashboard.mute_requested.connect(self.model.set_muted)
        self.dashboard.furniture_requested.connect(self.model.equip_furniture)
        self.dashboard.poke_requested.connect(self._room_poke)
        self.dashboard.pet_requested.connect(self._pet_head)
        self.dashboard.pin_requested.connect(self.pin_action.setChecked)
        self.dashboard.dev_requested.connect(self.dev_action.setChecked)
        self.dashboard.flat_requested.connect(self.flat_action.setChecked)
        self.dashboard.reset_requested.connect(self.window.reset_to_primary)
        self.dashboard.hunger_zero_requested.connect(lambda: self.model.set_hunger(0))
        self.dashboard.hunger_full_requested.connect(lambda: self.model.set_hunger(100))
        self.dashboard.gift_requested.connect(self.model.offer_collectible)
        self.dashboard.reload_requested.connect(self._reload_skins)
        self.dashboard.accessory_requested.connect(self.model.equip_accessory)
        self.dashboard.offset_requested.connect(self.model.set_accessory_offset)
        self.dashboard.scale_requested.connect(self.model.set_skin_scale)
        self.dashboard.preview_confirmed.connect(self._confirm_preview)
        self.dashboard.preview_cancelled.connect(self._cancel_preview)
        self.dashboard.skin_rename_requested.connect(self._rename_skin)
        self.dashboard.skin_archive_requested.connect(self._archive_skin)
        self.dashboard.backup_requested.connect(self._export_backup)
        self.dashboard.restore_requested.connect(self._restore_backup)
        self.dashboard.dev_level_requested.connect(self._dev_level)
        self.dashboard.trick_requested.connect(self._perform_trick)
        self.dashboard.skin_requested.connect(self._select_skin)
        self.dashboard.import_image_requested.connect(self._import_image)
        self.dashboard.import_pack_requested.connect(self._import_pack)
        self.dashboard.export_template_requested.connect(self._export_template)
        self.dashboard.import_unlock_requested.connect(self.model.unlock_custom_import)
        self.dashboard.debug_unlock_requested.connect(
            lambda enabled: self.model.set_debug_unlock(enabled, authorized=self.dev_mode))
        for action in (self.pin_action, self.dev_action, self.flat_action):
            action.toggled.connect(self._sync_settings)

    def _sync_settings(self, _enabled: bool = False) -> None:
        self.dashboard.set_settings(self.window.engine.pinned, self.dev_action.isChecked(), self.flat_action.isChecked())

    def _achievement_unlocked(self, achievement: dict) -> None:
        self.audio.play("coin")
        self.window.show_message(f" 解锁成就：《{achievement['name']}》！可前往主面板领奖", "achievement")
        if hasattr(self, "save_timer"):
            self.save_timer.start()

    def _dizzy(self) -> None:
        self.window.engine.get_dizzy()
        self.window.show_message(self.model.dialogue("dizzy"), "interaction")

    def _refresh_menu(self) -> None:
        data, rules = self.model.data, self.model.rules
        self.mute_action.blockSignals(True); self.mute_action.setChecked(data.muted); self.mute_action.blockSignals(False)
        exp = "MAX" if data.affection_level == 30 else f"{data.affection_exp}/{self.model.exp_required}"
        self.level_info.setText(f" 等级: Lv.{data.affection_level} (EXP: {exp})")
        self.hunger_info.setText(f" 饱食度: {data.hunger:g}/100" + (" · 饿扁啦" if self.model.starving else ""))
        self.coins_info.setText(f" 糯米币: {data.coins}")
        self.feed_action.setText(f" 快捷投喂白砂糖 (-{rules.sugar_cost}币, 饱食度+{rules.sugar_hunger:g})")
        self.feed_action.setEnabled(data.coins >= rules.sugar_cost)
        remaining = math.ceil(data.timers["pet_cooldown_remaining"])
        self.pet_action.setText(" 摸摸头 (好感+3)" + (f" · 冷却 {remaining} 秒" if remaining else ""))
        self.pet_action.setEnabled(remaining == 0)
        self.gift_action.setEnabled(not self.model.has_collectible)
        for trick_id, action in self.trick_actions.items():
            remaining = math.ceil(self.model.trick_cooldowns[trick_id])
            if not self.model.has_trick(trick_id):
                product = self.model.catalog.trick_products.get(trick_id)
                suffix = f" · 商城{product['cost']}币解锁" if product else " · Lv.{} 解锁".format(self.model.catalog.perks["trick_" + trick_id]["level"])
            else:
                suffix = f" · {remaining}s" if remaining else ""
            action.setText(self.model.trick_name(trick_id) + suffix)
            action.setEnabled(self.model.can_perform_trick(trick_id))

    def _state_changed(self, _state: dict) -> None:
        self._dirty = True
        scale=self.model.skin_config()["scale_multiplier"]
        if scale != self.window.engine.skin_scale:
            self.window.engine.cancel_trick()
            self.window.engine.skin_scale=scale
        self.window.set_accessories(self.model.effective_accessories())
        self.audio.set_muted(self.model.data.muted)
        self.mute_action.blockSignals(True); self.mute_action.setChecked(self.model.data.muted); self.mute_action.blockSignals(False)
        enabled = self.model.data.overlay_visible
        if self.window._overlay_enabled != enabled:
            self.window.set_overlay_visible(enabled)
        self.overlay_action.blockSignals(True)
        self.overlay_action.setChecked(enabled)
        self.overlay_action.setText(" 隐藏桌面悬浮窗" if enabled else " 显示桌面悬浮窗")
        self.overlay_action.blockSignals(False)
        self.dashboard.room.set_home_state(self.model.snapshot())
        self._refresh_menu()
        if hasattr(self, "save_timer"):
            self.save_timer.start()

    def _gains_received(self, gains: dict) -> None:
        self.window.show_gains(gains)
        if gains.get("coins", 0) > 0: self.audio.play("coin")

    def _interaction_started(self, kind: str) -> None:
        if kind == "poke": self.audio.play("poke")
        elif kind == "food" and not self.dashboard.room.isVisible(): self.audio.play("eat")

    def _room_poke(self) -> None:
        self.window.engine.click()
        self.model.poke()

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
        if level == 30: self.window.engine.fireworks_until=self.window.engine.elapsed+5
        self.window.show_message(f" 好感度升至 Lv.{level}！奖励 30 糯米币", "level")

    def _fed(self) -> None:
        # Feeding also ends the cosmetic test, while true starvation is model-owned.
        self.flat_action.setChecked(False)
        self.window.engine.rebound()

    def _pet_head(self) -> None:
        if self.model.pet_head():
            self.window.engine.rebound()

    def _set_accelerated(self, enabled: bool) -> None:
        self.model.set_rules(self._load_rules(enabled))
        self.dashboard.refresh()
        self._dirty = True
        self._refresh_menu()
        rules = self.model.rules
        self.window.show_message(f"{' 加速已开启' if enabled else '正常计时'}：{rules.hunger_seconds:g} 秒掉饥饿 / {rules.gift_seconds:g} 秒自动入账")

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
        self.dashboard.reload_artwork()
        self._reload_icon()

    def _perks_unlocked(self, names: list) -> None:
        self.window.set_accessories(self.model.effective_accessories())
        self.window.show_message(" 新特权解锁：" + "、".join(names), "achievement")

    def _perform_trick(self, trick_id: str) -> bool:
        if not self.model.can_perform_trick(trick_id):
            self.model.feedback.emit("特技还在休息，或尚未解锁哦～", "normal")
            return False
        if not self.window.perform_trick(trick_id):
            self.model.feedback.emit("先让汤圆站稳、吃饱，再来表演吧～", "normal")
            return False
        self.dashboard.room.begin_trick(trick_id)
        return self.model.record_trick(trick_id)

    def _refresh_wardrobe(self) -> None:
        self.dashboard.set_phase4_context(self.skin_manager.list_skins(), self.dev_mode)
        self.dashboard.refresh()

    def _select_skin(self, skin_id: str, imported: bool = False) -> bool:
        if skin_id != "default" and not self.model.has_perk("custom_import"):
            self.model.feedback.emit("衣橱将在 Lv.3 开启，也可花 50 币提前解锁。", "normal")
            self._refresh_wardrobe()
            return False
        directory = PROJECT_ROOT / "assets/skins/default" if skin_id=="default" else self.skin_manager.resolve(skin_id)
        if directory.name != skin_id or not self.window.set_skin(directory):
            self.model.feedback.emit("皮肤素材缺失或无效，当前外观已保留。", "hungry")
            self._refresh_wardrobe()
            return False
        self.model.select_skin(skin_id, imported=imported)
        self.window.set_accessories(self.model.effective_accessories())
        self._reload_icon()
        self._refresh_wardrobe()
        return True

    def _import_image(self, source: str, remove_white: bool) -> None:
        self._prepare_preview(source, remove_white=remove_white)

    def _import_pack(self, source: str) -> None:
        self._prepare_preview(source, pack=True)

    def _import_skin(self, source: str, *, pack: bool = False, remove_white: bool = False) -> None:
        if not self.model.has_perk("custom_import"):
            self.model.feedback.emit("请先解锁衣橱，再导入本地素材。", "normal")
            return
        try:
            skin = (self.skin_manager.import_pack(Path(source)) if pack else
                    self.skin_manager.import_image(Path(source), remove_white=remove_white))
            if not self._select_skin(skin["id"], imported=True):
                self._refresh_wardrobe()
        except (SkinImportError, OSError, ValueError) as error:
            logging.warning("皮肤导入被拒绝：%s", error)
            self.model.feedback.emit("导入未完成：" + str(error), "hungry")

    def _prepare_preview(self, source, *, pack=False, remove_white=False):
        if not self.model.has_perk("custom_import"): return
        try:
            entry=self.skin_manager.prepare_preview(Path(source),pack=pack,remove_white=remove_white)
            self._cancel_preview()
            self._preview_id=entry["id"]
            self.dashboard.show_skin_preview(entry)
        except (SkinImportError,OSError,ValueError) as error:
            self.model.feedback.emit("预览未完成："+str(error),"hungry")

    def _confirm_preview(self):
        if not self._preview_id or not self.model.has_perk("custom_import"): return
        try:
            entry=self.skin_manager.commit_preview(self._preview_id)
            self._preview_id=None
            self.dashboard.clear_skin_preview()
            self._select_skin(entry["id"],imported=True)
        except (SkinImportError,OSError,ValueError) as error:
            self.model.feedback.emit("导入未完成："+str(error),"hungry")

    def _cancel_preview(self):
        if getattr(self,"_preview_id",None): self.skin_manager.cancel_preview(self._preview_id)
        self._preview_id=None
        self.dashboard.clear_skin_preview()

    def _rename_skin(self, skin_id, name):
        try:
            self.skin_manager.rename(skin_id,name)
            self._refresh_wardrobe()
        except (SkinImportError,OSError,ValueError) as error:
            self.model.feedback.emit("重命名未完成："+str(error),"hungry")

    def _archive_skin(self, skin_id, archived):
        if skin_id==self.model.data.selected_skin_id and archived:
            if not self._select_skin("default"): return
        if self.model.archive_skin(skin_id,archived): self._refresh_wardrobe()

    def _export_backup(self, destination):
        try:
            if not self.save_manager or self._save_blocked: raise SaveDataError("当前没有可写入的存档")
            self._save()
            if self._dirty: raise SaveDataError("最新进度尚未保存，请先处理存档写入问题")
            result=BackupManager(self.save_manager,self.skin_manager).export(Path(destination))
            self.dashboard.backup_status.setText("备份完成："+str(result))
        except (SaveDataError,SkinImportError,OSError,ValueError) as error:
            self.dashboard.backup_status.setText("备份未完成："+str(error))

    def _restore_backup(self, source):
        try:
            if not self.save_manager or self._save_blocked: raise SaveDataError("当前无法安全恢复存档")
            self._save()
            if self._dirty: raise SaveDataError("当前进度尚未安全保存，恢复已停止")
            data,position,rollback=BackupManager(self.save_manager,self.skin_manager).restore(Path(source))
            self._cancel_preview()
            self.window.engine.cancel_trick()
            self.window.engine.fireworks_until=0
            self.flat_action.setChecked(False)
            self.window.restore_position(position)
            self.model.replace_data(data)
            self.window.set_starving(self.model.starving)
            self._select_skin(data.selected_skin_id)
            self.dashboard.room.interact(cancel_gift=True)
            self.dashboard.refresh(); self._save()
            self.dashboard.backup_status.setText("恢复完成；恢复前备份："+str(rollback))
        except (SaveDataError,SkinImportError,OSError,ValueError) as error:
            self.dashboard.backup_status.setText("恢复未完成，原进度与素材保留："+str(error))

    def _dev_level(self, level):
        if not self.dev_mode or type(level) is not int or not 1<=level<=30: return
        if level < self.model.data.affection_level: return
        previous=self.model.starving
        amount=500*level*(level-1)//2-self.model._lifetime_exp()
        levels=self.model._add_exp(max(0,amount))
        self.model._publish(previous,[levels[-1]] if levels else [])

    def wake(self):
        self.model.set_overlay_visible(True)
        self.dashboard.summon()
        self.window.set_overlay_visible(True)
        self.window.raise_()

    def _export_template(self, destination: str) -> None:
        target = Path(destination) / datetime.now().strftime("汤圆皮肤模板-%Y%m%d-%H%M%S-%f")
        try:
            result = self.skin_manager.export_template(target)
            self.model.feedback.emit(" 皮肤包模板已生成：" + str(result), "normal")
        except (SkinImportError, OSError, ValueError) as error:
            self.model.feedback.emit("模板导出未完成：" + str(error), "hungry")

    def _reload_icon(self) -> None:
        self.icon = create_tray_icon(self.window.renderer)
        self.app.setWindowIcon(self.icon)
        self.window.setWindowIcon(self.icon)
        self.dashboard.setWindowIcon(self.icon)
        self.tray.setIcon(self.icon)

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.dashboard.summon()

    def stop(self) -> None:
        if self._stopped:
            return
        self._save()
        self._stopped = True
        for timer in (self.tick_timer, self.autosave_timer, self.save_timer):
            timer.stop()
        self.audio.stop()
        self.window.stop()
        self.menu.hide()
        self.tray.hide()
        self.window.hide()
        self.dashboard.stop()
        self.dashboard.hide()


def main() -> int:
    parser = argparse.ArgumentParser(description=APP_VERSION)
    parser.add_argument("--version", action="version", version=APP_VERSION)
    parser.add_argument("--smoke-test", action="store_true",
                        help="启动真实窗口与托盘，2 秒后输出诊断并自动退出")
    parser.add_argument("--dev-mode", action="store_true", help="开启养成计时加速：饥饿 2 秒、拾币 10 秒")
    parser.add_argument("--demo", action="store_true", help="创建独立演示存档，不影响正式玩家数据")
    parser.add_argument("--resume-demo", type=Path, help="继续已有演示存档（仅允许 tests/artifacts 内的 save_data.json）")
    parser.add_argument("--smoke-report", type=Path, help="仅配合--smoke-test，将诊断写入一个新的JSON文件")
    args = parser.parse_args()
    if args.smoke_report is not None and not args.smoke_test:
        parser.error("--smoke-report 仅可配合 --smoke-test 使用")
    if args.resume_demo is not None:
        args.resume_demo = args.resume_demo.resolve()
        if args.demo or not args.resume_demo.is_relative_to((PROJECT_ROOT / "tests" / "artifacts").resolve()) or args.resume_demo.name != "save_data.json" or not args.resume_demo.is_file():
            parser.error("--resume-demo 需要 tests/artifacts 内已有的独立演示存档，且不能与 --demo 同时使用")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    windows_identity_configured = configure_windows_identity()
    # Qt 6 already enables high DPI. Never multiply globalPosition or screen
    # geometry by devicePixelRatio; only painting uses the backing-store DPR.
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication([sys.argv[0]])
    app.setApplicationName("Q弹汤圆")
    app.setOrganizationName("Q弹汤圆")
    app.setApplicationVersion("2.0.0")
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
    elif args.resume_demo is not None:
        save_path = args.resume_demo
        print(f"继续演示存档：{save_path}", flush=True)
    skins_root=None
    legacy=None
    if getattr(sys,"frozen",False) and not (args.demo or args.resume_demo or args.smoke_test):
        stable_save,skins_root=player_paths(PROJECT_ROOT,frozen=True)
        legacy=save_path if save_path.is_file() and not stable_save.exists() else None
        save_path=stable_save
    instance=None
    if not args.smoke_test:
        instance=SingleInstance(save_path,app)
        try:
            if not instance.acquire(): return 0
        except RuntimeError as error:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(None,"Q弹汤圆",str(error)); return 1
    if legacy:
        try:
            old=SaveManager(legacy); old.load_all()
            imported=SkinManager(PROJECT_ROOT/"assets/skins")
            target=save_path.parent/"backups"/("首次升级迁移-"+datetime.now().strftime("%Y%m%d-%H%M%S-%f")+".zip")
            BackupManager(old,imported).export(target)
            BackupManager(SaveManager(save_path),SkinManager(skins_root)).restore(target)
        except (SaveDataError,SkinImportError,OSError,ValueError) as error:
            logging.error("旧版数据迁移未完成，原件保留：%s",error)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(None,"数据迁移未完成",str(error)); return 1
    controller = PetApplication(app, save_path=None if args.smoke_test else save_path, accelerated=args.dev_mode, dev_mode=args.dev_mode,skins_root=skins_root)
    if instance:
        instance.awakened.connect(controller.wake)
        app.aboutToQuit.connect(instance.close)
    if args.smoke_test:
        def finish_smoke() -> None:
            window = controller.window
            area = window.engine.area
            diagnostics = {
                "version": APP_VERSION,
                "debug_menu_visible": controller.debug_menu.menuAction().isVisible(),
                "data_directory": str(save_path.parent),
                "platform": QGuiApplication.platformName(),
                "frozen": bool(getattr(sys, "frozen", False)),
                "resource_root": str(PROJECT_ROOT),
                "windows_identity_configured": windows_identity_configured,
                "windows_app_id": WINDOWS_APP_ID if windows_identity_configured else "",
                "application_icon": str(PROJECT_ROOT / "assets" / "icons" / "tangyuan.ico"),
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
                "dashboard_tabs": controller.dashboard.tabs.count(),
                "home_visible": controller.dashboard.isVisible(),
                "overlay_enabled": controller.model.data.overlay_visible,
                "home_scene": controller.dashboard.room.isVisible(),
            }
            if args.smoke_report is not None:
                report = args.smoke_report.resolve()
                report.parent.mkdir(parents=True, exist_ok=True)
                with report.open("x", encoding="utf-8") as output:
                    json.dump(diagnostics, output, ensure_ascii=False, indent=2)
                    output.write("\n")
            print("PHASE4_SMOKE_OK " + json.dumps(diagnostics, ensure_ascii=False), flush=True)
            app.quit()
        QTimer.singleShot(2000, finish_smoke)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
