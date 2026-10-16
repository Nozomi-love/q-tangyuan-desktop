"""Render the supplied expression pack and confirm the originals remain intact."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from pet_engine import PetEngine, PetState, SkinRenderer, WorkArea

app = QApplication.instance() or QApplication(["artwork-verification"])
directory = ROOT / "assets/skins/default"
config = json.loads((directory / "expressions.json").read_text(encoding="utf-8"))
files = [directory / filename for filename in config["files"].values()]
before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
started = time.perf_counter()
renderer = SkinRenderer(directory)
load_seconds = time.perf_counter() - started
assert set(renderer.pixmaps) == set(PetState), "四个表情必须全部加载"

destination = ROOT / "tests/artifacts" / datetime.now().strftime("artwork-%Y%m%d-%H%M%S-%f")
destination.mkdir(parents=True, exist_ok=False)
preview = QImage(1000, 320, QImage.Format.Format_ARGB32)
preview.fill(QColor("#eeeaf3"))
painter = QPainter(preview)
reports = []
for index, state in enumerate(PetState):
    engine = PetEngine(WorkArea(0, 0, 1600, 1000))
    if state == PetState.HAPPY:
        engine.click()
        engine.advance(0.10)
    elif state == PetState.DIZZY:
        engine.begin_drag()
    elif state == PetState.FLAT:
        engine.set_flat(True)
    source = renderer.images[state]
    assert source.hasAlphaChannel()
    alpha = bytes(source.convertToFormat(QImage.Format.Format_RGBA8888).constBits())[3::4]
    assert min(alpha) == 0 and max(alpha) == 255
    rect = renderer.draw_rects[state]
    # This point is inside the white upper rice body, above the facial marks.
    x = int((0 - rect.left()) / rect.width() * source.width())
    y = int((-80 - rect.top()) / rect.height() * source.height())
    rice = source.pixelColor(x, y)
    assert rice.alpha() == 255 and min(rice.red(), rice.green(), rice.blue()) > 235
    assert renderer.hit_test(engine, QPointF(0, 0),
                             renderer.body_transform(engine, QPointF(0, 0)).map(QPointF(0, -80)))

    frame = QImage(384, 288, QImage.Format.Format_ARGB32)
    frame.fill(Qt.GlobalColor.transparent)
    frame_painter = QPainter(frame)
    renderer.paint(frame_painter, engine, QPointF(192, 244))
    frame_painter.end()
    assert frame.save(str(destination / f"{state.value}.png"))

    painter.save()
    painter.translate(index * 250 + 125, 255)
    painter.scale(1.6, 1.6)
    renderer.paint(painter, engine, QPointF(0, 0))
    painter.restore()
    painter.setPen(QColor("#514758"))
    font = QFont("Segoe UI")
    font.setPixelSize(19)
    painter.setFont(font)
    painter.drawText(QRectF(index * 250, 270, 250, 30),
                     Qt.AlignmentFlag.AlignCenter, state.value)
    reports.append({
        "state": state.value, "file": renderer.source_paths[state].name,
        "cached_size": [source.width(), source.height()],
        "draw_rect": [round(rect.x(), 3), round(rect.y(), 3),
                      round(rect.width(), 3), round(rect.height(), 3)],
        "white_body_preserved": True,
        "transparent_pixels": sum(value == 0 for value in alpha),
    })
painter.end()
assert preview.save(str(destination / "preview.png"))
after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
assert before == after, "原始图片发生变化"
result = {
    "four_states_loaded": True, "original_files_unchanged": True,
    "load_seconds": round(load_seconds, 3), "states": reports, "sha256": after,
    "preview": str(destination / "preview.png"),
}
with (destination / "result.json").open("x", encoding="utf-8") as output:
    json.dump(result, output, ensure_ascii=False, indent=2)
print("ARTWORK_VERIFY_OK " + json.dumps(result, ensure_ascii=False), flush=True)
