"""Native five-tab, commerce, effects and two-process persistence verification."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(mode: str, file: Path) -> int:
    from PySide6.QtCore import QEvent, QPointF, Qt, QTimer
    from PySide6.QtGui import QGuiApplication, QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from main import PetApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(["phase3-native"])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
    controller = PetApplication(app, save_path=file, accelerated=mode == "write")
    window, model, panel = controller.window, controller.model, controller.dashboard
    failures = []
    started = time.perf_counter()
    result = {"mode": mode, "platform": QGuiApplication.platformName(), "dpr": window.devicePixelRatioF(),
              "screens": len(QGuiApplication.screens())}
    sys.excepthook = lambda typ, value, tb: (failures.append("".join(traceback.format_exception(typ, value, tb))), app.exit(1))

    def capture(name, tab=None):
        if tab is not None:
            panel.tabs.setCurrentIndex(tab)
        QTest.qWait(130)
        widget = window if tab is None else panel
        assert widget.grab().save(str(file.parent / (name + ".png")))
        result.setdefault("capture_times", {})[name] = round(time.perf_counter() - started, 3)

    def ensure_button(button):
        for tabs in (panel.tabs, panel.shop_tabs, panel.dress_tabs):
            for index in range(tabs.count()):
                if tabs.widget(index).isAncestorOf(button):
                    tabs.setCurrentIndex(index)
                    break
        page = button
        while page.parentWidget() is not None:
            page = page.parentWidget()
            if hasattr(page, 'ensureWidgetVisible'):
                page.ensureWidgetVisible(button)
        QTest.qWait(40)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    def pointer(kind, global_point):
        button = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
        buttons = Qt.MouseButton.NoButton if kind == QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
        event = QMouseEvent(kind, window.mapFromGlobal(global_point), global_point, button, buttons, Qt.KeyboardModifier.NoModifier)
        APP_RESULT = app.sendEvent(window, event)
        QTest.qWait(65)
        return APP_RESULT

    def begin():
        try:
            assert QGuiApplication.platformName() == "windows"
            assert panel.tabs.count() == 5
            assert window.engine.pinned
            if mode == "read":
                saved = json.loads(file.read_text(encoding="utf-8"))
                assert model.data.coins == saved["coins"]
                assert len(model.data.claimed_achievements) == 10
                assert model.data.equipped_title == "美食鉴赏家"
                assert model.data.inventory["water"] == 2
                assert model.data.active_buff["item_id"] == "sesame"
                assert window.engine.buff["scale"] == 1.2
                assert not model.claim_achievement("flavors_three")
                assert abs(window.capture_position()["x_ratio"] - 0.55) < 0.001
                assert abs(window.capture_position()["y_ratio"] - 0.48) < 0.001
                result["all_growth_inventory_titles_buff_pin_restored"] = True
                model.advance(61)
                controller._save()
                assert json.loads(file.read_text(encoding="utf-8"))["active_buff"] == {}
                result["expired_buff_not_resurrected"] = True
                return

            # Native double-click is confirmed on release, without any poke reward.
            point = (window.local_foot() + QPointF(0, -50)).toPoint()
            coins = model.data.coins
            QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=point)
            QTest.qWait(60)
            QTest.mouseDClick(window, Qt.MouseButton.LeftButton, pos=point)
            QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=point)
            QTest.qWait(260)
            assert panel.isVisible() and model.data.stats["total_clicks"] == 0
            assert model.data.coins == coins
            capture("01-status", 0)
            panel.close()
            assert not panel.isVisible() and window.isVisible()
            controller.dashboard_action.trigger()
            assert panel.isVisible()
            panel.tabs.setCurrentIndex(1)
            ensure_button(panel.shop_buttons["sesame"][0])
            assert model.data.inventory["sesame"] == 1
            capture("02-shop-top", 1)
            page = panel.shop_tabs.currentWidget()
            page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
            capture("03-shop-bottom", 1)
            capture("04-backpack", 0)
            ensure_button(panel.inventory_widgets["sesame"][2])
            assert window.engine.buff["scale"] == 1.2
            capture("05-sesame-overlay")
            for key in ("strawberry", "matcha"):
                panel.tabs.setCurrentIndex(1)
                ensure_button(panel.shop_buttons[key][1])
                assert window.engine.buff["item_id"] == key
                capture(key + "-overlay")
            assert "flavors_three" in model.data.unlocked_achievements
            panel.tabs.setCurrentIndex(2)
            for aid in ("first_feed", "flavors_three"):
                ensure_button(panel.achievement_widgets[aid][2])
            ensure_button(panel.achievement_widgets["flavors_three"][3])
            assert model.data.equipped_title == "美食鉴赏家"
            capture("06-achievements", 2)
            capture("07-settings", 4)
            panel.hide()
            # Real 250 ms input cadence demonstrates the rapid-poke easter egg.
            for _ in range(15):
                point = (window.local_foot() + QPointF(0, -50)).toPoint()
                QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=point)
                QTest.qWait(255)
            assert model.data.stats["total_clicks"] == 15
            assert not panel.isVisible()
            assert "rapid_pokes" in model.data.unlocked_achievements
            capture("08-dizzy-overlay")
            controller.pet_action.trigger()
            controller.hunger_zero_action.trigger()
            model.buy_item("water", True)
            assert "rescue" in model.data.unlocked_achievements
            for _ in range(3):
                model.offer_collectible()
                model.claim_collectible()
            # Seed the upgrade boundary; food deliberately grants no experience.
            model.data.affection_level = 2
            model.data.affection_exp = 999
            assert model.buy_item("paper_star", True)
            assert model.data.affection_level == 3
            # Fast native pointer events, alternating direction three times.
            origin = QPointF(window.engine.x, window.engine.y - 50)
            pointer(QEvent.Type.MouseButtonPress, origin)
            for dx in (-120, 0, -120, 0):
                pointer(QEvent.Type.MouseMove, origin + QPointF(dx, -80))
            pointer(QEvent.Type.MouseButtonRelease, origin + QPointF(0, -80))
            assert "shake" in model.data.unlocked_achievements
            # Only a released user drag landing counts as high-altitude drop.
            window.set_pinned(False)
            controller.reset_action.trigger()
            origin = QPointF(window.engine.x, window.engine.y - 50)
            pointer(QEvent.Type.MouseButtonPress, origin)
            pointer(QEvent.Type.MouseMove, origin + QPointF(-160, -300))
            pointer(QEvent.Type.MouseButtonRelease, origin + QPointF(-160, -300))
            QTest.qWait(1000)
            assert "first_drop" in model.data.unlocked_achievements
            model.buy_item("chili", True)
            free_start = window.engine.x
            QTest.qWait(650)
            assert abs(window.engine.x - free_start) > 20
            window.set_pinned(True)
            fixed = window.engine.x, window.engine.y
            QTest.qWait(650)
            assert (window.engine.x, window.engine.y) == fixed
            capture("09-chili-overlay")
            assert len(model.data.unlocked_achievements) == 10, model.data.unlocked_achievements
            controller.dashboard_action.trigger()
            panel.tabs.setCurrentIndex(2)
            panel.tier_filter.setCurrentIndex(3)
            for achievement in model.catalog.achievements:
                # Use the same model slot as each claim button, checking once-only rewards.
                aid = achievement["id"]
                model.claim_achievement(aid)
                balance = model.data.coins
                assert not model.claim_achievement(aid)
                assert model.data.coins == balance
            capture("10-hidden-achievements", 2)
            model.equip_title("美食鉴赏家")
            model.buy_item("water")
            model.buy_item("water")
            model.buy_item("sesame", True)
            area = window.engine.area
            window.engine.place(area.left + area.width * 0.55, area.top + area.height * 0.48)
            window._sync_window()
            controller._save()
            result.update(five_tabs=True, double_click_without_poke=True, close_hides_only=True,
                          commerce_buttons=True, title_controls=True, real_rapid_pokes=True,
                          shake_and_real_drop=True, spicy_free_and_fixed=True, all_ten_achievements_claimed=True,
                          frames=window.frame_count, growth=model.snapshot())
        except Exception:
            failures.append(traceback.format_exc())
        finally:
            controller.quit_action.trigger()

    QTimer.singleShot(250, begin)
    QTimer.singleShot(45000, lambda: (failures.append("native verification timed out"), app.quit()))
    code = app.exec()
    result["failures"] = failures
    result["clean_shutdown"] = not panel.isVisible() and not any(t.isActive() for t in (window.timer, window.click_timer, window.bubble.timer, controller.tick_timer, controller.autosave_timer, controller.save_timer))
    with (file.parent / (mode + "-result.json")).open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print("PHASE3_WORKER " + json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if failures or not result["clean_shutdown"] else code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("write", "read"))
    parser.add_argument("--save-file", type=Path)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker, args.save_file)
    destination = ROOT / "tests/artifacts" / datetime.now().strftime("phase3-native-%Y%m%d-%H%M%S-%f")
    destination.mkdir(parents=True, exist_ok=False)
    file = destination / "save_data.json"
    from PySide6.QtWidgets import QApplication
    app = QApplication(["screen-name"])
    initial = {"schema_version": 2, "coins": 1000, "window": {"pinned": True, "screen": app.primaryScreen().name(), "x_ratio": 0.55, "y_ratio": 0.48}}
    with file.open("x", encoding="utf-8") as output:
        json.dump(initial, output, ensure_ascii=False)
    runs = []
    for mode in ("write", "read"):
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()), "--worker", mode, "--save-file", str(file)],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=55,
                                 creationflags=subprocess.CREATE_NO_WINDOW)
        runs.append({"mode": mode, "code": process.returncode, "stdout": process.stdout, "stderr": process.stderr})
        if process.returncode:
            break
    passed = len(runs) == 2 and all(item["code"] == 0 for item in runs)
    result = {"passed": passed, "artifact_directory": str(destination), "runs": runs}
    with (destination / "result.json").open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print("PHASE3_NATIVE " + json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
