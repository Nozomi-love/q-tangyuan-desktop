"""Hand-painted vector item atlas. Existing local PNG artwork always wins."""
from __future__ import annotations

import logging
import math
from pathlib import Path
import re

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QIcon, QImage, QImageReader, QLinearGradient,
                           QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient)

_EMOJI = re.compile("[\U0001f000-\U0001faff\u2300-\u23ff\u2600-\u27bf\u2b00-\u2bff\ufe0f\u200d\u20e3]")


def plain_text(value) -> str:
    """Keep saved/custom names intact while presenting plain, literal captions."""
    return _EMOJI.sub("", str(value)).strip()


ICON_IDS = (
    "water", "sugar", "osmanthus", "sesame", "strawberry", "matcha", "chili",
    "paper_star", "flower_bouquet", "music_box", "spinning_top",
    "sprout", "crown", "sunglasses", "bow", "steam", "flip", "clone", "ball", "screen_roll",
    "cheese_room", "sakura_room", "matcha_room", "cloud_cushion", "lotus_cushion", "cat_paw_rug",
    "sunflower_painting", "rice_clock", "ficus_plant", "warm_lamp", "wood_bowl", "porcelain_bowl",
    "coin", "avatar", "home", "bag", "shop", "dress", "achievements", "settings", "desktop",
    "import_image", "import_folder", "import_zip", "template", "remove", "title", "debug", "lamp",
    "first_poke", "first_drop", "first_feed", "first_pet", "flavors_three", "gifts_three",
    "level_three", "rapid_pokes", "shake", "rescue", "soul_infusion", "warm_home",
    "level_1", "level_2", "level_3", "level_4", "level_5", "level_6",
)


