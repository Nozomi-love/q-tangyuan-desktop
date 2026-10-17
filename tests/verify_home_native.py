"""Windows native Home Scene, furniture, GIF crown and independent restart."""
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
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QScrollArea, QSystemTrayIcon
    from main import PetApplication
    from pet_engine import PetState
    from verify_phase4_native import make_gif

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(["home-native"])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
    controller = PetApplication(app, save_path=file, skins_root=file.parent / "skins")
    pet, model, panel = controller.window, controller.model, controller.dashboard
    errors = []
    result = dict(mode=mode, platform=QGuiApplication.platformName(), dpr=panel.devicePixelRatioF())
    sys.excepthook = lambda typ, value, tb: (errors.append("".join(traceback.format_exception(typ, value, tb))), app.exit(1))

    def capture(name):
        QTest.qWait(70)
        assert panel.grab().save(str(file.parent / (name + ".png")))

    def reveal(button):
        for tabs in (panel.tabs, panel.market_tabs, panel.shop_tabs, panel.dress_tabs):
            for index in range(tabs.count()):
                if tabs.widget(index).isAncestorOf(button):
                    if tabs is panel.tabs:
                        panel.show_section(("bag", "shop", "achievements", "dress", "settings", "furniture")[index], animate=False)
                    else:
                        tabs.setCurrentIndex(index)
                    break
        node = button
        while node.parentWidget() is not None:
            node = node.parentWidget()
            if isinstance(node, QScrollArea):
                node.ensureWidgetVisible(button)
        QTest.qWait(35)

    def click(button):
        reveal(button)
        assert button.isEnabled() and button.isVisible()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    def begin():
        try:
            assert result["platform"] == "windows"
            assert panel.isVisible() and panel.room.isVisible()
            assert not pet.isVisible()
            assert not model.data.overlay_visible
            controller.tick_timer.stop()
            if mode == "read":
                expected = json.loads((file.parent / "expected.json").read_text(encoding="utf-8"))
                for key in ("name", "coins", "hunger", "affection_level", "affection_exp", "owned_furniture",
                            "equipped_furniture", "placed_furniture", "lamp_on", "overlay_visible", "selected_skin_id", "accessories"):
                    assert model.snapshot()[key] == expected[key], key
                assert pet.renderer.movies
                QTest.qWait(250)
                assert any(movie.state().name == "Running" for movie in pet.renderer.movies.values())
                assert model.data.equipped_furniture["corner"] == "warm_lamp" and not model.data.lamp_on
                assert not panel.room.lamp_rect().isEmpty()
                assert model.effective_accessories()["head"] == "crown"
                capture("09-restart-gif-home")
                result["independent_restart_furniture_name_skin_accessories_visibility"] = True
                return

            assert model.data.equipped_furniture == {"theme": "cheese_room", "rug": "cloud_cushion", "wall": "", "corner": "", "bowl": "wood_bowl"}
            panel.room.daytime_override = True
            capture("01-home-day-default")
            model_before = model.data.stats["total_clicks"]
            QTest.mouseClick(panel.room, Qt.MouseButton.LeftButton, pos=panel.room.pet_center().toPoint())
            assert model.data.stats["total_clicks"] == model_before + 1
            assert panel.room._message == "急咯急咯"
            assert pet.engine.state == PetState.HAPPY and not pet.bubble.isVisible()
            result["home_poke_shared_jelly_and_new_phrase"] = True
            with patch("dashboard.QInputDialog.getText", return_value=("芝麻的小家", True)):
                QTest.mouseClick(panel.rename_button, Qt.MouseButton.LeftButton)
            assert model.data.name == "芝麻的小家" and "芝麻的小家" in panel.hud_name.text()
            anchor = pet.engine.x, pet.engine.y, pet.engine.pinned
            QTest.mouseClick(panel.overlay_button, Qt.MouseButton.LeftButton)
            assert pet.isVisible() and model.data.overlay_visible
            QTest.mouseClick(panel.overlay_button, Qt.MouseButton.LeftButton)
            assert not pet.isVisible() and not pet.bubble.isVisible()
            assert (pet.engine.x, pet.engine.y, pet.engine.pinned) == anchor
            panel.hide()
            controller._tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
            assert panel.isVisible() and not pet.isVisible()
            assert (pet.engine.x, pet.engine.y, pet.engine.pinned) == anchor
            result["rename_overlay_toggle_and_tray_open_without_reset"] = True

            chosen = {"theme": "sakura_room", "rug": "cat_paw_rug", "wall": "rice_clock", "corner": "warm_lamp", "bowl": "porcelain_bowl"}
            for key in chosen.values():
                click(panel.furniture_shop_buttons[key])
                assert key in model.data.owned_furniture
            capture("02-furniture-shop")
            for slot, key in chosen.items():
                click(panel.furniture_buttons[key])
                assert model.data.equipped_furniture[slot] == key
            capture("03-furniture-decoration-drawer")
            assert "warm_home" in model.data.unlocked_achievements
            claim = panel.achievement_widgets["warm_home"][2]
            coins = model.data.coins
            click(claim)
            assert model.data.coins == coins + 60 and not claim.isEnabled()
            panel.show_section("home", animate=False)
            panel.home_scroll.verticalScrollBar().setValue(0)
            panel.room.daytime_override = False
            QTest.mouseClick(panel.room, Qt.MouseButton.LeftButton, pos=panel.room.lamp_rect().center().toPoint())
            assert not model.data.lamp_on
            capture("04-home-night-decorated")
            result["native_purchase_five_slots_lamp_toggle_and_reward"] = True

            click(panel.shop_buttons["sesame"][0])
            assert model.data.inventory["sesame"] == 1
            model.set_hunger(0)
            panel.show_section("home", animate=False)
            panel.home_scroll.verticalScrollBar().setValue(0)
            before_exp = model.data.affection_exp
            QTest.mouseClick(panel.feeding_buttons["sesame"], Qt.MouseButton.LeftButton)
            assert model.data.hunger == 35 and model.data.affection_exp == before_exp
            assert not pet.engine.starving and pet.engine.buff["scale"] == 1.2
            assert panel.room._food_id == "sesame"
            assert not pet.isVisible()
            capture("05-home-feed-bowl-sesame")
            result["native_feeding_shelf_flat_rescue_buff_bowl_shared_state"] = True

            gif = file.parent / "home-two-frame.gif"
            gif.write_bytes(make_gif())
            panel.import_image_requested.emit(str(gif), False)
            assert model.data.selected_skin_id.startswith("user_") and pet.renderer.movies
            panel.head_combo.setCurrentIndex(panel.head_combo.findData("crown"))
            assert model.effective_accessories()["head"] == "crown"
            frames = []
            for movie in pet.renderer.movies.values():
                movie.frameChanged.connect(frames.append)
            QTest.qWait(450)
            assert len(set(frames)) >= 2
            click(panel.trick_buttons["flip"])
            assert pet.engine.active_trick == "flip"
            panel.show_section("home", animate=False)
            panel.home_scroll.verticalScrollBar().setValue(0)
            QTest.qWait(260)
            capture("06-home-gif-crown-flip")
            QTest.qWait(950)
            assert pet.engine.active_trick == ""
            assert not pet.isVisible()
            result["local_gif_crown_flip_in_room_no_overlay"] = True

            for section in ("furniture", "shop", "dress", "achievements", "home"):
                QTest.mouseClick(panel.nav_buttons[section], Qt.MouseButton.LeftButton)
                QTest.qWait(210)
                assert panel.current_section == section and panel.room.isVisible()
            panel.resize(600, 480)
            QTest.qWait(70)
            assert panel.hud_name.isVisible()
            assert panel.home_scroll.horizontalScrollBar().maximum() > 0
            assert panel.home_scroll.verticalScrollBar().maximum() > 0
            capture("07-small-window-scroll")
            panel.resize(1000, 860)
            panel.home_scroll.horizontalScrollBar().setValue(0)
            panel.home_scroll.verticalScrollBar().setValue(0)
            panel.room.daytime_override = True
            capture("08-home-final-day")
            result["five_room_drawers_and_small_screen_scroll"] = True
            controller._save()
            (file.parent / "expected.json").write_text(json.dumps(model.snapshot(), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            controller.quit_action.trigger()

    QTimer.singleShot(220, begin)
    QTimer.singleShot(22000, lambda: (errors.append("native watchdog timeout"), controller.quit_action.trigger()))
    code = app.exec()
    result["errors"] = errors
    result["clean_shutdown"] = controller._stopped and not any(timer.isActive() for timer in (
        pet.timer, pet.click_timer, pet.bubble.timer, panel.room._animation_timer,
        controller.tick_timer, controller.save_timer, controller.autosave_timer))
    result["movies_stopped"] = all(movie.state().name == "NotRunning" for movie in pet.renderer.movies.values())
    (file.parent / (mode + "-result.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return int(bool(errors) or not result["clean_shutdown"] or not result["movies_stopped"]) or code


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("write", "read"))
    parser.add_argument("--save-file", type=Path)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker, args.save_file)
    folder = ROOT / "tests/artifacts" / datetime.now().strftime("home-native-%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True, exist_ok=False)
    file = folder / "save_data.json"
    file.write_text(json.dumps({"schema_version": 5, "coins": 2500, "affection_level": 6,
                               "window": {"pinned": True, "x_ratio": .5, "y_ratio": .55}}), encoding="utf-8")
    runs = []
    for mode in ("write", "read"):
        completed = subprocess.run([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
                                    "--worker", mode, "--save-file", str(file)], cwd=ROOT,
                                   capture_output=True, text=True, encoding="utf-8", timeout=35,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        runs.append(dict(mode=mode, code=completed.returncode, stdout=completed.stdout, stderr=completed.stderr))
        if completed.returncode:
            break
    report = dict(passed=len(runs) == 2 and all(row["code"] == 0 for row in runs), artifact_directory=str(folder), runs=runs)
    (folder / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("HOME_NATIVE " + json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
