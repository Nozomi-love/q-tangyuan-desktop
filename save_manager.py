"""Versioned JSON saves with atomic writes, migration backup and stale-writer guards."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import time

from models import PetData


def _reject_constant(value: str):
    raise ValueError(f"不支持非标准数值：{value}")


class SaveDataError(RuntimeError):
    """Existing data is retained when reading or safely writing fails."""


_UNSEEN = object()


class SaveManager:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._expected = _UNSEEN

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
            if type(version) is not int or version not in (1, 2):
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
        raw, data = self._read()
        result = self._validate_window(data.get("window", {}))
        self._expected = raw
        return result

    def load_game_state(self) -> PetData:
        raw, data = self._read()
        try:
            result = PetData.from_dict(data)
        except (ValueError, TypeError, OverflowError) as error:
            raise SaveDataError(f"养成存档无效，原文件保留：{error}") from error
        self._expected = raw
        return result

    def load_all(self) -> tuple[PetData, dict]:
        raw, data = self._read()
        window = self._validate_window(data.get("window", {}))
        try:
            pet = PetData.from_dict(data)
        except (ValueError, TypeError, OverflowError) as error:
            raise SaveDataError(f"养成存档无效，原文件保留：{error}") from error
        self._expected = raw
        return pet, window

    @staticmethod
    def _merge(old: dict, new: dict) -> dict:
        result = deepcopy(old)
        for key, value in new.items():
            result[key] = SaveManager._merge(result[key], value) if isinstance(value, dict) and isinstance(result.get(key), dict) else deepcopy(value)
        return result

    def update_window(self, state: dict) -> None:
        self._update(window=state)

    def update_game(self, state: dict, window: dict | None = None) -> None:
        self._update(window=window, game=state)

    def _update(self, window: dict | None = None, game: dict | None = None) -> None:
        if window is not None:
            window = self._validate_window(window)
        if game is not None:
            try:
                game = PetData.from_dict(game).to_dict()
            except (ValueError, TypeError, OverflowError) as error:
                raise SaveDataError(f"拒绝写入无效养成数据：{error}") from error
        before, data = self._read()
        if self._expected is not _UNSEEN and self._expected != before:
            raise SaveDataError("存档已被其他进程修改，请退出后重新启动；本次不覆盖")
        old_version = data.get("schema_version", 1)
        if window is not None:
            old_window = self._validate_window(data.get("window", {}))
            data["window"] = {**old_window, **window}
        if game is not None:
            data = self._merge(data, game)
        data["schema_version"] = 2 if game is not None else old_version
        payload = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if before == payload:
            self._expected = before
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if before is not None and old_version == 1 and game is not None:
                # Back up the player's old position save before its first upgrade.
                stamp_time = datetime.now(timezone(timedelta(hours=8)))
                while True:
                    stamp = stamp_time.strftime("%Y%m%d-%H%M%S-%f")[:-3]
                    backup = self.path.with_name(f"{self.path.name}.bak.{stamp}")
                    try:
                        output = backup.open("xb")
                        break
                    except FileExistsError:
                        stamp_time += timedelta(milliseconds=1)
                with output:
                    output.write(before)
                    output.flush()
                    os.fsync(output.fileno())
                if backup.read_bytes() != before:
                    raise SaveDataError("升级备份回读不一致，存档未覆盖")
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
            if self.path.read_bytes() != payload:
                raise SaveDataError("写后回读不一致，请检查其他运行中的桌宠进程")
            self._expected = payload
        except OSError as error:
            raise SaveDataError(f"存档读写失败，请检查文件；未删除备份与临时文件：{error}") from error
