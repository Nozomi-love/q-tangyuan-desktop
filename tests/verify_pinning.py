"""Use two separate native app processes to verify persistent pinning."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run_worker(mode: str, save_file: Path) -> int:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    from main import PetApplication

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(["pinning-verification"])
    app.setQuitOnLastWindowClosed(False)
    controller = PetApplication(app, save_path=save_file)
    window = controller.window
    failures = []
    result = {"mode": mode}
    anchor = None

    def finish() -> None:
        try:
            if mode == "write":
                assert (window.engine.x, window.engine.y) == anchor
                assert window.engine.pinned
                result["fixed_during_click"] = True
            else:
                assert window.engine.y > anchor[1]
                result["unpin_restores_gravity"] = True
                controller.pin_action.trigger()
            result["position"] = window.capture_position()
            assert window.grab().save(str(save_file.parent / f"{mode}-pinned.png"))
        except Exception:
            failures.append(traceback.format_exc())
        finally:
            controller.quit_action.trigger()

    def begin() -> None:
        nonlocal anchor
        try:
            if mode == "write":
                area = window.engine.area
                window.engine.place(area.left + area.width * 0.55,
                                    area.top + area.height * 0.40)
                window._sync_window()
                controller.pin_action.trigger()
                assert controller.pin_action.isChecked()
                anchor = window.engine.x, window.engine.y
                window.engine.click()
            else:
                assert window.engine.pinned and controller.pin_action.isChecked()
                state = window.capture_position()
                assert abs(state["x_ratio"] - 0.55) < 0.001
                assert abs(state["y_ratio"] - 0.40) < 0.001
                result["restored_in_new_process"] = True
                anchor = window.engine.x, window.engine.y
                controller.pin_action.trigger()
            QTimer.singleShot(220, finish)
        except Exception:
            failures.append(traceback.format_exc())
            controller.quit_action.trigger()

    QTimer.singleShot(150, begin)
    exit_code = app.exec()
    result["failures"] = failures
    print("PIN_WORKER " + json.dumps(result, ensure_ascii=False), flush=True)
    return 1 if failures else exit_code


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", choices=("write", "read"))
    parser.add_argument("--save-file", type=Path)
    args = parser.parse_args()
    if args.worker:
        if args.save_file is None:
            parser.error("--worker requires --save-file")
        return run_worker(args.worker, args.save_file)
    if sys.platform != "win32":
        raise SystemExit("本脚本验证 Windows 原生窗口，请在 Windows 上运行。")
    destination = ROOT / "tests/artifacts" / datetime.now().strftime("pinning-%Y%m%d-%H%M%S-%f")
    destination.mkdir(parents=True, exist_ok=False)
    save_file = destination / "save_data.json"
    results = []
    for mode in ("write", "read"):
        completed = subprocess.run(
            [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", mode,
             "--save-file", str(save_file)], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8", timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        results.append({"mode": mode, "returncode": completed.returncode,
                        "stdout": completed.stdout, "stderr": completed.stderr})
        if completed.returncode:
            break
    passed = len(results) == 2 and all(item["returncode"] == 0 for item in results)
    report = {"passed": passed, "separate_processes": True, "results": results}
    with (destination / "result.json").open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(("PINNING_VERIFY_OK " if passed else "PINNING_VERIFY_FAILED ") +
          json.dumps(report, ensure_ascii=False), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
