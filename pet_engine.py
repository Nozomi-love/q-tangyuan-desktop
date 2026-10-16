"""Phase 1: state, elapsed-time physics, and a skin-independent renderer.

All distances are Qt logical pixels. x, y denotes the body's bottom-centre
anchor in desktop coordinates, never the window's top-left.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
import json
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor, QImage, QImageReader, QLinearGradient, QPainter, QPen,
    QPixmap, QTransform,
)

LOGGER = logging.getLogger(__name__)


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


class PetState(str, Enum):
    IDLE = "idle"
    HAPPY = "happy"
    DIZZY = "dizzy"
    FLAT = "flat"


@dataclass(frozen=True)
class WorkArea:
    left: float
    top: float
    width: float
    height: float

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("工作区宽高必须大于零")

    @property
    def right(self) -> float:
        # QRect.right()/bottom() are inclusive; use exclusive edges so the
        # last painted pixel remains inside availableGeometry.
        return self.left + self.width

    @property
    def bottom(self) -> float:
        return self.top + self.height


@dataclass(frozen=True)
class Pose:
    scale_x: float
    scale_y: float
    angle: float


class PetEngine:
    """Time-based movement; no QWidget, OS pixel coordinates, or file writes."""

    BODY_WIDTH = 128.0
    BODY_HEIGHT = 116.0
    GRAVITY = 2100.0
    CLICK_JUMP_SPEED = 265.0
    DRAG_INHERITANCE = 0.58
    MAX_THROW_SPEED = 2400.0
    MAX_STEP = 1.0 / 240.0
    MAX_FRAME_DELTA = 0.10

    def __init__(self, area: WorkArea) -> None:
        self.area = area
        self.elapsed = 0.0
        self.x = self.y = 0.0
        self.vx = self.vy = 0.0
        self.angle = 0.0
        self.target_angle = 0.0
        self.spring = self.spring_velocity = 0.0
        self.dragging = False
        self.held = False
        self.grounded = True
        self.flat = False
        self.pinned = False
        self.happy_until = 0.0
        self.last_drag_time = 0.0
        self.landing_count = 0
        self.reset(area)

    @property
    def state(self) -> PetState:
        if self.dragging:
            return PetState.DIZZY
        if self.flat:
            return PetState.FLAT
        if self.elapsed < self.happy_until:
            return PetState.HAPPY
        return PetState.IDLE

    @property
    def pose(self) -> Pose:
        breath = 1.0 + 0.033 * math.sin(math.tau * self.elapsed / 3.2)
        dynamic_height = breath * clamp(1.0 + self.spring, 0.55, 1.38)
        # Breathing and jelly motion conserve projected area. Hunger is a
        # separate deformation: flatten without excessive 2.5x widening.
        return Pose(
            (1.14 if self.flat else 1.0) / dynamic_height,
            dynamic_height * (0.4 if self.flat else 1.0),
            self.angle,
        )

    def bounds_offsets(self) -> tuple[float, float, float, float]:
        """Conservative transformed body bounds, relative to the foot anchor."""
        pose = self.pose
        radians = math.radians(pose.angle)
        cosine, sine = math.cos(radians), math.sin(radians)
        corners = [
            (x * pose.scale_x * cosine - y * pose.scale_y * sine,
             x * pose.scale_x * sine + y * pose.scale_y * cosine)
            for x, y in (
                (-self.BODY_WIDTH / 2, -self.BODY_HEIGHT),
                (self.BODY_WIDTH / 2, -self.BODY_HEIGHT),
                (-self.BODY_WIDTH / 2, 0.0),
                (self.BODY_WIDTH / 2, 0.0),
            )
        ]
        return (
            min(p[0] for p in corners), min(p[1] for p in corners),
            max(p[0] for p in corners), max(p[1] for p in corners),
        )

    def reset(self, area: WorkArea | None = None) -> None:
        if area is not None:
            self.area = area
        self.vx = self.vy = 0.0
        self.angle = self.target_angle = 0.0
        self.spring = self.spring_velocity = 0.0
        self.dragging = self.held = False
        self.grounded = True
        self.happy_until = 0.0
        self.x = self.area.right - self.BODY_WIDTH / 2 - 48.0
        self.y = self.area.bottom
        self._confine_horizontal()
        self._align_with_floor()

    def set_work_area(self, area: WorkArea) -> None:
        if area == self.area:
            return
        old_bottom = self.area.bottom
        self.area = area
        if self.pinned:
            self._confine_drag()
            return
        if self.grounded and area.bottom > old_bottom + 0.5:
            self.grounded = False
        if not self.held:
            self._confine_horizontal()
            if self.grounded:
                self._align_with_floor()

    def set_pinned(self, enabled: bool) -> None:
        self.pinned = bool(enabled)
        self.vx = self.vy = 0.0
        self.target_angle = 0.0
        self.grounded = False

    def place(self, x: float, y: float) -> None:
        self.x, self.y = x, y
        self.vx = self.vy = 0.0
        self.angle = self.target_angle = 0.0
        self.grounded = False
        self._confine_drag()

    def set_flat(self, enabled: bool) -> None:
        self.flat = bool(enabled)

    def hold(self) -> None:
        self.held = True

    def begin_drag(self) -> None:
        self.held = self.dragging = True
        self.grounded = False
        self.vx = self.vy = 0.0

    def drag_to(self, x: float, y: float, pointer_vx: float) -> None:
        self.x, self.y = x, y
        self.target_angle = clamp(pointer_vx / 85.0, -18.0, 18.0)
        self.last_drag_time = self.elapsed
        self._confine_drag()

    def _confine_drag(self) -> None:
        self._confine_horizontal(reflect=False)
        _, top, _, bottom = self.bounds_offsets()
        floor = self.area.bottom - bottom
        ceiling = self.area.top - top
        self.y = clamp(self.y, min(ceiling, floor), floor)

    def release_drag(self, pointer_vx: float, pointer_vy: float) -> None:
        self.dragging = self.held = False
        self.grounded = False
        self.target_angle = 0.0
        if self.pinned:
            self.vx = self.vy = 0.0
            return
        self.vx = clamp(pointer_vx, -self.MAX_THROW_SPEED, self.MAX_THROW_SPEED) * self.DRAG_INHERITANCE
        self.vy = clamp(pointer_vy, -self.MAX_THROW_SPEED, self.MAX_THROW_SPEED) * self.DRAG_INHERITANCE

    def click(self) -> None:
        self.held = False
        self.happy_until = self.elapsed + 0.8
        self.spring = min(self.spring, -0.29)
        self.spring_velocity = 0.0
        if not self.pinned:
            self.grounded = False
            self.vy = min(self.vy, -self.CLICK_JUMP_SPEED)

    def _squash_on_landing(self, speed: float) -> None:
        if speed >= 60.0:
            compression = clamp(0.08 + speed * 0.00019, 0.10, 0.44)
            self.spring = -compression
            self.spring_velocity = 0.0

    def _align_with_floor(self) -> None:
        self.y = self.area.bottom - self.bounds_offsets()[3]

    def _confine_horizontal(self, reflect: bool = True) -> None:
        left, _, right, _ = self.bounds_offsets()
        minimum, maximum = self.area.left - left, self.area.right - right
        if minimum > maximum:
            self.x = (self.area.left + self.area.right - left - right) / 2
            self.vx = 0.0
        elif self.x < minimum:
            self.x = minimum
            if reflect and self.vx < 0:
                self.vx = -self.vx * 0.66
        elif self.x > maximum:
            self.x = maximum
            if reflect and self.vx > 0:
                self.vx = -self.vx * 0.66

    def advance(self, elapsed_seconds: float) -> float | None:
        """Return an impact speed when a landing occurs during this frame.

        Clamp large stalls (e.g. resume from sleep), then substep the spring and
        collisions. Ordinary 30/60/120 Hz movement uses the same elapsed time.
        """
        if not math.isfinite(elapsed_seconds) or elapsed_seconds <= 0:
            return None
        self.elapsed += elapsed_seconds
        duration = min(elapsed_seconds, self.MAX_FRAME_DELTA)
        steps = max(1, math.ceil(duration / self.MAX_STEP))
        dt = duration / steps
        impact: float | None = None
        for _ in range(steps):
            self.spring_velocity += (-360.0 * self.spring - 15.0 * self.spring_velocity) * dt
            self.spring += self.spring_velocity * dt
            self.spring = clamp(self.spring, -0.45, 0.38)
            if abs(self.spring) < 0.00008 and abs(self.spring_velocity) < 0.001:
                self.spring = self.spring_velocity = 0.0

            target = self.target_angle if self.dragging else 0.0
            if self.dragging and self.elapsed - self.last_drag_time > 0.12:
                target = 0.0
            self.angle += (target - self.angle) * (1.0 - math.exp(-14.0 * dt))
            if abs(self.angle) < 0.002 and target == 0.0:
                self.angle = 0.0

            if self.held:
                if self.dragging:
                    self._confine_drag()
                continue

            if self.pinned:
                continue

            if self.grounded:
                self.vx *= math.exp(-9.0 * dt)
                if abs(self.vx) < 0.5:
                    self.vx = 0.0
                self.x += self.vx * dt
                self._align_with_floor()
            else:
                self.x += self.vx * dt
                self.vx *= math.exp(-0.45 * dt)
                self.y += self.vy * dt + 0.5 * self.GRAVITY * dt * dt
                self.vy += self.GRAVITY * dt
                _, top, _, bottom = self.bounds_offsets()
                floor = self.area.bottom - bottom
                ceiling = min(self.area.top - top, floor)
                if self.y < ceiling:
                    self.y = ceiling
                    if self.vy < 0:
                        self.vy = -self.vy * 0.25
                if self.y >= floor and self.vy >= 0:
                    impact = self.vy
                    self.y = floor
                    self.vy = 0.0
                    self.vx *= 0.70
                    self.grounded = True
                    self.landing_count += 1
                    self._squash_on_landing(impact)
                    self._align_with_floor()
            self._confine_horizontal()
        return impact


class SkinRenderer:
    """Load canonical PNGs or the expression mapping, without changing originals.

    Expressions with floating effects can use their largest connected component
    as the physical body. The complete artwork, including stars, still renders.
    """

    CACHE_EDGE = 768

    def __init__(self, skin_directory: Path) -> None:
        self.skin_directory = Path(skin_directory)
        self.pixmaps: dict[PetState, QPixmap] = {}
        self.images: dict[PetState, QImage] = {}
        self.draw_rects: dict[PetState, QRectF] = {}
        self.source_paths: dict[PetState, Path] = {}
        self.reload()

    def _configuration(self) -> dict:
        file_path = self.skin_directory / "expressions.json"
        if not file_path.is_file():
            return {}
        try:
            config = json.loads(file_path.read_text(encoding="utf-8"))
            if not isinstance(config, dict) or config.get("schema_version") != 1:
                raise ValueError("需要 schema_version=1 的对象")
            files = config.get("files", {})
            if not isinstance(files, dict) or not all(isinstance(v, str) for v in files.values()):
                raise ValueError("files 必须把状态名映射到文件名")
            return config
        except (OSError, UnicodeError, ValueError) as error:
            LOGGER.warning("表情配置不可用，回退标准文件名：%s", error)
            return {}

    @staticmethod
    def _flood_spans(mask: bytearray, width: int, height: int, seed: tuple[int, int]):
        """Consume a 4-connected region as horizontal spans."""
        stack = [seed]
        while stack:
            x, y = stack.pop()
            row = y * width
            if not mask[row + x]:
                continue
            left = x
            while left > 0 and mask[row + left - 1]:
                left -= 1
            right = x
            while right + 1 < width and mask[row + right + 1]:
                right += 1
            mask[row + left:row + right + 1] = bytes(right - left + 1)
            yield y, left, right
            for next_y in (y - 1, y + 1):
                if not 0 <= next_y < height:
                    continue
                start, end = next_y * width + left, next_y * width + right + 1
                index = start
                while index < end:
                    found = mask.find(b"\x01", index, end)
                    if found < 0:
                        break
                    stack.append((found % width, next_y))
                    index = found + 1
                    while index < end and mask[index]:
                        index += 1

    @classmethod
    def _remove_connected_white(cls, image: QImage) -> QImage:
        """Only the neutral, near-white region connected to the border clears.

        White rice and highlights enclosed by the outline remain opaque.
        This is a load-time rendering operation; no source PNG is rewritten.
        """
        width, height = image.width(), image.height()
        data = bytearray(image.constBits())
        eligible = bytearray(width * height)
        for pixel in range(width * height):
            offset = pixel * 4
            r, g, b = data[offset], data[offset + 1], data[offset + 2]
            if min(r, g, b) >= 225 and max(r, g, b) - min(r, g, b) <= 24:
                eligible[pixel] = 1
        seeds = (
            [(x, 0) for x in range(width)]
            + [(x, height - 1) for x in range(width)]
            + [(0, y) for y in range(1, height - 1)]
            + [(width - 1, y) for y in range(1, height - 1)]
        )
        for seed in seeds:
            if not eligible[seed[1] * width + seed[0]]:
                continue
            for y, left, right in cls._flood_spans(eligible, width, height, seed):
                start = (y * width + left) * 4 + 3
                stop = (y * width + right) * 4 + 4
                data[start:stop:4] = bytes(right - left + 1)
        return QImage(bytes(data), width, height, image.bytesPerLine(),
                      QImage.Format.Format_RGBA8888).copy()

    @classmethod
    def _foreground_boxes(cls, image: QImage, largest_body: bool):
        """Return union/body boxes as left, top, right-exclusive, bottom-exclusive."""
        width, height = image.width(), image.height()
        alpha = bytes(image.constBits())[3::4]
        union = [width, height, 0, 0]
        body = None
        if largest_body:
            mask = bytearray(int(value > 12) for value in alpha)
            search_from, largest_area = 0, 0
            while True:
                first = mask.find(b"\x01", search_from)
                if first < 0:
                    break
                box = [width, height, 0, 0]
                area = 0
                for y, left, right in cls._flood_spans(mask, width, height, (first % width, first // width)):
                    box = [min(box[0], left), min(box[1], y),
                           max(box[2], right + 1), max(box[3], y + 1)]
                    area += right - left + 1
                union = [min(union[0], box[0]), min(union[1], box[1]),
                         max(union[2], box[2]), max(union[3], box[3])]
                if area > largest_area:
                    largest_area, body = area, box
                search_from = first + 1
        else:
            for y in range(height):
                row = alpha[y * width:(y + 1) * width]
                nonzero = [x for x, value in enumerate(row) if value > 12]
                if nonzero:
                    union = [min(union[0], nonzero[0]), min(union[1], y),
                             max(union[2], nonzero[-1] + 1), y + 1]
            body = union
        if body is None or union[2] <= union[0]:
            return None
        return union, body

    def reload(self) -> None:
        self.pixmaps.clear()
        self.images.clear()
        self.draw_rects.clear()
        self.source_paths.clear()
        config = self._configuration()
        for state in PetState:
            canonical = self.skin_directory / f"{state.value}.png"
            file_path = canonical
            if not canonical.is_file():
                filename = config.get("files", {}).get(state.value, f"{state.value}.png")
                file_path = self.skin_directory / filename
            # Expression mappings may only refer to files inside this skin.
            if not file_path.resolve().is_relative_to(self.skin_directory.resolve()):
                LOGGER.warning("跳过皮肤目录之外的文件：%s", state.value)
                continue
            if not file_path.is_file():
                continue
            reader = QImageReader(str(file_path))
            reader.setAutoTransform(True)
            size = reader.size()
            if size.width() > 4096 or size.height() > 4096:
                LOGGER.warning("跳过过大的表情 PNG：%s（最长边上限 4096）", file_path.name)
                continue
            if max(size.width(), size.height()) > self.CACHE_EDGE:
                reader.setScaledSize(size.scaled(
                    self.CACHE_EDGE, self.CACHE_EDGE, Qt.AspectRatioMode.KeepAspectRatio
                ))
            image = reader.read()
            if image.isNull():
                LOGGER.warning("表情 PNG 无法读取，使用兜底：%s", file_path.name)
                continue
            has_alpha = image.hasAlphaChannel()
            image = image.convertToFormat(QImage.Format.Format_RGBA8888)
            if config.get("remove_connected_white") is True and not has_alpha:
                image = self._remove_connected_white(image)
            largest_body = config.get("fit") == "largest_body_contain"
            boxes = self._foreground_boxes(image, largest_body)
            if boxes is None:
                LOGGER.warning("表情 PNG 全透明，使用兜底：%s", file_path.name)
                continue
            foreground, body = boxes
            left, top, right, bottom = foreground
            image = image.copy(left, top, right - left, bottom - top)
            image.setDevicePixelRatio(1.0)
            if largest_body:
                bx1, by1, bx2, by2 = body
                scale = min(PetEngine.BODY_WIDTH / (bx2 - bx1),
                            PetEngine.BODY_HEIGHT / (by2 - by1))
                draw_rect = QRectF(
                    (left - (bx1 + bx2) / 2) * scale, (top - by2) * scale,
                    image.width() * scale, image.height() * scale,
                )
            else:
                draw_rect = self.body_rect()
            self.images[state] = image
            self.pixmaps[state] = QPixmap.fromImage(image)
            self.draw_rects[state] = draw_rect
            self.source_paths[state] = file_path

    def source_state(self, state: PetState) -> PetState | None:
        if state in self.pixmaps:
            return state
        if PetState.IDLE in self.pixmaps:
            return PetState.IDLE
        return None

    @staticmethod
    def body_rect() -> QRectF:
        return QRectF(-PetEngine.BODY_WIDTH / 2, -PetEngine.BODY_HEIGHT,
                      PetEngine.BODY_WIDTH, PetEngine.BODY_HEIGHT)

    @staticmethod
    def body_transform(engine: PetEngine, foot: QPointF) -> QTransform:
        pose = engine.pose
        transform = QTransform()
        transform.translate(foot.x(), foot.y())
        transform.rotate(pose.angle)
        transform.scale(pose.scale_x, pose.scale_y)
        return transform

    def hit_test(self, engine: PetEngine, foot: QPointF, point: QPointF) -> bool:
        inverse, invertible = self.body_transform(engine, foot).inverted()
        if not invertible:
            return False
        local = inverse.map(point)
        source = self.source_state(engine.state)
        rect = self.draw_rects[source] if source is not None else self.body_rect()
        if not rect.contains(local):
            return False
        if source is None:
            nx = local.x() / (PetEngine.BODY_WIDTH / 2)
            ny = (local.y() + PetEngine.BODY_HEIGHT / 2) / (PetEngine.BODY_HEIGHT / 2)
            return nx * nx + ny * ny <= 1.0
        image = self.images[source]
        u = int((local.x() - rect.left()) / rect.width() * image.width())
        v = int((local.y() - rect.top()) / rect.height() * image.height())
        u, v = min(u, image.width() - 1), min(v, image.height() - 1)
        return image.pixelColor(u, v).alpha() > 12

    def paint(self, painter: QPainter, engine: PetEngine, foot: QPointF) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setTransform(self.body_transform(engine, foot), combine=True)
        source = self.source_state(engine.state)
        if source is not None:
            pixmap = self.pixmaps[source]
            painter.drawPixmap(self.draw_rects[source], pixmap, QRectF(pixmap.rect()))
        else:
            self.paint_fallback(painter)
        painter.restore()

    @staticmethod
    def paint_fallback(painter: QPainter) -> None:
        """A faceless rice ball; expressions are supplied by PNG assets."""
        rect = SkinRenderer.body_rect()
        gradient = QLinearGradient(0.0, rect.top(), 14.0, 0.0)
        gradient.setColorAt(0.0, QColor("#fffefa"))
        gradient.setColorAt(0.55, QColor("#faf4ee"))
        gradient.setColorAt(1.0, QColor("#dfd3d0"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawEllipse(rect)
        painter.setPen(QPen(QColor("#c9bdbb"), 1.2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(rect.adjusted(0.6, 0.6, -0.6, -0.6))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 255, 255, 145))
        painter.drawEllipse(QRectF(-32.0, -97.0, 43.0, 19.0))
