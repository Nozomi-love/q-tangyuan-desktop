"""Native illustrated-shop viewport, visual wear, GIF tricks and restart proof."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(mode, file):
    from PySide6.QtCore import QPoint, Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLabel, QPushButton, QScrollArea
    from main import PetApplication
    from illustrated_assets import _EMOJI, ICON_IDS
    from verify_phase4_native import make_gif
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(["illustrated-native"]); app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
    c = PetApplication(app, save_path=file, skins_root=file.parent / "skins", dev_mode=True)
    panel, model, pet = c.dashboard, c.model, c.window
    errors = []; result = dict(mode=mode, platform=QGuiApplication.platformName(), dpr=panel.devicePixelRatioF())
    sys.excepthook = lambda typ, value, tb: (errors.append("".join(traceback.format_exception(typ, value, tb))), app.exit(1))

    def capture(name, widget=None):
        QTest.qWait(50)
        assert (widget or panel).grab().save(str(file.parent / (name + ".png")))

    def reveal(button):
        for tabs in (panel.tabs, panel.market_tabs, panel.shop_tabs, panel.dress_tabs):
            for index in range(tabs.count()):
                if tabs.widget(index).isAncestorOf(button):
                    if tabs is panel.tabs:
                        panel.show_section(("bag", "shop", "achievements", "dress", "settings", "furniture")[index], animate=False)
                    else: tabs.setCurrentIndex(index)
                    break
        node = button
        while node.parentWidget() is not None:
            node = node.parentWidget()
            if isinstance(node, QScrollArea): node.ensureWidgetVisible(button, 8, 12)
        QTest.qWait(15)
        assert button.isVisible()
        node = button.parentWidget()
        while node is not None:
            if isinstance(node, QScrollArea):
                area = node.viewport()
                origin = button.mapTo(area, QPoint())
                assert area.rect().contains(origin), (button.text(), "top", origin, area.rect())
                assert area.rect().contains(origin + button.rect().bottomRight()), (button.text(), "bottom", origin, area.rect())
            node = node.parentWidget()

    def click(button):
        reveal(button); assert button.isEnabled(), button.text()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    def no_emoji():
        for widget in panel.findChildren(QLabel) + panel.findChildren(QPushButton):
            assert not _EMOJI.search(widget.text()), widget.text()
        for action in c.menu.actions(): assert not _EMOJI.search(action.text()), action.text()

    def begin():
        try:
            assert result["platform"] == "windows"
            c.tick_timer.stop()
            assert panel.current_section == "home" and panel.drawer.isHidden()
            assert panel.room.height() >= 420 and panel.room.pet_bounds().width() > 150
            assert not panel.findChildren(QComboBox) and not panel.findChildren(QCheckBox)
            no_emoji()
            if mode == "read":
                expected = json.loads((file.parent / "expected.json").read_text(encoding="utf-8"))
                for key in ("name", "coins", "hunger", "affection_level", "affection_exp", "inventory", "accessories",
                            "selected_skin_id", "owned_furniture", "equipped_furniture", "lamp_on", "overlay_visible"):
                    assert model.snapshot()[key] == expected[key], key
                assert pet.renderer.movies and model.effective_accessories()["head"] == "crown"
                QTest.qWait(250); capture("09-restart-room")
                result["independent_restart_of_existing_save_and_gif"] = True
                return
            panel.room.daytime_override = True; capture("01-game-room-day")
            original_height = panel.room.height()
            panel.show_section("shop", animate=False)
            count = 0
            for width in (1000, 1280):
                panel.resize(width, 820); QTest.qWait(35)
                for _key, (buy, feed, _label) in panel.shop_buttons.items():
                    reveal(buy); reveal(feed); count += 1
                for button in panel.furniture_shop_buttons.values(): reveal(button); count += 1
                for buy, perform, _label in panel.shop_trick_buttons.values(): reveal(buy); reveal(perform); count += 1
                assert panel.room.height() >= 420 and panel.room.isVisible() and not panel.drawer.isWindow()
            result["all_shop_buttons_inside_same_window_drawer_at_1000_1280"] = count
            panel.show_section("shop", animate=False); panel.market_tabs.setCurrentIndex(0); panel.shop_tabs.setCurrentIndex(0)
            panel.shop_tabs.currentWidget().verticalScrollBar().setValue(0)
            capture("02-illustrated-food-shop", panel.drawer)
            coins = model.data.coins; click(panel.shop_buttons["water"][0])
            assert model.data.inventory["water"] == 1 and model.data.coins == coins - 10
            click(panel.shop_buttons["paper_star"][1]); assert model.data.affection_exp == 20
            click(panel.furniture_shop_buttons["cat_paw_rug"]); click(panel.furniture_buttons["cat_paw_rug"])
            assert model.data.equipped_furniture["rug"] == "cat_paw_rug"
            assert panel.furniture_buttons["cat_paw_rug"].badge == "已布置"
            capture("03-illustrated-decoration", panel.drawer)
            click(panel.head_combo.buttons[panel.head_combo.findData("crown")])
            assert model.effective_accessories()["head"] == "crown"
            assert panel.head_combo.buttons[2].badge == "已穿戴"
            capture("04-illustrated-accessories", panel.drawer)
            panel.show_section("home", animate=False); model.set_hunger(0)
            exp, coins = model.data.affection_exp, model.data.coins
            QTest.mouseClick(panel.feeding_buttons["water"], Qt.MouseButton.LeftButton)
            assert model.data.hunger == 15 and model.data.affection_exp == exp and model.data.coins == coins
            assert panel.room._food_id == "water"; QTest.qWait(270); capture("05-food-icon-flight")
            model.set_hunger(80)
            gif = file.parent / "native-friend.gif"; gif.write_bytes(make_gif())
            panel.show_section("dress", animate=False); panel.dress_tabs.setCurrentIndex(0)
            with patch("dashboard.QFileDialog.getOpenFileName", return_value=(str(gif), "")):
                click(panel.import_buttons["image"])
            assert pet.renderer.movies and model.data.selected_skin_id.startswith("user_")
            frames = []
            for movie in pet.renderer.movies.values(): movie.frameChanged.connect(frames.append)
            QTest.qWait(350); assert len(set(frames)) >= 2
            model.buy_item("sesame", True)
            QTest.qWait(150)
            click(panel.trick_buttons["flip"]); panel.show_section("home", animate=False)
            QTest.qWait(300); assert pet.engine.active_trick == "flip"; capture("06-gif-crown-flip")
            QTest.qWait(950)
            panel.show_section("achievements", animate=False); capture("07-illustrated-achievements", panel.drawer)
            for section in ("home", "bag", "shop", "dress", "achievements"):
                QTest.mouseClick(panel.nav_buttons[section], Qt.MouseButton.LeftButton); QTest.qWait(35)
                assert panel.current_section == section and panel.room.height() >= 420
            panel.hide(); panel.summon(); assert panel.current_section == "home" and panel.drawer.isHidden()
            no_emoji(); panel.room.daytime_override = False; capture("08-game-room-night")
            result.update(no_emoji_text=True, no_form_selectors=True, real_pixmap_icons=len(ICON_IDS),
                          food_gift_purchase_and_visual_equipping=True, food_flight_one_consumption=True,
                          animated_gif_crown_buff_flip=True, home_keeps_large_room=True)
            c._save(); (file.parent / "expected.json").write_text(json.dumps(model.snapshot(), ensure_ascii=False), encoding="utf-8")
        except Exception: errors.append(traceback.format_exc())
        finally: c.quit_action.trigger()

    QTimer.singleShot(200, begin)
    QTimer.singleShot(35000, lambda: (errors.append("native watchdog timeout"), c.quit_action.trigger()))
    code = app.exec(); result["errors"] = errors
    result["clean_shutdown"] = c._stopped and not panel.room._animation_timer.isActive()
    (file.parent / (mode + "-result.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return int(bool(errors) or not result["clean_shutdown"]) or code


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--worker", choices=("write", "read")); parser.add_argument("--save-file", type=Path)
    args = parser.parse_args()
    if args.worker: return worker(args.worker, args.save_file)
    folder = ROOT / "tests/artifacts" / datetime.now().strftime("illustrated-native-%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True, exist_ok=False); file = folder / "save_data.json"
    file.write_text(json.dumps({"schema_version": 5, "coins": 5000, "affection_level": 6,
                               "window": {"pinned": True, "x_ratio": .5, "y_ratio": .55}}), encoding="utf-8")
    runs = []
    for mode in ("write", "read"):
        child = subprocess.run([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--worker", mode, "--save-file", str(file)],
                               cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=45,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        runs.append(dict(mode=mode, code=child.returncode, stdout=child.stdout, stderr=child.stderr))
        if child.returncode: break
    report = dict(passed=len(runs) == 2 and all(x["code"] == 0 for x in runs), directory=str(folder), runs=runs)
    (folder / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("ILLUSTRATED_NATIVE " + json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
