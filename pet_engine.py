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

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor, QImage, QImageReader, QLinearGradient, QMovie, QPainter, QPainterPath, QPen, QPolygonF,
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
        self.manual_flat = False
        self.starving = False
        self._celebration_hops = 0
        self._next_celebration_at = 0.0
        self._trick = ""
        self._trick_started = 0.0
        self._trick_duration = 0.0
        self._trick_jump_height = 0.0
        self._roll_rect = QRectF()
        self._roll_start_distance = 0.0
        self._roll_revolutions = 1
        self.ball_x = self.ball_y = 0.0
        self.ball_vx = self.ball_vy = 0.0
        self.buff: dict = {}
        self.dizzy_until = 0.0
        self._next_spicy_at = 0.0
        self._run_direction = -1.0
        self.pinned = False
        self.happy_until = 0.0
        self.last_drag_time = 0.0
        self.landing_count = 0
        self.reset(area)

    @property
    def flat(self) -> bool:
        return self.manual_flat or self.starving

    @property
    def state(self) -> PetState:
        if self.elapsed < self.dizzy_until:
            return PetState.DIZZY
        if self.starving:
            return PetState.FLAT
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
        # Rolling keeps a stable envelope so the whole skin and accessories fit
        # beside each edge; the jelly spring resumes when the tour finishes.
        dynamic_height = breath if self._trick == "screen_roll" else breath * clamp(1.0 + self.spring, 0.55, 1.38)
        # Breathing and jelly motion conserve projected area. Hunger is a
        # separate deformation: flatten without excessive 2.5x widening.
        return Pose(
            (1.14 if self.flat else 1.0) / dynamic_height * self.buff.get("scale", 1.0),
            dynamic_height * (0.4 if self.flat else 1.0) * self.buff.get("scale", 1.0),
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

    @property
    def active_trick(self) -> str:
        return self._trick

    @property
    def trick_progress(self) -> float:
        if not self._trick or self._trick_duration <= 0:
            return 0.0
        return clamp((self.elapsed - self._trick_started) / self._trick_duration, 0.0, 1.0)

    @property
    def visual_offset(self) -> QPointF:
        # A visual jump preserves the saved foot anchor even when pinned.
        if self._trick == "screen_roll":
            return self._roll_offset()
        if self._trick == "flip":
            return QPointF(0, -self._trick_jump_height * math.sin(math.pi * self.trick_progress))
        if self._trick == "ball":
            hop = abs(math.sin((self.elapsed - self._trick_started) * math.pi * 2.4))
            return QPointF(0, -min(12.0, self._trick_jump_height) * hop)
        return QPointF()

    @property
    def visual_angle(self) -> float:
        if self._trick == "screen_roll":
            progress = clamp((self.trick_progress * 12.0 - 1.0) / 10.0, 0.0, 1.0)
            smooth = progress * progress * (3.0 - 2.0 * progress)
            return 360.0 * self._roll_revolutions * smooth
        if self._trick == "flip":
            progress = self.trick_progress
            smooth = progress * progress * (3.0 - 2.0 * progress)
            return 360.0 * smooth
        return 0.0

    def _roll_point(self, distance: float) -> QPointF:
        rect = self._roll_rect
        width, height = rect.width(), rect.height()
        distance %= 2.0 * (width + height)
        if distance <= width:
            return QPointF(rect.left() + distance, rect.top())
        distance -= width
        if distance <= height:
            return QPointF(rect.right(), rect.top() + distance)
        distance -= height
        if distance <= width:
            return QPointF(rect.right() - distance, rect.bottom())
        return QPointF(rect.left(), rect.bottom() - (distance - width))

    def _roll_offset(self) -> QPointF:
        """Approach the nearest edge, complete one clockwise lap, return home."""
        origin = QPointF(self.x, self.y - self.BODY_HEIGHT / 2 * self.pose.scale_y)
        edge = self._roll_point(self._roll_start_distance)
        progress = self.trick_progress
        if progress < 1.0 / 12.0:
            mix = progress * 12.0
            mix = mix * mix * (3.0 - 2.0 * mix)
            center = origin + (edge - origin) * mix
        elif progress > 11.0 / 12.0:
            mix = (progress * 12.0 - 11.0)
            mix = mix * mix * (3.0 - 2.0 * mix)
            center = edge + (origin - edge) * mix
        else:
            lap = (progress * 12.0 - 1.0) / 10.0
            perimeter = 2.0 * (self._roll_rect.width() + self._roll_rect.height())
            center = self._roll_point(self._roll_start_distance + lap * perimeter)
        return center - origin

    def _prepare_screen_roll(self, padding: float) -> bool:
        if not math.isfinite(padding) or padding < 1:
            return False
        rect = QRectF(self.area.left + padding, self.area.top + padding,
                      self.area.width - padding * 2, self.area.height - padding * 2)
        if rect.width() < 20 or rect.height() < 20:
            return False
        origin = QPointF(self.x, self.y - self.BODY_HEIGHT / 2 * self.pose.scale_y)
        x = clamp(origin.x(), rect.left(), rect.right())
        y = clamp(origin.y(), rect.top(), rect.bottom())
        width, height = rect.width(), rect.height()
        choices = [(QPointF(x, rect.top()), x - rect.left()),
                   (QPointF(rect.right(), y), width + y - rect.top()),
                   (QPointF(x, rect.bottom()), width + height + rect.right() - x),
                   (QPointF(rect.left(), y), width * 2 + height + rect.bottom() - y)]
        _point, distance = min(choices, key=lambda pair: (pair[0] - origin).manhattanLength())
        self._roll_rect, self._roll_start_distance = rect, distance
        perimeter = 2.0 * (width + height)
        self._roll_revolutions = max(4, round(perimeter / (math.tau * self.BODY_HEIGHT / 2)))
        return True

    def perform_trick(self, trick: str, *, roll_padding: float = 140.0) -> bool:
        durations = {"flip": 1.1, "clone": 2.5, "ball": 5.0, "screen_roll": 12.0}
        if (trick not in durations or self._trick or self.held or self.dragging
                or self.flat or not (self.grounded or self.pinned)):
            return False
        if trick == "screen_roll" and not self._prepare_screen_roll(roll_padding):
            return False
        self._trick = trick
        if trick == "screen_roll":
            self.angle = self.target_angle = 0.0
        self._trick_started = self.elapsed
        self._trick_duration = durations[trick]
        self._trick_jump_height = min(170.0, max(0.0,
            self.y - self.area.top - self.BODY_HEIGHT * self.buff.get("scale", 1.0) - 65.0))
        self.vx = self.vy = 0.0
        if trick == "ball":
            self.ball_x, self.ball_y = 0.0, -self.BODY_HEIGHT * self.pose.scale_y - 75.0
            self.ball_vx, self.ball_vy = 145.0, -30.0
        self._celebration_hops = 0
        self.happy_until = self.elapsed + self._trick_duration + 0.8
        return True

    def _advance_ball(self, duration: float) -> None:
        if self._trick != "ball":
            return
        steps = max(1, math.ceil(duration / self.MAX_STEP))
        dt = duration / steps
        for _ in range(steps):
            self.ball_x += self.ball_vx * dt
            self.ball_y += self.ball_vy * dt + 0.5 * 680.0 * dt * dt
            self.ball_vy += 680.0 * dt
            if abs(self.ball_x) > 145.0:
                self.ball_x = clamp(self.ball_x, -145.0, 145.0)
                self.ball_vx *= -0.94
            head = -self.BODY_HEIGHT * self.pose.scale_y + self.visual_offset.y() - 12.0
            floor = head if abs(self.ball_x) <= self.BODY_WIDTH * self.pose.scale_x * 0.5 else -12.0
            if self.ball_y >= floor and self.ball_vy > 0:
                self.ball_y = floor
                self.ball_vy = -max(190.0, self.ball_vy * 0.82)
                self.happy_until = self.elapsed + 0.8

    def cancel_trick(self) -> None:
        self._trick = ""
        self._trick_duration = 0.0

    def reset(self, area: WorkArea | None = None) -> None:
        if area is not None:
            self.area = area
        self.vx = self.vy = 0.0
        self.angle = self.target_angle = 0.0
        self.spring = self.spring_velocity = 0.0
        self.dragging = self.held = False
        self.cancel_trick()
        self.grounded = True
        self.happy_until = 0.0
        self._celebration_hops = 0
        self.x = self.area.right - self.BODY_WIDTH / 2 - 48.0
        self.y = self.area.bottom
        self._confine_horizontal()
        self._align_with_floor()

    def set_work_area(self, area: WorkArea) -> None:
        if area == self.area:
            return
        old_bottom = self.area.bottom
        if self._trick == "screen_roll":
            self.cancel_trick()
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
        if self._trick == "screen_roll":
            self.cancel_trick()
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
        self.manual_flat = bool(enabled)
        if self.manual_flat:
            self.cancel_trick()

    def set_starving(self, enabled: bool) -> None:
        was_flat = self.flat
        self.starving = bool(enabled)
        if self.starving:
            self.cancel_trick()
            self._celebration_hops = 0
            if self.vy < 0 and not self.held:
                self.vy = 0.0
        elif was_flat and not self.flat:
            self.rebound()

    def rebound(self) -> None:
        self.spring = -0.29
        self.spring_velocity = 0.0
        self.happy_until = self.elapsed + 0.8

    def celebrate(self) -> None:
        self.happy_until = self.elapsed + 2.5
        if self.flat:
            self.rebound()
            return
        self._celebration_hops = 3
        self._next_celebration_at = self.elapsed

    def set_buff(self, buff: dict) -> None:
        was_running = self.buff.get("behavior_remaining", 0) > 0
        self.buff = dict(buff)
        if was_running and not self.buff.get("behavior_remaining", 0):
            self.vx = 0.0
        if self.grounded and not self.pinned:
            self._align_with_floor()
            self._confine_horizontal()

    def get_dizzy(self) -> None:
        self.dizzy_until = self.elapsed + 3.0

    def hold(self) -> None:
        self.held = True

    def begin_drag(self) -> None:
        self.cancel_trick()
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
        if not self.pinned and not self.flat and not self._trick:
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
        if self._trick and self.elapsed - self._trick_started >= self._trick_duration:
            trick = self._trick
            self.cancel_trick()
            self.rebound()
            if trick == "flip":
                self._squash_on_landing(520.0)
        if (self._celebration_hops and not self._trick and not self.held and not self.flat
                and self.elapsed >= self._next_celebration_at
                and (self.grounded or self.pinned)):
            self.rebound()
            if not self.pinned:
                self.grounded = False
                self.vy = -self.CLICK_JUMP_SPEED * 1.1
            self._celebration_hops -= 1
            self._next_celebration_at = self.elapsed + 0.4
        duration = min(elapsed_seconds, self.MAX_FRAME_DELTA)
        if self.buff:
            self.buff["remaining_seconds"] = max(0.0, self.buff.get("remaining_seconds", 0) - duration)
            self.buff["behavior_remaining"] = max(0.0, self.buff.get("behavior_remaining", 0) - duration)
            if self.buff["remaining_seconds"] <= 0:
                self.set_buff({})
        running = self.buff.get("behavior_remaining", 0) > 0 and not self.flat
        if running and not self.held and not self._trick:
            if self.pinned:
                if self.elapsed >= self._next_spicy_at:
                    self.rebound()
                    self._next_spicy_at = self.elapsed + 0.16
            else:
                self.vx = self._run_direction * 280.0
                if self.grounded and self.elapsed >= self._next_spicy_at:
                    self.vy = -155.0
                    self.grounded = False
                    self._next_spicy_at = self.elapsed + 0.22
        self._advance_ball(duration)
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

            if self.pinned or self._trick:
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
            if running and abs(self.vx) > 1:
                self._run_direction = 1.0 if self.vx > 0 else -1.0
        return impact


class SkinRenderer(QObject):
    """Load canonical PNGs or the expression mapping, without changing originals.

    Expressions with floating effects can use their largest connected component
    as the physical body. The complete artwork, including stars, still renders.
    """

    frame_changed = Signal()
    CACHE_EDGE = 768
    CUSTOM_CACHE_EDGE = 512

    def __init__(self, skin_directory: Path) -> None:
        super().__init__()
        self.skin_directory = Path(skin_directory)
        self.movies: dict[PetState, QMovie] = {}
        self._movie_states: dict[QMovie, list[PetState]] = {}
        self._active_movie: QMovie | None = None
        self.anchor_rects: dict[PetState, QRectF] = {}
        self.content_rects: dict[PetState, QRectF] = {}
        self.accessories = {"head": "", "face": "", "effect": "", "offset_y": 0}
        self.pixmaps: dict[PetState, QPixmap] = {}
        self.tint_cache: dict[tuple[PetState, str], QPixmap] = {}
        self.images: dict[PetState, QImage] = {}
        self.draw_rects: dict[PetState, QRectF] = {}
        self.source_paths: dict[PetState, Path] = {}
        self.reload()

    @staticmethod
    def _guard_path(path: Path) -> None:
        from save_manager import SkinImportError, SkinManager
        try:
            SkinManager._no_links(path)
        except SkinImportError as error:
            raise ValueError(str(error)) from error

    def _configuration(self) -> dict:
        # User packages use the same safe state table as the importer. The
        # runtime checks paths again because files can be edited after import.
        manifest = self.skin_directory / "manifest.json"
        file_path = manifest if manifest.is_file() else self.skin_directory / "expressions.json"
        if not file_path.is_file():
            return {}
        try:
            from save_manager import SkinImportError, SkinManager
            try:
                payload = SkinManager._read_file(file_path, 65536)
            except SkinImportError as error:
                raise ValueError(str(error)) from error
            config = json.loads(payload.decode("utf-8-sig"))
            if not isinstance(config, dict) or config.get("schema_version", 1) != 1:
                raise ValueError("需要 schema_version=1 的对象")
            files = config.get("states", config.get("files", {}))
            if not isinstance(files, dict) or not all(isinstance(v, str) for v in files.values()):
                raise ValueError("状态必须映射到相对文件名")
            config["files"] = files
            config["custom"] = file_path == manifest
            return config
        except (OSError, UnicodeError, ValueError) as error:
            LOGGER.warning("表情配置不可用，回退标准文件名：%s", error)
            return {}

    def stop(self) -> None:
        self._active_movie = None
        for movie in set(self.movies.values()):
            movie.stop()

    def _dispose_movies(self) -> None:
        self.stop()
        for movie in set(self.movies.values()):
            movie.frameChanged.disconnect()
            movie.finished.disconnect()
            movie.deleteLater()
        self.movies.clear()
        self._movie_states.clear()

    def set_accessories(self, accessories: dict) -> None:
        values = accessories if isinstance(accessories, dict) else {}
        self.accessories = {
            "head": values.get("head") if values.get("head") in {"sprout", "crown", "bow"} else "",
            "face": "sunglasses" if values.get("face") == "sunglasses" else "",
            "effect": "steam" if values.get("effect") == "steam" else "",
            "offset_y": int(clamp(values.get("offset_y", 0), -30, 30))
                if isinstance(values.get("offset_y", 0), (int, float))
                and math.isfinite(values.get("offset_y", 0)) else 0,
        }
        self.frame_changed.emit()

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

    @staticmethod
    def _bounded_image(image: QImage, edge: int) -> QImage:
        if image.isNull() or max(image.width(), image.height()) <= edge:
            return image
        ratio = edge / max(image.width(), image.height())
        width = max(1, round(image.width() * ratio))
        height = max(1, round(image.height() * ratio))
        # KeepAspectRatio can round an 8192x1 strip to 512x0. One physical
        # texture pixel is the closest representable dimension at this bound.
        return image.scaled(width, height, Qt.AspectRatioMode.IgnoreAspectRatio,
                            Qt.TransformationMode.SmoothTransformation)

    @staticmethod
    def _visible_alpha_box(image: QImage) -> tuple[int, int, int, int] | None:
        """Find visible bounds without per-pixel Python work on GIF frames."""
        width, height = image.width(), image.height()
        alpha = bytes(image.constBits())[3::4]
        opaque = alpha.translate(bytes(1 if value > 12 else 0 for value in range(256)))
        first, last = opaque.find(b"\x01"), opaque.rfind(b"\x01")
        if first < 0:
            return None
        top, bottom = first // width, last // width + 1
        left, right = width, 0
        for y in range(top, bottom):
            row = opaque[y * width:(y + 1) * width]
            start = row.find(b"\x01")
            if start >= 0:
                left, right = min(left, start), max(right, row.rfind(b"\x01") + 1)
        return left, top, right, bottom

    @classmethod
    def _gif_reference_box(cls, reader: QImageReader, first_image: QImage,
                           frame_count: int) -> tuple[int, int, int, int]:
        # Use one fixed union of visible content. Transparent GIF padding never
        # lifts the visible feet or head ornaments; moving frame parts keep one
        # stable scale. Frames are decoded one at a time and immediately freed.
        union = None
        image = first_image
        for index in range(min(frame_count, 200)):
            if index:
                image = cls._bounded_image(reader.read(), cls.CUSTOM_CACHE_EDGE)
                if image.isNull():
                    raise ValueError("GIF 后续帧无法解码")
                image = image.convertToFormat(QImage.Format.Format_RGBA8888)
            box = cls._visible_alpha_box(image)
            if box is not None:
                union = box if union is None else (min(union[0], box[0]), min(union[1], box[1]),
                                                   max(union[2], box[2]), max(union[3], box[3]))
        if union is None:
            raise ValueError("GIF 所有帧均透明")
        return union

    def reload(self) -> None:
        self._dispose_movies()
        self.pixmaps.clear()
        self.tint_cache.clear()
        self.images.clear()
        self.draw_rects.clear()
        self.anchor_rects.clear()
        self.content_rects.clear()
        self.source_paths.clear()
        try:
            self._guard_path(self.skin_directory)
        except (ValueError, OSError) as error:
            LOGGER.warning("皮肤目录不安全，使用兜底：%s", error)
            return
        config = self._configuration()
        movies_by_path: dict[Path, QMovie] = {}
        for state in PetState:
            filename = config.get("files", {}).get(state.value, f"{state.value}.png")
            canonical = self.skin_directory / f"{state.value}.png"
            file_path = self.skin_directory / filename
            if not config.get("custom") and canonical.is_file():
                file_path = canonical
            try:
                self._guard_path(file_path)
                if ("\\" in filename or ":" in filename or ".." in Path(filename).parts
                        or Path(filename).is_absolute() or file_path.is_symlink()
                        or not file_path.resolve().is_relative_to(self.skin_directory.resolve())):
                    raise ValueError("状态路径不在本地皮肤目录内")
                if not file_path.is_file():
                    continue
                if file_path.suffix.lower() not in {".png", ".gif"} or file_path.stat().st_size > 20 * 1024 * 1024:
                    raise ValueError("只允许不超过 20 MiB 的 PNG/GIF")
                reader = QImageReader(str(file_path))
                reader.setAutoTransform(True)
                if not reader.canRead() or bytes(reader.format()).lower() != file_path.suffix[1:].lower().encode("ascii"):
                    raise ValueError("文件内容与 PNG/GIF 扩展名不符")
                size = reader.size()
                if file_path.suffix.lower() == ".gif":
                    from save_manager import SkinImportError, SkinManager
                    with file_path.open("rb") as stream:
                        payload = stream.read(20 * 1024 * 1024 + 1)
                    if len(payload) > 20 * 1024 * 1024:
                        raise ValueError("GIF 超过 20 MiB")
                    try:
                        logical_width, logical_height, _frames = SkinManager._gif_structure(payload)
                    except SkinImportError as error:
                        raise ValueError(str(error)) from error
                    # QImageReader.size() can describe the first image block;
                    # the GIF logical canvas may be much larger than it.
                    size.setWidth(logical_width)
                    size.setHeight(logical_height)
                if (not size.isValid() or max(size.width(), size.height()) > 8192
                        or size.width() * size.height() > 16_777_216):
                    raise ValueError("图片原始尺寸超过安全范围")
                animated = file_path.suffix.lower() == ".gif" and reader.imageCount() > 1
                if animated and reader.imageCount() > 200:
                    raise ValueError("GIF 不得超过 200 帧")
                edge = self.CUSTOM_CACHE_EDGE if config.get("custom") or animated else self.CACHE_EDGE
                scaled_size = (size.scaled(edge, edge, Qt.AspectRatioMode.KeepAspectRatio)
                               if max(size.width(), size.height()) > edge else size)
                scaled_size.setWidth(max(1, scaled_size.width()))
                scaled_size.setHeight(max(1, scaled_size.height()))
                if max(size.width(), size.height()) > edge:
                    reader.setScaledSize(scaled_size)
                image = self._bounded_image(reader.read(), edge)
                if image.isNull():
                    raise ValueError("无法解码图片")
                has_alpha = image.hasAlphaChannel()
                image = image.convertToFormat(QImage.Format.Format_RGBA8888)
                if (file_path.suffix.lower() == ".png"
                        and ((config.get("remove_connected_white") is True and not has_alpha)
                             or config.get("remove_white_background") is True)):
                    image = self._remove_connected_white(image)
                largest_body = config.get("fit") == "largest_body_contain"
                if animated:
                    bx1, by1, bx2, by2 = self._gif_reference_box(reader, image, reader.imageCount())
                    draw_scale = min(PetEngine.BODY_WIDTH / (bx2 - bx1),
                                     PetEngine.BODY_HEIGHT / (by2 - by1),
                                     256.0 / max(image.width(), image.height()))
                    draw_rect = QRectF(-(bx1 + bx2) * draw_scale / 2,
                                       -by2 * draw_scale,
                                       image.width() * draw_scale, image.height() * draw_scale)
                    anchor_rect = QRectF(-(bx2 - bx1) * draw_scale / 2,
                                         -(by2 - by1) * draw_scale,
                                         (bx2 - bx1) * draw_scale, (by2 - by1) * draw_scale)
                else:
                    boxes = self._foreground_boxes(image, largest_body)
                    if boxes is None:
                        raise ValueError("图片全透明")
                    foreground, body = boxes
                    left, top, right, bottom = foreground
                    image = image.copy(left, top, right - left, bottom - top)
                    if largest_body:
                        bx1, by1, bx2, by2 = body
                        scale = min(PetEngine.BODY_WIDTH / (bx2 - bx1),
                                    PetEngine.BODY_HEIGHT / (by2 - by1))
                        draw_rect = QRectF((left - (bx1 + bx2) / 2) * scale,
                                          (top - by2) * scale,
                                          image.width() * scale, image.height() * scale)
                        anchor_rect = QRectF(-(bx2 - bx1) * scale / 2,
                                             -(by2 - by1) * scale,
                                             (bx2 - bx1) * scale, (by2 - by1) * scale)
                    elif config.get("custom"):
                        scale = min(PetEngine.BODY_WIDTH / image.width(),
                                    PetEngine.BODY_HEIGHT / image.height())
                        draw_rect = QRectF(-image.width() * scale / 2, -image.height() * scale,
                                          image.width() * scale, image.height() * scale)
                        anchor_rect = QRectF(draw_rect)
                    else:
                        draw_rect = anchor_rect = self.body_rect()
                image.setDevicePixelRatio(1.0)
                self.images[state] = image
                self.pixmaps[state] = QPixmap.fromImage(image)
                self.draw_rects[state] = draw_rect
                self.anchor_rects[state] = anchor_rect
                self.content_rects[state] = QRectF(anchor_rect if animated else draw_rect)
                self.source_paths[state] = file_path
                if animated:
                    resolved = file_path.resolve()
                    movie = movies_by_path.get(resolved)
                    if movie is None:
                        movie = QMovie(str(file_path), parent=self)
                        movie.setCacheMode(QMovie.CacheMode.CacheNone)
                        movie.setScaledSize(scaled_size)
                        if not movie.isValid():
                            movie.deleteLater()
                            raise ValueError("GIF 动画不可用")
                        movies_by_path[resolved] = movie
                        self._movie_states[movie] = []
                        movie.frameChanged.connect(lambda _frame, item=movie: self._movie_frame(item))
                        movie.finished.connect(lambda item=movie: self._restart_movie(item))
                    self.movies[state] = movie
                    self._movie_states[movie].append(state)
            except (OSError, ValueError, RuntimeError) as error:
                LOGGER.warning("跳过不可用皮肤 %s：%s", state.value, error)
        self._activate_movie(PetState.IDLE)

    def _restart_movie(self, movie: QMovie) -> None:
        if self._active_movie is movie:
            movie.start()

    def _activate_movie(self, state: PetState) -> None:
        source = self.source_state(state)
        movie = self.movies.get(source)
        if movie is self._active_movie:
            return
        if self._active_movie is not None:
            self._active_movie.stop()
        self._active_movie = movie
        if movie is not None:
            movie.start()

    def _movie_frame(self, movie: QMovie) -> None:
        image = self._bounded_image(movie.currentImage(), self.CUSTOM_CACHE_EDGE)
        if image.isNull():
            return
        image = image.convertToFormat(QImage.Format.Format_RGBA8888)
        image.setDevicePixelRatio(1.0)
        for state in self._movie_states.get(movie, []):
            self.images[state] = image
            self.pixmaps[state] = QPixmap.fromImage(image)
            # Invalidate only the current frame, never accumulate frame caches.
            for key in [key for key in self.tint_cache if key[0] == state]:
                del self.tint_cache[key]
        self.frame_changed.emit()

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
        offset = engine.visual_offset
        transform.translate(foot.x() + offset.x(), foot.y() + offset.y())
        transform.rotate(pose.angle)
        transform.scale(pose.scale_x, pose.scale_y)
        if engine.visual_angle:
            transform.translate(0, -PetEngine.BODY_HEIGHT / 2)
            transform.rotate(engine.visual_angle)
            transform.translate(0, PetEngine.BODY_HEIGHT / 2)
        return transform

    def screen_roll_padding(self) -> float:
        """A rotation envelope for every expression, current ornaments and 1.2x Buff."""
        radius = 0.0
        center_y = -PetEngine.BODY_HEIGHT / 2
        for state in PetState:
            rect = self.visible_rect(state).united(self.accessory_bounds(state))
            for x in (rect.left(), rect.right()):
                for y in (rect.top(), rect.bottom()):
                    radius = max(radius, math.hypot(x, y - center_y))
        # 1.033 breathing with inverse width, maximum 1.2 Buff, plus antialiasing.
        return max(120.0, radius * 1.06 * 1.2 + 8.0)

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

    def tinted_pixmap(self, state: PetState, color: str) -> QPixmap:
        key = (state, color)
        if key not in self.tint_cache:
            if len(self.tint_cache) >= 32:
                self.tint_cache.clear()
            image = self.pixmaps[state].copy()
            tint = QColor(color)
            tint.setAlphaF(0.35)
            overlay = QPainter(image)
            overlay.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
            overlay.fillRect(image.rect(), tint)
            overlay.end()
            self.tint_cache[key] = image
        return self.tint_cache[key]

    def anchor_rect(self, state: PetState) -> QRectF:
        source = self.source_state(state)
        return QRectF(self.anchor_rects[source]) if source is not None else self.body_rect()

    def visible_rect(self, state: PetState) -> QRectF:
        source = self.source_state(state)
        return QRectF(self.content_rects[source]) if source is not None else self.body_rect()

    def accessory_bounds(self, state: PetState) -> QRectF:
        body = self.anchor_rect(state)
        result = QRectF(body)
        offset = self.accessories["offset_y"]
        top = body.top() + offset
        if self.accessories["head"]:
            result = result.united(QRectF(body.center().x() - 35, top - 38, 70, 48))
        if self.accessories["face"]:
            result = result.united(QRectF(body.left() - 5, body.top() + body.height() * 0.42 + offset - 15,
                                          body.width() + 10, 30))
        if self.accessories["effect"]:
            result = result.united(QRectF(body.center().x() - 63, top - 72, 126, 75))
        return result

    def _clone_offsets(self, engine: PetEngine) -> list[tuple[float, float, float]]:
        if engine.active_trick != "clone":
            return []
        progress = engine.trick_progress
        envelope = clamp(min(progress / 0.14, (1 - progress) / 0.14), 0, 1)
        envelope = envelope * envelope * (3 - 2 * envelope)
        time = engine.elapsed - engine._trick_started
        return [(side * 152.0 * envelope,
                 -abs(math.sin(time * math.tau * 1.25 + (0.4 if side > 0 else 0))) * 25 * envelope,
                 0.42 * envelope) for side in (-1, 1)]

    def scene_bounds(self, engine: PetEngine, foot: QPointF) -> QRectF:
        source = self.source_state(engine.state)
        body = self.visible_rect(engine.state)
        local = body.united(self.accessory_bounds(engine.state))
        result = self.body_transform(engine, foot).mapRect(local)
        for dx, dy, _opacity in self._clone_offsets(engine):
            result = result.united(self.body_transform(engine, foot + QPointF(dx, dy)).mapRect(local))
        if engine.active_trick == "ball":
            result = result.united(QRectF(foot.x() + engine.ball_x - 14,
                                          foot.y() + engine.ball_y - 14, 28, 28))
        if engine.buff.get("item_id") == "strawberry":
            offset = engine.visual_offset
            result = result.united(QRectF(foot.x() + offset.x() - 90, foot.y() + offset.y() - 165, 180, 170))
        return result.adjusted(-3, -3, 3, 3)

    def paint(self, painter: QPainter, engine: PetEngine, foot: QPointF) -> None:
        self._activate_movie(engine.state)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        for dx, dy, opacity in self._clone_offsets(engine):
            self._paint_instance(painter, engine, foot + QPointF(dx, dy), opacity)
        self._paint_instance(painter, engine, foot, 1.0)
        if engine.active_trick == "ball":
            self._paint_ball(painter, foot + QPointF(engine.ball_x, engine.ball_y))
        if engine.buff.get("item_id") == "strawberry":
            painter.setPen(Qt.PenStyle.NoPen)
            for index in range(9):
                phase = (engine.elapsed * 0.20 + index / 9) % 1.0
                x = foot.x() + engine.visual_offset.x() + math.sin(index * 2.4) * (70 + phase * 12)
                y = foot.y() - 8 - phase * 145 + engine.visual_offset.y()
                color = QColor("#efa3c2")
                color.setAlphaF(0.5 * math.sin(math.pi * phase))
                painter.setBrush(color)
                painter.drawEllipse(QPointF(x, y), 2.0 + index % 3, 2.0 + index % 3)
        painter.restore()

    def _paint_instance(self, painter: QPainter, engine: PetEngine, foot: QPointF, opacity: float) -> None:
        painter.save()
        painter.setOpacity(painter.opacity() * opacity)
        painter.setTransform(self.body_transform(engine, foot), combine=True)
        source = self.source_state(engine.state)
        if source is not None:
            color = engine.buff.get("color")
            pixmap = self.tinted_pixmap(source, color) if color else self.pixmaps[source]
            painter.drawPixmap(self.draw_rects[source], pixmap, QRectF(pixmap.rect()))
        else:
            self.paint_fallback(painter)
            if engine.buff.get("color"):
                tint = QColor(engine.buff["color"])
                tint.setAlphaF(0.35)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(tint)
                painter.drawEllipse(self.body_rect())
        self._paint_accessories(painter, engine)
        painter.restore()

    def _paint_accessories(self, painter: QPainter, engine: PetEngine) -> None:
        rect = self.anchor_rect(engine.state)
        offset = self.accessories["offset_y"]
        head = self.accessories["head"]
        painter.save()
        painter.translate(rect.center().x(), rect.top() + offset)
        if self.accessories["effect"] == "steam":
            for index in range(4):
                phase = (engine.elapsed * 0.32 + index * 0.25) % 1
                x = (index - 1.5) * 26
                y = -8 - phase * 49
                color = QColor("#e6bc87")
                color.setAlphaF(0.62 * math.sin(math.pi * phase))
                painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                path = QPainterPath(QPointF(x, y + 9))
                path.cubicTo(x - 8, y + 3, x + 8, y - 3, x, y - 10)
                painter.drawPath(path)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(245, 204, 116, int(150 * math.sin(math.pi * phase))))
                painter.drawEllipse(QPointF(x + 9, y - 5), 1.8, 1.8)
        if head == "sprout":
            painter.setPen(QPen(QColor("#5f9965"), 3.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            stem = QPainterPath(QPointF(0, 2))
            stem.cubicTo(-5, -8, 4, -15, 1, -25)
            painter.drawPath(stem)
            painter.setPen(QPen(QColor("#6b9f65"), 1.0))
            painter.setBrush(QColor("#a5d289"))
            leaf = QPainterPath(QPointF(1, -15))
            leaf.cubicTo(-20, -29, -23, -11, 1, -15)
            painter.drawPath(leaf)
            painter.setBrush(QColor("#b9dba1"))
            leaf = QPainterPath(QPointF(1, -20))
            leaf.cubicTo(19, -37, 26, -18, 1, -20)
            painter.drawPath(leaf)
        elif head == "crown":
            painter.setPen(QPen(QColor("#d19a3b"), 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                                Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QColor("#f8d675"))
            painter.drawPolygon(QPolygonF([QPointF(-25, -4), QPointF(-29, -28), QPointF(-13, -18),
                                           QPointF(0, -35), QPointF(13, -18), QPointF(29, -28),
                                           QPointF(25, -4)]))
            painter.setBrush(QColor("#f5c65d"))
            painter.drawRoundedRect(QRectF(-25, -8, 50, 10), 3, 3)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#e897a8"))
            painter.drawEllipse(QPointF(0, -15), 4, 5)
            painter.setBrush(QColor("#fff5cf"))
            for x, y in [(-29, -29), (0, -35), (29, -29)]:
                painter.drawEllipse(QPointF(x, y), 3.1, 3.1)
        elif head == "bow":
            painter.setPen(QPen(QColor("#cf819b"), 1.5))
            painter.setBrush(QColor("#f4b2c8"))
            for side in (-1, 1):
                wing = QPainterPath(QPointF(0, -8))
                wing.cubicTo(side * 32, -35, side * 32, 5, 0, -8)
                painter.drawPath(wing)
            painter.setBrush(QColor("#ef9ab7"))
            painter.drawRoundedRect(QRectF(-5, -14, 10, 13), 4, 4)
        painter.restore()
        if self.accessories["face"] == "sunglasses":
            painter.save()
            painter.translate(rect.center().x(), rect.top() + rect.height() * 0.42 + offset)
            width = min(94.0, rect.width() * 0.82)
            lens = width * 0.42
            painter.setPen(QPen(QColor("#373241"), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(QColor("#443d50"))
            painter.drawRoundedRect(QRectF(-width / 2, -9, lens, 19), 5, 5)
            painter.drawRoundedRect(QRectF(width / 2 - lens, -9, lens, 19), 5, 5)
            painter.drawLine(QPointF(-width * 0.08, -4), QPointF(width * 0.08, -4))
            painter.drawLine(QPointF(-width / 2 - 4, -6), QPointF(-width / 2, -5))
            painter.drawLine(QPointF(width / 2, -5), QPointF(width / 2 + 4, -6))
            painter.setPen(QPen(QColor("#a3a0b7"), 1.6))
            painter.drawLine(QPointF(-width * 0.37, -5), QPointF(-width * 0.23, 1))
            painter.drawLine(QPointF(width * 0.16, -5), QPointF(width * 0.30, 1))
            painter.restore()

    @staticmethod
    def _paint_ball(painter: QPainter, center: QPointF) -> None:
        painter.save()
        painter.translate(center)
        gradient = QLinearGradient(-9, -12, 9, 12)
        gradient.setColorAt(0, QColor("#676170"))
        gradient.setColorAt(1, QColor("#292731"))
        painter.setPen(QPen(QColor("#24212c"), 1.0))
        painter.setBrush(gradient)
        painter.drawEllipse(QPointF(), 12, 12)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#d9c69f"))
        for x, y, angle in [(-5, -4, -20), (3, -6, 30), (6, 2, -10), (-3, 5, 40)]:
            painter.save()
            painter.translate(x, y)
            painter.rotate(angle)
            painter.drawEllipse(QRectF(-1, -2, 2, 4))
            painter.restore()
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
