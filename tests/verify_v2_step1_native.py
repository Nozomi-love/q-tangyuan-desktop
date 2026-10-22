"""Native V2 step 1 proof: compact HUD, animated drawers and moving environment."""
from datetime import datetime
import json
from pathlib import Path
import sys
import traceback
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea
from dashboard import AdaptiveGrid
from main import PetApplication


def main():
    folder = ROOT / "tests/artifacts" / datetime.now().strftime("v2-step1-native-%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True, exist_ok=False)
    save = folder / "save_data.json"
    save.write_text(json.dumps({"schema_version": 5, "coins": 10000, "affection_level": 6,
        "window": {"pinned": True, "x_ratio": .5, "y_ratio": .5}}), encoding="utf-8")
    app = QApplication(["v2-step1-native"]); app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
    c = PetApplication(app, save_path=save, skins_root=folder / "skins", dev_mode=True)
    p, model, room = c.dashboard, c.model, c.dashboard.room
    result = {"platform": QGuiApplication.platformName(), "dpr": p.devicePixelRatioF(), "errors": []}
    def capture(name):
        app.processEvents(); assert p.grab().save(str(folder / (name + ".png")))
    def reveal(button):
        for tabs in (p.tabs, p.market_tabs, p.shop_tabs, p.dress_tabs):
            for index in range(tabs.count()):
                if tabs.widget(index).isAncestorOf(button):
                    if tabs is p.tabs:
                        p.show_section(("bag", "shop", "achievements", "dress", "settings", "furniture")[index], animate=False)
                    else: tabs.setCurrentIndex(index)
                    break
        node = button.parentWidget()
        while node is not None:
            if isinstance(node, QScrollArea): node.ensureWidgetVisible(button, 7, 7)
            node = node.parentWidget()
        app.processEvents(); assert button.isVisible()
        node = button.parentWidget()
        while node is not None:
            if isinstance(node, QScrollArea):
                pos = button.mapTo(node.viewport(), QPoint()); viewport = node.viewport().rect()
                assert viewport.contains(pos) and viewport.contains(pos + button.rect().bottomRight()), (button.text(), pos, viewport)
            node = node.parentWidget()
    def clicked(button):
        reveal(button); assert button.isEnabled(); QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    def crop_window():
        scale, w, h = room._geometry(); rect = room.window_rect(w, h)
        rect = type(rect)(rect.x() * scale, rect.y() * scale, rect.width() * scale, rect.height() * scale)
        image = room.grab(rect.toRect()).toImage()
        return bytes(image.constBits())
    def body():
        try:
            assert result["platform"] == "windows"
            c.tick_timer.stop(); c.window.timer.stop(); room._animation_timer.stop()
            p.resize(1240, 760); p.show_section("home", animate=False); app.processEvents()
            ratio = room.width() * room.height() / (p.width() * p.height())
            assert .75 <= ratio <= .83, ratio
            result["home_scene_area_ratio"] = ratio
            room.daytime_override = True; room.environment_time = 0; capture("01-home-day")
            widths = []; count = 0
            for width, height in ((820, 650), (1000, 720), (1240, 760)):
                p.resize(width, height)
                for section in ("bag", "shop", "dress", "furniture", "achievements", "settings"):
                    p.show_section(section, animate=False); app.processEvents()
                    assert not p.drawer.isWindow() and room.isVisible() and room.height() >= 420
                    for widget in (room, p.drawer, *p.nav_buttons.values()):
                        pos = widget.mapTo(p.home_scroll.viewport(), QPoint()); viewport = p.home_scroll.viewport().rect()
                        assert viewport.contains(pos) and viewport.contains(pos + widget.rect().bottomRight()), (width, section, widget.objectName())
                    assert p.hud_profile.geometry().right() < p.hud_right.geometry().left(), (width, section, room.size(), p.hud.size(), p.hud_profile.geometry(), p.hud_right.geometry())
                p.show_section("shop", animate=False); p.market_tabs.setCurrentIndex(0); p.shop_tabs.setCurrentIndex(0); app.processEvents()
                grid = p.shop_tabs.widget(0).widget().findChildren(AdaptiveGrid)[0]
                assert grid.columns == (3 if width == 1240 else 2), (width, grid.columns)
                widths.append([width, room.width(), p.drawer.width(), grid.columns])
                for buy, use, _text in p.shop_buttons.values():
                    reveal(buy); reveal(use); count += 2
                for button in p.furniture_shop_buttons.values(): reveal(button); count += 1
            result["viewports"] = widths; result["fully_visible_shop_buttons"] = count
            p.show_section("shop", animate=False); p.market_tabs.setCurrentIndex(0); p.shop_tabs.setCurrentIndex(0)
            p.shop_tabs.widget(0).verticalScrollBar().setValue(0); capture("02-shop-three-columns")
            clicked(p.head_combo.buttons[p.head_combo.findData("crown")])
            p.offset_slider.setValue(-18); assert model.data.accessories["offset_y"] == -18
            assert c.window.renderer.accessories["head"] == "crown"; capture("03-live-crown-offset")
            clicked(p.furniture_shop_buttons["sakura_room"]); clicked(p.furniture_buttons["sakura_room"])
            clicked(p.furniture_shop_buttons["cat_paw_rug"]); clicked(p.furniture_buttons["cat_paw_rug"])
            capture("04-live-decoration")
            p.show_section("home", animate=False); room.environment_time = 0
            cloud1 = crop_window(); room.environment_time = 12; cloud2 = crop_window(); assert cloud1 != cloud2
            clicked(p.environment_buttons["night"]); p.show_section("home", animate=False)
            assert room.daytime_override is False; room.environment_time = 0
            star1 = crop_window(); room.environment_time = 3; star2 = crop_window(); assert star1 != star2
            model.buy_furniture("warm_lamp"); model.equip_furniture("corner", "warm_lamp")
            model.buy_furniture("rice_clock"); model.equip_furniture("wall", "rice_clock")
            model.set_lamp_on(True); capture("05-night-lamp-clock")
            QTest.mouseClick(room, Qt.MouseButton.LeftButton, pos=room.lamp_rect().center().toPoint())
            assert not model.data.lamp_on; capture("06-night-lamp-off")
            p.show_section("shop"); p.drawer_animation.setCurrentTime(90); app.processEvents()
            assert p.drawer.width() > 1 and p.drawer.width() <= p._drawer_target and room.isVisible()
            p.drawer_animation.setCurrentTime(220); app.processEvents()
            p.show_section("home"); p.drawer_animation.setCurrentTime(220); app.processEvents(); assert p.drawer.isHidden()
            result.update(shared_crown_offset_and_decoration=True, animated_clouds_and_stars=True,
                global_night_tone_and_clickable_lamp=True, real_clock=room.clock_angles(), animated_same_window_drawer=True)
        except Exception: result["errors"].append(traceback.format_exc())
        finally: c.quit_action.trigger()
    sys.excepthook = lambda typ, value, tb: (result["errors"].append("".join(traceback.format_exception(typ, value, tb))), c.quit_action.trigger())
    QTimer.singleShot(200, body)
    QTimer.singleShot(45000, lambda: (result["errors"].append("watchdog timeout"), c.quit_action.trigger()))
    code = app.exec(); result["passed"] = not result["errors"] and c._stopped and code == 0
    result["directory"] = str(folder)
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
