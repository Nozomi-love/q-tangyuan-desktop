"""Local JSON persistence; window preferences are the first saved section."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import time


def _reject_constant(value: str):
    raise ValueError(f"不支持非标准数值：{value}")


class SaveDataError(RuntimeError):
    """A save could not be read or safely updated; existing data is retained."""


class SaveManager:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def _read(self) -> tuple[bytes | None, dict]:
        try:
            raw = self.path.read_bytes()
        except FileNotFoundError:
            return None, {}
        except OSError as error:
            raise SaveDataError(f"无法读取存档：{error}") from error
        try:
            data = json.loads(raw.decode("utf-8-sig"), parse_constant=_reject_constant)
            if not isinstance(data, dict):
                raise ValueError("存档根节点必须是对象")
            version = data.get("schema_version", 1)
            if type(version) is not int or version != 1:
                raise ValueError("不支持的存档版本")
            return raw, data
        except (UnicodeError, ValueError) as error:
            raise SaveDataError(f"存档格式错误，原文件保留：{error}") from error

    @staticmethod
    def _validate_window(state: dict) -> dict:
        if not isinstance(state, dict):
            raise SaveDataError("window 必须是对象")
        if type(state.get("pinned", False)) is not bool:
            raise SaveDataError("固定开关必须是布尔值")
        if "screen" in state and not isinstance(state["screen"], str):
            raise SaveDataError("显示器名称必须是字符串")
        for key in ("x_ratio", "y_ratio"):
            if key not in state and not state.get("pinned", False):
                continue
            value = state.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SaveDataError("位置比例必须是数值")
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise SaveDataError("位置比例必须在 0～1 之间")
        return dict(state)

    def load_window_state(self) -> dict:
        _, data = self._read()
        return self._validate_window(data.get("window", {}))

    def update_window(self, state: dict) -> None:
        """Merge only window settings, preserving future game/unknown sections."""
        state = self._validate_window(state)
        before, data = self._read()
        old_window = self._validate_window(data.get("window", {}))
        data["schema_version"] = 1
        data["window"] = {**old_window, **state}
        payload = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if before == payload:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(f"{self.path.name}.{time.time_ns()}.tmp")
            with temporary.open("xb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            try:
                current = self.path.read_bytes()
            except FileNotFoundError:
                current = None
            if current != before:
                raise SaveDataError("存档被其他进程修改，本次没有覆盖；临时文件保留")
            os.replace(temporary, self.path)
        except OSError as error:
            raise SaveDataError(f"存档写入失败，原文件保留：{error}") from error
