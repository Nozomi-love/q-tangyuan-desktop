"""Two native Windows processes verify the real timer, bubble and growth restart."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime
import json
from pathlib import Path
import random
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def worker(mode: str, file: Path) -> int:
    from PySide6.QtCore import QPointF, Qt, QTimer
    from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from main import PetApplication
    from pet_engine import PetState

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(["phase2-native-verification"])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
    controller = PetApplication(app, save_path=file, accelerated=mode == "write")
    window, model, bubble = controller.window, controller.model, controller.window.bubble
    failures = []
    result = {"mode": mode, "platform": QGuiApplication.platformName(),
              "dpr": window.devicePixelRatioF(), "screens": len(QGuiApplication.screens())}

    def snapshot(name: str) -> None:
        QTest.qWait(230)
        window._sync_window()
        pet_rect = window.geometry()
        bounds = pet_rect.united(bubble.geometry()) if bubble.isVisible() else pet_rect
        canvas = QImage(bounds.width(), bounds.height(), QImage.Format.Format_ARGB32)
        canvas.fill(QColor("#eeeaf3"))
        painter = QPainter(canvas)
        painter.drawPixmap(pet_rect.topLeft() - bounds.topLeft(), window.grab())
        if bubble.isVisible():
            painter.drawPixmap(bubble.pos() - bounds.topLeft(), bubble.grab())
        painter.end()
        assert canvas.save(str(file.parent / (name + ".png")))

    def finish() -> None:
        controller.quit_action.trigger()

    def guarded(callback):
        def run():
            try:
                callback()
            except Exception:
                failures.append(traceback.format_exc())
                finish()
        return run

    def after_real_timer() -> None:
        assert model.has_collectible, "real QTimer did not offer a gift after ten seconds"
        assert bubble.isVisible() and bubble._showing_gift
        area = window.active_screen.availableGeometry()
        assert area.contains(bubble.geometry()), (area, bubble.geometry())
        assert bubble.isWindow()
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        getter = user32.GetWindowLongPtrW
        getter.argtypes, getter.restype = [wintypes.HWND, ctypes.c_int], ctypes.c_ssize_t
        style = getter(int(bubble.winId()), -20)
        assert style & 0x00000008 and style & 0x00000080 and style & 0x00080000
        result["bubble_extended_style"] = hex(style)
        result["real_timer_gift_visible"] = True
        result["online_seconds_at_gift"] = model.data.stats["total_idle_seconds"]
        snapshot("gift")
        before = model.data.coins
        gift = model.data.pending_reward["coins"]
        QTest.mouseClick(bubble, Qt.MouseButton.LeftButton, pos=bubble.rect().center())
        assert not model.has_collectible and model.data.coins == before + gift
        assert model.data.stats["total_clicks"] == 20
        result["native_bubble_claim"] = gift
        controller.dev_action.setChecked(False)
        controller.hunger_zero_action.trigger()
        assert window.engine.starving and window.engine.state == PetState.FLAT
        snapshot("starving")
        controller.feed_action.trigger()
        assert model.data.hunger == 25 and not window.engine.flat
        assert model.data.affection_level == 2
        assert model.data.coins == before + gift - 10 + 30
        assert window.engine._celebration_hops > 0
        assert "Lv.2" in bubble._text
        snapshot("level-up-and-recovered")
        controller.menu.popup(window.mapToGlobal(window.local_foot()).toPoint())
        QTest.qWait(100)
        assert controller.menu.grab().save(str(file.parent / "menu.png"))
        controller.menu.hide()
        result["five_scenarios"] = ["poke_drops", "timed_gift_claim", "zero_hunger_flat", "sugar_recovery", "level_reward"]
        controller.model.offer_collectible()
        controller._save()
        result["saved_growth"] = model.snapshot()
        result["saved_position"] = window.capture_position()
        finish()

    def begin() -> None:
        assert QGuiApplication.platformName() == "windows"
        assert window.engine.pinned
        if mode == "write":
            model.rng = random.Random(1)
            for _ in range(20):
                at = window.local_foot() + QPointF(0, -50)
                QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=at.toPoint())
                QTest.qWait(240)
            assert model.data.stats["total_clicks"] == 20
            assert model.data.affection_exp == 40
            assert model.data.daily_stats["poke_coin_drops"] > 0
            result["poke_drops"] = model.data.daily_stats["poke_coin_drops"]
            controller.pet_action.trigger()
            assert model.data.affection_exp == 43
            QTimer.singleShot(10800, guarded(after_real_timer))
        else:
            saved = json.loads(file.read_text(encoding="utf-8"))
            assert model.data.affection_level == 2
            assert model.has_collectible and bubble._showing_gift
            assert model.data.stats["total_clicks"] == 20
            assert model.data.stats["total_feeds"] == 1
            assert abs(window.capture_position()["x_ratio"] - 0.55) < 0.001
            assert abs(window.capture_position()["y_ratio"] - 0.50) < 0.001
            amount = model.data.pending_reward["coins"]
            coins = model.data.coins
            assert model.claim_collectible()
            assert not model.claim_collectible()
            assert model.data.coins == coins + amount
            assert saved["inventory"] == {"future_item": 2}
            result["growth_and_pin_restored"] = True
            result["pending_gift_claimed_once_after_restart"] = True
            finish()

    QTimer.singleShot(200, guarded(begin))
    QTimer.singleShot(18000, guarded(lambda: (_ for _ in ()).throw(AssertionError("verification timeout"))))
    exit_code = app.exec()
    result["failures"] = failures
    result["clean_shutdown"] = not any(t.isActive() for t in (window.timer, bubble.timer, controller.tick_timer, controller.autosave_timer, controller.save_timer))
    with (file.parent / (mode + "-result.json")).open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print("PHASE2_WORKER " + json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if failures or not result["clean_shutdown"] else exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("write", "read"))
    parser.add_argument("--save-file", type=Path)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker, args.save_file)
    destination = ROOT / "tests/artifacts" / datetime.now().strftime("phase2-native-%Y%m%d-%H%M%S-%f")
    destination.mkdir(parents=True, exist_ok=False)
    file = destination / "save_data.json"
    # Native first-run migration starts with a real version-one position save.
    from PySide6.QtWidgets import QApplication
    app = QApplication(["screen-name-only"])
    screen_name = app.primaryScreen().name()
    initial = {"schema_version": 1, "window": {"pinned": True, "screen": screen_name, "x_ratio": 0.55, "y_ratio": 0.50},
               "inventory": {"future_item": 2}}
    with file.open("x", encoding="utf-8") as output:
        json.dump(initial, output, ensure_ascii=False)
    runs = []
    for mode in ("write", "read"):
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
                                  "--worker", mode, "--save-file", str(file)],
                                 cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                                 timeout=25, creationflags=subprocess.CREATE_NO_WINDOW)
        runs.append({"mode": mode, "code": process.returncode, "stdout": process.stdout, "stderr": process.stderr})
        if process.returncode:
            break
    passed = len(runs) == 2 and all(r["code"] == 0 for r in runs)
    report = {"passed": passed, "artifact_directory": str(destination), "runs": runs}
    with (destination / "result.json").open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print("PHASE2_NATIVE " + json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
