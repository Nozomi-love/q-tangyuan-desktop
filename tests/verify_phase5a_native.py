"""Native Windows evidence for Phase 5A; all data stays in a new test sandbox."""
from datetime import datetime
import json
from pathlib import Path
import sys
import traceback
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScrollArea
from main import PetApplication
from home_scene import GiftPerformance
from verify_phase4_native import make_gif


def main():
    folder = ROOT / "tests/artifacts" / datetime.now().strftime("phase5a-native-%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True, exist_ok=False)
    file = folder / "save_data.json"
    file.write_text(json.dumps({"schema_version": 5, "coins": 10000, "affection_level": 6,
        "window": {"pinned": True, "x_ratio": .6, "y_ratio": .55}}), encoding="utf-8")
    app = QApplication(["phase5a-native"]); app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
    c = PetApplication(app, save_path=file, skins_root=folder / "skins", dev_mode=True)
    p, room, model, engine = c.dashboard, c.dashboard.room, c.model, c.window.engine
    result = {"platform": QGuiApplication.platformName(), "dpr": p.devicePixelRatioF(), "errors": []}
    def capture(name):
        app.processEvents(); assert p.grab().save(str(folder / (name + ".png")))
    def body():
        try:
            assert result["platform"] == "windows"
            c.tick_timer.stop(); c.window.timer.stop(); room._animation_timer.stop()
            p.resize(1280, 820); p.show(); app.processEvents()
            pinned = (engine.x, engine.y, engine.pinned)
            room.daytime_override = True; capture("01-home-day")
            viewports = []
            for width, height in ((820, 650), (1000, 720), (1280, 820)):
                p.resize(width, height)
                for section in ("bag", "shop", "dress", "furniture", "achievements", "settings"):
                    p.show_section(section, animate=False); app.processEvents()
                    assert not p.drawer.isWindow() and room.isVisible() and room.height() >= 420
                    for widget in (room, p.drawer, *p.nav_buttons.values()):
                        pos = widget.mapTo(p.home_scroll.viewport(), QPoint())
                        assert p.home_scroll.viewport().rect().contains(pos)
                        assert p.home_scroll.viewport().rect().contains(pos + widget.rect().bottomRight()), (width, section, widget.geometry())
                    assert p.hud.geometry().bottom() < room.pet_bounds().top()
                    viewports.append([width, section, room.width(), room.height(), p.drawer.width()])
            result["same_window_viewports"] = viewports
            p.show_section("shop", animate=False); capture("02-shop-same-window")
            model.buy_furniture("cat_paw_rug"); model.equip_furniture("rug", "cat_paw_rug")
            model.buy_furniture("warm_lamp"); model.equip_furniture("corner", "warm_lamp")
            p.show_section("furniture", animate=False); capture("03-decoration-preview")
            model.equip_accessory("head", "crown"); model.set_accessory_offset(-10)
            p.show_section("dress", animate=False); p.dress_tabs.setCurrentIndex(1); capture("04-crown-preview")
            p.show_section("home", animate=False); room.life.last_line = -100
            room.start_activity("window"); room.advance_scene(2.8); capture("05-look-window")
            assert room.life.state == "look_window"
            room.life.last_line = -100; room.start_activity("nap"); room.advance_scene(1.4); capture("06-nap")
            room.advance_scene(4.4); capture("07-stretch"); assert room.life.state == "stretch"
            for index, key in enumerate(("spinning_top", "music_box", "paper_star", "flower_bouquet"), 8):
                room.performance = None; model.buy_item(key, True)
                for _ in range(20): engine.advance(.05)
                clock = engine.elapsed
                room.advance_scene(3.1)
                assert engine.elapsed == clock
                assert room.performance.item_id == key
                if key == "spinning_top": assert room.performance.bumped and room.performance.speed > 1000
                capture(str(index).zfill(2) + "-" + key)
            room.performance = None; model.set_hunger(94); model.buy_item("water", True)
            assert room._floating[-1][0] == "+6 饱食" and room._food_id == "water"
            with patch("home_scene.monotonic", return_value=room._fly_started + .4): capture("12-feeding-flight")
            room.performance = None; room._chew_started = -100; room.interact()
            assert pinned == (engine.x, engine.y, engine.pinned)
            result["pinned_desktop_and_single_physics_clock_preserved"] = True
            gif = folder / "friend.gif"; gif.write_bytes(make_gif())
            c._import_image(str(gif), False); model.equip_accessory("head", "crown"); model.buy_item("sesame", True)
            model.buy_item("music_box", True); assert c.window.renderer.movies
            room.advance_scene(1); capture("13-gif-crown-music-buff")
            room.performance = None; engine.perform_trick("flip"); engine.advance(.3)
            capture("14-gif-flip"); assert engine.active_trick == "flip"; engine.cancel_trick()
            room.daytime_override = False; model.set_lamp_on(True); capture("15-night-lamp")
            model.set_lamp_on(False); capture("16-night-lamp-off")
            # Two different QMovies must not restart each other while both views paint.
            from pet_engine import PetState
            pack = folder / "two-state-gif"; pack.mkdir()
            for state in ("idle", "happy"): (pack / (state + ".gif")).write_bytes(make_gif())
            (pack / "manifest.json").write_text(json.dumps({"schema_version": 1, "name": "双状态GIF验收",
                "author": "local-test", "states": {"idle": "idle.gif", "happy": "happy.gif"}}), encoding="utf-8")
            c._import_pack(str(pack))
            assert len(set(c.window.renderer.movies.values())) == 2
            model.set_overlay_visible(True); model.buy_item("music_box", True)
            seen = []
            movie = c.window.renderer.movies[PetState.HAPPY]
            movie.frameChanged.connect(seen.append)
            c.window._schedule_frame(); room._animation_timer.start()
            QTest.qWait(600)
            assert len(set(seen)) >= 2 and c.window.renderer._active_movie is movie, seen
            assert room._view().state == engine.state == PetState.HAPPY
            c.window.timer.stop(); room._animation_timer.stop()
            result["two_state_gif_continues_with_both_views_visible"] = True
            result.update(gifts=["spinning_top", "music_box", "paper_star", "flower_bouquet"],
                autonomous_window_nap_stretch=True, actual_gain_and_food_flight=True,
                custom_gif_crown_buff_trick=True, night_and_lamp=True)
        except Exception:
            result["errors"].append(traceback.format_exc())
        finally:
            c.quit_action.trigger()
    sys.excepthook = lambda typ, value, tb: (result["errors"].append("".join(traceback.format_exception(typ, value, tb))), c.quit_action.trigger())
    QTimer.singleShot(200, body)
    QTimer.singleShot(45000, lambda: (result["errors"].append("watchdog timeout"), c.quit_action.trigger()))
    code = app.exec()
    result["clean_shutdown"] = c._stopped and not room._animation_timer.isActive()
    result["passed"] = not result["errors"] and result["clean_shutdown"] and code == 0
    result["directory"] = str(folder)
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result["passed"] else 1


if __name__ == "__main__": raise SystemExit(main())
