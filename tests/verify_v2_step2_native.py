"""Windows high-DPI, real audio decoder and two-process save evidence, never player data."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def child(mode, folder):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtMultimedia import QSoundEffect
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from main import PetApplication
    from verify_phase4_native import make_gif
    app = QApplication(["v2-step2-native"]); app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf8"))
    save = folder / "save_data.json"
    if mode == "write":
        save.write_text(json.dumps({"schema_version": 5, "coins": 10000, "affection_level": 6,
            "window": {"pinned": True, "x_ratio": .6, "y_ratio": .5}}), encoding="utf8")
    c = PetApplication(app, save, skins_root=folder / "skins", dev_mode=True)
    p, r, m, e = c.dashboard, c.dashboard.room, c.model, c.window.engine
    result = {"platform": QGuiApplication.platformName(), "dpr": p.devicePixelRatioF(), "mode": mode}
    def capture(name):
        app.processEvents(); assert p.grab().save(str(folder / (name + ".png")))
    try:
        assert result["platform"] == "windows"
        c.tick_timer.stop(); c.window.timer.stop(); r._animation_timer.stop()
        p.resize(1280, 820); app.processEvents()
        if mode == "restore":
            expected = json.loads((folder / "expected.json").read_text(encoding="utf8"))
            for field, value in expected.items(): assert getattr(m.data, field) == value, field
            assert m.data.muted and c.audio.muted and c.mute_action.isChecked() and p.mute_button.isChecked()
            assert c.window.engine.pinned and c.window.renderer.movies
            result["cross_process_mute_skin_furniture_progress_restored"] = True
            capture("09-restored-muted-gif")
        else:
            pinned = (e.x, e.y, e.pinned); clock = e.elapsed
            statuses = {}
            for _ in range(120):
                app.processEvents(); QTest.qWait(30)
                statuses = {key: effect.status().name for key, effect in c.audio.effects.items()}
                if statuses and all(value == "Ready" for value in statuses.values()): break
            assert len(statuses) == 5 and all(value == "Ready" for value in statuses.values()), statuses
            result["real_qsoundeffect_decoders"] = statuses
            result["real_playback_started"] = {}
            for name, effect in c.audio.effects.items():
                c.audio.play(name); QTest.qWait(35)
                result["real_playback_started"][name] = effect.isPlaying()
                assert effect.isPlaying(), name
                effect.stop()
            r.daytime_override = False
            r.start_activity("window"); r.advance_scene(2.9); capture("01-window")
            assert r.life.state == "look_window"
            r.start_activity("nap"); r.advance_scene(1.8); r._repaint_if_visible()
            assert r.life.state == "nap"; capture("02-nap")
            r.advance_scene(3.9); assert r.life.state == "stretch"; capture("03-stretch")
            m.poke(); assert r.life.state == "idle"
            r.start_activity("hum"); r.advance_scene(.8); capture("04-humming")
            for i, key in enumerate(("spinning_top", "music_box", "paper_star", "flower_bouquet")):
                r.performance = None; m.buy_item(key, True); r.advance_scene(3.1)
                assert r.performance.item_id == key
                if key == "spinning_top": assert r.performance.pet_x == r.performance.start_x and r._view().visual_angle == 0 and r._view().yaw_scale != 1
                if key == "music_box":
                    QTest.qWait(50); assert c.audio.effects[key].isPlaying()
                capture("05-" + key)
            r.performance = None; r.life.x = .48
            m.set_hunger(62); p.show_section("shop", animate=False); app.processEvents()
            p.shop_buttons["strawberry"][1].click(); r.advance_scene(.38)
            assert r._fly_from is not None; assert not r._food_arrived
            capture("06-food-flight")
            r.advance_scene(.55); assert r._food_arrived
            assert any(text == "+35 饱食度" for text, _ in r._floating)
            capture("07-chew-hearts-gains")
            assert pinned == (e.x, e.y, e.pinned) and clock == e.elapsed
            result["pinned_desktop_and_single_clock_preserved"] = True
            p.mute_button.click(); assert c.audio.muted and m.data.muted and c.mute_action.isChecked()
            assert all(not effect.isPlaying() for effect in c.audio.effects.values())
            result["mute_stops_and_synchronizes_all_audio"] = True
            gif = folder / "friend.gif"; gif.write_bytes(make_gif()); c._import_image(str(gif), False); c._confirm_preview()
            m.equip_accessory("head", "crown"); assert m.buy_furniture("lotus_cushion"); assert m.equip_furniture("rug", "lotus_cushion")
            fields = ("muted", "selected_skin_id", "accessories", "owned_furniture", "equipped_furniture", "coins", "affection_exp")
            (folder / "expected.json").write_text(json.dumps({key: getattr(m.data, key) for key in fields}), encoding="utf8")
            c._save(); p.show_section("home", animate=False); capture("08-muted-gif-crown")
            result["visual_gifts"] = ["spinning_top", "music_box", "paper_star", "flower_bouquet"]
    except BaseException:
        result["error"] = traceback.format_exc()
    finally:
        c.stop(); c.dashboard.deleteLater(); c.window.deleteLater(); app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        (folder / (mode + "-result.json")).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf8")
    print(json.dumps(result, ensure_ascii=False))
    return 1 if "error" in result else 0


def main():
    if len(sys.argv) == 3: return child(sys.argv[1], Path(sys.argv[2]))
    folder = ROOT / "tests/artifacts" / datetime.now().strftime("v2-step2-native-%Y%m%d-%H%M%S-%f")
    folder.mkdir(parents=True)
    for mode in ("write", "restore"):
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", __file__, mode, str(folder)], cwd=ROOT, capture_output=True, text=True)
        (folder / (mode + "-output.txt")).write_text(result.stdout + result.stderr, encoding="utf8")
        print(result.stdout)
        if result.returncode: print(result.stderr); return result.returncode
    print("Evidence: " + str(folder)); return 0


if __name__ == "__main__": raise SystemExit(main())
