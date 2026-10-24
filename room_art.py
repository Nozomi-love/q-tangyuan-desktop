"""Storybook room layers and read-only artist PNG overrides.

All coordinates are scene-local. No character, economy or save state is changed
by this module. Artwork is cached in memory; an artist's files are never written.
"""
from __future__ import annotations

import math
import random
import re
import stat
from collections import OrderedDict
from functools import wraps
from pathlib import Path
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QImage, QImageReader, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient)


LAYER_ORDER = ("outdoors", "walls_floor", "back_furniture", "lighting",
               "middle_furniture", "pet", "foreground")


def line(color="#795d48", width=1.2):
    return QPen(QColor(color), width, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


def polygon(p, points, fill, stroke=None, width=1):
    p.setPen(line(stroke, width) if stroke else Qt.PenStyle.NoPen)
    p.setBrush(QColor(fill) if isinstance(fill, str) else fill)
    p.drawPolygon(QPolygonF([QPointF(*v) if isinstance(v, tuple) else v for v in points]))


def gradient(x1, y1, x2, y2, *colors):
    g = QLinearGradient(x1, y1, x2, y2)
    for i, color in enumerate(colors):
        g.setColorAt(i / max(1, len(colors)-1), QColor(color))
    return g


def soft_shadow(p, rect, strength=45):
    p.save(); p.setPen(Qt.PenStyle.NoPen)
    p.translate(rect.center()); p.scale(rect.width()/2, rect.height()/2)
    g = QRadialGradient(QPointF(), 1)
    g.setColorAt(0, QColor(65, 43, 32, strength)); g.setColorAt(.45, QColor(65, 43, 32, int(strength*.55)))
    g.setColorAt(1, QColor(65, 43, 32, 0)); p.setBrush(g)
    p.drawEllipse(QRectF(-1, -1, 2, 2)); p.restore()


def _cache_parameter(value):
    if isinstance(value,QRectF): return value.getRect()
    if isinstance(value,QPointF): return value.x(),value.y()
    if isinstance(value,QColor): return value.rgba()
    if isinstance(value,(tuple,list)): return tuple(_cache_parameter(v) for v in value)
    return value


def cached_art(bounds, *, live=None, parameters=None):
    """Cache an immutable vector drawing at its real display resolution.

    The cache sits below the PNG override check. It cannot hide a newly added
    artist file or suppress a dynamic clock/particle/furniture performance.
    """
    def decorate(draw):
        @wraps(draw)
        def paint(self,p,*args,**kwargs):
            if live is not None and live(*args,**kwargs):
                return draw(self,p,*args,**kwargs)
            rect=bounds(*args,**kwargs)
            ratio=max(.5,min(3.,abs(p.transform().m11())*p.device().devicePixelRatioF()))
            identity=parameters(*args,**kwargs) if parameters is not None else (args,tuple(sorted(kwargs.items())))
            key=(draw.__name__,_cache_parameter(identity),round(ratio,3))
            pixmap=self._sprite_cache.get(key)
            if pixmap is None:
                pixmap=QPixmap(max(1,math.ceil(rect.width()*ratio)),max(1,math.ceil(rect.height()*ratio)))
                pixmap.setDevicePixelRatio(ratio); pixmap.fill(Qt.GlobalColor.transparent)
                q=QPainter(pixmap); q.setRenderHint(QPainter.RenderHint.Antialiasing)
                q.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                q.translate(-rect.left(),-rect.top()); draw(self,q,*args,**kwargs); q.end()
                self._sprite_cache[key]=pixmap
                self._sprite_pixels+=pixmap.width()*pixmap.height()
                while len(self._sprite_cache)>32 or self._sprite_pixels>16_000_000:
                    old_key,old=self._sprite_cache.popitem(last=False)
                    self._sprite_pixels-=old.width()*old.height()
                    if old_key==key: break
            elif key in self._sprite_cache:
                self._sprite_cache.move_to_end(key)
            p.drawPixmap(rect.topLeft(),pixmap)
        return paint
    return decorate


class RoomLayerAtlas:
    """Bounded PNG reader with local-first, timestamp-aware memory caching."""
    MAX_FILE = 20 * 1024 * 1024
    MAX_PIXELS = 32_000_000
    MAX_TEXTURE = 4096

    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory or Path(__file__).resolve().parent / "assets" / "room_layers")
        self._cache = {}

    def pixmap(self, key):
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_]{1,100}", key):
            return None
        target = self.directory / (key + ".png")
        try:
            # The normal all-vector room has no overrides. An absent file must
            # cost one lstat, not a walk of every ancestor plus two realpaths.
            st = target.lstat()
            if not stat.S_ISREG(st.st_mode) or not 0 < st.st_size <= self.MAX_FILE:
                return None
            # Reject junctions as well as symlinks before any image decoder runs.
            for part in (target, *target.parents):
                if part.exists():
                    st = part.lstat()
                    if stat.S_ISLNK(st.st_mode) or getattr(st, "st_file_attributes", 0) & 0x400:
                        return None
            root = self.directory.resolve(strict=True)
            if not target.resolve(strict=True).is_relative_to(root): return None
            st = target.stat()
            if not target.is_file() or not 0 < st.st_size <= self.MAX_FILE: return None
            stamp = (st.st_mtime_ns, st.st_size)
            old = self._cache.get(key)
            if old and old[0] == stamp: return old[1]
            reader = QImageReader(str(target), b"png")
            size = reader.size()
            if size.width() <= 0 or size.height() <= 0 or size.width()*size.height() > self.MAX_PIXELS:
                return None
            if max(size.width(), size.height()) > self.MAX_TEXTURE:
                reader.setScaledSize(size.scaled(self.MAX_TEXTURE, self.MAX_TEXTURE, Qt.AspectRatioMode.KeepAspectRatio))
            image = reader.read()
            if image.isNull(): return None
            result = QPixmap.fromImage(image)
            self._cache[key] = (stamp, result)
            return result
        except (OSError, ValueError, RuntimeError):
            return None

    def paint(self, p, key, rect, *, stretch=False):
        image = self.pixmap(key)
        if image is None: return False
        target = QRectF(rect)
        if not stretch:
            factor = min(target.width()/image.width(), target.height()/image.height())
            target = QRectF(0, 0, image.width()*factor, image.height()*factor)
            target.moveCenter(rect.center())
        p.drawPixmap(target, image, QRectF(image.rect()))
        return True


