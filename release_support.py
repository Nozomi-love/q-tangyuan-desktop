"""Local-only release services: single instance IPC and validated portable backups."""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path, PurePosixPath
import stat
from uuid import uuid4
import zipfile

from PySide6.QtCore import QObject, Signal, QStandardPaths
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from models import PetData
from save_manager import SaveDataError, SaveManager, SkinManager, SkinImportError, _reject_constant, _UNSEEN

APP_VERSION = "Q弹汤圆 v2.0 正式版"

def player_paths(resource_root: Path, *, frozen: bool, isolated: bool = False):
    """Resolve paths without touching disk; frozen updates share a stable profile."""
    if frozen and not isolated:
        stable=Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
        return stable/"save_data.json",stable/"skins"
    return Path(resource_root)/"data/save_data.json",None


def timestamp():
    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y%m%d-%H%M%S-%f")[:-3]


class SingleInstance(QObject):
    awakened = Signal()

    def __init__(self, profile: Path, parent=None):
        super().__init__(parent)
        identity = str(Path(profile).resolve()).casefold().encode("utf-8")
        self.name = "QTangyuan-v2-" + hashlib.sha256(identity).hexdigest()[:32]
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self._clients = set()
        self.primary = False

    def acquire(self):
        # Serialize startup on Windows: named pipes permit several listeners
        # with the same name, so listen() alone is not an ownership test.
        if os.name == "nt":
            import ctypes
            kernel=ctypes.WinDLL("kernel32",use_last_error=True)
            kernel.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_bool,ctypes.c_wchar_p]
            kernel.CreateMutexW.restype=ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
            kernel.ReleaseMutex.argtypes=[ctypes.c_void_p];kernel.CloseHandle.argtypes=[ctypes.c_void_p]
            handle=kernel.CreateMutexW(None,False,"Local\\"+self.name+"-startup")
            if not handle: raise RuntimeError("无法取得启动保护，请稍后重试")
            acquired=kernel.WaitForSingleObject(handle,2500)
            if acquired not in (0,0x80):
                kernel.CloseHandle(handle)
                raise RuntimeError("另一个实例正在启动，请稍后重试")
            try: return self._acquire_serialized()
            finally:
                kernel.ReleaseMutex(handle);kernel.CloseHandle(handle)
        return self._acquire_serialized()

    def _acquire_serialized(self):
        if self._notify_existing(): return False
        if self.server.listen(self.name):
            self.primary = True
            return True
        if self._notify_existing(): return False
        raise RuntimeError("已有程序暂时无法响应，请稍候再启动；为保护存档没有另开实例")

    def _notify_existing(self):
        socket=QLocalSocket(self)
        socket.connectToServer(self.name)
        if not socket.waitForConnected(300):
            socket.abort();socket.deleteLater();return False
        socket.write(b"WAKE\n");socket.flush()
        if not socket.waitForBytesWritten(1000) and socket.bytesToWrite():
            raise RuntimeError("唤醒消息未送达，请稍后重试")
        socket.disconnectFromServer();socket.deleteLater()
        return True

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self._clients.add(socket)
            socket.setReadBufferSize(64)
            socket.setProperty("message", b"")
            socket.readyRead.connect(lambda s=socket: self._read(s))
            socket.disconnected.connect(lambda s=socket: self._closed(s))
            self._read(socket)

    def _read(self, socket):
        payload = bytes(socket.property("message") or b"") + bytes(socket.readAll())
        socket.setProperty("message", payload[:64])
        if payload == b"WAKE\n":
            self.awakened.emit(); socket.disconnectFromServer()
        elif len(payload) >= 64 or b"\n" in payload:
            socket.abort()

    def _closed(self, socket):
        self._clients.discard(socket)
        socket.deleteLater()

    def close(self):
        for socket in tuple(self._clients): socket.abort()
        self.server.close()