class Brush:
    """An 80-unit illustration with rounded cocoa outlines and soft highlights."""
    INK = "#79523b"

    def __init__(self, painter: QPainter):
        self.p = painter
        self.pen()

    def pen(self, color=INK, width=1.8):
        self.p.setPen(QPen(QColor(color), width, Qt.PenStyle.SolidLine,
                           Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

    def fill(self, color, end=None):
        if end:
            gradient = QLinearGradient(12, 12, 61, 70)
            gradient.setColorAt(0, QColor(color))
            gradient.setColorAt(1, QColor(end))
            self.p.setBrush(gradient)
        else:
            self.p.setBrush(QColor(color))

    def ellipse(self, x, y, w, h, color, end=None):
        self.fill(color, end)
        self.p.drawEllipse(QRectF(x, y, w, h))

    def rect(self, x, y, w, h, color, radius=5, end=None):
        self.fill(color, end)
        self.p.drawRoundedRect(QRectF(x, y, w, h), radius, radius)

    def line(self, *points):
        curve = QPainterPath(QPointF(*points[:2]))
        for index in range(2, len(points), 2):
            curve.lineTo(*points[index:index + 2])
        self.p.drawPath(curve)

    def poly(self, points, color, end=None):
        self.fill(color, end)
        self.p.drawPolygon(QPolygonF([QPointF(x, y) for x, y in points]))

    def shine(self, x=25, y=25, width=4, height=10):
        self.p.save()
        self.p.setPen(Qt.PenStyle.NoPen)
        self.ellipse(x, y, width, height, "#fffdf2")
        self.ellipse(x + width + 3, y - 2, 2, 2, "#ffffff")
        self.p.restore()

    def star(self, x, y, radius, color="#f9d47d"):
        points = []
        for index in range(10):
            angle = -math.pi / 2 + index * math.pi / 5
            r = radius if index % 2 == 0 else radius * .47
            points.append((x + math.cos(angle) * r, y + math.sin(angle) * r))
        self.poly(points, color, "#e9b35d")

    def leaf(self, x, y, angle=0, color="#9bbd82", size=1):
        self.p.save()
        self.p.translate(x, y)
        self.p.rotate(angle)
        self.p.scale(size, size)
        curve = QPainterPath(QPointF(0, 0))
        curve.cubicTo(-24, -8, -19, -28, -7, -29)
        curve.cubicTo(13, -25, 16, -6, 0, 0)
        self.fill("#c3d9a0", color)
        self.p.drawPath(curve)
        self.pen("#759566", 1)
        self.line(0, 0, -6, -22)
        self.p.restore()

    def dumpling(self, x, y, size=1, alpha=1):
        self.p.save()
        self.p.translate(x, y)
        self.p.scale(size, size)
        self.p.setOpacity(self.p.opacity() * alpha)
        self.pen()
        self.ellipse(-17, -17, 34, 31, "#fffef4", "#ede2cb")
        self.pen("#694a39", 2.4)
        self.line(-7, -3, -7, -1)
        self.line(7, -3, 7, -1)
        self.pen("#be8575", 1.5)
        smile = QPainterPath(QPointF(-3, 3))
        smile.quadTo(0, 7, 4, 3)
        self.p.drawPath(smile)
        self.p.setPen(Qt.PenStyle.NoPen)
        self.ellipse(-13, 2, 5, 2.6, "#eeb4a3")
        self.ellipse(8, 2, 5, 2.6, "#eeb4a3")
        self.shine(-10, -11, 3, 5)
        self.p.restore()

    def bowl(self, color="#e9cc96", porcelain=False, contents=None):
        self.pen()
        curve = QPainterPath(QPointF(13, 35))
        curve.cubicTo(15, 62, 26, 68, 40, 68)
        curve.cubicTo(55, 68, 66, 60, 68, 35)
        curve.closeSubpath()
        self.fill("#fff8dd" if porcelain else "#f3d8a1", "#c4d8e1" if porcelain else color)
        self.p.drawPath(curve)
        self.ellipse(12, 28, 57, 17, "#fdf6df" if porcelain else "#eed4a4")
        if contents:
            self.ellipse(17, 31, 47, 10, contents)
        if porcelain:
            self.pen("#6b94ad", 1.5)
            for x in (24, 37, 50):
                c = QPainterPath(QPointF(x, 47))
                c.cubicTo(x + 8, 43, x - 5, 58, x + 5, 56)
                self.p.drawPath(c)
        else:
            self.pen("#bd9666", 1)
            self.line(22, 50, 28, 59, 37, 61)
        self.shine(19, 43, 3, 8)

    def jar(self, color, lid="#b18969"):
        self.pen()
        self.rect(21, 22, 40, 45, "#fcf1da", 10, "#d9e4dd")
        self.rect(24, 35, 34, 28, color, 7)
        self.rect(19, 16, 44, 12, lid, 4, "#e1c99f")
        self.pen("#ad8665", 1)
        for x in range(25, 60, 7):
            self.line(x, 20, x, 24)
        self.pen()
        self.rect(27, 40, 28, 18, "#fff8df", 4)
        self.shine(24, 29, 3, 10)


def paint_icon(painter: QPainter, key: str) -> None:
    b = Brush(painter)
    painter.save()
    painter.setPen(Qt.PenStyle.NoPen)
    b.ellipse(14, 65, 52, 8, "#18794f35")
    b.pen()
    if key == "water":
        cup = QPainterPath(QPointF(20, 17))
        cup.lineTo(25, 64); cup.quadTo(41, 72, 56, 64); cup.lineTo(61, 17); cup.closeSubpath()
        b.fill("#f7ffff", "#cce6eb"); painter.drawPath(cup)
        water = QPainterPath(QPointF(23, 37)); water.quadTo(40, 32, 58, 37)
        water.lineTo(55, 62); water.quadTo(41, 68, 26, 62); water.closeSubpath()
        b.fill("#d5f0f2", "#94c6d7"); painter.drawPath(water)
        b.ellipse(20, 12, 41, 10, "#eff8f2")
        b.shine(27, 25, 4, 22); b.shine(48, 46, 2, 6)
        b.pen("#b7dbe4", 1); b.ellipse(37, 43, 4, 4, "#f0ffff")
    elif key == "sugar":
        b.poly([(23, 26), (7, 18), (11, 37), (7, 53), (24, 48)], "#e5b3bf", "#c88397")
        b.poly([(56, 27), (73, 19), (69, 39), (74, 55), (55, 49)], "#e5b3bf", "#c88397")
        b.rect(19, 23, 43, 32, "#fff3cc", 12, "#e6bc7c")
        b.pen("#c28e6c", 1); b.line(13, 29, 22, 36); b.line(64, 36, 69, 29)
        b.pen(); b.rect(30, 27, 21, 24, "#fffcef", 7)
        b.star(40, 39, 7, "#f2d5a4"); b.shine(25, 27, 3, 10)
    elif key == "sesame":
        b.bowl(porcelain=True, contents="#655d60")
        b.pen("#f7ebda", 1)
        for x, y in ((25, 35), (39, 34), (47, 38), (54, 34), (31, 38)):
            b.line(x, y, x + 1, y + 1)
        b.pen("#b69e86", 2)
        for x in (28, 40, 52):
            c = QPainterPath(QPointF(x, 25)); c.cubicTo(x - 8, 20, x + 7, 14, x, 8)
            painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(c)
    elif key in ("strawberry", "chili"):
        strawberry = key == "strawberry"
        b.jar("#df9b9d" if strawberry else "#cf7860", "#d9a2aa" if strawberry else "#9b735d")
        if strawberry:
            b.poly([(32, 43), (40, 41), (48, 43), (45, 52), (40, 56), (35, 51)], "#dc7f80")
            b.pen("#769867", 1.4); b.poly([(34, 43), (38, 40), (40, 43), (44, 40), (47, 43)], "#92ad78")
            b.pen("#f8d296", .9)
            for x, y in ((36, 47), (41, 46), (44, 49), (39, 51)): b.line(x, y, x + .5, y + 1)
        else:
            b.fill("#db7454", "#b4543c")
            chili = QPainterPath(QPointF(47, 43)); chili.cubicTo(45, 57, 33, 57, 30, 53)
            chili.cubicTo(43, 54, 38, 40, 47, 43); painter.drawPath(chili)
            b.pen("#788f5c", 2); b.line(47, 43, 48, 39, 53, 39)
    elif key == "matcha":
        b.bowl("#99ad77", contents="#95b16f")
        b.pen("#a7c486", 1); b.ellipse(23, 33, 5, 3, "#d2dfaf")
        b.pen(); b.poly([(48, 40), (52, 40), (61, 7), (57, 6)], "#d1b17e")
        b.rect(23, 6, 13, 24, "#d7bc89", 4)
        b.pen("#a48355", 1)
        for x in range(25, 36, 3): b.line(x, 10, x, 27)
        b.pen(); b.ellipse(24, 26, 12, 5, "#b99662")
    elif key == "osmanthus":
        jar = QPainterPath(QPointF(27, 26)); jar.cubicTo(5, 51, 18, 71, 40, 70)
        jar.cubicTo(68, 71, 73, 50, 54, 26); jar.closeSubpath()
        b.fill("#eacb96", "#b98a65"); painter.drawPath(jar)
        b.rect(25, 17, 31, 14, "#aa7d62", 6)
        b.poly([(24, 20), (30, 14), (55, 15), (59, 22), (51, 29), (31, 28)], "#d89a88", "#bc8071")
        b.rect(27, 39, 27, 20, "#fff1d1", 5)
        b.pen("#bc946b", 1); b.line(32, 45, 48, 45); b.line(35, 49, 46, 49)
        b.shine(20, 36, 4, 13)
    elif key == "paper_star":
        b.star(40, 38, 28, "#ffe8a4")
        b.pen("#c2a26e", 1); b.line(40, 12, 40, 38, 65, 46); b.line(40, 38, 24, 61)
        b.shine(30, 27, 3, 7)
    elif key == "flower_bouquet":
        b.poly([(16, 32), (40, 70), (64, 31)], "#f7e4c3", "#e3bc9c")
        b.pen("#839c69", 2); b.line(40, 57, 25, 24); b.line(40, 57, 53, 21)
        for x, y, color in ((25, 23, "#e6a9b2"), (43, 20, "#f0d99c"), (54, 29, "#d3b6cf")):
            b.pen("#b68b78", 1)
            for dx, dy in ((-6, 0), (5, 0), (0, -6), (0, 6)):
                b.ellipse(x + dx - 6, y + dy - 6, 12, 12, color)
            b.ellipse(x - 3, y - 3, 6, 6, "#ffe8aa")
        b.pen(); b.rect(30, 49, 22, 7, "#d5a1a7", 2)
    elif key == "music_box":
        b.rect(15, 39, 52, 28, "#eed6af", 6, "#c49c75")
        b.rect(17, 13, 48, 30, "#f3dfc4", 5, "#c9a985")
        b.rect(23, 18, 36, 19, "#e9cad1", 8)
        b.pen(); b.star(41, 27, 7); b.rect(35, 53, 12, 7, "#f3ca7e", 2)
        b.pen("#ae876c", 1); b.line(20, 45, 62, 45); b.shine(23, 50, 3, 9)
    elif key == "spinning_top":
        b.pen("#bda488", 1.5); painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(QRectF(6, 37, 68, 27), 10 * 16, 135 * 16)
        b.pen(); b.poly([(17, 37), (41, 66), (64, 37)], "#e6b46d", "#be8570")
        b.ellipse(16, 24, 49, 24, "#e5b5b9", "#c58195")
        b.ellipse(25, 28, 32, 13, "#f7deba")
        b.rect(37, 11, 8, 21, "#d6b587", 3)
        b.pen("#a77c69", 1); b.line(27, 46, 41, 60, 54, 46); b.shine(24, 29, 3, 7)
    elif key == "sprout":
        b.pen("#779265", 3); b.line(41, 68, 40, 39, 36, 27)
        b.leaf(39, 44, -58, size=1.1); b.leaf(42, 40, 48, size=1.05)
        b.shine(23, 18, 3, 6)
    elif key == "crown":
        b.poly([(12, 27), (26, 37), (40, 13), (54, 36), (69, 25), (61, 62), (20, 62)], "#ffe7a5", "#d4a34f")
        b.rect(18, 52, 45, 13, "#f8cd70", 4, "#dba954")
        b.pen("#d1a35e", 1.1); b.line(25, 49, 22, 36); b.line(39, 44, 40, 26); b.line(55, 48, 58, 37)
        b.pen(); b.ellipse(34, 38, 12, 14, "#d99aa6", "#ba7c93")
        for x, y in ((12, 26), (40, 13), (69, 25)): b.ellipse(x - 3, y - 3, 6, 6, "#fff3bc")
        b.shine(24, 37, 3, 8)
    elif key == "sunglasses":
        b.pen(width=3); b.line(9, 29, 17, 33, 66, 33, 74, 27)
        b.rect(12, 30, 26, 25, "#858e94", 8, "#414d59")
        b.rect(44, 30, 26, 25, "#858e94", 8, "#414d59")
        b.pen("#d1e2df", 3); b.line(19, 36, 26, 34); b.line(51, 36, 58, 34)
        b.pen("#5c4a42", 2); b.line(38, 37, 44, 37)
    elif key == "bow":
        b.poly([(34, 34), (17, 19), (10, 23), (10, 55), (17, 59), (36, 45)], "#efc8cf", "#d694a7")
        b.poly([(45, 34), (63, 18), (70, 23), (69, 55), (62, 59), (43, 44)], "#efc8cf", "#d694a7")
        b.pen("#c08b9d", 1.1); b.line(18, 29, 34, 39, 19, 50); b.line(62, 29, 47, 39, 61, 49)
        b.pen(); b.rect(33, 32, 14, 19, "#efc3c9", 5, "#dca0b2"); b.shine(35, 35, 3, 7)
    elif key == "steam":
        for x, y in ((25, 48), (40, 30), (57, 48)):
            painter.save(); painter.translate(x, y)
            c = QPainterPath(QPointF(-4, 10)); c.cubicTo(-17, 0, 11, -9, 0, -24)
            b.pen("#c1b09e", 6); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawPath(c)
            b.pen("#fff8e5", 3); painter.drawPath(c); painter.restore()
        b.star(14, 18, 5, "#f8db92"); b.star(64, 13, 4, "#f8db92")
    elif key in ("flip", "clone", "screen_roll"):
        if key == "clone":
            b.dumpling(18, 42, .72, .56); b.dumpling(63, 42, .72, .56); b.dumpling(41, 39, 1)
        else:
            b.pen("#bf9e77", 2.5); painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(QRectF(9, 9, 62, 58), 18 * 16, 290 * 16)
            b.poly([(67, 35), (61, 27), (73, 28)], "#d8bb88")
            if key == "screen_roll":
                b.pen("#bba38a", 1); painter.drawRoundedRect(QRectF(18, 18, 43, 40), 6, 6)
                b.dumpling(40, 39, .76)
            else:
                b.dumpling(42, 37, .95)
                b.pen("#d4bd9d", 1); b.line(14, 45, 19, 51); b.line(12, 51, 18, 56)
    elif key == "ball":
        b.ellipse(14, 13, 53, 53, "#f5eee0", "#bbb3a6")
        b.poly([(36, 28), (48, 30), (52, 42), (41, 49), (30, 40)], "#64605e", "#484c4b")
        b.pen("#938777", 1.3); b.line(36, 28, 31, 17); b.line(48, 30, 59, 25); b.line(52, 42, 64, 47)
        b.line(41, 49, 40, 65); b.line(30, 40, 17, 41)
        b.shine(22, 21, 5, 11)
    elif key in ("cloud_cushion", "cat_paw_rug", "lotus_cushion"):
        colors = {"cloud_cushion": ("#fff6df", "#e8d5b7"), "cat_paw_rug": ("#f5d3d5", "#e1b3bd"), "lotus_cushion": ("#c3d8a4", "#8fb187")}
        b.ellipse(8, 33, 65, 32, *colors[key])
        if key == "cloud_cushion":
            for x, y in ((13, 30), (27, 25), (43, 29)):
                b.ellipse(x, y, 24, 23, "#fff7e6")
            b.pen("#fffdf4", 2); b.line(18, 54, 31, 59, 54, 57)
        elif key == "cat_paw_rug":
            painter.setPen(Qt.PenStyle.NoPen); b.ellipse(29, 45, 25, 14, "#cf9aa8")
            for x, y in ((20, 42), (32, 36), (46, 37), (58, 44)): b.ellipse(x - 5, y - 4, 10, 8, "#cf9aa8")
        else:
            b.pen("#e5ecc9", 1.5)
            for x in (16, 27, 53, 65): b.line(40, 51, x, 41)
            b.line(40, 51, 42, 61)
    elif key in ("wood_bowl", "porcelain_bowl"):
        b.bowl(porcelain=key == "porcelain_bowl")
    elif key in ("ficus_plant", "warm_lamp", "lamp"):
        if key == "ficus_plant":
            b.pen("#849364", 2.8); b.line(41, 55, 39, 22)
            for x, y, a in ((38, 36, -65), (43, 43, 55), (40, 25, 40)):
                b.leaf(x, y, a, size=.65)
            b.pen(); b.poly([(24, 49), (57, 49), (52, 70), (29, 70)], "#dbb197", "#b78670")
            b.rect(22, 46, 37, 8, "#e7c4a8", 3)
        else:
            b.pen(width=3); b.line(41, 26, 41, 65)
            b.ellipse(24, 63, 34, 7, "#bc9c79")
            b.poly([(24, 14), (56, 14), (66, 40), (15, 40)], "#fff1bc", "#ddbb85")
            b.pen("#c6a47b", 1); b.line(56, 40, 56, 51); b.ellipse(54, 50, 4, 5, "#e8c173")
            b.shine(27, 19, 3, 9)
            if key == "lamp": b.star(15, 16, 7, "#f2d187")
    elif key in ("sunflower_painting", "rice_clock"):
        if key == "rice_clock":
            b.ellipse(12, 12, 56, 56, "#e5c49b", "#b99470"); b.ellipse(17, 17, 46, 46, "#fff9e9")
            for n in range(12):
                a = n * math.tau / 12; b.pen("#b39475", 1.5)
                b.line(40 + math.sin(a) * 18, 40 - math.cos(a) * 18, 40 + math.sin(a) * 20, 40 - math.cos(a) * 20)
            b.pen(width=2); b.line(40, 24, 40, 40, 51, 44); b.ellipse(38, 38, 4, 4, "#d69e92")
        else:
            b.rect(10, 10, 61, 58, "#d5ae80", 4); b.rect(16, 16, 49, 46, "#fff4d7", 1)
            b.pen("#8b9e6f", 2); b.line(41, 52, 41, 32)
            for n in range(8):
                a = n * math.tau / 8; b.pen("#d8ae64", .9)
                b.ellipse(35 + math.cos(a) * 10, 25 + math.sin(a) * 10, 12, 12, "#f3d48b")
            b.pen(); b.ellipse(33, 23, 16, 16, "#ac7f58")
    elif key in ("cheese_room", "sakura_room", "matcha_room", "home", "warm_home"):
        wall = {"sakura_room": "#f4d7dc", "matcha_room": "#cedbb2"}.get(key, "#f4dfb6")
        b.rect(14, 31, 52, 37, wall, 5)
        b.poly([(9, 33), (40, 10), (72, 33)], "#d6ae8c", "#b58b70")
        b.rect(25, 40, 15, 16, "#bcd9db", 3); b.pen("#a18064", 1); b.line(32, 40, 32, 56)
        b.pen(); b.rect(47, 45, 12, 23, "#b49574", 3); b.shine(18, 37, 3, 9)
        if key == "home": b.dumpling(33, 53, .38)
        elif key == "warm_home": b.star(59, 17, 8, "#f4ce84")
        elif key == "cheese_room":
            b.pen("#be9872", 1); b.line(18, 62, 41, 62); b.line(18, 66, 41, 66)
    elif key == "coin":
        b.ellipse(11, 10, 59, 59, "#fff0a9", "#d3a34f"); b.ellipse(17, 16, 47, 47, "#f6d984", "#dfb662")
        b.pen("#bc8d48", 2); b.rect(31, 29, 20, 20, "#f8dc92", 3)
        b.pen("#fdf4ca", 2); painter.drawArc(QRectF(20, 19, 41, 39), 40 * 16, 90 * 16)
        b.shine(21, 21, 4, 10)
    elif key == "bag":
        b.pen(width=2.4); painter.setBrush(Qt.BrushStyle.NoBrush); painter.drawArc(QRectF(26, 10, 27, 22), 0, 180 * 16)
        b.rect(16, 24, 50, 45, "#d9b691", 12, "#b78d6d"); b.rect(24, 42, 34, 23, "#efd3a9", 6)
        b.pen("#a78361", 1); b.line(21, 33, 60, 33); b.rect(36, 48, 11, 6, "#f0ca7d", 2)
        b.shine(21, 30, 3, 10)
    elif key == "shop":
        b.rect(14, 31, 53, 38, "#f7e7c5", 4); b.rect(22, 45, 20, 21, "#e0d4bc", 2)
        b.rect(48, 44, 12, 25, "#b49170", 2)
        b.poly([(12, 17), (68, 17), (73, 35), (7, 35)], "#edd0b4")
        for x in (12, 34, 56): b.poly([(x, 17), (x + 11, 17), (x + 14, 35), (x - 3, 35)], "#cb9292")
        b.pen(width=1.1); b.line(8, 36, 73, 36); b.shine(17, 41, 3, 9)
    elif key == "dress":
        b.rect(14, 14, 52, 55, "#d5b393", 8, "#bd9477")
        b.rect(20, 20, 40, 43, "#f3dcca", 5)
        b.pen("#b28a70", 1.4); b.line(40, 21, 40, 61)
        b.ellipse(34, 39, 3, 6, "#e3bd77"); b.ellipse(44, 39, 3, 6, "#e3bd77")
        b.shine(23, 24, 3, 11)
    elif key in ("avatar", "remove"):
        if key == "avatar": b.dumpling(41, 40, 1.65)
        else:
            b.ellipse(14, 14, 52, 52, "#f6e9d3"); b.pen("#bd9381", 3); b.line(25, 40, 55, 40)
    elif key in ("desktop", "settings", "debug"):
        if key == "desktop":
            b.rect(9, 12, 63, 44, "#c5d6d1", 6, "#94ada9"); b.rect(15, 18, 51, 31, "#f1e8cf", 3)
            b.pen(width=3); b.line(40, 57, 40, 67, 25, 67, 55, 67)
            b.dumpling(41, 35, .66)
        else:
            for n in range(8):
                painter.save(); painter.translate(40, 40); painter.rotate(n * 45)
                b.rect(-6, -30, 12, 19, "#c8beb0", 3); painter.restore()
            b.ellipse(17, 17, 46, 46, "#e1d4bd", "#b4ab9d"); b.ellipse(31, 31, 18, 18, "#fff4df")
            if key == "debug":
                b.pen("#a07657", 2.5); b.line(35, 40, 45, 40); b.line(40, 35, 40, 45)
    elif key in ("import_image", "import_folder", "import_zip", "template"):
        b.rect(14, 18, 53, 47, "#ebd0a2", 6, "#c9a57d")
        b.rect(17, 13, 25, 12, "#e4c293", 4)
        b.rect(22, 30, 35, 25, "#fff5df", 4)
        if key == "import_image": b.poly([(26, 50), (37, 38), (44, 46), (49, 41), (55, 50)], "#a6b68c")
        elif key == "import_zip":
            b.pen("#b19068", 2)
            for y in range(32, 54, 4): b.line(39, y, 42, y)
        else:
            b.pen("#ab8a69", 2); b.line(30, 37, 49, 37); b.line(30, 43, 48, 43); b.line(30, 49, 43, 49)
            if key == "template": b.poly([(47, 30), (57, 30), (57, 40)], "#e4c396")
    else:
        # Each achievement gets its own framed miniature, rather than an emoji.
        miniature = {"first_poke": "avatar", "first_drop": "flip", "first_feed": "sugar",
                     "first_pet": "sprout", "flavors_three": "strawberry", "gifts_three": "bag",
                     "level_three": "crown", "rapid_pokes": "clone", "shake": "spinning_top",
                     "rescue": "sesame", "soul_infusion": "bow", "title": "crown"}
        b.poly([(24, 51), (18, 72), (38, 65), (55, 72), (57, 49)], "#d4a3a4")
        b.ellipse(10, 8, 61, 57, "#f2dbab", "#c9a772"); b.ellipse(17, 14, 47, 44, "#fff2d4")
        if re.fullmatch(r"level_[1-6]", key):
            b.star(40, 36, 17, "#f2cf84")
            count = int(key[-1])
            b.pen("#ab8360", 2)
            for n in range(count): b.line(25 + n * 5, 58, 27 + n * 5, 58)
        elif key in miniature:
            painter.save(); painter.translate(15, 8); painter.scale(.64, .64)
            paint_icon(painter, miniature[key]); painter.restore()
            if key == "title": b.rect(24, 59, 32, 9, "#d6bf96", 2)
        else:
            b.star(40, 35, 18, "#f5d78f"); b.shine(31, 22, 3, 9)
    painter.restore()


class IconAtlas:
    """Load artist PNGs first; generate missing 80px PNGs without overwriting."""
    def __init__(self, directory: Path | None = None):
        self.directory = directory or Path(__file__).resolve().parent / "assets" / "item_icons"
        self._cache: dict = {}
        self._stamps: dict = {}
        self._writable = True
        try:
            current = self.directory.absolute()
            for part in (current, *current.parents):
                if part.exists() and (part.is_symlink() or getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
                    raise OSError("图标目录不能使用目录联接或符号链接")
            self.directory.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            logging.warning("图标缓存不可写，将直接绘制：%s", error)
            self._writable = False

    @staticmethod
    def render(key: str) -> QPixmap:
        image = QImage(240, 240, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(3, 3)
        try:
            paint_icon(painter, key)
        finally:
            painter.end()
        return QPixmap.fromImage(image.scaled(80, 80, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))

    def pixmap(self, key: str, size: int = 80) -> QPixmap:
        if re.fullmatch(r"[a-z][a-z0-9_]{0,63}", key) is None:
            key = "avatar"
        file = self.directory / (key + ".png")
        try:
            stamp = (file.stat().st_mtime_ns, file.stat().st_size)
        except OSError:
            stamp = None
        if key not in self._cache or self._stamps.get(key) != stamp:
            pixmap = QPixmap()
            if stamp is not None and stamp[1] <= 20 * 1024 * 1024 and not file.is_symlink():
                reader = QImageReader(str(file))
                dimensions = reader.size()
                if reader.format().data() == b"png" and 0 < dimensions.width() <= 8192 and 0 < dimensions.height() <= 8192:
                    reader.setScaledSize(dimensions.scaled(QSize(160, 160), Qt.AspectRatioMode.KeepAspectRatio))
                    image = reader.read()
                    if not image.isNull():
                        pixmap = QPixmap.fromImage(image)
            if pixmap.isNull():
                pixmap = self.render(key)
                if stamp is None and self._writable:
                    data = QByteArray()
                    buffer = QBuffer(data)
                    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
                    pixmap.save(buffer, "PNG")
                    buffer.close()
                    try:
                        with file.open("xb") as stream:
                            stream.write(bytes(data))
                        stamp = (file.stat().st_mtime_ns, file.stat().st_size)
                    except FileExistsError:
                        # Another instance/artist created the file first. Re-read it.
                        self._cache.pop(key, None)
                        self._stamps.pop(key, None)
                        return self.pixmap(key, size)
                    except OSError as error:
                        logging.warning("图标缓存写入未完成：%s", error)
            self._cache[key], self._stamps[key] = pixmap, stamp
        return self._cache[key].scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                      Qt.TransformationMode.SmoothTransformation)

    def icon(self, key: str) -> QIcon:
        return QIcon(self.pixmap(key))

    def warm(self) -> None:
        for key in ICON_IDS:
            self.pixmap(key)
