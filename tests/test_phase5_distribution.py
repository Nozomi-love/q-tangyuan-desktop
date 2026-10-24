"""Distribution boundaries and native Windows application identity."""
from datetime import datetime
import ctypes
from pathlib import Path
import sys
import unittest
import zipfile

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import WINDOWS_APP_ID, configure_windows_identity, create_tray_icon
from pet_engine import SkinRenderer
from tools.build_windows import checked_source, resource_files, write_new, zip_portable

APP = QApplication.instance() or QApplication(["distribution-tests"])
ART = ROOT / "tests/artifacts" / datetime.now().strftime("distribution-unit-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


class DistributionTests(unittest.TestCase):
    def test_build_allow_list_excludes_all_player_data(self):
        files = resource_files(ROOT)
        self.assertEqual(len([f for f in files if f.startswith("assets/item_icons/")]), 116)
        self.assertEqual(len([f for f in files if f.endswith(".png") and "/default/" in f]), 4)
        self.assertIn("config/catalog.json", files)
        self.assertNotIn("data/save_data.json", files)
        self.assertFalse(any("user_" in f or ".bak." in f or f.startswith("docs/") for f in files))

    def test_invalid_relative_resources_are_rejected(self):
        for value in ("../main.py", "/main.py", "D:/main.py", "assets/../../main.py", "assets\\main.py"):
            with self.subTest(value=value), self.assertRaises((ValueError, FileNotFoundError)):
                checked_source(ROOT, value)

    def test_zip_is_relocatable_and_does_not_replace_existing_archive(self):
        folder = ART / "clean/Q弹汤圆"
        write_new(folder / "Q弹汤圆.exe", b"test-only-executable")
        write_new(folder / "assets/item_icons/water.png", b"test-only-art")
        archive = ART / "clean.zip"
        self.assertEqual(zip_portable(folder, archive), 2)
        before = archive.read_bytes()
        with zipfile.ZipFile(archive) as packed:
            self.assertIn("Q弹汤圆/Q弹汤圆.exe", packed.namelist())
        with self.assertRaises(FileExistsError):
            zip_portable(folder, archive)
        self.assertEqual(archive.read_bytes(), before)

    def test_zip_refuses_save_and_imported_skin_before_writing(self):
        for key, relative in (("save", "data/save_data.json"), ("skin", "assets/skins/user_secret/media.png"),
                              ("backup", "config/catalog.json.bak.old")):
            folder = ART / key / "Q弹汤圆"
            write_new(folder / relative, b"private")
            archive = ART / (key + ".zip")
            with self.subTest(relative=relative), self.assertRaises(ValueError):
                zip_portable(folder, archive)
            self.assertFalse(archive.exists())

    def test_shared_icon_stays_identical_to_desktop_ico_across_skins(self):
        expected = QIcon(str(ROOT / "assets/icons/tangyuan.ico")).pixmap(32, 32).toImage()
        self.assertFalse(expected.isNull())
        for renderer in (None, SkinRenderer(ROOT / "assets/skins/default")):
            self.assertEqual(create_tray_icon(renderer).pixmap(32, 32).toImage(), expected)

    @unittest.skipUnless(sys.platform == "win32", "Windows taskbar identity")
    def test_windows_shell_reads_the_assigned_application_identity(self):
        self.assertTrue(configure_windows_identity())
        shell = ctypes.WinDLL("shell32")
        read_id = shell.GetCurrentProcessExplicitAppUserModelID
        read_id.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
        read_id.restype = ctypes.c_long
        result = ctypes.c_wchar_p()
        self.assertEqual(read_id(ctypes.byref(result)), 0)
        try:
            self.assertEqual(result.value, WINDOWS_APP_ID)
        finally:
            free = ctypes.WinDLL("ole32").CoTaskMemFree
            free.argtypes = [ctypes.c_void_p]
            free(result)


if __name__ == "__main__":
    unittest.main()
