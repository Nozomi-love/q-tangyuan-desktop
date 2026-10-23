"""Versioned JSON saves with atomic writes, migration backup and stale-writer guards."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
import stat
from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4
import zipfile
from pathlib import Path
import time

from models import PetData, TEAM_SKIN_IDS


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
            if type(version) is not int or version not in (1, 2, 3, 4, 5):
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
            # Furniture, pet name, overlay and mute preferences are additive version-5
            # fields; merge retains older layouts and unrelated future metadata.
            data = self._merge(data, game)
            # An expired/replaced Buff must not be resurrected by recursive merge.
            data["active_buff"] = deepcopy(game["active_buff"])
        data["schema_version"] = 5 if game is not None else old_version
        payload = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if before == payload:
            self._expected = before
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if before is not None and old_version < 5 and game is not None:
                # Back up the player's old save before its first upgrade.
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


class SkinImportError(RuntimeError):
    """Untrusted media is rejected without replacing existing user assets."""


class SkinManager:
    """Copy validated local media into UUID directories; never extract ZIP paths.

    The manifest is committed last, so interrupted copies cannot appear in the
    wardrobe. Invalid/incomplete directories are retained for inspection.
    """

    MAX_FILE_BYTES = 20 * 1024 * 1024
    MAX_TOTAL_BYTES = 64 * 1024 * 1024
    MAX_MANIFEST_BYTES = 64 * 1024
    MAX_ENTRIES = 64
    MAX_FRAMES = 200
    MAX_EDGE = 8192
    MAX_PIXELS = 16_000_000
    MAX_ANIMATED_PIXELS = 64_000_000
    TEXTURE_EDGE = 512
    STATES = ("idle", "happy", "dizzy", "flat")
    ID_PATTERN = re.compile(r"user_[0-9a-f]{32}\Z")

    def __init__(self, skins_root: Path, builtin_root: Path | None = None) -> None:
        self.root = Path(skins_root).absolute()
        self.builtin_root = Path(builtin_root).absolute() if builtin_root is not None else None
        if self.builtin_root is not None:
            self._no_links(self.builtin_root)
        self._no_links(self.root)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._resolved_root = self.root.resolve(strict=True)
        except OSError as error:
            raise SkinImportError(f"无法访问皮肤沙箱：{error}") from error
        self._guard_root()
        self._preview_request = False
        self._previews = {}

    @staticmethod
    def _no_links(path: Path) -> None:
        """Reject POSIX links and Windows junction/reparse components."""
        absolute = Path(path).absolute()
        for component in (absolute, *absolute.parents):
            try:
                info = component.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
                raise SkinImportError("不支持符号链接、目录联接或重解析点")

    def _guard_root(self) -> None:
        self._no_links(self.root)
        if self.root.resolve(strict=True) != self._resolved_root:
            raise SkinImportError("皮肤沙箱位置发生变化，请重新启动")

    @staticmethod
    def _relative(value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 240:
            raise SkinImportError("皮肤文件名必须是有效相对路径")
        if "\\" in value or ":" in value or "\x00" in value or value.startswith("/"):
            raise SkinImportError("皮肤包路径不能指向外部位置")
        parts = value.split("/")
        if len(parts) > 8 or any(not p or p in (".", "..") or p.rstrip(" .") != p for p in parts):
            raise SkinImportError("皮肤包包含不安全的路径")
        reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
        if any(p.split(".")[0].upper() in reserved for p in parts):
            raise SkinImportError("皮肤包包含系统保留文件名")
        return PurePosixPath(*parts).as_posix()

    @classmethod
    def _read_file(cls, source: Path, limit: int | None = None) -> bytes:
        cls._no_links(source)
        limit = cls.MAX_FILE_BYTES if limit is None else limit
        try:
            info = source.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise SkinImportError(f"文件必须是普通文件且不超过 {limit // 1024} KB")
            with source.open("rb") as stream:
                payload = stream.read(limit + 1)
            if len(payload) > limit or len(payload) != info.st_size:
                raise SkinImportError("文件过大或在读取时发生变化，请重试")
            cls._no_links(source)
            return payload
        except OSError as error:
            raise SkinImportError(f"无法读取本地文件：{error}") from error

    @classmethod
    def _manifest(cls, payload: bytes) -> dict:
        if len(payload) > cls.MAX_MANIFEST_BYTES:
            raise SkinImportError("manifest.json 不得超过 64 KB")
        try:
            source = json.loads(payload.decode("utf-8-sig"), parse_constant=_reject_constant)
            if not isinstance(source, dict):
                raise ValueError("配置根节点必须是对象")
            if type(source.get("schema_version", 1)) is not int or source.get("schema_version", 1) != 1:
                raise ValueError("不支持的皮肤包版本")
            name, author = source.get("name", "我的桌宠"), source.get("author", "本地用户")
            if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
                raise ValueError("名称须为 1～80 字符")
            if not isinstance(author, str) or len(author) > 80:
                raise ValueError("作者须在 80 字符以内")
            if any(ord(c) < 32 for c in name + author):
                raise ValueError("名称或作者包含控制字符")
            remove_white = source.get("remove_white_background", False)
            if type(remove_white) is not bool:
                raise ValueError("白底处理开关必须是布尔值")
            states = source.get("states", source.get("files"))
            if not isinstance(states, dict) or "idle" not in states or not set(states).issubset(cls.STATES):
                raise ValueError("states 须包含 idle，其他状态仅支持 happy/dizzy/flat")
            clean = {}
            for state, filename in states.items():
                filename = cls._relative(filename)
                if PurePosixPath(filename).suffix.lower() not in (".png", ".gif"):
                    raise ValueError("状态贴图仅支持 PNG 或 GIF")
                clean[state] = filename
            return {"schema_version": 1, "name": name.strip(), "author": author.strip(),
                    "remove_white_background": remove_white, "states": clean}
        except (UnicodeError, ValueError, TypeError) as error:
            raise SkinImportError(f"皮肤配置无效：{error}") from error

    @classmethod
    def _gif_structure(cls, payload: bytes) -> tuple[int, int, int]:
        """Check logical canvas and block boundaries before Qt's tolerant decoder."""
        if len(payload) < 14 or payload[:6] not in (b"GIF87a", b"GIF89a"):
            raise SkinImportError("GIF 头部不完整")
        width = int.from_bytes(payload[6:8], "little")
        height = int.from_bytes(payload[8:10], "little")
        pixels = width * height
        if not width or not height or max(width, height) > cls.MAX_EDGE or pixels > cls.MAX_PIXELS:
            raise SkinImportError("图片源尺寸过大；最长边须≤8192，像素总数须≤1600万")
        offset = 13
        packed = payload[10]
        if packed & 0x80:
            offset += 3 * (1 << ((packed & 7) + 1))
        frames = 0

        def skip_blocks(position: int) -> int:
            while position < len(payload):
                count = payload[position]
                position += 1
                if not count:
                    return position
                position += count
                if position > len(payload):
                    break
            raise SkinImportError("GIF 数据块被截断")

        while offset < len(payload):
            kind = payload[offset]
            offset += 1
            if kind == 0x3B:
                if not frames or offset != len(payload):
                    raise SkinImportError("GIF 结束标记或帧数无效")
                return width, height, frames
            if kind == 0x21:
                if offset >= len(payload):
                    raise SkinImportError("GIF 扩展块不完整")
                offset = skip_blocks(offset + 1)
                continue
            if kind != 0x2C or offset + 9 > len(payload):
                raise SkinImportError("GIF 图像描述块无效")
            left, top, frame_w, frame_h = (int.from_bytes(payload[offset+i:offset+i+2], "little") for i in (0, 2, 4, 6))
            flags = payload[offset + 8]
            offset += 9
            if not frame_w or not frame_h or left + frame_w > width or top + frame_h > height:
                raise SkinImportError("GIF 帧超出逻辑画布")
            if flags & 0x80:
                offset += 3 * (1 << ((flags & 7) + 1))
            if offset >= len(payload) or not 2 <= payload[offset] <= 8:
                raise SkinImportError("GIF 图像编码块无效")
            offset = skip_blocks(offset + 1)
            frames += 1
            if frames > cls.MAX_FRAMES or frames * pixels > cls.MAX_ANIMATED_PIXELS:
                raise SkinImportError("GIF 过长或解码量过大；最多200帧、累计6400万像素")
        raise SkinImportError("GIF 缺少结束标记或数据被截断")

    @classmethod
    def _validate_media(cls, payload: bytes, extension: str) -> None:
        """Bound source decoding as well as scaled runtime textures."""
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
        from PySide6.QtGui import QImage, QImageReader

        if not payload or len(payload) > cls.MAX_FILE_BYTES:
            raise SkinImportError("图片/GIF 必须在 20 MB 以内且不能为空")
        buffer = QBuffer()
        buffer.setData(QByteArray(payload))
        buffer.open(QIODevice.OpenModeFlag.ReadOnly)
        reader = QImageReader(buffer)
        expected = extension.lstrip(".").lower().encode("ascii")
        logical = cls._gif_structure(payload) if expected == b"gif" else None
        if expected not in (b"png", b"gif") or not reader.canRead() or bytes(reader.format()).lower() != expected:
            raise SkinImportError("图片内容与 PNG/GIF 扩展名不符或文件损坏")
        size = reader.size()
        pixels = logical[0] * logical[1] if logical else size.width() * size.height()
        if not size.isValid() or size.isEmpty() or max(size.width(), size.height()) > cls.MAX_EDGE or pixels > cls.MAX_PIXELS:
            raise SkinImportError("图片源尺寸过大；最长边须≤8192，像素总数须≤1600万")
        count = logical[2] if logical else max(1, reader.imageCount())
        if count > cls.MAX_FRAMES or count * pixels > cls.MAX_ANIMATED_PIXELS:
            raise SkinImportError("GIF 过长或解码量过大；最多200帧、累计6400万像素")
        source_size = QSize(logical[0], logical[1]) if logical else size
        scaled = source_size.scaled(QSize(cls.TEXTURE_EDGE, cls.TEXTURE_EDGE), Qt.AspectRatioMode.KeepAspectRatio)
        scaled.setWidth(max(1, scaled.width()))
        scaled.setHeight(max(1, scaled.height()))
        reader.setScaledSize(scaled)
        frames = 0
        visible = False
        while reader.canRead():
            frame_size = reader.size()
            if frame_size.isValid() and (max(frame_size.width(), frame_size.height()) > cls.MAX_EDGE or frame_size.width() * frame_size.height() > cls.MAX_PIXELS):
                raise SkinImportError("GIF 帧尺寸超出限制")
            frames += 1
            if frames > cls.MAX_FRAMES or frames * pixels > cls.MAX_ANIMATED_PIXELS:
                raise SkinImportError("GIF 解码预算超出限制")
            image = reader.read()
            if image.isNull():
                raise SkinImportError(f"无法完整解码图片/GIF：{reader.errorString()}")
            if not visible:
                if not image.hasAlphaChannel():
                    visible = True
                else:
                    # Keep the QImage alive while its borrowed pixel buffer is read.
                    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
                    alpha = bytes(rgba.constBits())[3::4]
                    visible = any(value > 12 for value in alpha)
            if expected == b"png":
                break
        if not visible:
            raise SkinImportError("图片/GIF 全透明或可见度过低，请选择可见的素材")
        if frames != count:
            raise SkinImportError("GIF 帧数据不完整或帧数无效")

    def _commit(self, manifest: dict, media: dict[str, bytes]) -> dict:
        self._guard_root()
        total = sum(len(data) for data in media.values())
        if total > self.MAX_TOTAL_BYTES:
            raise SkinImportError("皮肤包素材总大小不得超过64 MB")
        for name, payload in media.items():
            self._validate_media(payload, PurePosixPath(name).suffix.lower())
        normalized = deepcopy(manifest)
        names = {name: f"media_{index}{PurePosixPath(name).suffix.lower()}" for index, name in enumerate(media)}
        normalized["states"] = {state: names[name] for state, name in manifest["states"].items()}
        skin_id = (".preview_" if self._preview_request else "user_") + uuid4().hex
        destination = self.root / skin_id
        try:
            destination.mkdir(exist_ok=False)
            for original, payload in media.items():
                self._write_new(destination / names[original], payload)
            # A canonical manifest is the final success marker.
            payload = (json.dumps(normalized, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            self._write_new(destination / "manifest.json", payload)
        except OSError as error:
            raise SkinImportError(f"皮肤复制失败，原文件与已有皮肤均保留：{error}") from error
        if self._preview_request:
            self._previews[skin_id] = (deepcopy(manifest), deepcopy(media))
        return {"id": skin_id, "directory": str(destination), **normalized}

    def _write_new(self, target: Path, payload: bytes) -> None:
        self._guard_root()
        self._no_links(target.parent)
        if not target.parent.resolve(strict=True).is_relative_to(self._resolved_root):
            raise SkinImportError("拒绝写入皮肤沙箱外部")
        with target.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if target.read_bytes() != payload:
            raise SkinImportError("皮肤复制回读不一致")

    def import_image(self, source: Path, remove_white: bool = False) -> dict:
        source = Path(source)
        if type(remove_white) is not bool:
            raise SkinImportError("白底处理开关必须是布尔值")
        extension = source.suffix.lower()
        if extension not in (".png", ".gif"):
            raise SkinImportError("仅支持本地 PNG 和 GIF")
        payload = self._read_file(source)
        manifest = {"schema_version": 1, "name": source.stem[:80] or "我的桌宠", "author": "本地用户",
                    "remove_white_background": remove_white, "states": {"idle": "image" + extension}}
        return self._commit(self._manifest(json.dumps(manifest).encode()), {"image" + extension: payload})

    def import_pack(self, source: Path) -> dict:
        source = Path(source)
        self._no_links(source)
        if source.is_dir():
            manifest = self._manifest(self._read_file(source / "manifest.json", self.MAX_MANIFEST_BYTES))
            root = source.resolve(strict=True)
            media = {}
            for filename in dict.fromkeys(manifest["states"].values()):
                target = source.joinpath(*PurePosixPath(filename).parts)
                self._no_links(target)
                if not target.resolve().is_relative_to(root):
                    raise SkinImportError("皮肤贴图路径超出包目录")
                media[filename] = self._read_file(target)
            return self._commit(manifest, media)
        if source.suffix.lower() != ".zip":
            raise SkinImportError("请选择皮肤包文件夹或 ZIP 文件")
        payload = self._read_file(source)
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                entries = archive.infolist()
                if not entries or len(entries) > self.MAX_ENTRIES:
                    raise SkinImportError("ZIP 文件条目须在1～64个以内")
                total, seen = 0, set()
                for entry in entries:
                    name = self._relative(entry.orig_filename.rstrip("/"))
                    folded = name.casefold()
                    if folded in seen:
                        raise SkinImportError("ZIP 含重复或大小写冲突的文件名")
                    seen.add(folded)
                    mode = entry.external_attr >> 16
                    if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)) or entry.external_attr & 0x400:
                        raise SkinImportError("ZIP 不允许链接、特殊文件或重解析点")
                    if entry.flag_bits & 1:
                        raise SkinImportError("不支持加密 ZIP")
                    if entry.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                        raise SkinImportError("ZIP 仅支持普通存储或 Deflate 压缩，请重新打包")
                    total += entry.file_size
                    if entry.file_size > self.MAX_FILE_BYTES or total > self.MAX_TOTAL_BYTES:
                        raise SkinImportError("ZIP 单文件超过20 MB或解压总量超过64 MB")
                    if entry.file_size > 1024 * 1024 and entry.file_size > max(1, entry.compress_size) * 200:
                        raise SkinImportError("ZIP 压缩率异常，拒绝疑似压缩炸弹")
                manifests = [e for e in entries if not e.is_dir() and PurePosixPath(e.filename).name == "manifest.json"]
                if len(manifests) != 1:
                    raise SkinImportError("ZIP 须恰好包含一个 manifest.json")
                manifest_entry = manifests[0]
                if manifest_entry.file_size > self.MAX_MANIFEST_BYTES:
                    raise SkinImportError("manifest.json 不得超过64 KB")
                manifest = self._manifest(archive.read(manifest_entry))
                prefix = PurePosixPath(manifest_entry.filename).parent
                lookup = {entry.filename: entry for entry in entries if not entry.is_dir()}
                media = {}
                for filename in dict.fromkeys(manifest["states"].values()):
                    entry = lookup.get((prefix / filename).as_posix())
                    if entry is None:
                        raise SkinImportError(f"ZIP 缺少状态贴图：{filename}")
                    media[filename] = archive.read(entry)
            return self._commit(manifest, media)
        except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as error:
            if isinstance(error, SkinImportError):
                raise
            raise SkinImportError(f"无法安全读取皮肤ZIP：{error}") from error

    def _metadata(self, skin_id: str, validate: bool = False) -> dict:
        if not isinstance(skin_id, str) or self.ID_PATTERN.fullmatch(skin_id) is None:
            raise SkinImportError("皮肤 ID 无效")
        self._guard_root()
        directory = self.root / skin_id
        self._no_links(directory)
        if not directory.resolve(strict=True).is_relative_to(self._resolved_root):
            raise SkinImportError("皮肤路径超出沙箱")
        manifest = self._manifest(self._read_file(directory / "manifest.json", self.MAX_MANIFEST_BYTES))
        for filename in dict.fromkeys(manifest["states"].values()):
            target = directory.joinpath(*PurePosixPath(filename).parts)
            self._no_links(target)
            info = target.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_size > self.MAX_FILE_BYTES:
                raise SkinImportError("沙箱素材类型或文件大小无效")
            if validate:
                self._validate_media(self._read_file(target), PurePosixPath(filename).suffix.lower())
        return {"id": skin_id, "directory": str(directory), **manifest}

    def prepare_preview(self, source: Path, *, pack=False, remove_white=False) -> dict:
        self._preview_request = True
        try:
            return self.import_pack(source) if pack else self.import_image(source, remove_white)
        finally:
            self._preview_request = False

    def commit_preview(self, preview_id: str) -> dict:
        if preview_id not in self._previews:
            raise SkinImportError("预览已失效，请重新选择素材")
        manifest, media = self._previews[preview_id]
        result = self._commit(manifest, media)
        self._previews.pop(preview_id)
        return result

    def cancel_preview(self, preview_id: str) -> None:
        self._previews.pop(preview_id, None)

    def rename(self, skin_id: str, name: str) -> dict:
        metadata = self._metadata(skin_id, validate=True)
        metadata["name"] = name
        manifest = self._manifest(json.dumps(metadata, ensure_ascii=False).encode("utf-8"))
        target = self.root / skin_id / "manifest.json"
        before = self._read_file(target, self.MAX_MANIFEST_BYTES)
        stamp_time = datetime.now(timezone(timedelta(hours=8)))
        while True:
            stamp = stamp_time.strftime("%Y%m%d-%H%M%S-%f")[:-3]
            backup = target.with_name(target.name + ".bak." + stamp)
            try:
                self._write_new(backup, before)
                break
            except FileExistsError:
                stamp_time += timedelta(milliseconds=1)
        payload = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        temporary = target.with_name("rename_" + uuid4().hex + ".tmp")
        self._write_new(temporary, payload)
        self._guard_root()
        self._no_links(target)
        if target.read_bytes() != before:
            raise SkinImportError("名称被其他进程修改，本次未覆盖")
        os.replace(temporary, target)
        if target.read_bytes() != payload:
            raise SkinImportError("名称写后回读失败")
        return self._metadata(skin_id)

    def list_skins(self) -> list[dict]:
        result = [{"id": "default", "name": "白汤圆", "author": "内置默认皮肤", "states": {}}]
        self._guard_root()
        if self.builtin_root is not None:
            for skin_id in sorted(TEAM_SKIN_IDS):
                try:
                    result.append(self.builtin_metadata(skin_id))
                except (SkinImportError, OSError):
                    continue
        for directory in sorted(self.root.iterdir(), key=lambda p: p.name):
            if self.ID_PATTERN.fullmatch(directory.name):
                try:
                    result.append(self._metadata(directory.name))
                except (SkinImportError, OSError):
                    continue
        return result

    def builtin_metadata(self, skin_id: str, *, validate: bool = False) -> dict:
        if self.builtin_root is None or skin_id not in TEAM_SKIN_IDS:
            raise SkinImportError("内置战队皮肤不存在")
        self._no_links(self.builtin_root)
        directory = self.builtin_root / skin_id
        self._no_links(directory)
        if not directory.resolve(strict=True).is_relative_to(self.builtin_root.resolve(strict=True)):
            raise SkinImportError("战队皮肤路径无效")
        manifest = self._manifest(self._read_file(directory / "manifest.json", self.MAX_MANIFEST_BYTES))
        for filename in dict.fromkeys(manifest["states"].values()):
            target = directory / filename
            if not target.resolve(strict=True).is_relative_to(directory.resolve(strict=True)):
                raise SkinImportError("战队贴图路径越界")
            payload = self._read_file(target)
            if validate:
                self._validate_media(payload, PurePosixPath(filename).suffix.lower())
        return {"id": skin_id, "directory": str(directory), "builtin": True, **manifest}

    def resolve(self, skin_id: str) -> Path:
        if skin_id in TEAM_SKIN_IDS:
            try:
                return Path(self.builtin_metadata(skin_id, validate=True)["directory"])
            except (SkinImportError, OSError, TypeError):
                pass
        if skin_id != "default":
            try:
                self._metadata(skin_id, validate=True)
                return self.root / skin_id
            except (SkinImportError, OSError, TypeError):
                pass
        self._guard_root()
        default = self.root / "default"
        self._no_links(default)
        return default

    def export_template(self, destination: Path) -> Path:
        """Create a new complete, importable example; never overwrite a folder."""
        from PySide6.QtGui import QColor, QImage, QPainter, QPen
        from PySide6.QtCore import Qt

        destination = Path(destination).absolute()
        self._no_links(destination)
        if destination.exists():
            raise SkinImportError("模板目录已存在，请选择一个新的目录名称")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._no_links(destination.parent)
        destination.mkdir(exist_ok=False)
        manifest = {"schema_version": 1, "name": "我的多状态桌宠", "author": "请填写作者",
                    "remove_white_background": False, "states": {state: f"{state}.png" for state in self.STATES}}
        colors = {"idle": "#fff9ed", "happy": "#ffd9e3", "dizzy": "#e3ddff", "flat": "#e9f3d7"}
        try:
            for state, color in colors.items():
                image = QImage(160, 160, QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                painter.setBrush(QColor(color))
                painter.setPen(QPen(QColor("#a08374"), 3))
                painter.drawEllipse(15, 15, 130, 130)
                painter.end()
                # QImage saves through a Qt memory buffer, then a create-only file.
                from PySide6.QtCore import QBuffer, QByteArray, QIODevice
                encoded = QByteArray()
                device = QBuffer(encoded)
                device.open(QIODevice.OpenModeFlag.WriteOnly)
                if not image.save(device, "PNG"):
                    raise SkinImportError("模板图片编码失败")
                expected_image = bytes(encoded)
                with (destination / f"{state}.png").open("xb") as output:
                    output.write(expected_image)
                if (destination / f"{state}.png").read_bytes() != expected_image:
                    raise SkinImportError("模板图片写后回读失败")
            text = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            with (destination / "manifest.json").open("xb") as output:
                output.write(text)
            instructions = "皮肤包模板\n将四张示例PNG替换为您有权使用的PNG/GIF，并在manifest.json修改文件名。\nidle必填，其余状态可省略；所有路径须为包内相对路径，禁止..或绝对路径。\n单文件20MB以内；GIF最多200帧、累计6400万源像素。运行纹理最长边512px。\n可直接导入本文件夹，或将文件夹打包ZIP后导入。素材不会上传服务器。\n"
            with (destination / "README.txt").open("x", encoding="utf-8", newline="") as output:
                output.write(instructions)
            if (destination / "README.txt").read_text(encoding="utf-8") != instructions:
                raise SkinImportError("模板说明写后回读失败")
            if (destination / "manifest.json").read_bytes() != text:
                raise SkinImportError("模板写后回读失败")
            return destination
        except OSError as error:
            raise SkinImportError(f"模板导出失败，已有文件保留：{error}") from error
