"""Verify the distributable ZIP in a new location with Python removed from PATH."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, required=True)
    args = parser.parse_args()
    art = ROOT / "tests/artifacts" / datetime.now().strftime("distribution-native-%Y%m%d-%H%M%S-%f")
    art.mkdir(parents=True, exist_ok=False)
    destination = art / "换个目录运行"
    destination.mkdir()
    with zipfile.ZipFile(args.zip) as archive:
        assert archive.testzip() is None
        for entry in archive.infolist():
            name = PurePosixPath(entry.filename)
            assert not name.is_absolute() and all(p not in ("..", ".") and ":" not in p for p in name.parts)
            target = destination.joinpath(*name.parts)
            assert target.resolve().is_relative_to(destination.resolve())
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                output.write(archive.read(entry))
    folder = destination / "Q弹汤圆"
    exe = folder / "Q弹汤圆.exe"
    manifest = json.loads((folder / "release_manifest.json").read_text(encoding="utf-8"))
    expected = {item["path"] for item in manifest["files"]} | {"release_manifest.json"}
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    assert actual == expected
    for item in manifest["files"]:
        file = folder / item["path"]
        assert file.stat().st_size == item["bytes"]
        assert hashlib.sha256(file.read_bytes()).hexdigest() == item["sha256"]
    assert not (folder / "data").exists()
    assert not list((folder / "assets/skins").glob("user_*"))
    assert (folder / "assets/icons/tangyuan.ico").read_bytes() == (ROOT / "assets/icons/tangyuan.ico").read_bytes()

    # Compare Windows EXE's actual icon resource bytes to the desktop ICO.
    import pefile
    pe = pefile.PE(str(exe))
    assert pe.VS_FIXEDFILEINFO[0].FileVersionMS == (1 << 16)
    assert pe.VS_FIXEDFILEINFO[0].FileVersionLS == 0
    icons = set()
    groups = 0
    for resource_type in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if resource_type.id == 14:
            groups += len(resource_type.directory.entries)
        if resource_type.id == 3:
            for image in resource_type.directory.entries:
                for language in image.directory.entries:
                    info = language.data.struct
                    icons.add(pe.get_data(info.OffsetToData, info.Size))
    ico = (ROOT / "assets/icons/tangyuan.ico").read_bytes()
    count = struct.unpack_from("<H", ico, 4)[0]
    originals = set()
    for index in range(count):
        size, offset = struct.unpack_from("<II", ico, 6 + index * 16 + 8)
        originals.add(ico[offset:offset + size])
    assert groups > 0 and originals == icons

    system = Path(os.environ.get("SystemRoot", "C:/Windows"))
    (art / "temp").mkdir()
    env = {"SystemRoot": str(system), "WINDIR": str(system), "PATH": str(system / "System32"),
           "TEMP": str(art / "temp"), "TMP": str(art / "temp"), "QT_QPA_PLATFORM": "windows"}
    outcomes = []
    for name, program, arguments, frozen, resource_root in (
        ("source-normal", Path(sys.executable), [str(ROOT / "main.py")], False, ROOT),
        ("source-demo-dev", Path(sys.executable), [str(ROOT / "main.py"), "--demo", "--dev-mode"], False, ROOT),
        ("exe-normal", exe, [], True, folder),
        ("exe-demo-dev", exe, ["--demo", "--dev-mode"], True, folder),
    ):
        report = art / (name + ".json")
        result = subprocess.run([str(program), *arguments, "--smoke-test", "--smoke-report", str(report)],
                                cwd=destination, env=env, capture_output=True, timeout=45)
        assert result.returncode == 0, (name, result.returncode, result.stderr.decode(errors="replace"))
        assert not result.stderr, (name, result.stderr.decode(errors="replace"))
        state = json.loads(report.read_text(encoding="utf-8"))
        assert state["version"] == "Q弹汤圆 v1.0 正式版"
        assert state["debug_menu_visible"] == ("demo-dev" in name)
        assert state["frozen"] is frozen
        assert Path(state["resource_root"]).resolve() == resource_root.resolve()
        assert state["windows_identity_configured"] and state["windows_app_id"] == "Nozomi.QTangyuan.Desktop"
        assert Path(state["application_icon"]).read_bytes() == ico
        assert state["home_visible"] and state["home_scene"]
        assert set(state["loaded_png_states"]) == {"idle", "happy", "dizzy", "flat"}
        assert state["growth"]["coins"] == 100
        # Accelerated mode legitimately consumes hunger during the two-second smoke.
        if "demo-dev" in name:
            assert 78 <= state["growth"]["hunger"] <= 80
        else:
            assert state["growth"]["hunger"] == 80
        outcomes.append({"mode": name, "code": result.returncode, "frames": state["frames"],
                         "frozen": state["frozen"], "application_id": state["windows_app_id"]})
    assert not (folder / "data/save_data.json").exists()
    record = {"zip": str(args.zip.resolve()), "verified_files": len(actual), "icon_resources": len(icons),
              "python_on_path": False, "outcomes": outcomes, "artifact_directory": str(art)}
    with (art / "result.json").open("x", encoding="utf-8") as output:
        json.dump(record, output, ensure_ascii=False, indent=2)
    print("DISTRIBUTION_NATIVE_OK " + json.dumps(record, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
