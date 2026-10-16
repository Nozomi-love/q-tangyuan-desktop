"""Transparent desktop overlay and pointer/screen adaptation."""
from __future__ import annotations

from collections import deque
import math
from pathlib import Path
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent, QGuiApplication, QMouseEvent, QPaintEvent, QPainter, QScreen,
)
from PySide6.QtWidgets import QWidget

from pet_engine import PetEngine, SkinRenderer, WorkArea


class PetWindow(QWidget):
    clicked = Signal()
    drag_started = Signal()
    landed = Signal(float)
    context_menu_requested = Signal(QPoint)
    close_requested = Signal()

    FRAME_PERIOD = 1.0 / 60.0
    DRAG_THRESHOLD = 5.0
    CANVAS_WIDTH = 384
    CANVAS_HEIGHT = 288
    ANCHOR_X = 192.0
    ANCHOR_Y = 244.0

    def __init__(self, skin_directory: Path) -> None:
        super().__init__()
        self.setWindowTitle("Q弹汤圆 · Phase 1")
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
        self.engine.reset(self.work_area(primary))
        self._sync_window()
        self.show()
        self.raise_()

    def set_test_flat(self, enabled: bool) -> None:
        self.engine.set_flat(enabled)
        self.update()

    def reload_skins(self) -> None:
        self.renderer.reload()
        self.update()

    def local_foot(self) -> QPointF:
        # The native window origin can land on a fractional logical pixel
        # at 150% DPI. Let Qt map that origin instead of subtracting x()/y(),
        # whose integer rounding can otherwise shift the foot by one pixel.
        return self.mapFromGlobal(QPointF(self.engine.x, self.engine.y))

    def _sync_window(self) -> None:
        self.move(math.floor(self.engine.x - self.ANCHOR_X),
                  math.floor(self.engine.y - self.ANCHOR_Y))
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
        self._pressed = True
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
            self.engine.begin_drag()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self.drag_started.emit()
        # Use the cursor's display first, allowing a held pet to cross screens
        # instead of being trapped by the previous display's collision wall.
        self._adopt_screen(self._screen_for_point(global_point))
        vx, _ = self._pointer_velocity()
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
            self.engine.release_drag(vx, vy)
        else:
            self.engine.click()
            self.clicked.emit()
        self._samples.clear()
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sync_window()
        event.accept()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        # Phase 1 treats the second press as another poke. Dashboard opening
        # will be connected in Phase 2; flips have a separate menu entry.
        self.mousePressEvent(event)

    def event(self, event: QEvent) -> bool:
        # A system popup or capture cancellation may consume the release.
        # Do not leave the pet permanently suspended in the held state.
        if event.type() == QEvent.Type.UngrabMouse and getattr(self, "_pressed", False):
            self._pressed = False
            if self.engine.dragging:
                self.engine.release_drag(0.0, 0.0)
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
        self._pressed = False
        self.engine.held = self.engine.dragging = False