class StorybookRoomArt:
    """Perspective shell, shaded furniture and atmospheric foreground."""
    def __init__(self, directory=None):
        self.layers = RoomLayerAtlas(directory)
        self._architecture_cache = None
        self._sprite_cache=OrderedDict()
        self._sprite_pixels=0
        rng = random.Random(4179)
        paper = QImage(128, 128, QImage.Format.Format_ARGB32_Premultiplied)
        paper.fill(Qt.GlobalColor.transparent)
        for y in range(128):
            for x in range(128):
                # Fine translucent paper fibres, not a flashing per-frame filter.
                a = rng.randrange(0, 13)
                paper.setPixelColor(x, y, QColor(119, 83, 49, a) if rng.random() < .54 else QColor(255, 250, 227, a))
        self.paper = QPixmap.fromImage(paper)

    @staticmethod
    def floor_y(height): return height * .61

    @classmethod
    def floor_geometry(cls,w,h):
        floor=cls.floor_y(h); vp=QPointF(w*.56,floor-h*.19)
        edges=[]
        for n in range(-12,15):
            bottom=QPointF(w*.5+n*w*.12,h)
            top=QPointF(vp.x()+(bottom.x()-vp.x())*(floor-vp.y())/(h-vp.y()),floor)
            edges.append((top,bottom))
        return {"corner":w*.22,"floor":floor,"vanishing":vp,"edges":edges}

    def layer(self, p, theme, name, rect):
        return self.layers.paint(p, theme + "__" + name, rect, stretch=True)

    def outdoors(self, p, window, daytime, time):
        p.save(); p.setClipRect(window)
        p.fillRect(window, gradient(window.left(), window.top(), window.left(), window.bottom(),
            "#8dbaca" if daytime else "#293b59", "#e6dfb8" if daytime else "#72758f"))
        p.setPen(Qt.PenStyle.NoPen)
        if daytime:
            center = window.topRight()+QPointF(-40, 36)
            glow = QRadialGradient(center, 72); glow.setColorAt(0, QColor(255, 242, 187, 170)); glow.setColorAt(1, QColor(255, 242, 187, 0))
            p.setBrush(glow); p.drawEllipse(center, 72, 72)
            p.setBrush(QColor("#fff2bc")); p.drawEllipse(center, 18, 18)
            for n in range(3):
                x = window.left()+((time*.85+n*89)%(window.width()+85))-42
                y = window.top()+28+n*21
                cloud = QPainterPath(QPointF(x-24, y+6))
                cloud.cubicTo(x-42,y-8,x-21,y-21,x-10,y-13)
                cloud.cubicTo(x-2,y-36,x+26,y-31,x+28,y-11)
                cloud.cubicTo(x+55,y-13,x+56,y+12,x+29,y+12)
                cloud.lineTo(x-20,y+12); cloud.closeSubpath()
                p.setBrush(QColor(255, 251, 230, 190)); p.drawPath(cloud)
        else:
            moon = QPainterPath(); moon.addEllipse(window.topRight()+QPointF(-40,36), 18,18)
            cut = QPainterPath(); cut.addEllipse(window.topRight()+QPointF(-32,29),17,17)
            p.setBrush(QColor("#f7e7b6")); p.drawPath(moon.subtracted(cut))
            for n in range(13):
                c = QColor("#fff1cd"); c.setAlphaF(.45+.26*math.sin(time*.7+n*1.7))
                p.setBrush(c); x=window.left()+11+(n*41)%max(12,int(window.width()-22)); y=window.top()+13+(n*29)%max(15,int(window.height()*.67))
                p.drawEllipse(QPointF(x,y),1.1+(n%3)*.25,1.1+(n%3)*.25)
        # Three distance planes: misty ridge, forest ridge, foreground canopy.
        for layer, color in enumerate(("#99b5ad" if daytime else "#687686", "#76958c" if daytime else "#4b6470", "#56786c" if daytime else "#324f5b")):
            base=window.bottom()-window.height()*(.24-layer*.075)
            path=QPainterPath(QPointF(window.left()-20,window.bottom()+2))
            path.lineTo(window.left()-20,base)
            for n in range(8):
                x=window.left()-20+n*window.width()/5
                y=base-math.sin(n*1.4+layer)*12-layer*2
                path.cubicTo(x+12,y-16,x+25,y-19,x+window.width()/5,y+2)
            path.lineTo(window.right()+40,window.bottom()+4); path.closeSubpath(); p.setBrush(QColor(color)); p.drawPath(path)
        p.restore()

    def architecture(self,p,w,h,palette,theme,window):
        key=(round(w,3),round(h,3),tuple(palette),theme,window.getRect())
        if self._architecture_cache is None or self._architecture_cache[0]!=key:
            image=QPixmap(max(1,math.ceil(w)),max(1,math.ceil(h)))
            image.fill(Qt.GlobalColor.transparent)
            q=QPainter(image); q.setRenderHint(QPainter.RenderHint.Antialiasing)
            self._architecture_uncached(q,w,h,palette,theme,window); q.end()
            self._architecture_cache=(key,image)
        p.drawPixmap(QPointF(),self._architecture_cache[1])

    def _architecture_uncached(self, p, w, h, palette, theme, window):
        wall, trim, wood, plank, grain = palette
        geometry=self.floor_geometry(w,h)
        floor=geometry["floor"]; corner=geometry["corner"]
        p.save()
        full=QPainterPath(); full.addRect(QRectF(0,0,w,h))
        hole=QPainterPath(); hole.addRect(window.adjusted(-1,-1,1,1))
        p.setClipPath(full.subtracted(hole))
        p.fillRect(QRectF(0,0,w,floor),gradient(0,0,w*.5,floor,QColor(wall).lighter(102),QColor(trim).lighter(105)))
        polygon(p,[(0,0),(corner,0),(corner,floor),(0,floor+h*.075)],gradient(0,0,corner,0,QColor(trim).darker(108),QColor(wall).darker(103)))
        # Quiet wallpaper texture follows the left-wall projection.
        p.setPen(line(QColor(grain).lighter(112),.45))
        for x in range(int(corner)+22,int(w),37): p.drawLine(QPointF(x,0),QPointF(x,floor))
        for i in range(8):
            x=corner*i/8; p.drawLine(QPointF(x,0),QPointF(x,floor+(corner-x)*.15))
        p.setPen(line(QColor(136,102,72,36),.6))
        for y in range(30,int(floor),45):
            for x in range(int(corner)+36,int(w),74):
                stem=QPainterPath(QPointF(x,y+7)); stem.cubicTo(x+6,y+2,x-5,y-2,x,y-9)
                p.drawPath(stem); p.drawLine(QPointF(x,y),QPointF(x+5,y-3))
        # All long plank edges converge to one point beyond the rear skirting.
        p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(QRectF(0,floor,w,h-floor),QColor(plank))
        vp=geometry["vanishing"]
        spread=w*.12
        for n in range(-12,14):
            xb=geometry["edges"][n+12][1].x(); xe=xb+spread
            def top_at(x): return vp.x()+(x-vp.x())*(floor-vp.y())/(h-vp.y())
            shade=QColor(plank).lighter((99,104,96)[n%3])
            polygon(p,[(top_at(xb),floor),(top_at(xe),floor),(xe,h),(xb,h)],shade)
            p.setPen(line(QColor(grain).darker(105),.8)); p.drawLine(QPointF(top_at(xb),floor),QPointF(xb,h))
            # Fine flowing grain bends inside each plank, following depth.
            p.setPen(line(QColor(255,244,215,68),.7))
            for j in range(2):
                start=QPointF(top_at(xb+spread*(.25+j*.36)),floor+7)
                end=QPointF(xb+spread*(.25+j*.36),h)
                curve=QPainterPath(start); curve.cubicTo(start+(end-start)*.4+QPointF(2,0),start+(end-start)*.75-QPointF(3,0),end); p.drawPath(curve)
            # Staggered joints get farther apart toward the viewer.
            p.setPen(line(QColor(grain).lighter(104),.65))
            for t in (.12+(n%3)*.035,.34+(n%2)*.07,.74):
                y=floor+(h-floor)*t*t
                xl=vp.x()+(xb-vp.x())*(y-vp.y())/(h-vp.y())
                xr=vp.x()+(xe-vp.x())*(y-vp.y())/(h-vp.y())
                p.drawLine(QPointF(xl,y),QPointF(xr,y))
        # The floor is bounded by the receding left skirting rather than a
        # horizontal paint rectangle cutting through the near-side wall.
        polygon(p,[(0,floor),(corner,floor),(0,floor+h*.075)],
                gradient(0,0,corner,0,QColor(trim).darker(108),QColor(wall).darker(103)))
        polygon(p,[(0,floor+h*.075),(corner,floor),(w,floor),(w,floor+12),(corner,floor+12),(0,floor+h*.075+12)],QColor(wood).darker(106))
        p.setPen(line(QColor(wood).lighter(139),2)); p.drawLine(QPointF(corner,floor),QPointF(w,floor))
        p.drawLine(QPointF(0,floor+h*.075),QPointF(corner,floor))
        corner_shadow=QLinearGradient(corner-9,0,corner+23,0)
        corner_shadow.setColorAt(0,QColor(80,61,44,0)); corner_shadow.setColorAt(.4,QColor(80,61,44,23)); corner_shadow.setColorAt(1,QColor(80,61,44,0))
        p.fillRect(QRectF(corner-9,0,32,floor),corner_shadow)
        if theme=="practice_room":
            # Muted chalk paths belong to the rear wall, never flatten the floor.
            p.save(); p.setClipRect(QRectF(corner+12,118,w-corner-30,max(20,floor-145)))
            p.setPen(line(QColor(113,137,105,52),1.1)); p.setBrush(Qt.BrushStyle.NoBrush)
            for n in range(3):
                route=QPainterPath(QPointF(corner+24,174+n*55))
                route.cubicTo(w*.35,128+n*55,w*.43,205+n*45,w*.59,158+n*51)
                p.drawPath(route)
                end=route.pointAtPercent(1); p.drawLine(end,end+QPointF(-8,-4)); p.drawLine(end,end+QPointF(-6,7))
            p.restore()
        if theme=="postmatch_studio":
            for i in range(7):
                rect=QRectF(corner+18+i*28,140,20,max(40,floor-164))
                p.setPen(line("#796773",.7)); p.setBrush(gradient(rect.left(),0,rect.right(),0,"#b29da1","#877781","#b09a98")); p.drawRoundedRect(rect,4,4)
        if theme=="camp_room":
            p.setPen(Qt.PenStyle.NoPen)
            for n in range(30):
                alpha=int(27+15*math.sin(n*1.9)); p.setBrush(QColor(255,235,173,alpha))
                p.drawEllipse(QPointF((n*63)%int(w),50+(n*43)%max(80,int(floor)-70)),1.1,1.1)
        p.drawTiledPixmap(QRectF(0,0,w,h),self.paper)
        p.restore()

    @cached_art(lambda r,wood:r.adjusted(-36,-28,36,46))
    def window_frame(self, p, r, wood):
        soft_shadow(p,r.adjusted(-17,-9,24,26),35)
        p.save(); p.setPen(line("#846447",1.2))
        outer=r.adjusted(-12,-12,13,15)
        # Paint only the surround; a filled outer rectangle would hide the sky.
        ring=QPainterPath(); ring.addRoundedRect(outer,5,5)
        opening=QPainterPath(); opening.addRect(r)
        p.save(); p.setClipPath(ring.subtracted(opening),Qt.ClipOperation.IntersectClip)
        p.setBrush(gradient(outer.left(),0,outer.right(),0,"#d9b68c","#b48b66")); p.drawRoundedRect(outer,5,5); p.restore()
        # Recess: bright left reveal, shaded upper and right reveals.
        polygon(p,[outer.topLeft(),r.topLeft(),r.bottomLeft(),QPointF(outer.left(),outer.bottom())],"#dfc29c")
        polygon(p,[outer.topLeft(),outer.topRight(),r.topRight(),r.topLeft()],"#917055")
        polygon(p,[r.topRight(),outer.topRight(),outer.bottomRight(),r.bottomRight()],"#967456")
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(line("#765e4b",1.4)); p.drawRect(r)
        for a,b in ((QPointF(r.center().x(),r.top()),QPointF(r.center().x(),r.bottom())),(QPointF(r.left(),r.center().y()),QPointF(r.right(),r.center().y()))):
            p.setPen(line("#735947",6)); p.drawLine(a,b)
            p.setPen(line("#cfac83",3)); p.drawLine(a+QPointF(-1,-1),b+QPointF(-1,-1))
        sill=QRectF(r.left()-24,r.bottom()+9,r.width()+49,17)
        polygon(p,[(sill.left(),sill.top()),(sill.right()-9,sill.top()),(sill.right(),sill.top()+8),(sill.left()-8,sill.top()+8)],"#e5c69d","#9a7758",.8)
        polygon(p,[(sill.left()-8,sill.top()+8),(sill.right(),sill.top()+8),(sill.right(),sill.bottom()),(sill.left()-8,sill.bottom())],gradient(0,sill.top(),0,sill.bottom(),"#c49c71","#ab835d"))
        p.setPen(line("#f7dfb8",1.3)); p.drawLine(QPointF(sill.left()-5,sill.top()+8),QPointF(sill.right()-2,sill.top()+8)); p.restore()

    @cached_art(lambda rect,key,clock_angles=(0,0,0):rect.adjusted(-13,-12,20,24),
                live=lambda rect,key,clock_angles=(0,0,0):key=="rice_clock",
                parameters=lambda rect,key,clock_angles=(0,0,0):(rect,key))
    def wall_decoration(self,p,rect,key,clock_angles=(0,0,0)):
        p.save()
        if key=="rice_clock":
            center=rect.center(); radius=min(rect.width(),rect.height())*.48
            soft_shadow(p,rect.adjusted(-4,2,9,9),33)
            p.translate(center)
            p.setPen(line("#9b7b56",1)); p.setBrush(gradient(-radius,0,radius,0,"#c59b6e","#e4c397","#b38a61")); p.drawEllipse(QPointF(),radius,radius)
            p.setBrush(gradient(0,-radius,0,radius,"#fff3d6","#ecdfbf")); p.drawEllipse(QPointF(-1,-2),radius-6,radius-6)
            for n in range(12):
                a=n*math.tau/12; p.setPen(line("#a08664",1.1 if n%3 else 1.8)); p.drawLine(QPointF(math.sin(a)*(radius-12),-math.cos(a)*(radius-12)),QPointF(math.sin(a)*(radius-15),-math.cos(a)*(radius-15)))
            for angle,length,width,color in zip(clock_angles,(radius*.43,radius*.64,radius*.72),(2.6,1.8,.8),("#7d6650","#7d6650","#bd8a74")):
                p.save(); p.rotate(angle); p.setPen(line(color,width)); p.drawLine(QPointF(0,3),QPointF(0,-length)); p.restore()
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#a47e55")); p.drawEllipse(QPointF(),2.8,2.8)
            p.restore(); return
        soft_shadow(p,rect.adjusted(-2,-1,9,10),32)
        polygon(p,[rect.topRight(),rect.topRight()+QPointF(5,-3),rect.bottomRight()+QPointF(5,-3),rect.bottomRight()],"#9f7753")
        polygon(p,[rect.topLeft(),rect.topRight(),rect.topRight()+QPointF(5,-3),rect.topLeft()+QPointF(5,-3)],"#ead0a5")
        p.setPen(line("#a38562",1)); p.setBrush(gradient(rect.left(),0,rect.right(),0,"#ccb18a","#e6cda7","#bf9d74")); p.drawRect(rect)
        inner=rect.adjusted(6,6,-6,-6); p.fillRect(inner,QColor("#f8edd6"))
        if key=="sunflower_painting":
            p.save(); p.setClipRect(inner); p.translate(inner.center()+QPointF(0,-7)); p.scale(.9,.9)
            p.setPen(line("#8d9d71",2.4)); stem=QPainterPath(QPointF(1,3)); stem.cubicTo(0,16,-6,27,-2,48); p.drawPath(stem)
            for side,yy in ((1,27),(-1,37)):
                leaf=QPainterPath(QPointF(-3,yy)); leaf.cubicTo(side*18,yy-17,side*27,yy-7,side*22,yy+1); leaf.quadTo(side*5,yy+6,-3,yy)
                p.setBrush(QColor("#a2b382")); p.setPen(line("#8b9c70",.6)); p.drawPath(leaf)
            for n in range(13):
                p.save(); p.rotate(n*360/13+math.sin(n*2.3)*3)
                petal=QPainterPath(QPointF(-3,2)); petal.cubicTo(-17,-7,-13,-31,-3,-35-math.sin(n)*3); petal.cubicTo(10,-32,17,-9,3,3)
                p.setPen(line("#c8a255",.6)); p.setBrush(gradient(-8,-28,6,0,"#e8c87d","#d7ad59")); p.drawPath(petal); p.restore()
            p.setPen(line("#a27c51",.7)); p.setBrush(gradient(-15,-15,12,15,"#ba925c","#886341")); p.drawEllipse(QPointF(),15,15)
            p.setPen(Qt.PenStyle.NoPen)
            for n in range(28):
                angle=n*2.4; radius=math.sqrt(n/28)*12; p.setBrush(QColor("#dcc28c" if n%2 else "#75583d")); p.drawEllipse(QPointF(math.cos(angle)*radius,math.sin(angle)*radius),.7,.9)
            p.restore()
        else:
            p.save(); p.setClipRect(inner)
            p.fillRect(inner,gradient(0,inner.top(),0,inner.bottom(),"#d8e1d0","#f0dfbb"))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#efcc86")); p.drawEllipse(inner.topRight()+QPointF(-21,19),10,10)
            for n,col in enumerate(("#bdc8af","#94aa92","#7d9786")):
                y=inner.bottom()-n*9
                mountain=QPainterPath(QPointF(inner.left()-10,inner.bottom()+5)); mountain.lineTo(inner.left()-10,y)
                mountain.cubicTo(inner.left()+19,y-27,inner.center().x()-9,y-18,inner.center().x()+6,y-8)
                mountain.cubicTo(inner.center().x()+26,y-29,inner.right()-8,y-22,inner.right()+10,y-5)
                mountain.lineTo(inner.right()+10,inner.bottom()+5); p.setBrush(QColor(col)); p.drawPath(mountain)
            p.restore()
        p.restore()

    @cached_art(lambda x,y,scale=1:QRectF(x-95*scale,y-164*scale,201*scale,203*scale))
    def bookcase(self,p,x,y,scale=1):
        p.save(); p.translate(x,y); p.scale(scale,scale)
        soft_shadow(p,QRectF(-84,-5,185,24),42)
        polygon(p,[(-72,-134),(64,-134),(82,-144),(-56,-144)],"#d7b187","#967350",.8)
        polygon(p,[(64,-134),(82,-144),(82,-5),(64,6)],"#a27a54","#876344",.8)
        polygon(p,[(-72,-134),(64,-134),(64,6),(-72,6)],gradient(-72,0,64,0,"#bf956a","#d1aa7c"),"#8b694b",1)
        for top,bottom in ((-122,-69),(-59,-8)):
            p.fillRect(QRectF(-62,top,117,bottom-top),gradient(0,top,0,bottom,"#8e6c50","#b28c65"))
            p.fillRect(QRectF(-62,bottom-2,117,6),QColor("#dfb98a"))
            p.setPen(line("#efd1a3",.8)); p.drawLine(QPointF(-60,bottom-2),QPointF(54,bottom-2))
        # Individually shaded, leaning linen book spines.
        for n,(bx,bh,c) in enumerate(((-53,36,"#9ea89a"),(-40,41,"#b57e75"),(-26,34,"#d5b67c"),(-11,43,"#859aa2"),(5,37,"#b5a1b4"))):
            p.save(); p.translate(bx,-70); p.rotate(-5+n*2)
            p.setPen(line(QColor(c).darker(127),.7)); p.setBrush(gradient(0,0,12,0,QColor(c).lighter(118),c)); p.drawRoundedRect(QRectF(0,-bh,11,bh),1.5,1.5)
            p.setPen(line("#e6d6b3",1)); p.drawLine(QPointF(2,-bh+7),QPointF(9,-bh+7)); p.restore()
        for n in range(3):
            p.setPen(line("#ac8260",.7)); p.setBrush(QColor(("#bd9490","#acb7a1","#d1b58b")[n])); p.drawRoundedRect(QRectF(-50+n*2,-17-n*8,54,7),2,2)
        # Teapot has a curved belly, spout, open handle and a highlighted lid.
        p.setPen(line("#8f7358",1.1)); p.setBrush(gradient(17,0,45,0,"#b9baa1","#eeebd0","#acae94")); p.drawEllipse(QRectF(15,-43,34,31))
        spout=QPainterPath(QPointF(18,-28)); spout.cubicTo(6,-29,7,-39,3,-41); spout.lineTo(9,-42); spout.cubicTo(13,-37,19,-38,24,-31); p.drawPath(spout)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(line("#b9b89d",5)); p.drawEllipse(QRectF(39,-39,16,20))
        p.setPen(line("#8c7759",.8)); p.setBrush(QColor("#e6dfbf")); p.drawEllipse(QRectF(23,-46,21,6)); p.drawEllipse(QRectF(30,-50,7,6))
        p.restore()

    @cached_art(lambda x,y,size=1:QRectF(x-63*size,y-222*size,126*size,255*size))
    def plant(self,p,x,y,size=1):
        p.save(); p.translate(x,y); p.scale(size,size)
        soft_shadow(p,QRectF(-42,-1,89,17),44)
        p.setPen(line("#768362",2.2)); trunk=QPainterPath(QPointF(0,-29)); trunk.cubicTo(-6,-76,4,-119,-3,-162); p.drawPath(trunk)
        for n,(lx,ly,angle,length) in enumerate(((-20,-84,-62,45),(19,-106,49,48),(-23,-132,-59,47),(8,-160,30,45),(-20,-58,-65,42))):
            p.setPen(line("#788461",1.6)); p.drawLine(QPointF(0,ly+13),QPointF(lx,ly))
            p.save(); p.translate(lx,ly); p.rotate(angle)
            leaf=QPainterPath(QPointF(0,13)); leaf.cubicTo(-20,0,-22,-length*.68,0,-length); leaf.cubicTo(19,-length*.59,19,0,0,13)
            p.setPen(line("#718363",.9)); p.setBrush(gradient(-14,0,15,0,"#6e8f70" if n%2 else "#86a280","#b3c59b")); p.drawPath(leaf)
            vein=QPainterPath(QPointF(0,11)); vein.cubicTo(3,-10,-2,-length*.65,0,-length+5)
            p.setPen(line("#cad3ab",.8)); p.drawPath(vein)
            for k in range(3):
                yy=-4-k*9; p.drawLine(QPointF(0,yy),QPointF(-10,yy-7)); p.drawLine(QPointF(0,yy-2),QPointF(9,yy-9))
            p.restore()
        pot=QPainterPath(QPointF(-30,-42)); pot.lineTo(-24,-3); pot.cubicTo(-22,7,22,7,24,-3); pot.lineTo(30,-42); pot.closeSubpath()
        p.setPen(line("#956e55",1.1)); p.setBrush(gradient(-30,0,30,0,"#bb8d70","#dfb696","#aa795f")); p.drawPath(pot)
        p.setBrush(gradient(0,-47,0,-35,"#ebc4a0","#c99574")); p.drawRoundedRect(QRectF(-33,-47,66,13),4,4)
        p.setBrush(QColor("#7f6952")); p.drawEllipse(QRectF(-27,-45,54,7))
        p.setPen(line("#f0cfac",1)); p.drawLine(QPointF(-21,-30),QPointF(-18,-7)); p.restore()

    @cached_art(lambda x,y,on=True:QRectF(x-78,y-220,156,257))
    def lamp(self,p,x,y,on=True):
        p.save(); p.translate(x,y)
        soft_shadow(p,QRectF(-62,-5,124,25),42)
        p.setPen(line("#8d7358",1.2)); p.setBrush(gradient(-37,0,35,0,"#a48965","#cfb38a","#897052")); p.drawEllipse(QRectF(-37,-11,74,17))
        p.setPen(line("#8f785a",5)); p.drawLine(QPointF(0,-11),QPointF(0,-163))
        p.setPen(line("#e8cea4",1.1)); p.drawLine(QPointF(-1,-16),QPointF(-1,-162))
        shade=QPainterPath(QPointF(-32,-201)); shade.lineTo(31,-201); shade.cubicTo(37,-183,44,-159,50,-138); shade.quadTo(0,-126,-50,-138); shade.closeSubpath()
        p.setPen(line("#a88a65",1.1)); p.setBrush(gradient(-50,-170,50,-170,"#d4ba8f","#fff0be" if on else "#e0cfac","#d5b58a")); p.drawPath(shade)
        p.setPen(line("#c3a178",.65))
        for xx in (-27,-12,12,27): p.drawLine(QPointF(xx*.7,-197),QPointF(xx*1.5,-138))
        p.setBrush(QColor("#ffe8ac" if on else "#c8b68e")); p.setPen(line("#bd9a70",.7)); p.drawEllipse(QRectF(-48,-144,96,14))
        p.setPen(line("#b3966d",1)); p.drawLine(QPointF(30,-138),QPointF(30,-113)); p.setBrush(QColor("#d6b77d")); p.drawEllipse(QRectF(27,-115,6,8)); p.restore()

    @cached_art(lambda foot,key:QRectF(foot.x()-176,foot.y()-58,352,124))
    def rug(self,p,foot,key):
        p.save(); p.translate(foot+QPointF(0,9))
        soft_shadow(p,QRectF(-160,-29,320,77),35)
        colors={"cloud_cushion":("#d7bc9d","#f1e2c9"),"cat_paw_rug":("#c69b99","#efd3cf"),"lotus_cushion":("#7f9c7c","#b8caa0"),"royal_rug":("#754c5a","#aa6c7e")}
        side,top=colors.get(key,colors["cloud_cushion"])
        shape=QPainterPath(); shape.addEllipse(QRectF(-143,-24,286,59))
        if key=="cloud_cushion":
            shape=QPainterPath(QPointF(-139,8)); shape.cubicTo(-155,-3,-130,-26,-105,-25); shape.cubicTo(-95,-42,-53,-42,-41,-30); shape.cubicTo(-7,-51,39,-37,50,-29); shape.cubicTo(104,-37,152,-11,141,13); shape.cubicTo(127,43,-107,48,-139,8)
        p.setPen(line(QColor(side).darker(107),1.1)); p.setBrush(QColor(side)); p.save(); p.translate(0,6); p.drawPath(shape); p.restore()
        p.setBrush(gradient(0,-28,0,35,QColor(top).lighter(104),top,QColor(top).darker(104))); p.drawPath(shape)
        p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(line(QColor(top).lighter(112),1.4)); p.drawArc(QRectF(-124,-19,248,47),190*16,158*16)
        p.setPen(line(QColor(side).lighter(120),.65))
        for n in range(55):
            a=n*math.tau/55; x=math.cos(a)*140; y=math.sin(a)*26+7
            p.drawLine(QPointF(x,y),QPointF(x+math.cos(a)*3,y+4))
        if key=="lotus_cushion":
            p.setPen(line("#d9e4bf",.85))
            for n in range(9):
                a=n*math.tau/9; vein=QPainterPath(QPointF()); vein.quadTo(math.cos(a)*70,math.sin(a)*13,math.cos(a)*127,math.sin(a)*23); p.drawPath(vein)
        elif key=="cat_paw_rug":
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#d6a7ad")); p.drawEllipse(QRectF(-40,-6,80,30))
            for x in (-65,-23,23,65): p.drawEllipse(QRectF(x-14,-19,28,18))
        elif key=="royal_rug":
            p.setPen(line("#dfbf7e",1.8)); p.drawEllipse(QRectF(-130,-19,260,48))
        p.restore()

    @cached_art(lambda x,y,porcelain=False,food=None:QRectF(x-109,y-77,218,143))
    def tea_table(self,p,x,y,porcelain=False,food=None):
        p.save(); p.translate(x,y); soft_shadow(p,QRectF(-89,12,178,35),45)
        for xx in (-53,43):
            polygon(p,[(xx,-2),(xx+10,-2),(xx+10,35),(xx,36)],gradient(xx,0,xx+10,0,"#b2865e","#d0aa7d"),"#9a7655",.8)
            polygon(p,[(xx+10,-2),(xx+15,-8),(xx+15,29),(xx+10,35)],"#967250")
        polygon(p,[(-76,-18),(65,-18),(78,-3),(-76,-3)],"#c8a079","#977553",.8)
        polygon(p,[(65,-18),(78,-29),(78,-3),(65,7)],"#a9825d")
        surface=QPainterPath(); surface.addRoundedRect(QRectF(-76,-32,154,24),9,9)
        p.setPen(line("#aa825a",.9)); p.setBrush(gradient(0,-32,0,-8,"#e1c49b","#cfaa7c")); p.drawPath(surface)
        p.setPen(line("#f0d7ae",.8))
        for yy in (-26,-18):
            curve=QPainterPath(QPointF(-65,yy)); curve.cubicTo(-27,yy-2,12,yy+3,65,yy); p.drawPath(curve)
        # Low tea tray instead of a second character-sized empty bowl.
        p.setBrush(QColor("#b18a60")); p.setPen(line("#96744f",.75)); p.drawEllipse(QRectF(-31,-40,67,15))
        p.setBrush(gradient(-24,0,27,0,"#e4ebe6" if porcelain else "#dbc09a","#fff7dc","#c1cbd0" if porcelain else "#c8a57d")); p.drawRoundedRect(QRectF(-24,-54,50,18),5,5)
        p.setBrush(QColor("#c4a77f")); p.drawEllipse(QRectF(-23,-57,48,9))
        if porcelain:
            p.setPen(line("#7b9bab",1)); p.drawArc(QRectF(-14,-50,10,9),0,160*16); p.drawArc(QRectF(4,-50,10,9),0,160*16)
        if food:
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(food)); p.drawEllipse(QRectF(-18,-55,37,6))
        p.restore()

    def ambience(self,p,w,h,window,daytime,time,lamp=None):
        self._ambient_base(p,w,h,window,daytime,lamp)
        warm=(255,231,170) if daytime else (181,207,241)
        p.save(); p.setPen(Qt.PenStyle.NoPen)
        for n in range(12):
            t=(time*.023+n*.079)%1
            point=QPointF(window.center().x()-t*w*.22+math.sin(n*1.7)*22,window.bottom()+t*(h-window.bottom()))
            c=QColor(*warm,int((.5+.5*math.sin(t*math.pi))*28)); p.setBrush(c); p.drawEllipse(point,.8,.8)
        p.restore()

    @cached_art(lambda w,h,window,daytime,lamp=None:QRectF(0,0,w,h))
    def _ambient_base(self,p,w,h,window,daytime,lamp=None):
        p.save(); p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(QRectF(0,0,w,h),QColor(255,222,169,8) if daytime else QColor(38,51,79,30))
        warm=(255,231,170) if daytime else (181,207,241)
        # Nested translucent wedges feather both sides of the oblique beam.
        for n in range(7):
            inset=n*3.2
            beam=QLinearGradient(window.center(),QPointF(window.left()-w*.12,h))
            beam.setColorAt(0,QColor(*warm,5)); beam.setColorAt(.65,QColor(*warm,8)); beam.setColorAt(1,QColor(*warm,0))
            polygon(p,[QPointF(window.left()+inset,window.bottom()),QPointF(window.right()-inset,window.bottom()),QPointF(w*.77-inset,h),QPointF(w*.31+inset,h)],beam)
        if lamp:
            lx,ly=lamp
            glow=QRadialGradient(QPointF(lx,ly-165),230)
            glow.setColorAt(0,QColor(255,208,125,72)); glow.setColorAt(.5,QColor(255,206,127,25)); glow.setColorAt(1,QColor(255,199,117,0))
            p.setBrush(glow); p.drawEllipse(QPointF(lx,ly-165),230,230)
            p.save(); p.translate(lx,ly+3); p.scale(1,.28)
            glow=QRadialGradient(QPointF(),180); glow.setColorAt(0,QColor(255,214,143,60)); glow.setColorAt(1,QColor(255,214,143,0)); p.setBrush(glow); p.drawEllipse(QPointF(),180,180); p.restore()
        p.restore()

    def foreground(self,p,w,h,table,time):
        # The string lights are steadily lit. Cloud/stardust motion is separate.
        self._foreground_base(p,w,h,table)

    @cached_art(lambda w,h,table:QRectF(0,0,w,h))
    def _foreground_base(self,p,w,h,table):
        # Stronger scale at the front provides an intentional foreground plane.
        x,y,tw,th=table.x(),table.y(),table.width(),table.height()
        p.save(); soft_shadow(p,QRectF(x-13,y+th-17,tw+30,35),46)
        depth=th*.65; thickness=th*.15
        for lx in (x+23,x+tw-35):
            polygon(p,[(lx,y+depth+thickness-2),(lx+11,y+depth+thickness-2),(lx+10,y+th),(lx+2,y+th)],"#a47d54","#9a744d",.8)
            polygon(p,[(lx+11,y+depth+thickness-2),(lx+15,y+depth+thickness-5),(lx+14,y+th-4),(lx+10,y+th)],"#8e6c48")
        polygon(p,[(x,y+depth),(x+tw,y+depth),(x+tw,y+depth+thickness),(x,y+depth+thickness)],gradient(0,y+depth,0,y+depth+thickness,"#c29764","#ae824f"),"#9f774f",.9)
        polygon(p,[(x,y+depth),(x+tw,y+depth),(x+tw-14,y),(x+14,y)],gradient(0,y,0,y+depth,"#edcf9e","#d8b27b"),"#b18b5d",.9)
        p.setPen(line("#f4dab1",1.1)); p.drawLine(QPointF(x+2,y+depth+1),QPointF(x+tw-2,y+depth+1))
        for n in range(3):
            yy=y+9+n*14; grain=QPainterPath(QPointF(x+14,yy)); grain.cubicTo(x+tw*.3,yy-3,x+tw*.66,yy+4,x+tw-15,yy)
            p.setPen(line(QColor(244,219,171,85),.85)); p.drawPath(grain)
        # Top edge garland: foreground cable, glowing bulbs and curved leaves.
        wire=QPainterPath(QPointF(-10,1)); wire.cubicTo(w*.21,39,w*.33,14,w*.48,12); wire.cubicTo(w*.7,10,w*.83,45,w+10,4)
        p.setPen(line("#928269",1.7)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(wire)
        for n in range(13):
            t=(n+.4)/13; point=wire.pointAtPercent(t)
            glow=QRadialGradient(point+QPointF(0,7),14); glow.setColorAt(0,QColor(255,226,158,95)); glow.setColorAt(1,QColor(255,226,158,0))
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow); p.drawEllipse(point+QPointF(0,7),14,14)
            p.setPen(line("#b59c70",1)); p.drawLine(point,point+QPointF(0,5))
            p.setBrush(QColor("#ffedb1")); p.setPen(line("#dbc28f",.6)); p.drawEllipse(point+QPointF(0,8),3.4,4.2)
        for side in (-1,1):
            p.save(); p.translate(15 if side<0 else w-12,-4); p.scale(-side,1)
            for n in range(4):
                p.save(); p.translate(n*19,1+n*3); p.rotate(-40+n*23)
                leaf=QPainterPath(QPointF()); leaf.cubicTo(-8,12,-5,32,4,44); leaf.cubicTo(17,27,13,8,0,0)
                p.setOpacity(.7-n*.08); p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#6f8967" if n%2 else "#8da17b")); p.drawPath(leaf); p.restore()
            p.restore()
        p.restore()

    @staticmethod
    def summit_holds(rect):
        return tuple(QPointF(rect.left()+rect.width()*x, rect.top()+rect.height()*y)
                     for x,y in ((.28,.76),(.63,.48),(.45,.21)))

    @cached_art(lambda rect:rect.adjusted(-12,-9,15,17))
    def summit_wall(self, p, rect):
        soft_shadow(p,rect.adjusted(-2,3,7,11),28)
        p.save();p.setPen(line("#8c7356",1.2));p.setBrush(gradient(rect.left(),0,rect.right(),0,"#c6ae84","#a78c64"));p.drawRoundedRect(rect,7,7)
        inner=rect.adjusted(7,7,-7,-7)
        p.setBrush(gradient(0,inner.top(),0,inner.bottom(),"#ddc7a1","#bea77e"));p.drawRoundedRect(inner,3,3)
        p.setPen(line(QColor(122,100,70,72),.8))
        for n in range(8):
            x=inner.left()+9+n*inner.width()/8
            path=QPainterPath(QPointF(x,inner.top()+5));path.cubicTo(x-4,inner.center().y()-11,x+5,inner.center().y()+15,x,inner.bottom()-5);p.drawPath(path)
        holds=self.summit_holds(rect)
        p.setPen(line("#f1e4c5",1.8));p.setBrush(Qt.BrushStyle.NoBrush)
        path=QPainterPath(holds[0]);path.cubicTo(holds[0]+QPointF(38,1),holds[1]+QPointF(-25,15),holds[1]);path.cubicTo(holds[1]+QPointF(10,-17),holds[2]+QPointF(23,11),holds[2]);p.drawPath(path)
        for i,point in enumerate(holds):
            polygon(p,[(point.x()-10,point.y()+5),(point.x()-8,point.y()-4),(point.x()+4,point.y()-8),(point.x()+12,point.y()+1),(point.x()+7,point.y()+8)],("#c48c73","#8ca2a3","#9daa80")[i],"#8b775b",1)
            p.setPen(line("#f5e5c8",.9));p.drawLine(point+QPointF(-6,-2),point+QPointF(3,-5))
        for point in (inner.topLeft()+QPointF(3,3),inner.topRight()+QPointF(-3,3),inner.bottomLeft()+QPointF(3,-3),inner.bottomRight()+QPointF(-3,-3)):
            p.setPen(line("#806d54",1));p.setBrush(QColor("#b89f79"));p.drawEllipse(point,2,2)
        p.restore()