class BackupManager:
    MAX_TOTAL = 256 * 1024 * 1024
    MAX_ENTRIES = 2048
    MAX_SAVE = 2 * 1024 * 1024

    def __init__(self, saves: SaveManager, skins: SkinManager):
        self.saves, self.skins = saves, skins

    @staticmethod
    def _game(payload):
        if len(payload) > BackupManager.MAX_SAVE:
            raise SaveDataError("备份存档超过2MB")
        raw = json.loads(payload.decode("utf-8-sig"), parse_constant=_reject_constant)
        if not isinstance(raw, dict) or type(raw.get("schema_version", 5)) is not int or raw.get("schema_version", 5) not in (1,2,3,4,5):
            raise SaveDataError("备份存档版本无效")
        PetData.from_dict(raw)
        SaveManager._validate_window(raw.get("window", {}))
        return raw

    def export(self, destination: Path):
        destination = Path(destination).absolute()
        SkinManager._no_links(destination)
        before, raw = self.saves._read()
        if before is None:
            raise SaveDataError("尚无可导出的存档")
        if self.saves._expected is not _UNSEEN and before != self.saves._expected:
            raise SaveDataError("存档已被其他进程修改，未导出过时数据")
        self._game(before)
        files = {"save_data.json": before}
        for entry in self.skins.list_skins()[1:]:
            sid = entry["id"]
            self.skins._metadata(sid, validate=True)
            folder = self.skins.root / sid
            for filename in ("manifest.json", *dict.fromkeys(entry["states"].values())):
                files[f"skins/{sid}/{filename}"] = self.skins._read_file(folder / filename)
        selected = raw.get("selected_skin_id", "default")
        if selected != "default" and f"skins/{selected}/manifest.json" not in files:
            raise SaveDataError("当前皮肤缺失，请先切回默认外观再备份")
        if len(files) + 1 > self.MAX_ENTRIES or sum(map(len,files.values())) > self.MAX_TOTAL:
            raise SaveDataError("备份素材过多，超过256MB或2048文件限制")
        meta={"format": "qtangyuan-backup", "version": 1, "created": timestamp(),
              "sha256": {key: hashlib.sha256(value).hexdigest() for key,value in files.items()}}
        files["backup.json"]=(json.dumps(meta,ensure_ascii=False,indent=2)+"\n").encode("utf-8")
        destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open("xb") as output:
            # Stored media avoids false zip-bomb flags for very compressible PNGs.
            with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_STORED) as archive:
                for name,value in files.items(): archive.writestr(name,value)
            output.flush(); os.fsync(output.fileno())
        checked,_ = self.validate(destination)
        if checked["save_data.json"] != before:
            raise SaveDataError("备份回读不一致")
        return destination

    def validate(self, source: Path):
        payload=SkinManager._read_file(Path(source), self.MAX_TOTAL + 4*1024*1024)
        files={}; total=0
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                entries=archive.infolist()
                if not 2 <= len(entries) <= self.MAX_ENTRIES:
                    raise SaveDataError("备份文件数量无效")
                seen=set()
                for entry in entries:
                    name=SkinManager._relative(entry.orig_filename)
                    mode=entry.external_attr >> 16
                    limit=self.MAX_SAVE if name in ("backup.json","save_data.json") else SkinManager.MAX_FILE_BYTES
                    if (entry.is_dir() or name.casefold() in seen or entry.flag_bits & 1 or stat.S_ISLNK(mode)
                        or stat.S_IFMT(mode) not in (0,stat.S_IFREG) or entry.external_attr & 0x400
                        or entry.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED)
                        or entry.file_size > limit):
                        raise SaveDataError("备份含重复、链接、加密或超限文件")
                    seen.add(name.casefold()); total+=entry.file_size
                    if total > self.MAX_TOTAL or (entry.file_size > 1024*1024 and entry.file_size > max(1,entry.compress_size)*200):
                        raise SaveDataError("备份解压量或压缩率异常")
                    if name not in ("backup.json","save_data.json"):
                        parts=PurePosixPath(name).parts
                        if len(parts)<3 or parts[0]!="skins" or not SkinManager.ID_PATTERN.fullmatch(parts[1]):
                            raise SaveDataError("备份包含非存档或非皮肤文件")
                    files[name]=archive.read(entry)
            meta=json.loads(files["backup.json"].decode("utf-8"),parse_constant=_reject_constant)
            if not isinstance(meta,dict): raise SaveDataError("备份索引须为对象")
            hashes=meta.get("sha256")
            if (meta.get("format")!="qtangyuan-backup" or type(meta.get("version")) is not int or meta["version"]!=1
                    or not isinstance(hashes,dict) or set(hashes)!=set(files)-{"backup.json"}):
                raise SaveDataError("备份索引无效")
            if any(hashlib.sha256(files[name]).hexdigest()!=digest for name,digest in hashes.items()):
                raise SaveDataError("备份校验失败：文件已损坏或被修改")
            raw=self._game(files["save_data.json"])
            expected={"backup.json","save_data.json"}
            ids={PurePosixPath(name).parts[1] for name in files if name.startswith("skins/")}
            for sid in ids:
                prefix=f"skins/{sid}/"
                manifest=SkinManager._manifest(files[prefix+"manifest.json"])
                expected.add(prefix+"manifest.json")
                media_names=set(manifest["states"].values())
                if sum(len(files[prefix+n]) for n in media_names)>SkinManager.MAX_TOTAL_BYTES:
                    raise SaveDataError("单个皮肤素材超过64MB")
                for name in media_names:
                    expected.add(prefix+name)
                    SkinManager._validate_media(files[prefix+name],PurePosixPath(name).suffix.lower())
            if expected!=set(files): raise SaveDataError("备份包含未引用的额外文件")
            selected=raw.get("selected_skin_id","default")
            if selected!="default" and selected not in ids:
                raise SaveDataError("备份缺少当前皮肤")
            return files,raw
        except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,RuntimeError) as error:
            if isinstance(error,SaveDataError): raise
            raise SaveDataError("备份未通过安全校验："+str(error)) from error

    def restore(self, source: Path):
        files,raw=self.validate(source)
        SkinManager._no_links(self.saves.path)
        before,_=self.saves._read()
        if self.saves._expected is not _UNSEEN and before!=self.saves._expected:
            raise SaveDataError("存档被其他进程修改，本次恢复已停止")
        rollback=None
        if before is not None:
            rollback=self.export(self.saves.path.parent/"backups"/("恢复前-"+timestamp()+"-"+uuid4().hex[:6]+".zip"))
        mapping={}
        ids=sorted({PurePosixPath(n).parts[1] for n in files if n.startswith("skins/")})
        self.skins._guard_root()
        for sid in ids:
            prefix=f"skins/{sid}/"
            content={n[len(prefix):]:v for n,v in files.items() if n.startswith(prefix)}
            target=self.skins.root/sid
            if target.exists():
                self.skins._no_links(target)
                identical=all((target/n).is_file() and self.skins._read_file(target/n)==v for n,v in content.items())
                if identical: continue
                mapped="user_"+uuid4().hex; mapping[sid]=mapped; target=self.skins.root/mapped
            target.mkdir(exist_ok=False)
            for name,value in sorted(content.items(),key=lambda row:row[0]=="manifest.json"):
                dest=target.joinpath(*PurePosixPath(name).parts)
                dest.parent.mkdir(parents=True,exist_ok=True)
                self.skins._write_new(dest,value)
        state=PetData.from_dict(raw)
        state.selected_skin_id=mapping.get(state.selected_skin_id,state.selected_skin_id)
        state.skin_configs={mapping.get(k,k):v for k,v in state.skin_configs.items()}
        state.archived_skins=[mapping.get(k,k) for k in state.archived_skins]
        restored=deepcopy(raw); restored.update(state.to_dict()); restored["schema_version"]=5
        payload=(json.dumps(restored,ensure_ascii=False,indent=2,allow_nan=False)+"\n").encode("utf-8")
        self.saves.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.saves.path.with_name("restore_"+uuid4().hex+".tmp")
        SkinManager._no_links(temporary)
        with temporary.open("xb") as output:
            output.write(payload); output.flush(); os.fsync(output.fileno())
        current,_=self.saves._read()
        if current!=before: raise SaveDataError("恢复前存档发生变化，原存档保留")
        os.replace(temporary,self.saves.path)
        if self.saves.path.read_bytes()!=payload: raise SaveDataError("恢复写后回读失败，恢复前备份保留")
        self.saves._expected=payload
        return state,SaveManager._validate_window(restored.get("window",{})),rollback
