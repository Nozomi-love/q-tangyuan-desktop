"""Illustrated room view; the desktop engine remains the only physics clock."""
from __future__ import annotations

import math
from time import monotonic
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF, QRadialGradient, QTransform)
from pet_engine import RoomCanvas, clamp
from illustrated_assets import IconAtlas, plain_text


class IllustratedRoomCanvas(RoomCanvas):
    """A large pet, curtained window, wallpaper detail and feeding flight."""
    def __init__(self, engine, renderer_provider, parent=None, atlas: IconAtlas | None = None):
        super().__init__(engine, renderer_provider, parent)
        self.atlas = atlas or IconAtlas()
        self.setMinimumHeight(420)
        self.setAccessibleName("汤圆的家：互动房间")
        self._fly_started = -100.0
        self._fly_from: QPointF | None = None
        self._pet_zoom = 1.48

    def _base_foot(self):
        _scale, width, height = self._geometry()
        return QPointF(width * .48, height - 83)

    def _pet_transform(self):
        foot = self._base_foot()
        scale, width, height = self._geometry()
        top = max(125.0, 148.0 / scale)
        bounds = self.renderer_provider().scene_bounds(self.engine, self._render_foot())
        # The HUD occupies widget pixels while the room uses logical scene
        # units. Fit the full accessory/trick envelope beneath it on small views.
        zoom = min(self._pet_zoom, max(20.0, width - 50) / max(1.0, bounds.width()),
                   max(20.0, height - 23 - top) / max(1.0, bounds.height()))
        transform = QTransform()
        transform.translate(foot.x(), foot.y())
        transform.scale(zoom, zoom)
        transform.translate(-foot.x(), -foot.y())
        rect = transform.mapRect(bounds)
        dx = max(0.0, 25 - rect.left()) - max(0.0, rect.right() - width + 25)
        dy = max(0.0, top - rect.top()) - max(0.0, rect.bottom() - height + 23)
        return transform * QTransform.fromTranslate(dx, dy)

    def pet_center(self):
        renderer = self.renderer_provider()
        point = renderer.body_transform(self.engine, self._render_foot()).map(renderer.visible_rect(self.engine.state).center())
        return self._pet_transform().map(point) * self._geometry()[0]

    def pet_bounds(self):
        rect = self._pet_transform().mapRect(self.renderer_provider().scene_bounds(self.engine, self._render_foot()))
        scale = self._geometry()[0]
        return QRectF(rect.x() * scale, rect.y() * scale, rect.width() * scale, rect.height() * scale)

    def _hit_pet(self, point):
        local = point / self._geometry()[0]
        inverse, ok = self._pet_transform().inverted()
        return ok and self.renderer_provider().hit_test(self.engine, self._render_foot(), inverse.map(local))

    def show_message(self, text, tone="info", duration=2.5):
        super().show_message(plain_text(text), tone, duration)

    def show_food(self, item_id):
        super().show_food(item_id)
        self._fly_started = monotonic()
        self._fly_from = None

    def launch_food(self, item_id, origin: QPointF):
        self.show_food(item_id)
        self._fly_from = QPointF(origin)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        clip = QPainterPath(); clip.addRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 25, 25)
        painter.setClipPath(clip)
        scale, width, height = self._geometry()
        painter.save(); painter.scale(scale, scale)
        self._paint_room(painter, width, height)
        self._paint_wall_decoration(painter, width, height)
        self._paint_corner(painter, width, height)
        foot = self._base_foot()
        painter.save(); painter.translate(foot.x(), foot.y()); painter.scale(1.36, 1.36); painter.translate(-foot.x(), -foot.y())
        self._paint_rug(painter, foot)
        painter.restore()
        painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(QColor(91, 61, 39, 28))
        painter.drawEllipse(QRectF(foot.x() - 87, foot.y() - 4, 174, 17))
        painter.save(); painter.setTransform(self._pet_transform(), combine=True)
        self.renderer_provider().paint(painter, self.engine, self._render_foot())
        painter.restore()
        self._paint_bowl(painter, width, height)
        painter.restore()
        self._paint_food_flight(painter)
        self._advance_message()
        self._paint_message(painter)
        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor("#a77c59"), 3))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(2, 2, -2, -2), 25, 25)
        painter.end()

    def _paint_room(self, p, width, height):
        wall, trim, wood, plank, grain = self.THEMES.get(self._slot("theme"), self.THEMES["cheese_room"])
        floor = height * .65
        grad = QLinearGradient(0, 0, 0, floor)
        grad.setColorAt(0, QColor(wall).lighter(103)); grad.setColorAt(1, QColor(trim).lighter(108))
        p.fillRect(QRectF(0, 0, width, floor), grad)
        p.setPen(QPen(QColor(trim), .75))
        for x in range(18, int(width), 32):
            p.drawLine(QPointF(x, 0), QPointF(x, floor))
        p.setPen(QPen(QColor(169, 137, 106, 24), .8))
        for y in range(15, int(floor), 44):
            for x in range(25 + (y % 2) * 14, int(width), 52):
                sprig = QPainterPath(QPointF(x, y + 8)); sprig.quadTo(x - 4, y, x, y - 6)
                sprig.quadTo(x + 5, y, x, y + 8); p.drawPath(sprig)
        floor_grad = QLinearGradient(0, floor, 0, height)
        floor_grad.setColorAt(0, QColor(plank)); floor_grad.setColorAt(1, QColor(wood).lighter(125))
        p.fillRect(QRectF(0, floor, width, height - floor), floor_grad)
        for row in range(8):
            y = floor + row * 35
            p.setPen(QPen(QColor(grain), 1.3)); p.drawLine(QPointF(0, y), QPointF(width, y))
            for x in range(-110 + (row % 2) * 110, int(width), 220):
                p.drawLine(QPointF(x, y), QPointF(x, y + 35))
                p.setPen(QPen(QColor(255, 247, 224, 130), .8))
                for dx, dy, length in ((17, 13, 145), (28, 18, 70), (80, 25, 116)):
                    curve = QPainterPath(QPointF(x + dx, y + dy)); curve.quadTo(x + dx + length * .4, y + dy - 2, x + dx + length, y + dy)
                    p.drawPath(curve)
                p.setPen(QPen(QColor(grain), 1.3))
        p.fillRect(QRectF(0, floor - 14, width, 14), QColor(wood))
        p.fillRect(QRectF(0, floor - 19, width, 6), QColor(trim).lighter(113))
        p.setPen(QPen(QColor("#94704f"), 1.5)); p.drawLine(QPointF(0, floor), QPointF(width, floor))
        # The upper 110 units belong to the floating HUD, not a second title.
        window = QRectF(width - 298, 139, 174, min(157, floor - 154))
        self._paint_window(p, window, wood)
        self._curtains(p, window)
        if not self._slot("wall"):
            self._little_landscape(p, QRectF(width * .22 - 56, 161, 112, 91))
        self._houseplant(p, width - 91, height - 78)
        if self.daytime:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(255, 248, 197, 57))
            p.drawPolygon(QPolygonF([QPointF(window.left() + 12, floor), QPointF(window.right(), floor),
                                     QPointF(width - 16, height), QPointF(window.left() - 70, height)]))
        else:
            soft = QLinearGradient(0, 0, width, height)
            soft.setColorAt(0, QColor(124, 126, 169, 10)); soft.setColorAt(1, QColor(154, 137, 151, 26))
            p.fillRect(QRectF(0, 0, width, height), soft)

    def _curtains(self, p, rect):
        p.save()
        p.setPen(QPen(QColor("#957051"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(rect.topLeft() + QPointF(-32, -17), rect.topRight() + QPointF(32, -17))
        p.setPen(QPen(QColor("#ba9480"), 1.8))
        for sign, x in ((1, rect.left() - 23), (-1, rect.right() + 23)):
            p.save(); p.translate(x, rect.top() - 13); p.scale(sign, 1)
            fabric = QPainterPath(QPointF(0, 0)); fabric.lineTo(35, 0)
            fabric.cubicTo(34, 44, 4, 61, 17, rect.height() + 10)
            fabric.quadTo(7, rect.height() + 19, -5, rect.height() + 10); fabric.closeSubpath()
            shade = QLinearGradient(0, 0, 30, 0); shade.setColorAt(0, QColor("#e5b6a6")); shade.setColorAt(.5, QColor("#f3d6bf")); shade.setColorAt(1, QColor("#d8a690"))
            p.setBrush(shade); p.drawPath(fabric)
            p.setPen(QPen(QColor("#c29e86"), 1)); p.drawLine(QPointF(8, 5), QPointF(9, 35))
            p.setPen(QPen(QColor("#bd9870"), 3)); p.drawLine(QPointF(1, rect.height() * .54), QPointF(17, rect.height() * .54 - 4))
            p.restore()
        p.restore()

    @staticmethod
    def _little_landscape(p, rect):
        p.save(); p.setPen(QPen(QColor("#a47b56"), 4)); p.setBrush(QColor("#f8ecd3")); p.drawRoundedRect(rect, 3, 3)
        inner = rect.adjusted(7, 7, -7, -7); p.fillRect(inner, QColor("#d3e3db"))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#f9e5ae")); p.drawEllipse(inner.topRight() + QPointF(-20, 19), 10, 10)
        p.setBrush(QColor("#9db394")); p.drawPolygon(QPolygonF([inner.bottomLeft(), inner.topLeft() + QPointF(26, 29), inner.bottomLeft() + QPointF(66, 0)]))
        p.setBrush(QColor("#b8c7a5")); p.drawPolygon(QPolygonF([inner.bottomLeft() + QPointF(25, 0), inner.topRight() + QPointF(-12, 34), inner.bottomRight()]))
        p.restore()

    @staticmethod
    def _houseplant(p, x, y):
        p.save(); p.translate(x, y); p.setPen(QPen(QColor("#907657"), 2))
        p.setBrush(QColor("#d7ae8b")); p.drawRoundedRect(QRectF(-22, -30, 44, 34), 7, 7)
        p.setBrush(QColor("#eed0a7")); p.drawRoundedRect(QRectF(-25, -34, 50, 9), 3, 3)
        p.setPen(QPen(QColor("#7d9266"), 3)); p.drawLine(QPointF(0, -32), QPointF(0, -100))
        for lx, ly, angle in ((-10, -58, -30), (9, -80, 30), (-8, -96, -20)):
            p.save(); p.translate(lx, ly); p.rotate(angle)
            p.setPen(QPen(QColor("#7e9668"), 1.4)); p.setBrush(QColor("#a8bf8d")); p.drawEllipse(QRectF(-10, -22, 20, 36)); p.restore()
        p.restore()

    def _paint_wall_decoration(self, p, width, height):
        # Keep decorations below the game HUD and away from the curtains.
        p.save(); p.translate(0, max(0, 191 - height * .34))
        super()._paint_wall_decoration(p, width, height)
        p.restore()

    def _paint_food_flight(self, p):
        age = monotonic() - self._fly_started
        if not 0 <= age <= 1.5 or not self._food_id:
            return
        scale, width, height = self._geometry()
        destination = QPointF(width * .5 + 159, height - 69) * scale
        origin = self._fly_from or QPointF(65, self.height() - 30)
        t = min(1.0, age / .78)
        if t < 1:
            control = QPointF((origin.x() + destination.x()) / 2, min(origin.y(), destination.y()) - 150)
            point = origin * (1 - t) ** 2 + control * (2 * t * (1 - t)) + destination * t * t
            side = 62 - 24 * t
            p.save(); p.translate(point); p.rotate(math.sin(t * math.pi) * -22)
            p.drawPixmap(QRectF(-side / 2, -side / 2, side, side), self.atlas.pixmap(self._food_id), QRectF(0, 0, 80, 80)); p.restore()
        else:
            fade = max(0, 1 - (age - .78) / .72)
            p.save(); p.setOpacity(fade); p.setPen(Qt.PenStyle.NoPen)
            for n in range(6):
                angle = n * math.tau / 6
                radius = (1 - fade) * 36 + 5
                p.setBrush(QColor("#e4bc6c" if n % 2 else "#fff4ce"))
                p.drawEllipse(destination + QPointF(math.cos(angle) * radius, math.sin(angle) * radius - 8), 3, 3)
            p.restore()
