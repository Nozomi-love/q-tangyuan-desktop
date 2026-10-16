"""Secure local skin imports and cross-process persisted selection (no cleanup)."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import struct
import subprocess
import sys
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from models import PetData
from save_manager import SaveDataError, SaveManager, SkinImportError, SkinManager

APP = QApplication.instance() or QApplication(["phase4-skin-tests"])
ARTIFACTS = ROOT / "tests/artifacts" / datetime.now().strftime("phase4-skins-%Y%m%d-%H%M%S-%f")
ARTIFACTS.mkdir(parents=True, exist_ok=False)


def gif_bytes(frames=2, width=1, height=1):
    header = b"GIF89a" + struct.pack("<HH", width, height) + b"\x80\x00\x00\x00\x00\x00\xff\xff\xff"
    loop = b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    result = header + loop
    for index in range(frames):
        result += b"\x21\xf9\x04\x00\x08\x00\x00\x00"
        result += b"\x2c\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02"
        result += b"\x44\x01\x00" if index % 2 == 0 else b"\x4c\x01\x00"
    return result + b"\x3b"


class SkinImportTests(unittest.TestCase):
    def setUp(self):
        self.work = ARTIFACTS / (self._testMethodName + "-" + uuid4().hex)
        self.work.mkdir()
        self.skins = self.work / "skins"
        self.manager = SkinManager(self.skins)
        (self.skins / "default").mkdir()

    def png(self, name="pet.png", size=(40, 32)):
        target = self.work / name
        image = QImage(*size, QImage.Format.Format_ARGB32)
        image.fill(QColor("#fff9ed"))
        self.assertTrue(image.save(str(target), "PNG"))
        return target

    def gif(self, frames=2):
        target = self.work / ("animated-" + uuid4().hex + ".gif")
        target.write_bytes(gif_bytes(frames))
        return target

    def folder(self, states=None, **extra):
        source = self.work / ("pack-" + uuid4().hex)
        source.mkdir()
        png = self.png("sample-" + uuid4().hex + ".png")
        (source / "idle.png").write_bytes(png.read_bytes())
        manifest = {"name": "测试桌宠", "author": "本地作者", "states": states or {"idle": "idle.png"}, **extra}
        (source / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return source

    def zipped(self, entries):
        target = self.work / (uuid4().hex + ".zip")
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for name, payload in entries:
                info = zipfile.ZipInfo("safe.txt")
                info.filename = name
                archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED)
        return target

    def test_png_is_copied_create_only_and_original_bytes_preserved(self):
        source = self.png()
        original = source.read_bytes()
        metadata = self.manager.import_image(source, remove_white=True)
        self.assertRegex(metadata["id"], r"^user_[0-9a-f]{32}$")
        self.assertTrue(metadata["remove_white_background"])
        folder = self.manager.resolve(metadata["id"])
        self.assertEqual((folder / metadata["states"]["idle"]).read_bytes(), original)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(len(self.manager.list_skins()), 2)

    def test_gif_frames_are_kept_animated(self):
        source = self.gif()
        metadata = self.manager.import_image(source)
        self.assertTrue(metadata["states"]["idle"].endswith(".gif"))
        self.assertEqual((self.manager.resolve(metadata["id"]) / metadata["states"]["idle"]).read_bytes(), source.read_bytes())

    def test_repeated_imports_have_distinct_ids_without_overwrite(self):
        source = self.png()
        first = self.manager.import_image(source)
        second = self.manager.import_image(source)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.manager.list_skins()), 3)

    def test_folder_all_four_states_png_and_gif(self):
        source = self.folder({"idle": "idle.png", "happy": "happy.gif", "dizzy": "idle.png", "flat": "idle.png"})
        (source / "happy.gif").write_bytes(gif_bytes())
        result = self.manager.import_pack(source)
        self.assertEqual(set(result["states"]), set(SkinManager.STATES))
        self.assertEqual(result["states"]["dizzy"], result["states"]["idle"])
        self.assertEqual(result["name"], "测试桌宠")
        self.assertEqual(result["author"], "本地作者")

    def test_nested_zip_pack_is_supported_without_extractall(self):
        source = self.folder()
        archive = self.zipped([("my_pet/manifest.json", (source / "manifest.json").read_bytes()),
                               ("my_pet/idle.png", (source / "idle.png").read_bytes()),
                               ("my_pet/README.txt", b"personal local image")])
        result = self.manager.import_pack(archive)
        destination = self.manager.resolve(result["id"])
        self.assertEqual({p.name for p in destination.iterdir()}, {"manifest.json", "media_0.png"})

    def test_missing_expressions_fall_back_to_idle_manifest(self):
        result = self.manager.import_pack(self.folder())
        self.assertEqual(set(result["states"]), {"idle"})

    def test_fully_transparent_png_is_rejected_before_wardrobe_commit(self):
        source = self.work / "transparent.png"
        image = QImage(48, 40, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        self.assertTrue(image.save(str(source), "PNG"))
        original = source.read_bytes()
        with self.assertRaisesRegex(SkinImportError, "全透明"):
            self.manager.import_image(source)
        self.assertEqual(len(self.manager.list_skins()), 1)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(list(self.skins.glob("user_*")), [])

    def test_fully_transparent_gif_is_rejected_before_wardrobe_commit(self):
        source = self.work / "transparent.gif"
        payload = gif_bytes(frames=1).replace(b"\x21\xf9\x04\x00", b"\x21\xf9\x04\x01")
        source.write_bytes(payload)
        with self.assertRaisesRegex(SkinImportError, "全透明"):
            self.manager.import_image(source)
        self.assertEqual(len(self.manager.list_skins()), 1)
        self.assertEqual(list(self.skins.glob("user_*")), [])

    def test_gif_with_blank_first_frame_and_visible_later_frame_is_accepted(self):
        source = self.work / "blank-then-visible.gif"
        source.write_bytes(gif_bytes().replace(b"\x21\xf9\x04\x00", b"\x21\xf9\x04\x01"))
        imported = self.manager.import_image(source)
        self.assertEqual(self.manager.resolve(imported["id"]).name, imported["id"])
        self.assertEqual(len(self.manager.list_skins()), 2)

    def test_wrong_extension_and_spoofed_extension_are_rejected(self):
        for name, payload in (("evil.py", b"print(1)"), ("fake.png", gif_bytes()), ("fake.gif", b"not an image")):
            source = self.work / name
            source.write_bytes(payload)
            with self.subTest(name=name), self.assertRaises(SkinImportError):
                self.manager.import_image(source)
        self.assertEqual(len(self.manager.list_skins()), 1)

    def test_empty_image_is_rejected(self):
        source = self.work / "empty.png"
        source.write_bytes(b"")
        with self.assertRaises(SkinImportError):
            self.manager.import_image(source)

    def test_single_file_limit_is_checked_before_decode(self):
        source = self.work / "huge.png"
        with source.open("wb") as output:
            output.truncate(SkinManager.MAX_FILE_BYTES + 1)
        with self.assertRaisesRegex(SkinImportError, "普通文件"):
            self.manager.import_image(source)

    def test_large_valid_image_is_accepted_for_scaled_runtime(self):
        source = self.png(size=(1024, 768))
        metadata = self.manager.import_image(source)
        self.assertNotEqual(self.manager.resolve(metadata["id"]).name, "default")

    def test_oversize_source_dimensions_rejected_without_full_decode(self):
        source = self.work / "wide.gif"
        source.write_bytes(gif_bytes(width=8193))
        with self.assertRaisesRegex(SkinImportError, "源尺寸过大"):
            self.manager.import_image(source)

    def test_gif_frame_count_limit_rejected(self):
        with self.assertRaisesRegex(SkinImportError, "200帧"):
            self.manager.import_image(self.gif(201))

    def test_gif_cumulative_pixel_budget_rejected(self):
        source = self.work / "costly.gif"
        source.write_bytes(gif_bytes(frames=5, width=4000, height=4000))
        with self.assertRaisesRegex(SkinImportError, "解码量过大"):
            self.manager.import_image(source)

    def test_truncated_media_does_not_commit_wardrobe_manifest(self):
        source = self.work / "broken.gif"
        source.write_bytes(gif_bytes()[:-7])
        with self.assertRaises(SkinImportError):
            self.manager.import_image(source)
        self.assertEqual(len(self.manager.list_skins()), 1)

    def test_manifest_requires_idle_and_known_states(self):
        for states in ({"happy": "idle.png"}, {"idle": "idle.png", "execute": "idle.png"}):
            source = self.folder(states)
            with self.subTest(states=states), self.assertRaises(SkinImportError):
                self.manager.import_pack(source)

    def test_manifest_invalid_values_are_rejected(self):
        for extra in ({"name": ""}, {"author": []}, {"schema_version": 99}, {"remove_white_background": "yes"}):
            with self.subTest(extra=extra), self.assertRaises(SkinImportError):
                self.manager.import_pack(self.folder(**extra))

    def test_manifest_nonstandard_json_numbers_rejected(self):
        source = self.folder()
        (source / "manifest.json").write_text('{"name":NaN,"states":{"idle":"idle.png"}}', encoding="utf8")
        with self.assertRaises(SkinImportError):
            self.manager.import_pack(source)

    def test_folder_path_traversal_absolute_drive_backslash_and_ads_rejected(self):
        for filename in ("../outside.png", "/outside.png", "C:/outside.png", "sub\\outside.png", "idle.png:stream", "./idle.png", "CON.png"):
            with self.subTest(filename=filename), self.assertRaises(SkinImportError):
                self.manager.import_pack(self.folder({"idle": filename}))
        self.assertEqual(len(self.manager.list_skins()), 1)

    def test_missing_pack_image_rejected(self):
        with self.assertRaises(SkinImportError):
            self.manager.import_pack(self.folder({"idle": "missing.png"}))

    def test_invalid_json_and_oversize_manifest_rejected(self):
        for payload in (b"{broken", b" " * (SkinManager.MAX_MANIFEST_BYTES + 1)):
            source = self.folder()
            (source / "manifest.json").write_bytes(payload)
            with self.subTest(size=len(payload)), self.assertRaises(SkinImportError):
                self.manager.import_pack(source)

    def test_zip_slip_entries_rejected_even_when_unreferenced(self):
        folder = self.folder()
        valid = [("manifest.json", (folder / "manifest.json").read_bytes()), ("idle.png", (folder / "idle.png").read_bytes())]
        for name in ("../escape.png", "/escape.png", "C:/escape.png", "folder\\escape.png", "folder/../escape.png"):
            with self.subTest(name=name), self.assertRaises(SkinImportError):
                self.manager.import_pack(self.zipped(valid + [(name, b"escape")]))
        self.assertFalse((self.work / "escape.png").exists())

    def test_zip_symlink_rejected(self):
        entry = zipfile.ZipInfo("link.png")
        entry.create_system = 3
        entry.external_attr = (0o120777 << 16)
        archive = self.work / "symlink.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr(entry, "../../outside")
        with self.assertRaisesRegex(SkinImportError, "链接"):
            self.manager.import_pack(archive)

    def test_zip_case_collision_rejected(self):
        archive = self.zipped([("idle.png", b"first"), ("IDLE.PNG", b"second")])
        with self.assertRaisesRegex(SkinImportError, "大小写冲突"):
            self.manager.import_pack(archive)

    def test_zip_entry_count_limit_rejected(self):
        archive = self.zipped([(f"x{i}.txt", b"x") for i in range(65)])
        with self.assertRaisesRegex(SkinImportError, "1～64"):
            self.manager.import_pack(archive)

    def test_zip_lzma_and_bzip2_rejected_before_any_decompression(self):
        for compression in (zipfile.ZIP_LZMA, zipfile.ZIP_BZIP2):
            archive = self.work / f"method-{compression}.zip"
            with zipfile.ZipFile(archive, "w", compression=compression) as output:
                output.writestr("manifest.json", '{"states":{"idle":"idle.png"}}')
            with self.subTest(method=compression), patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("decompression must not start")) as read:
                with self.assertRaisesRegex(SkinImportError, "Deflate"):
                    self.manager.import_pack(archive)
                read.assert_not_called()
            self.assertEqual(len(self.manager.list_skins()), 1)

    def test_zip_unknown_method_rejected_before_any_decompression(self):
        archive = self.work / "unknown-method.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as output:
            output.writestr("manifest.json", '{"states":{"idle":"idle.png"}}')
        raw = bytearray(archive.read_bytes())
        local = raw.index(b"PK\x03\x04")
        central = raw.index(b"PK\x01\x02")
        raw[local + 8:local + 10] = struct.pack("<H", 99)
        raw[central + 10:central + 12] = struct.pack("<H", 99)
        archive.write_bytes(raw)
        with patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("decompression must not start")) as read:
            with self.assertRaisesRegex(SkinImportError, "Deflate"):
                self.manager.import_pack(archive)
            read.assert_not_called()
        self.assertEqual(len(self.manager.list_skins()), 1)

    def test_zip_high_compression_rejected(self):
        archive = self.zipped([("bomb.txt", b"0" * (2 * 1024 * 1024))])
        with self.assertRaisesRegex(SkinImportError, "压缩率异常"):
            self.manager.import_pack(archive)

    def test_zip_oversize_uncompressed_entry_rejected(self):
        archive = self.zipped([("huge.txt", b"0" * (SkinManager.MAX_FILE_BYTES + 1))])
        with self.assertRaisesRegex(SkinImportError, "单文件超过20"):
            self.manager.import_pack(archive)

    def test_invalid_zip_and_missing_or_multiple_manifest_rejected(self):
        broken = self.work / "broken.zip"
        broken.write_bytes(b"not zip")
        for source in (broken, self.zipped([("readme.txt", b"x")]), self.zipped([("manifest.json", b"{}"), ("other/manifest.json", b"{}")])):
            with self.subTest(source=source), self.assertRaises(SkinImportError):
                self.manager.import_pack(source)

    def test_resolve_bad_id_missing_and_tampered_skin_fall_back(self):
        for skin_id in ("../escape", "user_nope", "user_" + "0" * 32, None):
            self.assertEqual(self.manager.resolve(skin_id), self.skins / "default")
        result = self.manager.import_image(self.png())
        directory = self.skins / result["id"]
        (directory / result["states"]["idle"]).write_bytes(b"tampered")
        self.assertEqual(self.manager.resolve(result["id"]), self.skins / "default")

    def test_incomplete_directory_ignored_without_removing_files(self):
        folder = self.skins / ("user_" + "a" * 32)
        folder.mkdir()
        (folder / "partial.png").write_bytes(b"incomplete")
        self.assertEqual(len(self.manager.list_skins()), 1)
        self.assertTrue((folder / "partial.png").exists())

    def test_copy_failure_never_commits_manifest_or_deletes_source(self):
        source = self.png()
        original = source.read_bytes()
        with patch.object(self.manager, "_write_new", side_effect=OSError("simulated permission failure")):
            with self.assertRaises(SkinImportError):
                self.manager.import_image(source)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(len(self.manager.list_skins()), 1)
        self.assertTrue(any(self.skins.glob("user_*")))

    def test_template_is_importable_and_export_never_overwrites(self):
        target = self.work / "my-template"
        self.assertEqual(self.manager.export_template(target), target)
        original = (target / "manifest.json").read_bytes()
        result = self.manager.import_pack(target)
        self.assertEqual(set(result["states"]), set(SkinManager.STATES))
        with self.assertRaises(SkinImportError):
            self.manager.export_template(target)
        self.assertEqual((target / "manifest.json").read_bytes(), original)

    def test_windows_junction_sources_and_sandbox_are_rejected(self):
        if sys.platform != "win32":
            self.skipTest("Windows junction behavior")
        source = self.folder()
        junction = self.work / "linked-pack"
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(source)],
                                cwd=ROOT, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(junction.exists())
        with self.assertRaisesRegex(SkinImportError, "重解析点"):
            self.manager.import_pack(junction)
        with self.assertRaisesRegex(SkinImportError, "重解析点"):
            SkinManager(junction)
        self.assertTrue((source / "idle.png").exists())

    def test_zip_embedded_null_name_rejected_from_original_name(self):
        archive = self.zipped([("idle.png\x00hidden", b"not image")])
        with self.assertRaisesRegex(SkinImportError, "外部位置"):
            self.manager.import_pack(archive)

    def test_folder_symbolic_media_path_rejected(self):
        if sys.platform != "win32":
            self.skipTest("Windows junction behavior")
        source = self.folder({"idle": "linked/idle.png"})
        target = self.folder()
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(source / "linked"), str(target)],
                                cwd=ROOT, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        with self.assertRaisesRegex(SkinImportError, "重解析点"):
            self.manager.import_pack(source)

    def test_cross_process_restart_restores_custom_gif_and_accessories(self):
        imported = self.manager.import_image(self.gif())
        save = self.work / "save_data.json"
        data = PetData.from_dict({"selected_skin_id": imported["id"], "affection_level": 3,
                                  "accessories": {"head": "crown", "face": "", "effect": "", "offset_y": -12}})
        SaveManager(save).update_game(data.to_dict(), {"pinned": True, "x_ratio": .4, "y_ratio": .5})
        script = "\n".join([
            "import json,sys", "from pathlib import Path", "from PySide6.QtWidgets import QApplication",
            "from save_manager import SaveManager,SkinManager", "app=QApplication([])",
            "data,window=SaveManager(Path(sys.argv[1])).load_all()", "manager=SkinManager(Path(sys.argv[2]))",
            "result={'id':data.selected_skin_id,'accessories':data.accessories,'resolved':manager.resolve(data.selected_skin_id).name,'pinned':window['pinned']}",
            "print(json.dumps(result))",
        ])
        result = subprocess.run([sys.executable, "-B", "-X", "utf8", "-c", script, str(save), str(self.skins)], cwd=ROOT, capture_output=True, text=True, encoding="utf8", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        restored = json.loads(result.stdout)
        self.assertEqual(restored["id"], imported["id"])
        self.assertEqual(restored["resolved"], imported["id"])
        self.assertEqual(restored["accessories"]["head"], "crown")
        self.assertEqual(restored["accessories"]["offset_y"], -12)
        self.assertTrue(restored["pinned"])

    def test_schema3_migration_backups_and_preserves_unknown_fields(self):
        save = self.work / "save_data.json"
        old = {"schema_version": 3, "coins": 234, "future": {"retained": True}, "window": {"pinned": True, "x_ratio": .2, "y_ratio": .7}}
        original = json.dumps(old).encode()
        save.write_bytes(original)
        manager = SaveManager(save)
        data, window = manager.load_all()
        manager.update_game(data.to_dict(), window)
        migrated = json.loads(save.read_text(encoding="utf-8"))
        self.assertEqual(migrated["schema_version"], 5)
        self.assertEqual(migrated["coins"], 234)
        self.assertTrue(migrated["future"]["retained"])
        backups = list(self.work.glob("save_data.json.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
