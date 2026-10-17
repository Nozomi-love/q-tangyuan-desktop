"""Transparent desktop overlay and pointer/screen adaptation."""
from __future__ import annotations

from collections import deque
import math
from pathlib import Path
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QCloseEvent, QFont, QFontMetrics, QGuiApplication, QMouseEvent, QPaintEvent, QPainter, QPen, QScreen,
)
from PySide6.QtWidgets import QWidget

from pet_engine import PetEngine, SkinRenderer, WorkArea


class SpeechBubble(QWidget):
    """Independent no-focus tool window: never clipped by the pet canvas."""
    claimed = Signal()
    GIFT_TEXT = "🎁 捡到糯米币啦\n点击领取 · 30 秒后自动收好"

    def __init__(self, owner: QWidget) -> None:
        super().__init__(owner, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFont(QFont("Microsoft YaHei UI", 10))
        self._notifications = deque()
        self._text = ""
        self._tone = "normal"
        self._expires = 0.0
        self._born = time.perf_counter()
        self._gift = False
        self._showing_gift = False
        self._pressed_at: QPointF | None = None
        self._body = QRectF()
        self._area = None
        self._alpha = 0.0
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

    def set_collectible(self, available: bool) -> None:
        # Compatibility entry point: coin income is now always collected by
        # the model. Never replace or clear an interaction message with a gift.
        self._gift = self._showing_gift = False
        self._refresh()

    def show_message(self, text: str, tone: str = "normal", duration: float = 2.5) -> None:
        now = time.perf_counter()
        priority = {"achievement": 2, "level": 3, "special": 4, "interaction": 5}
        current = priority.get(self._tone, 0) if self._expires > now else 0
        incoming = priority.get(tone, 0)
        if tone == "interaction":
            # Repeated pokes replace the current line, never queue a backlog.
            if current and self._tone != "interaction":
                self._notifications.appendleft((self._text, self._tone, max(1.0, self._expires - now)))
        elif current:
            if incoming == 0:
                return
            if incoming <= current:
                self._notifications.append((text, tone, duration))
                return
            self._notifications.appendleft((self._text, self._tone, max(1.0, self._expires - now)))
        self._text, self._tone = text, tone
        self._born = now
        self._expires = now + duration + 0.3
        self._refresh()

    def follow(self, body: QRectF, area: WorkArea) -> None:
        self._body, self._area = QRectF(body), area
        self._reposition()

    def _refresh(self) -> None:
        now = time.perf_counter()
        if self._expires <= now and self._notifications:
            self._text, self._tone, duration = self._notifications.popleft()
            self._born = now
            self._expires = now + duration + 0.3
        has_message = self._expires > now
        show_gift = self._gift and (not has_message or self._tone not in ("level", "reward", "achievement", "special"))
        visible = has_message or self._gift
        if not visible:
            self.hide()
            self.timer.stop()
            self._tone = "normal"
            return
        if show_gift != self._showing_gift:
            self._born = now
            self._pressed_at = None
        self._showing_gift = show_gift
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not show_gift)
        self.setCursor(Qt.CursorShape.PointingHandCursor if show_gift else Qt.CursorShape.ArrowCursor)
        text = self.GIFT_TEXT if show_gift else self._text
        width = min(330, max(80, int(self._area.width - 16))) if self._area else 330
        flags = Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap
        bounds = QFontMetrics(self.font()).boundingRect(QRect(0, 0, width - 40, 400), flags, text)
        height = max(62, bounds.height() + 34)
        if self._area:
            height = min(height, int(self._area.height))
        self.setFixedSize(width, height)
        self._reposition()
        self._alpha = min(1.0, max(0.0, (now - self._born) / 0.18))
        if not show_gift:
            self._alpha *= min(1.0, max(0.0, (self._expires - now) / 0.3))
        self.show()
        if not self.timer.isActive():
            self.timer.start()
        self.update()

    def _reposition(self) -> None:
        if self._area is None:
            return
        area, body = self._area, self._body
        bob = 3 * math.sin((time.perf_counter() - self._born) * math.tau / 2.4) if self._showing_gift else 0
        x = body.center().x() - self.width() / 2
        y = body.top() - self.height() - 8 + bob
        if y < area.top + 4:
            y = body.bottom() + 8 + bob
        x = max(area.left + 4, min(x, area.right - self.width() - 4))
        y = max(area.top, min(y, area.bottom - self.height()))
        self.move(math.floor(x), math.floor(y))

    def _tick(self) -> None:
        self._refresh()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._alpha)
        panel = QRectF(self.rect()).adjusted(5, 5, -5, -5)
        gift = self._showing_gift
        accent = QColor("#e9b763" if gift else "#d5a9bd" if self._tone == "level" else "#dacbd5")
        if gift or self._tone in ("level", "achievement", "special"):
            glow = QColor(accent)
            glow.setAlpha(int(40 + 20 * math.sin(time.perf_counter() * 3)))
            painter.setPen(QPen(glow, 8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(panel, 17, 17)
        painter.setPen(QPen(accent, 1.2))
        painter.setBrush(QColor(255, 247, 222, 242) if gift else QColor(255, 249, 253, 239))
        painter.drawRoundedRect(panel, 17, 17)
        painter.setPen(QColor("#69523f" if gift else "#675360"))
        painter.setFont(self.font())
        painter.drawText(self.rect().adjusted(20, 14, -20, -14),
                         Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                         self.GIFT_TEXT if gift else self._text)
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if self._showing_gift and event.button() == Qt.MouseButton.LeftButton:
            self._pressed_at = QPointF(event.globalPosition())
            event.accept()
        else:
            event.ignore()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        pressed, self._pressed_at = self._pressed_at, None
        if self._showing_gift and event.button() == Qt.MouseButton.LeftButton and pressed is not None:
            delta = event.globalPosition() - pressed
            if abs(delta.x()) < 5 and abs(delta.y()) < 5 and self.rect().contains(event.position().toPoint()):
                self.claimed.emit()
            event.accept()
        else:
            event.ignore()

    def stop(self) -> None:
        self.timer.stop()
        self.hide()


class PetWindow(QWidget):
    trick_finished = Signal(str)
    clicked = Signal()
    collectible_clicked = Signal()
    dashboard_requested = Signal()
    drag_landed = Signal()
    shaken = Signal()
    drag_started = Signal()
    landed = Signal(float)
    context_menu_requested = Signal(QPoint)
    close_requested = Signal()
    pinned_changed = Signal(bool)
    position_changed = Signal()

    FRAME_PERIOD = 1.0 / 60.0
    DRAG_THRESHOLD = 5.0
    CANVAS_WIDTH = 800
    CANVAS_HEIGHT = 640
    ANCHOR_X = 400.0
    ANCHOR_Y = 544.0
    DOUBLE_CLICK_SECONDS = 0.2

    def __init__(self, skin_directory: Path) -> None:
        super().__init__()
        self.setWindowTitle("Q弹汤圆 · Phase 4")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFixedSize(self.CANVAS_WIDTH, self.CANVAS_HEIGHT)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        primary = QGuiApplication.primaryScreen()
        if primary is None:
            raise RuntimeError("未找到可用显示器")
        self.active_screen = primary
        self.engine = PetEngine(self.work_area(primary))
        self.renderer = SkinRenderer(skin_directory)
        self.renderer.frame_changed.connect(self.update)
        self.bubble = SpeechBubble(self)
        self.bubble.claimed.connect(self.collectible_clicked.emit)
        self._pending_pokes = deque()
        self.click_timer = QTimer(self)
        self.click_timer.setSingleShot(True)
        self.click_timer.timeout.connect(self.confirm_pending_clicks)
        self._press_time = 0.0
        self._awaiting_drop = False
        self._reported_trick = ""
        self.shake_min_speed = 700.0
        self.shake_distance = 400.0
        self.shake_reversals = 3
        self._shake_total = 0.0
        self._shake_turns = 0
        self._shake_direction = 0
        self._shake_last = None
        self._shake_emitted = False
        self._pressed = False
        self._press_global = QPointF()
        self._drag_offset = QPointF()
        self._samples: deque[tuple[float, QPointF]] = deque(maxlen=32)
        self._watched_screens: list[QScreen] = []

        application = QGuiApplication.instance()
        application.screenAdded.connect(self._watch_screen)
        application.screenRemoved.connect(self._screen_removed)
        for screen in QGuiApplication.screens():
            self._watch_screen(screen)

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._on_frame)
        self._last_frame = time.perf_counter()
        self._next_frame = self._last_frame + self.FRAME_PERIOD
        self.frame_count = 0
        self._sync_window()
        self._schedule_frame()

    @staticmethod
    def work_area(screen: QScreen) -> WorkArea:
        rect = screen.availableGeometry()
        return WorkArea(rect.x(), rect.y(), rect.width(), rect.height())

    def _watch_screen(self, screen: QScreen) -> None:
        if screen in self._watched_screens:
            return
        self._watched_screens.append(screen)
        screen.availableGeometryChanged.connect(self._screen_geometry_changed)
        screen.geometryChanged.connect(self._screen_geometry_changed)

    def _screen_geometry_changed(self, _rect: object) -> None:
        if self.active_screen in QGuiApplication.screens():
            self.engine.set_work_area(self.work_area(self.active_screen))
            self._sync_window()
            self.position_changed.emit()

    def _screen_removed(self, screen: QScreen) -> None:
        self._watched_screens = [s for s in self._watched_screens if s is not screen]
        if self.active_screen is screen:
            self.reset_to_primary()

    def _screen_for_point(self, point: QPointF) -> QScreen:
        integer_point = QPoint(round(point.x()), round(point.y()))
        screen = QGuiApplication.screenAt(integer_point)
        if screen is not None:
            return screen
        # Mixed scaling can leave logical-coordinate gaps between displays.
        screens = QGuiApplication.screens()
        if not screens:
            raise RuntimeError("没有可用显示器")
        def distance(candidate: QScreen) -> float:
            rect = candidate.geometry()
            dx = max(rect.left() - point.x(), 0, point.x() - (rect.x() + rect.width()))
            dy = max(rect.top() - point.y(), 0, point.y() - (rect.y() + rect.height()))
            return dx * dx + dy * dy
        return min(screens, key=distance)

    def _adopt_screen(self, screen: QScreen) -> None:
        self.active_screen = screen
        self.engine.set_work_area(self.work_area(screen))

    def reset_to_primary(self) -> None:
        primary = QGuiApplication.primaryScreen()
        if primary is None:
            return
        self._pressed = False
        self._samples.clear()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.active_screen = primary
        self._awaiting_drop = False
        self.engine.reset(self.work_area(primary))
        self._sync_window()
        self.show()
        self.raise_()
        self.position_changed.emit()

    def set_pinned(self, enabled: bool) -> None:
        if self.engine.pinned == bool(enabled):
            return
        self.engine.set_pinned(enabled)
        self._sync_window()
        self.pinned_changed.emit(self.engine.pinned)
        self.position_changed.emit()

    def capture_position(self) -> dict:
        area = self.engine.area
        return {
            "pinned": self.engine.pinned,
            "screen": self.active_screen.name(),
            "x_ratio": min(1.0, max(0.0, (self.engine.x - area.left) / area.width)),
            "y_ratio": min(1.0, max(0.0, (self.engine.y - area.top) / area.height)),
        }

    def restore_position(self, state: dict) -> None:
        if not state.get("pinned", False):
            return
        screens = QGuiApplication.screens()
        screen = next((s for s in screens if s.name() == state.get("screen")),
                      QGuiApplication.primaryScreen())
        if screen is None:
            return
        self._adopt_screen(screen)
        area = self.engine.area
        self.engine.set_pinned(True)
        self.engine.place(area.left + state["x_ratio"] * area.width,
                          area.top + state["y_ratio"] * area.height)
        self._sync_window()
        self.pinned_changed.emit(True)

    def set_skin(self, directory: Path) -> bool:
        candidate = SkinRenderer(directory)
        if not candidate.pixmaps:
            candidate.stop()
            candidate.deleteLater()
            return False
        old = self.renderer
        if self.engine.active_trick == "screen_roll":
            self.engine.cancel_trick()
        candidate.set_accessories(old.accessories)
        self.renderer = candidate
        candidate.frame_changed.connect(self.update)
        old.stop()
        old.deleteLater()
        self._sync_window()
        return True

    def set_accessories(self, accessories: dict) -> None:
        before = dict(self.renderer.accessories)
        self.renderer.set_accessories(accessories)
        if self.engine.active_trick == "screen_roll" and before != self.renderer.accessories:
            self.engine.cancel_trick()
        self._sync_window()

    def perform_trick(self, trick: str) -> bool:
        started = (self.engine.perform_trick(trick, roll_padding=self.renderer.screen_roll_padding())
                   if trick == "screen_roll" else self.engine.perform_trick(trick))
        if not started:
            return False
        self._awaiting_drop = False
        self._sync_window()
        return True

    def set_buff(self, buff: dict) -> None:
        self.engine.set_buff(buff)
        self._sync_window()

    def set_test_flat(self, enabled: bool) -> None:
        self.engine.set_flat(enabled)
        self.update()

    def set_starving(self, enabled: bool) -> None:
        self.engine.set_starving(enabled)
        self._sync_window()

    def show_message(self, text: str, tone: str = "normal") -> None:
        self.bubble.show_message(text, tone)

    def show_collectible(self, enabled: bool) -> None:
        self.bubble.set_collectible(enabled)
        self._position_bubble()

    def _position_bubble(self) -> None:
        state = self.renderer.source_state(self.engine.state)
        rect = self.renderer.visible_rect(self.engine.state)
        transform = self.renderer.body_transform(self.engine, QPointF(self.engine.x, self.engine.y))
        rect = rect.united(self.renderer.accessory_bounds(self.engine.state))
        self.bubble.follow(transform.mapRect(rect), self.engine.area)

    def reload_skins(self) -> None:
        self.renderer.reload()
        self.update()

    def local_foot(self) -> QPointF:
        # The native window origin can land on a fractional logical pixel
        # at 150% DPI. Let Qt map that origin instead of subtracting x()/y(),
        # whose integer rounding can otherwise shift the foot by one pixel.
        return self.mapFromGlobal(QPointF(self.engine.x, self.engine.y))

    def _sync_window(self) -> None:
        active = self.engine.active_trick
        previous, self._reported_trick = self._reported_trick, active
        if previous and not active:
            self.trick_finished.emit(previous)
        offset = self.engine.visual_offset if active == "screen_roll" else QPointF()
        # Follow the rolling drawing with the native window instead of enlarging
        # one transparent window across the desktop. Saved x/y stay at home.
        anchor_y = (self.CANVAS_HEIGHT / 2 + self.engine.BODY_HEIGHT / 2 * self.engine.pose.scale_y
                    if active == "screen_roll" else self.ANCHOR_Y)
        self.move(math.floor(self.engine.x + offset.x() - self.ANCHOR_X),
                  math.floor(self.engine.y + offset.y() - anchor_y))
        self._position_bubble()
        self.update()

    def _schedule_frame(self) -> None:
        remaining = self._next_frame - time.perf_counter()
        self.timer.start(max(1, math.ceil(remaining * 1000)))

    def _on_frame(self) -> None:
        now = time.perf_counter()
        dt, self._last_frame = now - self._last_frame, now
        if self.active_screen not in QGuiApplication.screens():
            self.reset_to_primary()
        else:
            self.engine.set_work_area(self.work_area(self.active_screen))
        impact = self.engine.advance(dt)
        if impact is not None:
            self.landed.emit(impact)
            if self._awaiting_drop:
                self._awaiting_drop = False
                self.drag_landed.emit()
        self._sync_window()
        self.frame_count += 1
        self._next_frame += self.FRAME_PERIOD
        if self._next_frame <= now:
            self._next_frame = now + self.FRAME_PERIOD
        self._schedule_frame()

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        # Clear the previous alpha surface so flattening cannot leave ghosts.
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        self.renderer.paint(painter, self.engine, self.local_foot())
        painter.end()

    def _inside_body(self, point: QPointF) -> bool:
        return self.renderer.hit_test(self.engine, self.local_foot(), point)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.RightButton:
            if self._inside_body(event.position()):
                self.context_menu_requested.emit(event.globalPosition().toPoint())
                event.accept()
            else:
                event.ignore()
            return
        if event.button() != Qt.MouseButton.LeftButton or not self._inside_body(event.position()):
            event.ignore()
            return
        if self.engine.active_trick == "screen_roll":
            self.engine.cancel_trick()
            self.engine.rebound()
            self._sync_window()
            event.accept()
            return
        self._pressed = True
        self._press_time = time.perf_counter()
        self._press_global = QPointF(event.globalPosition())
        self._drag_offset = QPointF(
            self.engine.x - event.globalPosition().x(),
            self.engine.y - event.globalPosition().y(),
        )
        self._samples.clear()
        self._samples.append((time.perf_counter(), QPointF(event.globalPosition())))
        self.engine.hold()
        event.accept()

    def _record_sample(self, point: QPointF) -> None:
        now = time.perf_counter()
        self._samples.append((now, QPointF(point)))
        while len(self._samples) > 2 and self._samples[0][0] < now - 0.12:
            self._samples.popleft()

    def _pointer_velocity(self) -> tuple[float, float]:
        recent = [sample for sample in self._samples if sample[0] >= time.perf_counter() - 0.12]
        if len(recent) < 2:
            return 0.0, 0.0
        first_time, first_point = recent[0]
        last_time, last_point = recent[-1]
        duration = last_time - first_time
        if duration < 0.001:
            return 0.0, 0.0
        return ((last_point.x() - first_point.x()) / duration,
                (last_point.y() - first_point.y()) / duration)

    def _apply_drag(self, global_point: QPointF) -> None:
        if not self.engine.dragging:
            delta = global_point - self._press_global
            if math.hypot(delta.x(), delta.y()) < self.DRAG_THRESHOLD:
                return
            self._awaiting_drop = False
            self._shake_total = 0.0
            self._shake_turns = self._shake_direction = 0
            self._shake_last = (self._press_time, self._press_global.x())
            self._shake_emitted = False
            self.engine.begin_drag()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.drag_started.emit()
        # Use the cursor's display first, allowing a held pet to cross screens
        # instead of being trapped by the previous display's collision wall.
        self._adopt_screen(self._screen_for_point(global_point))
        vx, _ = self._pointer_velocity()
        now = time.perf_counter()
        if self._shake_last is not None:
            last_at, last_x = self._shake_last
            dx = global_point.x() - last_x
            speed = abs(dx) / max(0.001, now - last_at)
            if speed >= self.shake_min_speed and abs(dx) >= 5:
                direction = 1 if dx > 0 else -1
                self._shake_total += abs(dx)
                if self._shake_direction and direction != self._shake_direction:
                    self._shake_turns += 1
                self._shake_direction = direction
                if (not self._shake_emitted and self._shake_total >= self.shake_distance
                        and self._shake_turns >= self.shake_reversals):
                    self._shake_emitted = True
                    self.shaken.emit()
            self._shake_last = (now, global_point.x())
        self.engine.drag_to(
            global_point.x() + self._drag_offset.x(),
            global_point.y() + self._drag_offset.y(),
            vx,
        )
        self._sync_window()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self._pressed:
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if self._inside_body(event.position())
                else Qt.CursorShape.ArrowCursor
            )
            event.ignore()
            return
        self._record_sample(event.globalPosition())
        self._apply_drag(event.globalPosition())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or not self._pressed:
            event.ignore()
            return
        self._record_sample(event.globalPosition())
        self._apply_drag(event.globalPosition())
        self._pressed = False
        if self.engine.dragging:
            vx, vy = self._pointer_velocity()
            self._awaiting_drop = not self.engine.pinned and self.engine.y + self.engine.bounds_offsets()[3] < self.engine.area.bottom - 20
            self.engine.release_drag(vx, vy)
            self.position_changed.emit()
        else:
            self.engine.held = False
            if self._pending_pokes:
                previous_time, previous_point = self._pending_pokes[-1]
                delta = self._press_global - previous_point
                if (0 <= self._press_time - previous_time <= self.DOUBLE_CLICK_SECONDS
                        and math.hypot(delta.x(), delta.y()) <= 8):
                    self._pending_pokes.pop()
                    self.click_timer.stop()
                    self.dashboard_requested.emit()
                else:
                    self._pending_pokes.append((time.perf_counter(), QPointF(event.globalPosition())))
            else:
                self._pending_pokes.append((time.perf_counter(), QPointF(event.globalPosition())))
            if self._pending_pokes:
                self.click_timer.start(max(1, math.ceil((self._pending_pokes[0][0] + self.DOUBLE_CLICK_SECONDS - time.perf_counter()) * 1000)))
        self._samples.clear()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_window()
        event.accept()

    def confirm_pending_clicks(self) -> None:
        now = time.perf_counter()
        # A second press can precede the deadline while its release follows it.
        if self._pressed and not self.engine.dragging and self._pending_pokes:
            when, point = self._pending_pokes[-1]
            delta = self._press_global - point
            if 0 <= self._press_time - when <= self.DOUBLE_CLICK_SECONDS and math.hypot(delta.x(), delta.y()) <= 8:
                self.click_timer.start(20)
                return
        while self._pending_pokes and now >= self._pending_pokes[0][0] + self.DOUBLE_CLICK_SECONDS:
            self._pending_pokes.popleft()
            if not self.engine.held:
                self.engine.click()
            self.clicked.emit()
        if self._pending_pokes:
            self.click_timer.start(max(1, math.ceil((self._pending_pokes[0][0] + self.DOUBLE_CLICK_SECONDS - now) * 1000)))
        self._sync_window()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # Native Qt double-click timing may be longer; use the same application
        # 200 ms rule for native and synthetic press/release events.
        self.mousePressEvent(event)

    def event(self, event: QEvent) -> bool:
        # A system popup or capture cancellation may consume the release.
        # Do not leave the pet permanently suspended in the held state.
        if event.type() == QEvent.Type.UngrabMouse and getattr(self, "_pressed", False):
            self._pressed = False
            if self.engine.dragging:
                self._awaiting_drop = not self.engine.pinned and self.engine.y + self.engine.bounds_offsets()[3] < self.engine.area.bottom - 20
                self.engine.release_drag(0.0, 0.0)
                self.position_changed.emit()
            else:
                self.engine.held = False
            self._samples.clear()
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        return super().event(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        event.ignore()
        self.close_requested.emit()

    def stop(self) -> None:
        self.timer.stop()
        self.click_timer.stop()
        self._pending_pokes.clear()
        self.bubble.stop()
        self.renderer.stop()
        self.engine.cancel_trick()
        self._pressed = False
        self.engine.held = self.engine.dragging = False
