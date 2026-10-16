"""Native Windows integration check of our own window, without moving the cursor."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
import json
from pathlib import Path
import sys
import time
import traceback

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import PetApplication

QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)
app = QApplication(["phase1-native-verification"])
app.setQuitOnLastWindowClosed(False)
app.setStyleSheet((ROOT / "styles/theme.qss").read_text(encoding="utf-8"))
destination = ROOT / "tests" / "artifacts" / datetime.now().strftime("native-%Y%m%d-%H%M%S-%f")
destination.mkdir(parents=True, exist_ok=False)
controller = PetApplication(app, save_path=destination / "save_data.json")
window = controller.window
result: dict[str, object] = {}
failures: list[str] = []
started = time.perf_counter()


def verify() -> None:
    try:
        assert QGuiApplication.platformName() == "windows"
        assert window.isVisible()
        assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        assert window.frame_count >= 8
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        get_style = user32.GetWindowLongPtrW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        style = get_style(int(window.winId()), -20)
        assert style & 0x00000008, "WS_EX_TOPMOST missing"
        assert style & 0x00000080, "WS_EX_TOOLWINDOW missing"
        assert style & 0x00080000, "WS_EX_LAYERED missing"

        window.timer.stop()
        global_foot = window.mapToGlobal(window.local_foot())
        assert abs(global_foot.x() - window.engine.x) < 0.01
        assert abs(global_foot.y() - window.engine.area.bottom) < 0.01
        idle = window.grab()
        assert not idle.isNull()
        assert idle.save(str(destination / "idle.png"))

        controller.flat_action.trigger()
        assert window.engine.flat
        assert window.engine.pose.scale_y < 0.43
        assert window.grab().save(str(destination / "flat.png"))
        controller.flat_action.trigger()
        assert not window.engine.flat

        window.engine.begin_drag()
        window.engine.drag_to(window.engine.area.left + 250, window.engine.area.top + 300, 900)
        controller.reset_action.trigger()
        assert not window.engine.held
        assert abs(window.engine.y - window.engine.area.bottom) < 0.01
        area = window.engine.area
        window.engine.place(area.left + area.width * 0.5, area.top + area.height * 0.4)
        controller.pin_action.trigger()
        anchor = window.engine.x, window.engine.y
        window.engine.click()
        window.engine.advance(0.1)
        assert (window.engine.x, window.engine.y) == anchor
        controller.pin_action.trigger()
        window.engine.advance(0.1)
        assert window.engine.y > anchor[1]
        controller.reset_action.trigger()
        controller.reload_action.trigger()

        result.update({
            "platform": QGuiApplication.platformName(),
            "screen_count": len(QGuiApplication.screens()),
            "device_pixel_ratio": window.devicePixelRatioF(),
            "native_extended_style": hex(style),
            "topmost_tool_layered": True,
            "mapped_foot_matches_work_area": True,
            "tray_actions_checked": ["flat_on", "flat_off", "pin_on", "pin_off", "reset", "reload", "quit"],
            "frames_before_actions": window.frame_count,
            "elapsed_before_actions": round(time.perf_counter() - started, 3),
            "snapshots": [str(destination / "idle.png"), str(destination / "flat.png")],
        })
    except Exception as error:
        failures.append(f"{type(error).__name__}: {error}")
        print(traceback.format_exc(), file=sys.stderr)
    finally:
        controller.quit_action.trigger()


QTimer.singleShot(500, verify)
exit_code = app.exec()
if window.timer.isActive() or controller.tray.isVisible():
    failures.append("退出时计时器或托盘没有停止")
result["shutdown_clean"] = not failures and exit_code == 0
result["failures"] = failures
result_file = destination / "result.json"
with result_file.open("x", encoding="utf-8") as output:
    json.dump(result, output, ensure_ascii=False, indent=2)
print(("NATIVE_VERIFY_OK " if not failures else "NATIVE_VERIFY_FAILED ") +
      json.dumps(result, ensure_ascii=False), flush=True)
raise SystemExit(1 if failures else exit_code)
