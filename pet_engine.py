"""Phase 1: state, elapsed-time physics, and a skin-independent renderer.

All distances are Qt logical pixels. x, y denotes the body's bottom-centre
anchor in desktop coordinates, never the window's top-left.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from typing import Callable
from enum import Enum
import logging
import json
import math
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QFontMetricsF, QImage, QImageReader, QLinearGradient, QMovie, QPainter, QPainterPath, QPen, QPolygonF, QRadialGradient,
    QPixmap, QTransform,
)

from PySide6.QtWidgets import QWidget

from illustrated_assets import plain_text
from item_expansion import paint_headwear
from content_registry import BUILTIN_REGISTRY, BUILTIN_TRICKS

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


class PresentationLifecycle(QObject):
    """One explicit foreground performance; presentation events never pay rewards.

    A token identifies one acceptance, including two consecutive uses of the same
    item. Ending an already ended token is harmless. The engine owns trick
    events; each room owns only its food/gift events and follows engine tricks.
    """
    changed = Signal(dict)
    accepted = Signal(dict)
    finished = Signal(dict)
    cancelled = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.active = None
        self._serial = 0

    def _emit(self, phase, reason="", record=None):
        event = dict(self.active if record is None else record)
        event.update(phase=phase, reason=str(reason))
        # A receiver may retain this event; never expose our mutable anchor.
        event["anchor"] = list(event["anchor"])
        self.changed.emit(event)
        getattr(self, phase).emit(event)
        return event

    def begin(self, kind, item_id, anchor):
        if self.active is not None:
            self.cancel("replaced")
        self._serial += 1
        self.active = {"kind": str(kind), "id": str(item_id),
                       "token": self._serial,
                       "anchor": [float(anchor.x()), float(anchor.y())]}
        return self._emit("accepted")

    def finish(self, reason="completed"):
        if self.active is None:
            return None
        record = self.active
        self.active = None
        return self._emit("finished", reason, record)

    def cancel(self, reason="cancelled"):
        if self.active is None:
            return None
        record = self.active
        self.active = None
        return self._emit("cancelled", reason, record)


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
        self.presentation = PresentationLifecycle()
        self.area = area
        self.elapsed = 0.0
        self.x = self.y = 0.0
        self._rest_x: float | None = None
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
        self._flash_distance = 0.0
        self.scarf_lag = 0.0
        self.goggles_flash_until = 0.0
        self.ball_x = self.ball_y = 0.0
        self.ball_vx = self.ball_vy = 0.0
        self.buff: dict = {}
        self.cooling = False
        self.skin_scale = 1.0
        self.fireworks_until = 0.0
        self.hood_flash_until = 0.0
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
        dynamic_height = breath if self._trick in {"screen_roll", "reverse_flash"} else breath * clamp(1.0 + self.spring, 0.55, 1.38)
        # Breathing and jelly motion conserve projected area. Hunger is a
        # separate deformation: flatten without excessive 2.5x widening.
        return Pose(
            (1.14 if self.flat else 1.0) / dynamic_height * self.buff.get("scale", 1.0) * self.skin_scale,
            dynamic_height * (0.4 if self.flat else 1.0) * self.buff.get("scale", 1.0) * self.skin_scale,
            self.angle + (12 * math.sin((self.elapsed - self._trick_started) * math.tau * 3) if self._trick == "disco" else 0),
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
        if self._trick == "reverse_flash":
            return self.reverse_flash_offset()
        if self._trick == "flip":
            return QPointF(0, -self._trick_jump_height * math.sin(math.pi * self.trick_progress))
        if self._trick == "disco":
            return QPointF(0, -8 * abs(math.sin((self.elapsed - self._trick_started) * math.tau * 3)))
        if self._trick == "ball":
            hop = abs(math.sin((self.elapsed - self._trick_started) * math.pi * 2.4))
            return QPointF(0, -min(12.0, self._trick_jump_height) * hop)
        return QPointF()

    def reverse_flash_offset(self, distance: float | None = None,
                             pinned: bool | None = None) -> QPointF:
        """A bounded presentation displacement, never a physical coordinate.

        A room can pass its own safe distance and pinned=False; desktop pinning
        must not suppress the independent room performance.
        """
        if self._trick != "reverse_flash":
            return QPointF()
        if (self.pinned if pinned is None else bool(pinned)):
            return QPointF()
        span = self._flash_distance if distance is None else float(distance)
        if not math.isfinite(span):
            return QPointF()
        span = clamp(span, 0.0, 60.0)
        age = clamp(self.elapsed - self._trick_started, 0.0, 2.6)
        if age < .4:
            return QPointF()
        if age < .65:
            u = (age - .4) / .25
            mix = u * u * (3 - 2 * u)
        elif age < 1.4:
            mix = 1.0
        else:
            u = (age - 1.4) / 1.2
            mix = 1.0 - u * u * (3 - 2 * u)
        return QPointF(-span * mix, 0.0)

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

    def perform_trick(self, trick: str, *, roll_padding: float = 140.0,
                      flash_distance: float | None = None) -> bool:
        if not self.can_start_trick(trick, roll_padding=roll_padding, flash_distance=flash_distance):
            return False
        if trick == "screen_roll" and not self._prepare_screen_roll(roll_padding):
            return False
        self._trick = trick
        if trick in {"screen_roll", "reverse_flash"}:
            self.angle = self.target_angle = 0.0
        if trick == "reverse_flash":
            body_left = self.x - self.BODY_WIDTH * self.pose.scale_x * .54
            safe = min(60.0, self.area.width * .08, max(0.0, body_left - self.area.left - 4))
            self._flash_distance = min(safe, 60.0 if flash_distance is None else flash_distance)
        self._trick_started = self.elapsed
        self._trick_duration = BUILTIN_TRICKS[trick].duration
        self._trick_jump_height = min(170.0, max(0.0,
            self.y - self.area.top - self.BODY_HEIGHT * self.buff.get("scale", 1.0) - 65.0))
        self.vx = self.vy = 0.0
        if trick == "ball":
            self.ball_x, self.ball_y = 0.0, -self.BODY_HEIGHT * self.pose.scale_y - 75.0
            self.ball_vx, self.ball_vy = 145.0, -30.0
        self._celebration_hops = 0
        self.happy_until = self.elapsed + self._trick_duration + 0.8
        self.presentation.begin("trick", trick, QPointF(self.x, self.y))
        return True

    def can_start_trick(self, trick: str, *, replacing: bool = False,
                        roll_padding: float = 140.0,
                        flash_distance: float | None = None) -> bool:
        """Validate before replacing a previous performance; do not move it."""
        if (trick not in BUILTIN_TRICKS or (self._trick and not replacing)
                or self.held or self.dragging or self.flat
                or self.state == PetState.DIZZY
                or not (self.grounded or self.pinned)):
            return False
        if trick == "screen_roll":
            if not math.isfinite(roll_padding) or roll_padding < 1:
                return False
            if min(self.area.width, self.area.height) - roll_padding * 2 < 20:
                return False
        if (trick == "reverse_flash" and flash_distance is not None
                and (isinstance(flash_distance, bool) or not isinstance(flash_distance, (int, float))
                     or not math.isfinite(flash_distance) or not 0 <= flash_distance <= 60)):
            return False
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

    def cancel_trick(self, reason: str = "cancelled") -> None:
        self._trick = ""
        self._trick_duration = 0.0
        self._trick_jump_height = 0.0
        self._roll_rect = QRectF()
        self._roll_start_distance = 0.0
        self._flash_distance = 0.0
        self.ball_x = self.ball_y = self.ball_vx = self.ball_vy = 0.0
        if reason == "completed":
            self.presentation.finish(reason)
        else:
            self.presentation.cancel(reason)

    def reset(self, area: WorkArea | None = None) -> None:
        self._rest_x = None
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
        self._rest_x = None
        old_bottom = self.area.bottom
        if self._trick == "screen_roll":
            self.cancel_trick("work_area_changed")
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
        self._rest_x = None
        self.cancel_trick()
        self.pinned = bool(enabled)
        self.vx = self.vy = 0.0
        self.target_angle = 0.0
        self.grounded = False

    def place(self, x: float, y: float) -> None:
        self._rest_x = None
        self.cancel_trick()
        self.spring = self.spring_velocity = 0.0
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
        self._remember_rest_x()
        self.spring = -0.29
        self.spring_velocity = 0.0
        self.happy_until = self.elapsed + 0.8

    def enjoy_interaction(self, duration: float) -> None:
        """Both views choose the same expression, so multi-state QMovies agree."""
        if not self.flat:
            self.happy_until = max(self.happy_until, self.elapsed + clamp(float(duration), .8, 20.0))

    def celebrate(self) -> None:
        self.happy_until = self.elapsed + 2.5
        if self.flat:
            self.rebound()
            return
        self._celebration_hops = 3
        self._next_celebration_at = self.elapsed

    def set_buff(self, buff: dict) -> None:
        self._remember_rest_x()
        was_running = self.buff.get("behavior_remaining", 0) > 0
        self.buff = dict(buff)
        if was_running and not self.buff.get("behavior_remaining", 0):
            self.vx = 0.0
        if self.grounded and not self.pinned:
            if self._rest_x is not None:
                self.x = self._rest_x
            self._align_with_floor()
            self._confine_horizontal()

    def get_dizzy(self) -> None:
        self.dizzy_until = self.elapsed + 3.0

    def hold(self) -> None:
        self.held = True

    def begin_drag(self) -> None:
        self._rest_x = None
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
        self._remember_rest_x()
        self.held = False
        self.happy_until = self.elapsed + 0.8
        self.spring = min(self.spring, -0.29)
        self.spring_velocity = 0.0
        # One deadline, not a queue of flashes: rapid pokes merge into one glint.
        self.goggles_flash_until = self.elapsed + .55
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

    def _remember_rest_x(self) -> None:
        """Keep a resting anchor separate from temporary squash edge clearance."""
        if (self._rest_x is None and self.grounded and not self.held and not self.dragging
                and abs(self.vx) < .5 and not self.pinned
                and not self.buff.get("behavior_remaining", 0)):
            self._rest_x = self.x

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
        self._remember_rest_x()
        self.elapsed += elapsed_seconds
        if self._trick and self.elapsed - self._trick_started >= self._trick_duration:
            trick = self._trick
            self.cancel_trick("completed")
            self.rebound()
            if trick == "flip":
                self.hood_flash_until = self.elapsed + 1.4
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
        if running or abs(self.vx) >= .5:
            self._rest_x = None
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
            scarf_target = clamp(-target * 1.35, -25.0, 25.0) if self.dragging else 0.0
            self.scarf_lag += (scarf_target - self.scarf_lag) * (1.0 - math.exp(-8.0 * dt))
            if abs(self.angle) < 0.002 and target == 0.0:
                self.angle = 0.0

            if self.held:
                if self.dragging:
                    self._confine_drag()
                continue

            if self.pinned or self._trick:
                continue

            if self._rest_x is not None:
                self.x = self._rest_x

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
            # A stationary body's widening may require temporary clearance, but
            # must not turn that visual correction into a throw or a new home.
            self._confine_horizontal(reflect=self._rest_x is None)
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
        self._flash_snapshots: dict[str, tuple] = {}
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

    @staticmethod
    def normalize_accessories(accessories: dict) -> dict:
        values = accessories if isinstance(accessories, dict) else {}
        choices = BUILTIN_REGISTRY.accessory_choices
        result = {
            "head": values.get("head") if values.get("head") in choices["head"] else "",
            "face": values.get("face") if values.get("face") in choices["face"] else "",
            "effect": values.get("effect") if values.get("effect") in choices["effect"] else "",
            "offset_y": int(clamp(values.get("offset_y", 0), -30, 30))
                if isinstance(values.get("offset_y", 0), (int, float))
                and math.isfinite(values.get("offset_y", 0)) else 0,
        }
        if values.get("back") in choices["back"] and values.get("back"):
            result["back"] = values["back"]
        return result

    def set_accessories(self, accessories: dict) -> None:
        self.accessories = self.normalize_accessories(accessories)
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
        transform.scale(pose.scale_x * getattr(engine, "yaw_scale", 1.0), pose.scale_y)
        if engine.visual_angle:
            transform.translate(0, -PetEngine.BODY_HEIGHT / 2)
            transform.rotate(engine.visual_angle)
            transform.translate(0, PetEngine.BODY_HEIGHT / 2)
        return transform

    def screen_roll_padding(self, scale_multiplier: float = 1.0) -> float:
        """A rotation envelope for every expression, current ornaments and 1.2x Buff."""
        radius = 0.0
        center_y = -PetEngine.BODY_HEIGHT / 2
        for state in PetState:
            rect = self.visible_rect(state).united(self.accessory_bounds(state))
            for x in (rect.left(), rect.right()):
                for y in (rect.top(), rect.bottom()):
                    radius = max(radius, math.hypot(x, y - center_y))
        # 1.033 breathing with inverse width, maximum 1.2 Buff, plus antialiasing.
        return max(120.0, radius * 1.06 * 1.2 * scale_multiplier + 8.0)

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
            result = result.united(QRectF(body.center().x() - 44, top - 45, 88, 60))
        if self.accessories["face"]:
            result = result.united(QRectF(body.left() - 5, body.top() + body.height() * 0.42 + offset - 15,
                                          body.width() + 10, 30))
        if self.accessories["effect"]:
            result = result.united(QRectF(body.center().x() - 63, top - 72, 126, 75))
        if self.accessories["effect"] in {"fireflies", "rainbow"}:
            result = result.united(body.adjusted(-38, -35, 38, 20))
        if self.accessories.get("back") == "phoenix_wings":
            result = result.united(QRectF(body.center().x()-body.width()*.95,
                                          body.top()-12+offset, body.width()*1.9, body.height()+24))
        elif self.accessories.get("back") == "summit_backpack":
            result = result.united(QRectF(body.right()-20, top+body.height()*.25-35, 57, body.height()*.7+40))
        elif self.accessories.get("back") == "kiting_scarf":
            result = result.united(QRectF(body.left()-55, top+body.height()*.42-8,
                                         body.width()+110, body.height()*.5+30))
        return result

    def _flash_neutral_bounds(self, engine: PetEngine) -> QRectF:
        """Time-independent art envelope for a pinned/free flash surface.

        Expressions, ornaments, inverse breathing and the largest supported Buff
        are included, so a GIF frame or breathing cannot resize the native Tool
        window midway through this short performance.
        """
        local = QRectF()
        for state in PetState:
            local = local.united(self.visible_rect(state).united(self.accessory_bounds(state)))
        scale = max(.6, float(engine.skin_scale)) * 1.2 * 1.065
        result = QTransform().scale(scale, scale).mapRect(local)
        return result.adjusted(-4, -38, 4, 4)

    def desktop_flash_distance(self, engine: PetEngine) -> float:
        """Shorten the visual dash using real art, never move a saved anchor."""
        extent = self._flash_neutral_bounds(engine)
        clearance = engine.x + extent.left() - engine.area.left - 5.0
        return min(60.0, engine.area.width * .08, max(0.0, clearance))

    @staticmethod
    def flash_render_distance(engine: PetEngine) -> float:
        value = getattr(engine, "flash_distance", getattr(engine, "_flash_distance", 0.0))
        return clamp(float(value), 0.0, 60.0) if isinstance(value, (int, float)) and math.isfinite(value) else 0.0

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
        if engine.active_trick == "reverse_flash":
            base = self._flash_neutral_bounds(engine).translated(foot)
            span = self.flash_render_distance(engine)
            return base.united(base.translated(-span, 0)).adjusted(-3, -3, 3, 3)
        source = self.source_state(engine.state)
        body = self.visible_rect(engine.state)
        local = body.united(self.accessory_bounds(engine.state))
        result = self.body_transform(engine, foot).mapRect(local)
        for dx, dy, _opacity in self._clone_offsets(engine):
            result = result.united(self.body_transform(engine, foot + QPointF(dx, dy)).mapRect(local))
        if engine.active_trick == "disco" or engine.elapsed < engine.fireworks_until:
            result = result.united(QRectF(foot.x() - 195, foot.y() - 390, 390, 405))
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
        if engine.active_trick == "reverse_flash":
            self._paint_flash_echo(painter, engine, foot)
        else:
            self._flash_snapshots.clear()
        for dx, dy, opacity in self._clone_offsets(engine):
            self._paint_instance(painter, engine, foot + QPointF(dx, dy), opacity)
        if engine.active_trick == "disco":
            self._paint_disco(painter, engine, foot)
        self._paint_instance(painter, engine, foot, 1.0)
        if engine.active_trick == "reverse_flash":
            self._paint_flash_sign(painter, engine, foot)
        if engine.elapsed < engine.fireworks_until:
            self._paint_fireworks(painter, engine, foot)
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

    def _paint_flash_echo(self, painter: QPainter, engine: PetEngine, foot: QPointF) -> None:
        """One frozen alpha silhouette per view/token; never accumulating trails."""
        context = type(engine).__name__
        token = (engine.presentation.active or {}).get("token", 0)
        entry = self._flash_snapshots.get(context)
        if entry is None or entry[0] != token:
            # Capture the current PNG/GIF frame once in neutral coordinates.
            class SnapshotView:
                def __init__(self, owner):
                    self.owner = owner
                    self.visual_offset = QPointF()
                    self.visual_angle = 0.0
                    self.pose = owner.pose
                    self.elapsed = owner.elapsed
                def __getattr__(self, key):
                    return getattr(self.owner, key)
            rect = self._flash_neutral_bounds(engine).toAlignedRect()
            pixmap = QPixmap(rect.size()); pixmap.fill(Qt.GlobalColor.transparent)
            capture = QPainter(pixmap); capture.setRenderHint(QPainter.RenderHint.Antialiasing)
            capture.translate(-rect.topLeft()); self._paint_instance(capture, SnapshotView(engine), QPointF(), 1.0)
            capture.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            capture.fillRect(rect, QColor("#d8ba7d")); capture.end()
            entry = (token, pixmap, QRectF(rect))
            self._flash_snapshots[context] = entry
        age = engine.elapsed - engine._trick_started
        if not .4 <= age < 2.5:
            return
        # Free bodies leave the silhouette behind; pinned bodies send only the
        # silhouette left. A room supplies its own independent visual offset.
        span = self.flash_render_distance(engine)
        moving = engine.visual_offset
        echo_offset = (engine.reverse_flash_offset(span, pinned=False)
                       if abs(moving.x()) < 1e-8 and getattr(engine, "pinned", False) else QPointF())
        opacity = .22 * min(1.0, (age - .4) / .12, max(0.0, (2.5 - age) / .55))
        painter.save(); painter.setOpacity(painter.opacity() * max(0.0, opacity))
        painter.drawPixmap(entry[2].translated(foot + echo_offset), entry[1], QRectF(entry[1].rect()))
        painter.restore()

    def _paint_flash_sign(self, painter: QPainter, engine: PetEngine, foot: QPointF) -> None:
        age = engine.elapsed - engine._trick_started
        opacity = min(1.0, age / .2, max(0.0, (2.6 - age) / .35))
        if opacity <= 0:
            return
        bounds = self._flash_neutral_bounds(engine)
        painter.save(); painter.setOpacity(painter.opacity() * opacity)
        painter.translate(foot + QPointF(0, bounds.top() + 17))
        turn = clamp((age - .65) / .75, 0, 1)
        painter.scale(math.cos(math.pi * turn), 1)
        painter.setPen(QPen(QColor("#a57a42"), 1.6, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        gradient = QLinearGradient(0, -10, 0, 10)
        gradient.setColorAt(0, QColor("#fff0b9")); gradient.setColorAt(1, QColor("#dbb76f"))
        painter.setBrush(gradient)
        painter.drawRoundedRect(QRectF(-27, -12, 54, 24), 7, 7)
        arrow = QPainterPath(QPointF(-15, 0)); arrow.lineTo(14, 0)
        arrow.moveTo(6, -6); arrow.lineTo(14, 0); arrow.lineTo(6, 6)
        painter.setPen(QPen(QColor("#8f6838"), 2.4, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(arrow); painter.restore()
        painter.save(); painter.setPen(Qt.PenStyle.NoPen)
        for index in range(2):
            pulse = .5 + .5 * math.sin(age * 9 + index * math.pi)
            color = QColor("#f0d18e"); color.setAlphaF(opacity * pulse * .6)
            painter.setBrush(color)
            painter.drawEllipse(foot + QPointF((index * 2 - 1) * 13, -8), 2.5, 2.5)
        painter.restore()

    def _paint_instance(self, painter: QPainter, engine: PetEngine, foot: QPointF, opacity: float) -> None:
        painter.save()
        painter.setOpacity(painter.opacity() * opacity)
        painter.setTransform(self.body_transform(engine, foot), combine=True)
        source = self.source_state(engine.state)
        self._paint_back_accessory(painter, engine)
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

    def _paint_back_accessory(self, painter: QPainter, engine: PetEngine) -> None:
        if self.accessories.get("back") == "kiting_scarf":
            body = self.anchor_rect(engine.state)
            lag = clamp(float(getattr(engine, "scarf_lag", 0.0)), -25, 25)
            sway = math.sin(engine.elapsed * 2.2) * 2.5
            painter.save()
            painter.translate(body.center().x(), body.top() + body.height() * .55 + self.accessories["offset_y"])
            painter.setPen(QPen(QColor("#805a4d"), 1.7, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            for side, color in ((-1, "#ba7472"), (1, "#88a7b8")):
                tip_x = side * (body.width() * .43 + 31) + lag
                tip_y = 25 + side * sway + abs(lag) * .15
                ribbon = QPainterPath(QPointF(side * 14, -3))
                ribbon.cubicTo(side * 35 + lag * .3, -8, tip_x - side * 16, tip_y - 10, tip_x, tip_y)
                ribbon.lineTo(tip_x - side * 5, tip_y + 12)
                ribbon.cubicTo(tip_x - side * 20, tip_y + 2, side * 32, 10, side * 10, 8)
                ribbon.closeSubpath()
                gradient = QLinearGradient(0, -4, 0, 40)
                gradient.setColorAt(0, QColor(color).lighter(116)); gradient.setColorAt(1, QColor(color))
                painter.setBrush(gradient); painter.drawPath(ribbon)
                painter.setPen(QPen(QColor("#e8c9b0"), 1.2))
                for i in range(3):
                    x = tip_x - side * (3 + i * 2.8)
                    painter.drawLine(QPointF(x, tip_y + 8), QPointF(x + side * 2, tip_y + 13))
                painter.setPen(QPen(QColor("#805a4d"), 1.7))
            painter.setBrush(QColor("#c48f89")); painter.drawRoundedRect(QRectF(-21, -7, 42, 15), 7, 7)
            painter.setBrush(QColor("#e4b9a3")); painter.drawEllipse(QPointF(2, 0), 8, 8)
            painter.restore(); return
        if self.accessories.get("back") == "summit_backpack":
            body=self.anchor_rect(engine.state)
            painter.save(); painter.translate(body.right()-4, body.top()+body.height()*.55+self.accessories["offset_y"])
            painter.setPen(QPen(QColor("#79523b"),2)); painter.setBrush(QColor("#d79c62"))
            painter.drawRoundedRect(QRectF(-17,-24,43,52),10,10)
            painter.setBrush(QColor("#efbf7b")); painter.drawRoundedRect(QRectF(1,2,28,21),5,5)
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.setPen(QPen(QColor("#f0d295"),2.4))
            painter.drawEllipse(QRectF(-12,-19,31,13)); painter.drawEllipse(QRectF(-7,-16,22,7))
            wave=math.sin(engine.elapsed*3)*4
            painter.setPen(QPen(QColor("#826147"),2)); painter.drawLine(QPointF(22,-7),QPointF(24+wave,-48))
            painter.setBrush(QColor("#ffe2a1" if getattr(engine,"trail_flash",False) else "#da8c75"))
            painter.drawPolygon(QPolygonF([QPointF(24+wave,-48),QPointF(38+wave,-40),QPointF(24+wave,-33)]))
            painter.restore(); return
        if self.accessories.get("back") != "phoenix_wings":
            return
        body = self.anchor_rect(engine.state)
        flap = .94 + .055 * math.sin(engine.elapsed*3.2)
        painter.save(); painter.translate(body.center().x(), body.top()+body.height()*.58+self.accessories["offset_y"])
        for side in (-1,1):
            painter.save(); painter.scale(side*body.width()/128*flap, body.height()/116)
            wing=QPainterPath(QPointF(10,15)); wing.cubicTo(37,-11,58,-46,108,-64)
            wing.cubicTo(102,-42,94,-25,80,-16)
            wing.quadTo(95,-24,105,-32); wing.cubicTo(95,-6,82,9,65,14)
            wing.quadTo(79,12,89,7); wing.cubicTo(72,34,46,41,10,15)
            gradient=QLinearGradient(30,24,106,-59)
            gradient.setColorAt(0,QColor("#c63f37")); gradient.setColorAt(.5,QColor("#ed7550")); gradient.setColorAt(1,QColor("#ffe19b"))
            painter.setBrush(gradient); painter.setPen(QPen(QColor("#8a473b"),2.4,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(wing)
            painter.setPen(QPen(QColor("#f6c071"),2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            for index in range(3):
                feather=QPainterPath(QPointF(24+index*5,17+index*2))
                feather.quadTo(58+index*4,5+index*3,96-index*8,-47+index*25)
                painter.drawPath(feather)
            painter.restore()
        painter.restore()

    def _paint_accessories(self, painter: QPainter, engine: PetEngine) -> None:
        rect = self.anchor_rect(engine.state)
        offset = self.accessories["offset_y"]
        head = self.accessories["head"]
        painter.save()
        painter.translate(rect.center().x(), rect.top() + offset)
        hot = engine.buff.get("item_id") == "chili" and not getattr(engine, "cooling", False)
        if self.accessories["effect"] == "steam":
            for index in range(4):
                cooled = getattr(engine, "cooling", False)
                phase = (engine.elapsed * (.65 if hot else .16 if cooled else .32) + index * 0.25) % 1
                x = (index - 1.5) * 26
                y = -8 - phase * 49
                color = QColor("#ce6858" if hot else "#b39e94" if cooled else "#cf8b78")
                color.setAlphaF((.3 if cooled else .68) * math.sin(math.pi * phase))
                painter.setPen(QPen(color, 2.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                path = QPainterPath(QPointF(x, y + 9))
                path.cubicTo(x - 8, y + 3, x + 8, y - 3, x, y - 10)
                painter.drawPath(path)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(228, 132, 108, int(110 * math.sin(math.pi * phase))))
                painter.drawEllipse(QPointF(x + 9, y - 5), 1.8, 1.8)
        effect = self.accessories["effect"]
        if effect == "fireflies":
            painter.setPen(Qt.PenStyle.NoPen)
            for i in range(12):
                phase = engine.elapsed * .65 + i * math.tau / 12
                x = math.cos(phase) * (rect.width() / 2 + 21)
                y = rect.height() * .55 + math.sin(phase * 1.3) * rect.height() * .6
                glow = QColor("#f7dc83"); glow.setAlphaF(.35 + .25 * math.sin(phase * 3))
                painter.setBrush(glow); painter.drawEllipse(QPointF(x, y), 6, 6)
                painter.setBrush(QColor("#fff5b8")); painter.drawEllipse(QPointF(x, y), 2, 2)
        elif effect == "rainbow":
            painter.setPen(Qt.PenStyle.NoPen)
            for side in (-1,1):
                x=side*(rect.width()*.35+8+math.sin(engine.elapsed*.7)*4)
                gradient=QLinearGradient(x,-62,0,rect.height()+8)
                gradient.setColorAt(0,QColor(255,230,168,12)); gradient.setColorAt(.7,QColor(255,239,192,65)); gradient.setColorAt(1,QColor(255,247,219,10))
                painter.setBrush(gradient)
                painter.drawPolygon(QPolygonF([QPointF(x-5,-62),QPointF(x+5,-62),QPointF(30,rect.height()+8),QPointF(-30,rect.height()+8)]))
            painter.setPen(QPen(QColor(220,185,107,145),2)); painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(-rect.width()/2-16,rect.height()-8,rect.width()+32,14))
        if head == "orange":
            painter.setPen(QPen(QColor("#79523b"), 2.0))
            painter.setBrush(QColor("#efa54d")); painter.drawEllipse(QRectF(-21, -32, 42, 33))
            painter.setBrush(QColor("#a6bd78")); painter.drawEllipse(QRectF(1, -37, 19, 8))
            painter.setBrush(QColor("#fff0b5")); painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(-13, -24, 6, 4))
            if engine.state == PetState.DIZZY:
                painter.setPen(QPen(QColor("#bb823e"),1.5)); painter.setBrush(QColor("#f5cc89"))
                for side in (-1,1):
                    spread=6+abs(math.sin(engine.elapsed*7))*6
                    painter.drawPolygon(QPolygonF([QPointF(side*12,-22),QPointF(side*(24+spread),-29),QPointF(side*(27+spread),-13),QPointF(side*13,-9)]))
        elif head in {"cooling_cap", "demon_hood", "mini_gnar_hat"}:
            paint_headwear(painter, head, engine.elapsed, bool(engine.active_trick), hot,
                           engine.elapsed < engine.hood_flash_until)
        elif head == "sprout":
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
        if self.accessories["face"] == "seven_goggles":
            painter.save()
            painter.translate(rect.center().x(), rect.top() + rect.height() * .42 + offset)
            width = min(100.0, rect.width() * .86)
            painter.setPen(QPen(QColor("#7c6453"), 2.2, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            band = QPainterPath(QPointF(-width / 2 - 8, 0))
            band.quadTo(0, 9, width / 2 + 8, 0)
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(band)
            lens = width * .43
            for side in (-1, 1):
                x = -width / 2 if side < 0 else width / 2 - lens
                gradient = QLinearGradient(x, -12, x + lens, 12)
                gradient.setColorAt(0, QColor("#e9f5e9")); gradient.setColorAt(.5, QColor("#a1c8c4")); gradient.setColorAt(1, QColor("#69969e"))
                painter.setBrush(gradient); painter.drawRoundedRect(QRectF(x, -12, lens, 24), 7, 7)
                painter.setPen(QPen(QColor("#eff8ef"), 1.7))
                painter.drawLine(QPointF(x + 7, -6), QPointF(x + 16, -2))
                painter.setPen(QPen(QColor("#7c6453"), 2.2))
            painter.setBrush(QColor("#d1b889")); painter.drawRoundedRect(QRectF(-8, -6, 16, 10), 3, 3)
            remaining = getattr(engine, "goggles_flash_until", 0) - engine.elapsed
            if 0 < remaining <= .55:
                opacity = math.sin(math.pi * remaining / .55)
                painter.setPen(QPen(QColor(255, 247, 196, int(220 * opacity)), 3.0,
                                    Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
                seven = QPainterPath(QPointF(10, -7)); seven.lineTo(26, -7); seven.lineTo(15, 9)
                painter.drawPath(seven)
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
    def _paint_disco(painter, engine, foot):
        painter.save()
        painter.translate(foot)
        phase = (engine.elapsed - engine._trick_started)
        painter.setPen(Qt.PenStyle.NoPen)
        colors = ("#edb6ca", "#b4c9e3", "#ead28d", "#a6d1c1")
        for i in range(10):
            angle = phase * 1.1 + i * math.tau / 10
            color = QColor(colors[i % 4]); color.setAlpha(55)
            painter.setBrush(color)
            painter.drawEllipse(QPointF(math.sin(angle) * 150, -75 + math.cos(angle) * 65), 22, 10)
        drop = min(1, phase / .6, (6 - phase) / .5)
        y = -285 - (1 - max(0, drop)) * 35
        painter.setPen(QPen(QColor("#79523b"), 1.5))
        painter.drawLine(QPointF(0, y - 28), QPointF(0, y - 1))
        painter.setBrush(QColor("#e1d8b7")); painter.drawEllipse(QPointF(0, y), 25, 25)
        painter.save(); painter.translate(0, y); painter.rotate(phase * 65)
        for row in range(-2, 3):
            for column in range(-2, 3):
                if row*row + column*column <= 5:
                    painter.setBrush(QColor(colors[(row+column) % 4]))
                    painter.drawRoundedRect(QRectF(column*8-3, row*8-3, 6, 6), 1, 1)
        painter.restore(); painter.restore()

    @staticmethod
    def _paint_fireworks(painter, engine, foot):
        painter.save(); painter.setPen(Qt.PenStyle.NoPen)
        age = 5 - (engine.fireworks_until - engine.elapsed)
        for burst in range(3):
            t = (age - burst * .7) % 2.3
            center = foot + QPointF((burst-1)*85, -230 - (burst%2)*35)
            for i in range(14):
                a = i * math.tau / 14
                c = QColor(("#e8acbd", "#efd18a", "#a5cbb6", "#b7bce1")[i%4]); c.setAlphaF(max(0, 1-t/2.3))
                painter.setBrush(c); painter.drawEllipse(center+QPointF(math.cos(a)*t*42, math.sin(a)*t*42+t*t*9), 3, 3)
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


class RoomCanvas(QWidget):
    """A local, interactive home view over the existing pet render pipeline.

    PetWindow remains the sole owner of the shared engine clock and renderer.
    This canvas only maps its visual pose into room coordinates; opening a second
    view never advances gravity, consumes inventory, or moves a saved anchor.
    """

    poke_requested = Signal()
    pet_requested = Signal()
    lamp_toggle_requested = Signal()

    THEMES = {
        "cheese_room": ("#fbefdb", "#f4dcc1", "#ceab83", "#edcfad", "#c69b73"),
        "sakura_room": ("#fff0f3", "#f5d9e2", "#cda2a6", "#eed1c5", "#c89c90"),
        "matcha_room": ("#eff2df", "#dce4c9", "#9aa886", "#d1caa4", "#ada780"),
    }

    def __init__(self, engine: PetEngine, renderer_provider: Callable[[], SkinRenderer],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.renderer_provider = renderer_provider
        self.setObjectName("roomCanvas")
        self.setMinimumHeight(220)
        self.setMouseTracking(True)
        self.setAccessibleName("汤圆小窝互动房间")
        self.setToolTip("左键戳一戳汤圆，右键摸摸头；点击落地灯可开关灯光。")
        self.daytime_override: bool | None = None
        self._home: dict = {}
        self._catalog: dict = {}
        self._message = ""
        self._message_tone = "info"
        self._message_started = 0.0
        self._message_duration = 2.8
        self._notifications: deque[tuple[str, str, float]] = deque()
        self._food_id = ""
        self._food_until = 0.0
        self._pressed: QPointF | None = None
        self._animation_timer = QTimer(self)
        self._animation_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._animation_timer.setInterval(16)
        self._animation_timer.timeout.connect(self._repaint_if_visible)
        self._animation_timer.start()

    @staticmethod
    def is_daytime(at: datetime | None = None) -> bool:
        """Follow the computer's local clock, with an explicit deterministic seam."""
        return 6 <= (at or datetime.now()).hour < 18

    @property
    def daytime(self) -> bool:
        return self.is_daytime() if self.daytime_override is None else self.daytime_override

    def set_home_state(self, snapshot: dict, furniture_catalog: dict | None = None) -> None:
        self._home = dict(snapshot)
        self._home["equipped_furniture"] = dict(snapshot.get("equipped_furniture", {}))
        if furniture_catalog is not None:
            self._catalog = dict(furniture_catalog)
        self.update()

    def show_message(self, text: str, tone: str = "normal", duration: float = 2.5) -> None:
        # Match SpeechBubble's priorities and expiry so both visible views show
        # the same dialogue. Interaction text replaces repeated poke text;
        # achievements and level celebrations wait instead of stealing it.
        now = monotonic()
        priority = {"achievement": 2, "level": 3, "special": 4, "interaction": 5}
        expires = self._message_started + self._message_duration
        current = priority.get(self._message_tone, 0) if expires > now else 0
        incoming = priority.get(tone, 0)
        duration = max(0.5, float(duration))
        if tone == "interaction":
            if current and self._message_tone != "interaction":
                self._notifications.appendleft((self._message, self._message_tone, max(1.0, expires - now)))
        elif current:
            if incoming == 0:
                return
            if incoming <= current:
                self._notifications.append((str(text), tone, duration))
                return
            self._notifications.appendleft((self._message, self._message_tone, max(1.0, expires - now)))
        self._message = plain_text(text)
        self._message_tone = tone
        self._message_started = now
        self._message_duration = duration + 0.3
        self.update()

    def _advance_message(self) -> None:
        now = monotonic()
        if now >= self._message_started + self._message_duration and self._notifications:
            self._message, self._message_tone, duration = self._notifications.popleft()
            self._message_started = now
            self._message_duration = duration + 0.3

    def show_food(self, item_id: str) -> None:
        self._food_id = item_id
        self._food_until = monotonic() + 2.7
        self.update()

    def stop(self) -> None:
        """Stop this view's repaint timer; never stop the shared skin's QMovie."""
        self._animation_timer.stop()

    def _repaint_if_visible(self) -> None:
        self._advance_message()
        if self.isVisible():
            self.update()

    def _geometry(self) -> tuple[float, float, float]:
        scale = max(0.05, min(self.width() / 960.0, self.height() / 500.0))
        return scale, self.width() / scale, self.height() / scale

    def _slot(self, slot: str) -> str:
        defaults = {"theme": "cheese_room", "rug": "cloud_cushion", "bowl": "wood_bowl"}
        return self._home.get("equipped_furniture", {}).get(slot, defaults.get(slot, ""))

    def _base_foot(self) -> QPointF:
        _scale, width, height = self._geometry()
        return QPointF(width * 0.5, height - 78.0)

    def _trick_home_foot(self) -> QPointF:
        return self._base_foot()

    def _local_roll_offset(self) -> QPointF:
        """Mirror a screen tour inside the room, without changing desktop physics."""
        _scale, width, height = self._geometry()
        padding = max(130.0, self.renderer_provider().screen_roll_padding())
        rect = QRectF(padding, padding, max(20.0, width - 2 * padding),
                      max(20.0, height - 2 * padding))
        foot = self._trick_home_foot()
        center = foot - QPointF(0, PetEngine.BODY_HEIGHT / 2 * self.engine.pose.scale_y)
        edge = QPointF(clamp(center.x(), rect.left(), rect.right()), rect.bottom())
        progress = self.engine.trick_progress
        if progress < 1 / 12:
            mix = progress * 12
            mix = mix * mix * (3 - 2 * mix)
            position = center + (edge - center) * mix
        elif progress > 11 / 12:
            mix = progress * 12 - 11
            mix = mix * mix * (3 - 2 * mix)
            position = edge + (center - edge) * mix
        else:
            distance = (progress * 12 - 1) / 10 * 2 * (rect.width() + rect.height())
            start = rect.width() + rect.height() + rect.right() - edge.x()
            distance = (start + distance) % (2 * (rect.width() + rect.height()))
            if distance < rect.width():
                position = QPointF(rect.left() + distance, rect.top())
            elif distance < rect.width() + rect.height():
                position = QPointF(rect.right(), rect.top() + distance - rect.width())
            elif distance < rect.width() * 2 + rect.height():
                position = QPointF(rect.right() - (distance - rect.width() - rect.height()), rect.bottom())
            else:
                position = QPointF(rect.left(), rect.bottom() - (distance - rect.width() * 2 - rect.height()))
        return position - center

    def _render_foot(self) -> QPointF:
        foot = self._base_foot()
        engine = self.engine
        if engine.active_trick == "screen_roll":
            return foot + self._local_roll_offset() - engine.visual_offset
        # Global desktop positions are intentionally not used as room positions.
        # Only the relative height of a real jump is mirrored, including a drag.
        if not engine.pinned and not engine.grounded:
            foot.setY(foot.y() - clamp(engine.area.bottom - engine.y, 0.0, 110.0))
        if engine.buff.get("behavior_remaining", 0) > 0 and not engine.pinned and not engine.flat:
            foot.setX(foot.x() + math.sin(engine.elapsed * 3.4) * 110.0)
        return foot

    def pet_center(self) -> QPointF:
        renderer = self.renderer_provider()
        scale, _width, _height = self._geometry()
        point = renderer.body_transform(self.engine, self._render_foot()).map(
            renderer.visible_rect(self.engine.state).center())
        return point * scale

    def pet_bounds(self) -> QRectF:
        scale, _width, _height = self._geometry()
        bounds = self.renderer_provider().scene_bounds(self.engine, self._render_foot())
        return QRectF(bounds.x() * scale, bounds.y() * scale,
                      bounds.width() * scale, bounds.height() * scale)

    def lamp_rect(self) -> QRectF:
        if self._slot("corner") != "warm_lamp":
            return QRectF()
        scale, width, height = self._geometry()
        return QRectF((width * 0.17 - 62) * scale, (height - 286) * scale,
                      124 * scale, 220 * scale)

    def _hit_pet(self, point: QPointF) -> bool:
        scale, _width, _height = self._geometry()
        return self.renderer_provider().hit_test(self.engine, self._render_foot(), point / scale)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.RightButton and self._hit_pet(event.position()):
            self.pet_requested.emit()
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._pressed = QPointF(event.position())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        pressed, self._pressed = self._pressed, None
        if (event.button() == Qt.MouseButton.LeftButton and pressed is not None
                and (event.position() - pressed).manhattanLength() <= 8):
            if self._hit_pet(event.position()):
                self.poke_requested.emit()
            elif self.lamp_rect().contains(event.position()):
                self.lamp_toggle_requested.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        # The first click already pokes; a room double-click opens no extra action.
        self._pressed = None
        event.accept()

    def mouseMoveEvent(self, event) -> None:
        interactive = self._hit_pet(event.position()) or self.lamp_rect().contains(event.position())
        self.setCursor(Qt.CursorShape.PointingHandCursor if interactive else Qt.CursorShape.ArrowCursor)
        super().mouseMoveEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        scale, width, height = self._geometry()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()), 22, 22)
        painter.setClipPath(clip)
        painter.save()
        painter.scale(scale, scale)
        self._paint_room(painter, width, height)
        self._paint_wall_decoration(painter, width, height)
        self._paint_corner(painter, width, height)
        self._paint_rug(painter, self._base_foot())
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(95, 65, 45, 20))
        foot = self._base_foot()
        painter.drawEllipse(QRectF(foot.x() - 62, foot.y() - 6, 124, 16))
        self.renderer_provider().paint(painter, self.engine, self._render_foot())
        self._paint_bowl(painter, width, height)
        painter.restore()
        self._paint_message(painter)
        painter.end()

    def _paint_room(self, painter: QPainter, width: float, height: float) -> None:
        wall, trim, wood, plank, grain = self.THEMES.get(self._slot("theme"), self.THEMES["cheese_room"])
        floor_y = height * 0.64
        gradient = QLinearGradient(0, 0, 0, floor_y)
        gradient.setColorAt(0, QColor(wall))
        gradient.setColorAt(1, QColor(trim).lighter(108))
        painter.fillRect(QRectF(0, 0, width, floor_y), gradient)
        # Fine wallpaper detail stays decorative rather than competing with the pet.
        painter.setPen(QPen(QColor(trim), 1))
        for x in range(30, int(width), 48):
            painter.drawLine(QPointF(x, 0), QPointF(x, floor_y))
        painter.fillRect(QRectF(0, floor_y, width, height - floor_y), QColor(plank))
        painter.setPen(QPen(QColor(grain), 1.2))
        for row in range(7):
            y = floor_y + row * 35
            painter.drawLine(QPointF(0, y), QPointF(width, y))
            for x in range(-100 + (row % 2) * 110, int(width), 220):
                painter.drawLine(QPointF(x, y), QPointF(x, y + 35))
                painter.setPen(QPen(QColor(255, 250, 238, 105), 1))
                painter.drawLine(QPointF(x + 16, y + 15), QPointF(x + 165, y + 15))
                painter.setPen(QPen(QColor(grain), 1.2))
        painter.fillRect(QRectF(0, floor_y - 13, width, 13), QColor(wood))
        painter.fillRect(QRectF(0, floor_y - 17, width, 5), QColor(trim).lighter(112))
        self._paint_window(painter, QRectF(width - 290, 45, 176, 170), wood)
        painter.setPen(QColor("#876754"))
        painter.setFont(QFont("Microsoft YaHei UI", 20, QFont.Weight.DemiBold))
        title = QFontMetricsF(painter.font()).elidedText(
            plain_text(self._home.get("name", "白汤圆")) + "的小窝", Qt.TextElideMode.ElideRight,
            max(80.0, width - 380))
        painter.drawText(QRectF(40, 24, width - 380, 42),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        painter.setFont(QFont("Microsoft YaHei UI", 11))
        painter.setPen(QColor("#a0816f"))
        painter.drawText(QRectF(42, 71, width - 380, 24), Qt.AlignmentFlag.AlignLeft,
                         "阳光正好，慢慢陪你长大" if self.daytime else "月亮来值班啦，今晚也有我陪你")
        # A gentle pool of sunlight, never a rectangular image background.
        if self.daytime:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 246, 207, 65))
            painter.drawPolygon(QPolygonF([QPointF(width - 260, floor_y + 4),
                QPointF(width - 130, floor_y + 4), QPointF(width - 45, height),
                QPointF(width - 330, height)]))

    def _paint_window(self, painter: QPainter, rect: QRectF, wood: str) -> None:
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(90, 68, 55, 20))
        painter.drawRoundedRect(rect.adjusted(-9, -6, 12, 15), 18, 18)
        painter.setBrush(QColor(wood))
        painter.drawRoundedRect(rect.adjusted(-7, -7, 7, 7), 13, 13)
        sky = QLinearGradient(rect.topLeft(), rect.bottomRight())
        sky.setColorAt(0, QColor("#bcdff0" if self.daytime else "#30385f"))
        sky.setColorAt(1, QColor("#edf9f4" if self.daytime else "#72718e"))
        painter.setBrush(sky)
        painter.drawRoundedRect(rect, 8, 8)
        if self.daytime:
            painter.setBrush(QColor("#fff4b2"))
            painter.drawEllipse(rect.topLeft() + QPointF(126, 40), 22, 22)
            painter.setBrush(QColor("#ffffff"))
            for dx, dy in [(24, 56), (42, 47), (60, 57), (109, 109), (129, 101)]:
                painter.drawEllipse(rect.topLeft() + QPointF(dx, dy), 20, 11)
        else:
            painter.setBrush(QColor("#fff1bd"))
            painter.drawEllipse(rect.topLeft() + QPointF(128, 42), 20, 20)
            painter.setBrush(QColor("#454966"))
            painter.drawEllipse(rect.topLeft() + QPointF(136, 36), 18, 18)
            painter.setBrush(QColor("#fff6d5"))
            for dx, dy in [(23, 25), (57, 62), (89, 31), (39, 119), (140, 126), (112, 96)]:
                painter.drawEllipse(rect.topLeft() + QPointF(dx, dy), 2.2, 2.2)
        painter.setPen(QPen(QColor(wood), 7))
        painter.drawLine(QPointF(rect.center().x(), rect.top()), QPointF(rect.center().x(), rect.bottom()))
        painter.drawLine(QPointF(rect.left(), rect.center().y()), QPointF(rect.right(), rect.center().y()))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#f9e8d8"))
        painter.drawRoundedRect(QRectF(rect.left() - 16, rect.bottom() + 6, rect.width() + 32, 12), 5, 5)
        painter.restore()

    @staticmethod
    def clock_angles(at: datetime | None = None) -> tuple[float, float, float]:
        now = at or datetime.now()
        seconds = now.second + now.microsecond / 1_000_000
        minutes = now.minute + seconds / 60
        return ((now.hour % 12 + minutes / 60) * 30, minutes * 6, seconds * 6)

    def _paint_wall_decoration(self, painter: QPainter, width: float, height: float) -> None:
        furniture = self._slot("wall")
        painter.save()
        painter.translate(width * 0.27, height * 0.34)
        if furniture == "sunflower_painting":
            painter.setPen(QPen(QColor("#70513b"), 4))
            painter.setBrush(QColor("#fffaf0"))
            painter.drawRoundedRect(QRectF(-67, -64, 134, 125), 4, 4)
            painter.setPen(QPen(QColor("#779266"), 4))
            painter.drawLine(QPointF(0, 0), QPointF(0, 48))
            painter.setBrush(QColor("#a8bc79"))
            painter.drawEllipse(QRectF(0, 20, 26, 13))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f3cd6e"))
            for index in range(10):
                painter.save()
                painter.rotate(index * 36)
                painter.drawEllipse(QRectF(-9, -42, 18, 31))
                painter.restore()
            painter.setBrush(QColor("#986a4c"))
            painter.drawEllipse(QPointF(), 18, 18)
            painter.setBrush(QColor("#c29a6d"))
            for x, y in [(-7, -4), (3, -8), (9, 3), (-1, 5), (-8, 8)]:
                painter.drawEllipse(QPointF(x, y), 1.7, 1.7)
        elif furniture == "rice_clock":
            painter.setPen(QPen(QColor("#70513b"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(QColor("#fffaf1"))
            painter.drawEllipse(QPointF(), 58, 58)
            painter.setPen(QPen(QColor("#70513b"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for index in range(12):
                angle = index * math.tau / 12
                painter.drawLine(QPointF(math.sin(angle) * 47, -math.cos(angle) * 47),
                                 QPointF(math.sin(angle) * 51, -math.cos(angle) * 51))
            hour, minute, second = self.clock_angles()
            for angle, length, thickness, color in ((hour, 25, 4, "#70513b"),
                    (minute, 38, 2.5, "#70513b"), (second, 43, 1.1, "#b47769")):
                painter.save(); painter.rotate(angle)
                painter.setPen(QPen(QColor(color), thickness, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(QPointF(), QPointF(0, -length)); painter.restore()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#e9b6ad"))
            painter.drawEllipse(QPointF(), 4, 4)
        painter.restore()

    def _paint_corner(self, painter: QPainter, width: float, height: float) -> None:
        furniture = self._slot("corner")
        painter.save()
        painter.translate(width * 0.17, height - 76)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(88, 65, 48, 22))
        if furniture:
            painter.drawEllipse(QRectF(-52, -5, 104, 18))
        if furniture == "ficus_plant":
            painter.setPen(QPen(QColor("#70513b"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(0, -36), QPointF(-5, -166))
            for index, (x, y, angle) in enumerate([(-23, -80, -45), (19, -112, 42),
                                                  (-23, -144, -46), (10, -176, 26)]):
                painter.save()
                painter.translate(x, y)
                painter.rotate(angle)
                painter.setPen(QPen(QColor("#70513b"), 2.8))
                painter.setBrush(QColor("#8db783" if index % 2 else "#729d6a"))
                painter.drawEllipse(QRectF(-18, -27, 36, 54))
                painter.setPen(QPen(QColor("#b8cf9a"), 1.3))
                painter.drawLine(QPointF(0, -20), QPointF(0, 20))
                painter.restore()
            painter.setPen(QPen(QColor("#70513b"), 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QColor("#cf9f83"))
            painter.drawPolygon(QPolygonF([QPointF(-34, -53), QPointF(34, -53), QPointF(25, 0), QPointF(-25, 0)]))
            painter.setBrush(QColor("#e3baa0"))
            painter.drawRoundedRect(QRectF(-38, -59, 76, 13), 5, 5)
            painter.setBrush(QColor("#8b6c53"))
            painter.drawEllipse(QRectF(-31, -57, 62, 8))
        elif furniture == "warm_lamp":
            on = self._home.get("lamp_on", True)
            if on:
                glow = QRadialGradient(QPointF(0, -132), 156)
                glow.setColorAt(0, QColor(255, 230, 158, 105))
                glow.setColorAt(1, QColor(255, 230, 158, 0))
                painter.setBrush(glow)
                painter.drawEllipse(QPointF(0, -132), 156, 156)
            painter.setPen(QPen(QColor("#70513b"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(0, -22), QPointF(0, -171))
            painter.setPen(QPen(QColor("#70513b"), 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QColor("#a98a69"))
            painter.drawEllipse(QRectF(-37, -14, 74, 18))
            painter.setBrush(QColor("#fff1c3" if on else "#d4c1a9"))
            painter.drawPolygon(QPolygonF([QPointF(-36, -202), QPointF(36, -202),
                                           QPointF(60, -135), QPointF(-60, -135)]))
            painter.setPen(QPen(QColor("#cbb18b"), 2))
            painter.drawLine(QPointF(-60, -135), QPointF(60, -135))
            painter.setPen(QPen(QColor("#b39977"), 1.5))
            painter.drawLine(QPointF(38, -135), QPointF(38, -112))
            painter.setBrush(QColor("#e4bd72"))
            painter.drawEllipse(QPointF(38, -108), 4, 5)
        painter.restore()

    def _paint_rug(self, painter: QPainter, foot: QPointF) -> None:
        rug = self._slot("rug")
        painter.save()
        painter.translate(foot + QPointF(0, 13))
        painter.setPen(QPen(QColor("#70513b"), 2.3))
        painter.setBrush(QColor("#f8ecd9"))
        if rug == "lotus_cushion":
            painter.setPen(QPen(QColor("#70513b"), 2.5))
            painter.setBrush(QColor("#a9c9a0"))
            painter.drawEllipse(QRectF(-120, -29, 240, 58))
            painter.setPen(QPen(QColor("#d7e6bf"), 1.7))
            for x in [-102, -66, -25, 25, 66, 102]:
                painter.drawLine(QPointF(0, 2), QPointF(x, -19 if x % 2 else 19))
        elif rug == "royal_rug":
            painter.setBrush(QColor("#8b5266")); painter.drawEllipse(QRectF(-140, -37, 280, 77))
            painter.setPen(QPen(QColor("#e4c583"), 4)); painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(-130, -30, 260, 63))
            painter.setPen(QPen(QColor("#d6ac77"), 1.5))
            for x in range(-108, 109, 18):
                painter.drawLine(QPointF(x, 30), QPointF(x+3, 37))
        elif rug == "cat_paw_rug":
            painter.setPen(QPen(QColor("#70513b"), 2.5))
            painter.setBrush(QColor("#fae2e1"))
            painter.drawEllipse(QRectF(-135, -35, 270, 76))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#eebfc4"))
            painter.drawEllipse(QRectF(-48, -11, 96, 37))
            for x in [-70, -24, 24, 70]:
                painter.drawEllipse(QRectF(x - 16, -24, 32, 22))
        else:
            cloud = QPainterPath()
            cloud.setFillRule(Qt.FillRule.WindingFill)
            cloud.addRoundedRect(QRectF(-111, -22, 222, 54), 26, 26)
            for x, y, w in [(-119, -18, 68), (-77, -29, 77), (-20, -32, 87), (49, -20, 78)]:
                cloud.addEllipse(QRectF(x, y, w, 48))
            painter.drawPath(cloud.simplified())
            painter.setPen(QPen(QColor("#fffaf3"), 2))
            painter.drawArc(QRectF(-92, -12, 184, 40), 185 * 16, 170 * 16)
        painter.restore()

    def _paint_bowl(self, painter: QPainter, width: float, height: float) -> None:
        painter.save()
        painter.translate(width * 0.5 + 159, height - 53)
        porcelain = self._slot("bowl") == "porcelain_bowl"
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(99, 70, 50, 24))
        painter.drawEllipse(QRectF(-49, 3, 98, 17))
        painter.setPen(QPen(QColor("#87a4b8" if porcelain else "#ad825c"), 2))
        painter.setBrush(QColor("#edf4fa" if porcelain else "#d3ad80"))
        bowl = QPainterPath(QPointF(-43, -15))
        bowl.cubicTo(-37, 25, 37, 25, 43, -15)
        bowl.closeSubpath()
        painter.drawPath(bowl)
        painter.setBrush(QColor("#fcfeff" if porcelain else "#f1d1a2"))
        painter.drawEllipse(QRectF(-43, -25, 86, 22))
        if porcelain:
            painter.setPen(QPen(QColor("#638fae"), 2))
            for x in [-23, -8, 8, 23]:
                wave = QPainterPath(QPointF(x - 4, -1))
                wave.cubicTo(x + 7, 1, x - 7, 9, x + 4, 10)
                painter.drawPath(wave)
        if monotonic() < self._food_until:
            colors = {"sesame": "#716b70", "strawberry": "#eaa4b6", "matcha": "#a8bf85",
                      "chili": "#de856c", "osmanthus": "#e9c878", "water": "#b9dde8", "sugar": "#fffaf1"}
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors.get(self._food_id, "#f1cd90")))
            painter.drawEllipse(QRectF(-34, -21, 68, 15))
            painter.setBrush(QColor(255, 255, 255, 155))
            painter.drawEllipse(QRectF(-23, -19, 18, 4))
        painter.restore()

    def _paint_message(self, painter: QPainter) -> None:
        self._advance_message()
        age = monotonic() - self._message_started
        if not self._message or age >= self._message_duration:
            return
        opacity = min(1.0, age / 0.13, (self._message_duration - age) / 0.35)
        painter.save()
        painter.setOpacity(max(0.0, opacity))
        font = QFont("Microsoft YaHei UI", 11)
        font.setPointSizeF(max(9.0, min(11.0, self.width() / 80)))
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        width = min(340.0, max(180.0, self.width() * 0.48))
        content = metrics.boundingRect(QRectF(0, 0, width - 28, 300),
                                      Qt.TextFlag.TextWordWrap, self._message)
        height = min(max(40.0, content.height() + 20), self.height() - 24)
        pet = self.pet_bounds()
        x = clamp(pet.center().x() - width / 2, 12, max(12.0, self.width() - width - 12))
        y = clamp(pet.top() - height - 14, 12, max(12.0, self.height() - height - 12))
        rect = QRectF(x, y, width, height)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(128, 89, 72, 20))
        painter.drawRoundedRect(rect.translated(0, 3), 14, 14)
        painter.setPen(QPen(QColor("#e9ccaa" if self._message_tone in {"achievement", "level"} else "#ead9cf"), 1))
        painter.setBrush(QColor(255, 252, 246, 246))
        painter.drawRoundedRect(rect, 14, 14)
        painter.setPen(QColor("#795e52"))
        painter.drawText(rect.adjusted(14, 8, -14, -8),
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self._message)
        painter.restore()
