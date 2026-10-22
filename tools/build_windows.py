"""Build a fresh Windows portable ZIP without copying player data or deleting files."""
from __future__ import annotations

import ast
from datetime import datetime
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import subprocess
import sys
import sysconfig
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def checked_source(root: Path, relative: str) -> Path:
    """Reject links and anything outside the explicitly selected project assets."""
    parts = PurePosixPath(relative).parts
    if not parts or PurePosixPath(relative).is_absolute() or any(p in (".", "..") or ":" in p or "\\" in p for p in parts):
        raise ValueError("Unsafe resource path: " + relative)
    base = root.resolve(strict=True)
    target = base
    for part in parts:
        target /= part
        info = target.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked build resource: " + relative)
    if not target.is_file() or not target.resolve(strict=True).is_relative_to(base):
        raise ValueError("Invalid build resource: " + relative)
    return target


def resource_files(root: Path) -> list[str]:
    """Allow-list only built-in art, current configuration and the theme."""
    tree = ast.parse((root / "illustrated_assets.py").read_text(encoding="utf-8"))
    icons = next(ast.literal_eval(n.value) for n in tree.body
                 if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ICON_IDS" for t in n.targets))
    expression_file = "assets/skins/default/expressions.json"
    expressions = json.loads(checked_source(root, expression_file).read_text(encoding="utf-8"))
    selected = ["assets/icons/tangyuan.ico", "config/catalog.json", "styles/theme.qss", expression_file]
    selected += ["assets/skins/default/" + name for name in dict.fromkeys(expressions["files"].values())]
    selected += ["assets/item_icons/" + icon + ".png" for icon in icons]
    selected += ["assets/sounds/" + name + ".wav" for name in ("poke", "eat", "coin", "music_box", "chime")]
    for relative in selected:
        checked_source(root, relative)
    return sorted(set(selected))


def write_new(file: Path, payload: bytes) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    with file.open("xb") as output:
        output.write(payload)
    if file.read_bytes() != payload:
        raise OSError("Readback failed: " + str(file))


def zip_portable(folder: Path, destination: Path) -> int:
    """A pristine archive must never contain a player's save or imported skin."""
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    for file in files:
        relative = file.relative_to(folder)
        if file.is_symlink() or getattr(file.stat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("Linked output: " + str(relative))
        if any(p.startswith("user_") or p in ("data", "tests", ".git", ".venv", ".env") for p in relative.parts) or file.name == "save_data.json" or ".bak." in file.name:
            raise ValueError("Private/development data in release: " + str(relative))
    with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file in files:
            archive.write(file, (Path(folder.name) / file.relative_to(folder)).as_posix())
    with zipfile.ZipFile(destination) as archive:
        if archive.testzip() is not None or len(archive.infolist()) != len(files):
            raise OSError("ZIP verification failed")
    return len(files)


def main() -> int:
    if sys.platform != "win32" or sysconfig.get_platform() != "win-amd64":
        raise SystemExit("Run with the Windows x64 project Python environment.")
    try:
        packager_version = version("pyinstaller")
    except Exception as error:
        raise SystemExit("Install requirements-build.txt in the project environment first.") from error
    root = ROOT.resolve(strict=True)
    release_root = root / "releases"
    if release_root.exists() and (release_root.is_symlink() or release_root.resolve().parent != root):
        raise SystemExit("Release directory must be inside this project.")
    release_root.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:8]
    session = release_root / ("build-" + stamp)
    session.mkdir(exist_ok=False)
    stage = session / "resources"
    for relative in resource_files(root):
        write_new(stage / relative, checked_source(root, relative).read_bytes())
    output = release_root / ("Q弹汤圆-Windows-x64-" + stamp)
    output.mkdir(exist_ok=False)
    env = dict(os.environ)
    env["PYINSTALLER_CONFIG_DIR"] = str(session / "cache")
    env["TEMP"] = env["TMP"] = str(session / "temp")
    (session / "temp").mkdir()
    command = [sys.executable, "-m", "PyInstaller", "--onedir", "--windowed", "--noupx",
               "--contents-directory", ".", "--version-file", str(root / "tools/windows_version.txt"), "--name", "Q弹汤圆", "--icon", str(root / "assets/icons/tangyuan.ico"),
               "--distpath", str(output), "--workpath", str(session / "work"), "--specpath", str(session),
               "--copy-metadata", "PySide6", "--copy-metadata", "shiboken6"]
    for directory in ("assets", "config", "styles"):
        command += ["--add-data", str(stage / directory) + os.pathsep + directory]
    command += [str(root / "main.py")]
    # All output/cache paths are fresh. Never use --clean or --noconfirm.
    subprocess.run(command, cwd=root, env=env, check=True)
    folder = output / "Q弹汤圆"
    instructions = ("Q弹汤圆 · Windows 64位便携版\n\n"
                    "1. 先把整个ZIP解压到自己常用且可写的文件夹。\n"
                    "2. 双击同文件夹里的 Q弹汤圆.exe，无需安装Python或其他开发环境。\n"
                    "3. 不要只复制EXE，也不要在压缩包里直接运行；其他文件是运行依赖。\n"
                    "4. 关闭小窝只是收起；退出请右键系统托盘选择退出程序。\n"
                    "5. 进度与皮肤存放在系统本地应用数据目录，小窝设置中可查看完整路径。\n"
                    "   更新可解压至新文件夹，进度自动接续；换电脑请用设置中的备份/恢复。\n"
                    "6. 再次双击会唤醒现有小窝与桌宠，不会重复启动；正式版默认隐藏调试。\n\n"
                    "自定义皮肤：换装与小窝装修 → 皮肤衣橱 → 导入本地PNG/GIF。\n"
                    "推荐透明背景、主体居中、最长边256～512像素；PNG单图或循环GIF均可。\n"
                    "单文件不超过20MB；GIF最多200帧、累计6400万源像素。\n"
                    "多状态皮肤用导出模板，替换idle/happy/dizzy/flat图片后导入文件夹或ZIP。\n"
                    "达到Lv.3或50糯米币提前解锁导入。素材仅保存在本机，不会上传。\n")
    write_new(folder / "开始使用.txt", instructions.encode("utf-8-sig"))
    for name in ("LGPL-3.0-only.txt", "GPL-3.0-only.txt"):
        write_new(folder / "licenses" / name, checked_source(root, "tools/licenses/" + name).read_bytes())
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    write_new(folder / "licenses/Python-LICENSE.txt", python_license.read_bytes())
    notices = ("Qt / PySide6 / Shiboken6 6.8.3 are used under LGPL version 3.\n"
               "Copyright (C) The Qt Company Ltd. and contributors.\n"
               "See the accompanying LGPL-3.0-only.txt and GPL-3.0-only.txt.\n"
               "These are unmodified, dynamically linked DLLs; replacing compatible libraries is permitted.\n"
               "Reverse engineering for debugging modifications of these libraries is permitted.\n"
               "Qt source: https://download.qt.io/archive/qt/6.8/6.8.3/submodules/\n"
               "PySide/Shiboken source: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/\n"
               "Qt third-party notices: https://doc.qt.io/qt-6.8/licenses-used-in-qt.html\n"
               "Python license: licenses/Python-LICENSE.txt.\n"
               "PyInstaller's bootloader is distributed with its exception: https://pyinstaller.org/en/stable/license.html\n")
    write_new(folder / "licenses/THIRD_PARTY_NOTICES.txt", notices.encode())
    records = []
    for file in sorted(p for p in folder.rglob("*") if p.is_file()):
        records.append({"path": file.relative_to(folder).as_posix(), "bytes": file.stat().st_size,
                        "sha256": hashlib.sha256(file.read_bytes()).hexdigest()})
    manifest = {"platform": "Windows-x64", "python": platform.python_version(), "pyside6": version("PySide6"),
                "pyinstaller": packager_version, "files": records}
    write_new(folder / "release_manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode())
    archive = release_root / ("Q弹汤圆-Windows-x64-" + stamp + ".zip")
    count = zip_portable(folder, archive)
    result = {"folder": str(folder), "exe": str(folder / "Q弹汤圆.exe"), "zip": str(archive),
              "zip_bytes": archive.stat().st_size, "file_count": count,
              "zip_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}
    write_new(session / "build_result.json", (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode())
    print("PORTABLE_BUILD_OK " + json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
