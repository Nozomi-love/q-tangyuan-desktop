"""Illustrated room view; the desktop engine remains the only physics clock."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime
from time import monotonic
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF, QRadialGradient, QTransform)
from pet_engine import RoomCanvas, PetState, Pose, clamp
from illustrated_assets import IconAtlas, plain_text



OUTLINE = "#70513b"


def ink(width=3.0):
    return QPen(QColor(OUTLINE), width, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


class RoomLife:
    """Room-only activity clock. Input cancels a pose through a short blend."""
    KINDS = ("bowl", "window", "nap", "hum", "hop")

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.accelerated = False
        self.elapsed = self.phase_time = self.quiet = 0.0
        self.state = "idle"
        self.x = self.target = .48
        self.wait = self.rng.uniform(12, 25)
        self.last_line = -80.0
        self.cycle = 0
        self.toy_available = False
        self._nap_announced = False
        self._previous_kind = ""
        self._blend_from = (1, 1, 0, 0)
        self._blend_age = .22

    def _next_wait(self):
        return self.rng.uniform(2, 4) if self.accelerated else self.rng.uniform(12, 25)

    def interact(self):
        if self.state != "idle":
            self._blend_from = self.pose; self._blend_age = 0.0
        self.state = "idle"
        self.phase_time = self.quiet = 0.0
        self.wait = self._next_wait()

    def start_activity(self, kind):
        choices = {"bowl": ("walk_bowl", .68), "window": ("walk_window", .60),
                   "nap": ("nap", self.x), "toy": ("walk_toy", .63),
                   "hum": ("hum", self.x), "hop": ("hop", self.x)}
        if kind not in choices: return False
        self._blend_from = self.pose; self._blend_age = 0
        self.state, self.target = choices[kind]; self.phase_time = 0.0
        self._nap_announced = False; self._previous_kind = kind
        return True

    @staticmethod
    def daily_line(hour, hunger, level):
        if hunger < 35: return "饭香好像从那边飘过来了。"
        if hour < 6 or hour >= 23: return "夜深啦，我陪你慢慢收个尾，记得早点休息。"
        if hour < 11: return "太阳升起了，大脑空空"
        if hour < 14: return "午饭时间，别忘了也照顾好自己。"
        if hour < 17: return "午后的光好暖，想和你坐一会儿。"
        if level >= 3: return "你回来啦，这盏小灯一直为你留着。"
        return "月亮来值班，我也在这里陪你。"

    def advance(self, dt, *, hunger=80, level=1, hour=12, blocked=False):
        messages = []; remaining = max(0.0, min(float(dt), 60.0))
        while remaining > 1e-9:
            step = min(.05, remaining); remaining -= step; self.elapsed += step
            self._blend_age += step
            if blocked:
                self.interact(); continue
            self.quiet += step; self.phase_time += step
            if self.state == "idle":
                self.wait -= step
                if self.wait <= 0 and self.quiet >= (1 if self.accelerated else 6):
                    options = list(self.KINDS) + (["toy"] if self.toy_available else [])
                    options = [kind for kind in options if kind != self._previous_kind]
                    choice = "bowl" if hunger < 35 and self._previous_kind != "bowl" else self.rng.choice(options)
                    self.cycle += 1; self.start_activity(choice)
            elif self.state.startswith("walk_") or self.state == "return":
                difference = self.target - self.x
                self.x += clamp(difference, -step * .055, step * .055)
                if abs(difference) < .002:
                    self.x = self.target
                    self.state = {"walk_bowl": "sniff", "walk_window": "look_window", "walk_toy": "inspect", "return": "idle"}[self.state]
                    self.phase_time = 0.0
                    if self.state == "idle": self.wait = self._next_wait()
                    elif self.elapsed - self.last_line >= (20 if self.accelerated else 55):
                        text = ("闻到香味了，给我留一口好不好？" if self.state == "sniff" and hunger < 50
                                else "看看小玩具，还在乖乖等我。" if self.state == "inspect"
                                else "云朵也在慢慢散步呢。" if 6 <= hour < 18 and self.state == "look_window"
                                else "月亮今晚也圆乎乎的。" if self.state == "look_window"
                                else self.daily_line(hour, hunger, level))
                        messages.append(text); self.last_line = self.elapsed
            elif self.state == "nap":
                if not self._nap_announced:
                    self._nap_announced = True
                    if self.elapsed - self.last_line >= 55:
                        messages.append("zZ  眯一小会儿"); self.last_line = self.elapsed
                if self.phase_time >= 5: self.state = "stretch"; self.phase_time = 0.0
            elif self.state == "stretch":
                if self.phase_time >= 2: self.state = "return"; self.target = .48; self.phase_time = 0.0
            elif self.phase_time >= (1.3 if self.state == "hop" else 3.5):
                self.state = "return"; self.target = .48; self.phase_time = 0.0
            if self.quiet > 6 and self.elapsed - self.last_line >= (20 if self.accelerated else 70):
                messages.append(self.daily_line(hour, hunger, level)); self.last_line = self.elapsed
            self.x = clamp(self.x, .28, .70)
        return messages

    def _pose(self):
        t = self.phase_time
        if self.state == "nap":
            sy = 1 - .22 * min(1, t * 2) + .015 * math.sin(t * 2)
            return 1 / sy, sy, 0.0, 0.0
        if self.state == "stretch":
            sy = 1 + .22 * math.sin(min(1, t / 2) * math.pi)
            return 1 / sy, sy, math.sin(t * 16) * 2 * max(0, 1 - t / 2), 0.0
        if self.state.startswith("walk_") or self.state == "return":
            return 1.0, 1.0, math.sin(self.elapsed * 6) * 3, -abs(math.sin(self.elapsed * 6)) * 4
        if self.state == "sniff": return 1.02, .98, math.sin(t * 5) * 4, 0.0
        if self.state == "look_window": return .98, 1.02, -6.0, -2.0
        if self.state == "inspect": return 1.02, .98, math.sin(t * 4) * 5, -abs(math.sin(t * 3)) * 5
        if self.state == "hum": return 1.02, .98, math.sin(t * 4) * 7, 0.0
        if self.state == "hop": return 1.0, 1.0, math.sin(t * 5) * 3, -28 * max(0, math.sin(min(1, t / 1.3) * math.pi))
        return 1.0, 1.0, 0.0, 0.0

    @property
    def pose(self):
        t = clamp(self._blend_age / .22, 0, 1); t = t * t * (3 - 2 * t)
        return tuple(a + (b - a) * t for a, b in zip(self._blend_from, self._pose()))


@dataclass
class GiftPerformance:
    item_id: str
    duration: float = 7.0
    age: float = 0.0
    angle: float = 0.0
    speed: float = 620.0
    top_x: float = .735
    start_x: float = .48

    def advance(self, dt):
        remaining = max(0.0, min(float(dt), 60))
        while remaining > 1e-9:
            step = min(.02, remaining); remaining -= step; self.age += step
            if self.item_id == "spinning_top":
                self.angle = (self.angle + self.speed * step) % 360
                self.speed = max(240, self.speed * math.exp(-.045 * step))

    @property
    def active(self): return self.age < self.duration

    @property
    def pet_x(self):
        if self.item_id == "spinning_top": return self.start_x
        # Only the bouquet needs an approach. Other gifts play where the pet is.
        # Reserve the final 1.4 seconds to return to this performance's origin.
        target = .61 if self.item_id == "flower_bouquet" else self.start_x
        returning = self.age >= self.duration - 1.4
        t = (clamp((self.duration - self.age) / 1.4, 0, 1) if returning
             else clamp(self.age / min(2.5, self.duration * .4), 0, 1))
        t = t * t * (3 - 2 * t)
        return self.start_x + (target - self.start_x) * t

    @property
    def spin_angle(self):
        if self.item_id != "spinning_top": return 0.0
        progress = clamp((self.age - .6) / max(.1, self.duration - 1.1), 0, 1)
        # Eight full turns; zero starting/ending speed and an upright finish.
        return 2880 * (progress - math.sin(math.tau * progress) / math.tau)

    @property
    def yaw_scale(self):
        if self.item_id != "spinning_top": return 1.0
        cosine = math.cos(math.radians(self.spin_angle))
        # A side-on silhouette stays thin and invertible for pointer hit testing.
        return math.copysign(max(.065, abs(cosine)), cosine)

    @property
    def pose(self):
        t = self.age
        if self.item_id in ("music_box", "tes_guitar", "tes_microphone"):
            wave = .035 * math.sin(t * 7)
            return 1 + wave, 1 - wave, math.sin(t * 7) * 10, -abs(math.sin(t * 3.5)) * 6
        if self.item_id == "spinning_top":
            return 1.0, 1.0, 0.0, 0.0
        if self.item_id == "paper_star": return 1.0, 1.0, math.sin(t * 3) * 6, -abs(math.sin(t * 3)) * 9
        return 1.03, .97, math.sin(t * 2) * 4, -2.0


class RoomPetView:
    """Read-only pose adapter for the shared skin and ornament pipeline."""
    def __init__(self, engine, local_pose=(1, 1, 0, 0), yaw_scale=1.0):
        self.engine, self.local_pose = engine, local_pose
        self.yaw_scale = yaw_scale
    @property
    def visual_angle(self): return self.engine.visual_angle
    def __getattr__(self, name): return getattr(self.engine, name)
    @property
    def pose(self):
        base = self.engine.pose; sx, sy, angle, _hop = self.local_pose
        return Pose(base.scale_x * sx, base.scale_y * sy, base.angle + angle)


class IllustratedRoomCanvas(RoomCanvas):
    """A large pet, curtained window, wallpaper detail and feeding flight."""
    sound_requested = Signal(str)
    mood_requested = Signal(float)
    air_conditioner_toggle_requested = Signal()

    THEMES = dict(RoomCanvas.THEMES, camp_room=("#bbb9d0", "#ada4bd", "#877664", "#d0b9a4", "#a18b7a"))

    FLIGHT_SECONDS = .78
    CHEW_SECONDS = .9

    def __init__(self, engine, renderer_provider, parent=None, atlas: IconAtlas | None = None):
        super().__init__(engine, renderer_provider, parent)
        self.atlas = atlas or IconAtlas()
        self.setMinimumHeight(420)
        self.setAccessibleName("汤圆的家：互动房间")
        self._fly_started = -100.0
        self._fly_from: QPointF | None = None
        self._pet_zoom = 1.48
        self.life = RoomLife()
        self.performance: GiftPerformance | None = None
        self._gift_queue = []
        self._floating = []
        self._last_scene_tick = monotonic()
        self._last_external = (-1.0, -1.0, -1.0)
        self._chew_started = -100.0
        self._last_toy = ""
        self._room_trick = ""
        self._room_trick_origin = self.life.x
        self._food_age = 100.0
        self._food_queue = []
        self._food_arrived = False
        self._pending_hunger = 0.0
        self._food_gain = 0.0
        self._next_food_origin = None
        self.environment_time = 0.0
        self._chime_rang_at = -100.0
        self.poke_requested.connect(self.interact)
        self.pet_requested.connect(self.interact)

    def _mood(self, duration):
        self.mood_requested.emit(duration)
        e = self.engine
        self._last_external = (e.happy_until, e.dizzy_until, e.last_drag_time)

    def interact(self, cancel_gift=False):
        if cancel_gift:
            if self.performance:
                self.life.x = self.performance.pet_x
                self.performance = None
            self._last_toy = ""
            self.update()
        self.life.interact()

    def stop(self):
        self.performance = None
        self._gift_queue.clear()
        self._last_toy = ""
        super().stop()

    def start_activity(self, kind):
        if self._busy(): return False
        self.interact(cancel_gift=True)
        started = self.life.start_activity(kind)
        if started and kind == "nap": self._mood(5.0)
        if started and kind == "hop": self.mood_requested.emit(1.5)
        return started

    def _busy(self):
        e = self.engine
        return bool(e.held or e.dragging or e.flat or e.active_trick or e.state == PetState.DIZZY)

    def _local_pose(self):
        if self._busy(): return (1, 1, 0, 0)
        pose = self.performance.pose if self.performance else self.life.pose
        age = self._food_age - self.FLIGHT_SECONDS
        if self._food_arrived and 0 <= age <= self.CHEW_SECONDS:
            # Three closed squash/stretch cycles, then exactly the neutral pose.
            wave = -.12 * math.sin(age / self.CHEW_SECONDS * math.pi * 3) ** 2
            return pose[0] / (1 + wave), pose[1] * (1 + wave), pose[2], pose[3]
        return pose

    def begin_trick(self, trick_id):
        if self._room_trick == trick_id: return
        self.interact(cancel_gift=True)
        self._room_trick_origin = self.life.x
        self._room_trick = trick_id
        self.life.interact()

    def finish_trick(self, trick_id):
        if trick_id != self._room_trick: return
        if not self.performance: self.life.x = self._room_trick_origin
        self._room_trick = ""
        self.life.interact()

    def _sync_room_trick(self):
        current = self.engine.active_trick
        if current != self._room_trick:
            if self._room_trick: self.finish_trick(self._room_trick)
            if current: self.begin_trick(current)

    def _trick_home_foot(self):
        self._sync_room_trick()
        foot = self._base_foot()
        foot.setX(self._geometry()[1] * self._room_trick_origin)
        return foot

    def _view(self):
        self._sync_room_trick()
        yaw = self.performance.yaw_scale if self.performance and not self._busy() else 1.0
        return RoomPetView(self.engine, self._local_pose(), yaw)

    def _repaint_if_visible(self):
        now = monotonic(); dt = clamp(now - getattr(self, "_last_scene_tick", now), 0, .1)
        self._last_scene_tick = now
        if not self.isVisible(): return
        e = self.engine
        external = (e.happy_until, e.dizzy_until, e.last_drag_time)
        if external != self._last_external:
            self.life.interact(); self._last_external = external
        self.advance_scene(dt)
        self._advance_message(); self.update()

    def advance_scene(self, dt, hour=None):
        """One visible-scene tick, exposed for deterministic animation tests."""
        self._sync_room_trick()
        self.environment_time += clamp(float(dt), 0, 60)
        busy = self._busy()
        if busy and self.performance:
            self.interact(cancel_gift=True)
        self.life.toy_available = any(self._home.get("inventory", {}).get(k, 0)
            for k in ("spinning_top", "music_box", "paper_star", "flower_bouquet", "tes_guitar", "tes_microphone"))
        old_state = self.life.state
        messages = self.life.advance(dt, hunger=self._home.get("hunger", 80),
            level=self._home.get("affection_level", 1), hour=datetime.now().hour if hour is None else hour,
            blocked=busy or bool(self.performance) or self._food_age < self.FLIGHT_SECONDS + self.CHEW_SECONDS)
        if old_state != "nap" and self.life.state == "nap": self.mood_requested.emit(5.0)
        for text in messages:
            self.show_message(text, "ambient", 2.7)
        if self.performance and not busy:
            self.performance.advance(dt)
            if not self.performance.active:
                finished = self.performance
                self.life.x = finished.start_x
                self.performance = None
                self._last_toy = ""
                self.life.interact()
        if not self.performance and self._gift_queue and not busy:
            self._begin_gift(*self._gift_queue.pop(0))
        self._advance_food(dt)
        self._floating = [f for f in self._floating if monotonic() - f[1] < 1.2]

    def _begin_gift(self, item_id, duration, dialogue=""):
        self.performance = GiftPerformance(item_id, duration, start_x=self.life.x)
        self._last_toy = ""
        if dialogue: self.show_message(dialogue, "interaction")
        self.mood_requested.emit(duration)
        if item_id in ("music_box", "tes_guitar", "tes_microphone"): self.sound_requested.emit("music_box")

    def receive_gains(self, gains):
        # Hunger arrives with its food. Other rewards need no item performance.
        self._pending_hunger += max(0, gains.get("hunger", 0))
        self.show_gains({key: value for key, value in gains.items() if key != "hunger"})

    def show_gains(self, gains):
        now = monotonic()
        names = {"hunger": "饱食度", "exp": "好感", "coins": "糯米币"}
        self._floating = [f for f in self._floating if now - f[1] < 1.2]
        for key, value in gains.items():
            if key not in names or value <= 0: continue
            suffix = names[key]
            # Combine a rapid stream in the same lane instead of covering dialogue.
            index = next((i for i, (text, born) in enumerate(self._floating)
                          if text.endswith(suffix) and now - born < .18), None)
            if index is not None:
                previous = float(self._floating[index][0].split()[0][1:])
                self._floating[index] = (f"+{previous + value:g} {suffix}", now)
            else:
                self._floating.append((f"+{value:g} {suffix}", now))
        self._floating = self._floating[-6:]
        self.update()

    def present_item(self, event):
        self.interact()
        if event.get("category") == "food":
            gain = max(0, event.get("hunger_gain", 0))
            self._pending_hunger = max(0, self._pending_hunger - gain)
            self.show_food(event["item_id"], gain)
        else:
            item_id = event.get("effect", event["item_id"])
            if item_id in {"spinning_top", "music_box", "paper_star", "flower_bouquet", "tes_guitar", "tes_microphone"}:
                duration = clamp(float(event.get("duration", 7)), 6, 8)
                dialogue = event.get("dialogue", "")
                if not self.performance and not self._busy(): self._begin_gift(item_id, duration, dialogue)
                else:
                    self._gift_queue.append((item_id, duration, dialogue)); self._gift_queue = self._gift_queue[-8:]
        self.update()

    def _render_foot(self):
        self._sync_room_trick()
        if self.engine.active_trick == "screen_roll":
            return self._trick_home_foot() + self._local_roll_offset() - self.engine.visual_offset
        foot = super()._render_foot()
        if self.engine.active_trick:
            foot.setX(self._trick_home_foot().x())
        else:
            _scale, width, _height = self._geometry()
            ratio = self.performance.pet_x if self.performance else self.life.x
            # Busy states override the pose, never the room's saved location.
            # Preserve the separate spicy-running displacement from the base view.
            foot.setX(width * ratio + foot.x() - self._base_foot().x())
        if not self._busy():
            foot.setY(foot.y() + self._local_pose()[3])
        return foot

    def _base_foot(self):
        _scale, width, height = self._geometry()
        return QPointF(width * .48, height - 83)

    def _pet_transform(self):
        foot = self._base_foot()
        scale, width, height = self._geometry()
        top = max(125.0, 148.0 / scale)
        renderer = self.renderer_provider(); view = self._view()
        bounds = renderer.scene_bounds(view, self._render_foot())
        if self.performance and self.performance.item_id == "spinning_top" and not self._busy():
            # Fit both faces at full width so a thin side view never zooms in.
            front = RoomPetView(self.engine, self._local_pose())
            back = RoomPetView(self.engine, self._local_pose(), -1.0)
            bounds = renderer.scene_bounds(front, self._render_foot()).united(
                renderer.scene_bounds(back, self._render_foot()))
        # The HUD occupies widget pixels while the room uses logical scene
        # units. Fit the full accessory/trick envelope beneath it on small views.
        zoom = min(self._pet_zoom * min(1.9, max(1.0, 900 / max(1, self.width()))), max(20.0, width - 50) / max(1.0, bounds.width()),
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
        point = renderer.body_transform(self._view(), self._render_foot()).map(renderer.visible_rect(self.engine.state).center())
        return self._pet_transform().map(point) * self._geometry()[0]

    def pet_bounds(self):
        rect = self._pet_transform().mapRect(self.renderer_provider().scene_bounds(self._view(), self._render_foot()))
        scale = self._geometry()[0]
        return QRectF(rect.x() * scale, rect.y() * scale, rect.width() * scale, rect.height() * scale)

    def _hit_pet(self, point):
        local = point / self._geometry()[0]
        inverse, ok = self._pet_transform().inverted()
        return ok and self.renderer_provider().hit_test(self._view(), self._render_foot(), inverse.map(local))

    def show_message(self, text, tone="info", duration=2.5):
        super().show_message(plain_text(text), tone, duration)

    def _begin_food(self, item_id, gain, origin):
        super().show_food(item_id)
        self._fly_started = monotonic(); self._chew_started = self._fly_started + self.FLIGHT_SECONDS
        self._food_age = 0.0; self._food_arrived = False
        self._food_gain = gain; self._fly_from = origin
        self._food_audio_already = not self.isVisible()

    def show_food(self, item_id, gain=0):
        self.interact(cancel_gift=True)
        origin = self._next_food_origin
        self._next_food_origin = None
        if self._food_age < self.FLIGHT_SECONDS + self.CHEW_SECONDS:
            if len(self._food_queue) < 6: self._food_queue.append((item_id, gain, origin))
            else:
                key, amount, point = self._food_queue[-1]
                self._food_queue[-1] = (key, amount + gain, point)
        else: self._begin_food(item_id, gain, origin)

    def launch_food(self, item_id, origin: QPointF):
        self._next_food_origin = QPointF(origin)
        self.show_food(item_id)

    def _advance_food(self, dt):
        self._food_age += max(0, dt)
        if not self._food_arrived and self._food_age >= self.FLIGHT_SECONDS and self._food_age < 100:
            self._food_arrived = True
            self.mood_requested.emit(1.2)
            if not self._food_audio_already: self.sound_requested.emit("eat")
            self.show_gains({"hunger": self._food_gain})
        if self._food_age >= self.FLIGHT_SECONDS + self.CHEW_SECONDS and self._food_queue:
            self._begin_food(*self._food_queue.pop(0))

    def _paint_life_particles(self, p):
        if self._busy() or self.performance: return
        bounds = self.pet_bounds()
        if self.life.state == "nap":
            p.save(); p.setPen(QColor("#827a9f"))
            for i in range(3):
                phase = (self.life.phase_time * .3 + i / 3) % 1
                p.setOpacity(math.sin(phase * math.pi)); p.setFont(QFont("Microsoft YaHei UI", 10 + i * 2, QFont.Weight.Bold))
                p.drawText(QPointF(bounds.right() - 8 + phase * 15, bounds.top() + 20 - phase * 40), "z" if i == 0 else "Z")
            p.restore()
        elif self.life.state == "hum":
            for i in range(3):
                phase = (self.life.phase_time * .32 + i / 3) % 1
                p.save(); p.setOpacity(math.sin(phase * math.pi))
                self._note(p, QPointF(bounds.right() + math.sin(phase * 5) * 14, bounds.top() + 35 - phase * 50),
                           ("#b88298", "#8b9f76", "#c69c5e")[i]); p.restore()

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
        self._shadow(painter, foot + QPointF(0, 19), 175, 24)
        painter.save(); painter.translate(foot.x(), foot.y()); painter.scale(1.36, 1.36); painter.translate(-foot.x(), -foot.y())
        self._paint_rug(painter, foot)
        painter.restore()
        self._paint_bowl(painter, width, height)
        foreground_gift = self.performance and self.performance.item_id in {"tes_guitar", "tes_microphone"}
        if not foreground_gift:
            self._paint_gift(painter, width, height)
        self._paint_companion(painter)
        contact = self._pet_transform().map(self._render_foot())
        self._shadow(painter, QPointF(contact.x(), self._base_foot().y() + 3), 88, 15)
        painter.save(); painter.setTransform(self._pet_transform(), combine=True)
        self.renderer_provider().paint(painter, self._view(), self._render_foot())
        painter.restore()
        if foreground_gift:
            self._paint_gift(painter, width, height)
        self._paint_ambient(painter, width, height)
        painter.restore()
        self._paint_life_particles(painter)
        self._paint_food_flight(painter)
        self._paint_gains(painter)
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
        if self._slot("theme") == "camp_room":
            p.setPen(Qt.PenStyle.NoPen)
            for i in range(26):
                x=23+(i*83) % max(40,int(width-50)); y=142+(i*47)%max(35,int(floor-160))
                color=QColor("#fff0be");color.setAlphaF(.3+.2*math.sin(self.environment_time*.7+i))
                p.setBrush(color);p.drawEllipse(QPointF(x,y),1.6,1.6)
            p.setPen(QPen(QColor("#79523b"),2.2));p.setBrush(QColor("#d6ba90"))
            tent_x=width*.18
            p.drawPolygon(QPolygonF([QPointF(tent_x-56,height-53),QPointF(tent_x,height-142),QPointF(tent_x+56,height-53)]))
            p.setBrush(QColor("#67617d"))
            p.drawPolygon(QPolygonF([QPointF(tent_x-21,height-53),QPointF(tent_x,height-110),QPointF(tent_x+22,height-53)]))
        # The upper 110 units belong to the floating HUD, not a second title.
        window = self.window_rect(width, height)
        self._paint_window(p, window, wood)
        self._curtains(p, window)
        self._paint_chime(p, window)
        if not self._slot("wall"):
            self._little_landscape(p, QRectF(width * .22 - 56, 161, 112, 91))
        self._shadow(p, QPointF(width - 91, height - 73), 37, 8)
        self._houseplant(p, width - 91, height - 78)
    def chime_rect(self):
        scale, width, height = self._geometry()
        window = self.window_rect(width, height)
        return QRectF((window.right() + 7) * scale, window.top() * scale,
                      48 * scale, 105 * scale)

    def mouseReleaseEvent(self, event):
        if self._slot("wall") == "air_conditioner" and self.air_conditioner_rect().contains(event.position()):
            if event.button() == Qt.MouseButton.LeftButton:
                self.air_conditioner_toggle_requested.emit()
                event.accept()
                return
        if self._slot("window") == "sunny_chime" and self.chime_rect().contains(event.position()):
            self._chime_rang_at = self.environment_time
            self.sound_requested.emit("chime")
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _paint_chime(self, p, window):
        if self._slot("window") != "sunny_chime":
            return
        elapsed = self.environment_time - self._chime_rang_at
        angle = math.sin(self.environment_time * 1.6) * 2 + 22 * math.sin(elapsed * 9) * math.exp(-elapsed * 1.4)
        p.save(); p.translate(window.right() + 30, window.top() + 5); p.rotate(angle)
        p.setPen(QPen(QColor("#79523b"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(0, 0), QPointF(0, 22)); p.setBrush(QColor("#cce1df"))
        bell = QPainterPath(QPointF(-16, 46)); bell.quadTo(-14, 15, 0, 18); bell.quadTo(14, 15, 16, 46); bell.closeSubpath()
        p.drawPath(bell); p.drawLine(QPointF(0, 43), QPointF(0, 77))
        p.setBrush(QColor("#efd6b3")); p.drawRoundedRect(QRectF(-7, 67, 14, 27), 3, 3)
        p.setPen(QPen(QColor("#fff7e1"), 2)); p.drawArc(QRectF(-9, 26, 16, 18), 40*16, 100*16)
        p.restore()

    def _paint_companion(self, p):
        if self._slot("companion") != "sesame_friend":
            return
        foot = self._base_foot() + QPointF(128, 4)
        self._shadow(p, foot + QPointF(0, 5), 24, 6)
        pose = self.engine.pose
        jump = max(0, -self.engine.visual_offset.y()) * .24
        if not self.engine.grounded:
            jump += abs(math.sin(self.engine.elapsed * 6)) * 9
        p.save(); p.translate(foot.x(), foot.y()-jump)
        p.scale(pose.scale_x / max(.6, self.engine.skin_scale), pose.scale_y / max(.6, self.engine.skin_scale))
        p.setPen(QPen(QColor("#79523b"), 2.5)); p.setBrush(QColor("#655b58"))
        p.drawEllipse(QRectF(-25, -43, 50, 43))
        p.setPen(QPen(QColor("#fff0d7"), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(-9, -24), QPointF(-9, -21)); p.drawLine(QPointF(9, -24), QPointF(9, -21))
        smile=QPainterPath(QPointF(-4,-15)); smile.quadTo(0,-10,4,-15); p.drawPath(smile)
        p.restore()

    def window_rect(self, width, height):
        scale = self._geometry()[0]
        top = max(139, 112 / scale + 12)
        return QRectF(width - 298, top, 174, min(157, max(95, height * .65 - top - 25)))

    def _paint_ambient(self, p, width, height):
        """Light the complete scene, including the pet and equipped furniture."""
        p.save(); p.setPen(Qt.PenStyle.NoPen)
        p.fillRect(QRectF(0, 0, width, height), QColor(255, 231, 188, 9) if self.daytime else QColor(53, 63, 102, 42))
        window = self.window_rect(width, height)
        beam = QLinearGradient(window.left(), window.bottom(), width - 20, height)
        beam.setColorAt(0, QColor(255, 239, 184, 40) if self.daytime else QColor(178, 202, 245, 53))
        beam.setColorAt(1, QColor(255, 239, 184, 0) if self.daytime else QColor(178, 202, 245, 2))
        p.setBrush(beam)
        p.drawPolygon(QPolygonF([window.bottomLeft(), window.bottomRight(),
            QPointF(width - 8, height), QPointF(window.left() - 190, height)]))
        # A softly feathered patch catches the wood grain on the floor.
        p.save(); p.translate(width - 195, height - 57); p.scale(1, .23)
        local = QRadialGradient(QPointF(), 180)
        local.setColorAt(0, QColor(255, 233, 172, 42) if self.daytime else QColor(190, 210, 247, 30))
        local.setColorAt(1, QColor(255, 239, 190, 0)); p.setBrush(local); p.drawEllipse(QPointF(), 180, 180); p.restore()
        if self._slot("corner") == "warm_lamp" and self._home.get("lamp_on", True):
            glow = QRadialGradient(QPointF(width * .17, height - 208), 210)
            glow.setColorAt(0, QColor(255, 199, 111, 74 if not self.daytime else 38))
            glow.setColorAt(.55, QColor(255, 213, 141, 24)); glow.setColorAt(1, QColor(255, 218, 153, 0))
            p.setBrush(glow); p.drawEllipse(QPointF(width * .17, height - 208), 210, 210)
        p.restore()

    def _curtains(self, p, rect):
        p.save()
        p.setPen(QPen(QColor("#957051"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(rect.topLeft() + QPointF(-32, -17), rect.topRight() + QPointF(32, -17))
        p.setPen(ink(2.4))
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
        p.save(); p.setPen(ink(4)); p.setBrush(QColor("#f8ecd3")); p.drawRoundedRect(rect, 3, 3)
        inner = rect.adjusted(7, 7, -7, -7); p.fillRect(inner, QColor("#d3e3db"))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#f9e5ae")); p.drawEllipse(inner.topRight() + QPointF(-20, 19), 10, 10)
        p.setBrush(QColor("#9db394")); p.drawPolygon(QPolygonF([inner.bottomLeft(), inner.topLeft() + QPointF(26, 29), inner.bottomLeft() + QPointF(66, 0)]))
        p.setBrush(QColor("#b8c7a5")); p.drawPolygon(QPolygonF([inner.bottomLeft() + QPointF(25, 0), inner.topRight() + QPointF(-12, 34), inner.bottomRight()]))
        p.restore()

    @staticmethod
    def _houseplant(p, x, y):
        p.save(); p.translate(x, y); p.setPen(ink(3))
        p.setBrush(QColor("#d7ae8b")); p.drawRoundedRect(QRectF(-22, -30, 44, 34), 7, 7)
        p.setBrush(QColor("#eed0a7")); p.drawRoundedRect(QRectF(-25, -34, 50, 9), 3, 3)
        p.setPen(ink(3)); p.drawLine(QPointF(0, -32), QPointF(0, -100))
        for lx, ly, angle in ((-10, -58, -30), (9, -80, 30), (-8, -96, -20)):
            p.save(); p.translate(lx, ly); p.rotate(angle)
            p.setPen(ink(2.5)); p.setBrush(QColor("#a8bf8d")); p.drawEllipse(QRectF(-10, -22, 20, 36)); p.restore()
        p.restore()

    def _paint_wall_decoration(self, p, width, height):
        if self._slot("wall") == "air_conditioner":
            scale, _w, _h = self._geometry()
            rect = self.air_conditioner_rect()
            rect = QRectF(rect.x()/scale,rect.y()/scale,rect.width()/scale,rect.height()/scale)
            p.save(); p.setPen(ink(3)); p.setBrush(QColor("#ecf4f5"))
            p.drawRoundedRect(rect,12,12); p.setBrush(QColor("#899fac"))
            vent=rect.adjusted(12,rect.height()*.64,-12,-9); p.drawRoundedRect(vent,4,4)
            on=self._home.get("air_conditioner_on",True)
            p.setBrush(QColor("#8abca3" if on else "#b2aca5")); p.drawEllipse(rect.topRight()+QPointF(-17,15),3,3)
            if on:
                p.setBrush(Qt.BrushStyle.NoBrush)
                for n in range(4):
                    phase=(self.environment_time*.45+n*.25)%1
                    color=QColor("#a4d5de"); color.setAlphaF((1-phase)*.7)
                    p.setPen(QPen(color,2.2,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
                    start=QPointF(rect.left()+25+n*25,rect.bottom()+6+phase*75)
                    wind=QPainterPath(start); wind.cubicTo(start+QPointF(-12,10),start+QPointF(12,25),start+QPointF(0,36)); p.drawPath(wind)
            p.restore(); return
        # Keep decorations below the game HUD and away from the curtains.
        p.save(); p.translate(0, max(0, 191 - height * .34))
        super()._paint_wall_decoration(p, width, height)
        p.restore()

    def air_conditioner_rect(self):
        scale,width,height=self._geometry()
        return QRectF(width*.20*scale, max(194,height*.34)*scale, 144*scale, 54*scale)

    def _paint_food_flight(self, p):
        age = self._food_age
        if not 0 <= age <= 2.0 or not self._food_id:
            return
        scale, width, height = self._geometry()
        destination = self.pet_center() + QPointF(0, 20)
        origin = self._fly_from or QPointF(65, self.height() - 30)
        t = min(1.0, age / .78)
        if t < 1:
            control = QPointF((origin.x() + destination.x()) / 2, min(origin.y(), destination.y()) - 150)
            point = origin * (1 - t) ** 2 + control * (2 * t * (1 - t)) + destination * t * t
            side = 62 - 24 * t
            p.save(); p.translate(point); p.rotate(math.sin(t * math.pi) * -22)
            p.drawPixmap(QRectF(-side / 2, -side / 2, side, side), self.atlas.pixmap(self._food_id), QRectF(0, 0, 80, 80)); p.restore()
        else:
            fade = max(0, 1 - (age - .78) / 1.2)
            p.save(); p.setOpacity(fade); p.setPen(Qt.PenStyle.NoPen)
            for n in range(6):
                angle = n * math.tau / 6
                radius = (1 - fade) * 40 + 14
                point = destination + QPointF(math.cos(angle) * radius, -18 - (1 - fade) * 66 + math.sin(angle) * 18)
                p.save(); p.translate(point); p.setPen(ink(1.2)); p.setBrush(QColor("#e4bc6c" if n % 2 else "#e6a5ac"))
                if n % 2:
                    heart = QPainterPath(QPointF(0, 6)); heart.cubicTo(-14, -1, -6, -12, 0, -5); heart.cubicTo(6, -12, 14, -1, 0, 6); p.drawPath(heart)
                else:
                    p.drawPolygon(QPolygonF([QPointF(math.sin(i * math.pi / 5) * (7 if i % 2 == 0 else 3), -math.cos(i * math.pi / 5) * (7 if i % 2 == 0 else 3)) for i in range(10)]))
                p.restore()
            p.restore()

    @staticmethod
    def _shadow(p, center, width, height):
        p.save(); p.setPen(Qt.PenStyle.NoPen)
        p.translate(center); p.scale(1, height / width)
        # Gradient coordinates must follow this ellipse's local space.
        local = QRadialGradient(QPointF(), width)
        local.setColorAt(0, QColor(72, 48, 31, 65)); local.setColorAt(1, QColor(72, 48, 31, 0))
        p.setBrush(local); p.drawEllipse(QPointF(), width, width); p.restore()

    @staticmethod
    def cloud_centers(time, width):
        return [(((phase + time * .006) % 1.0) * (width + 66) - 33, y)
                for phase, y in ((.23, 55), (.72, 104))]

    @staticmethod
    def star_opacity(index, time):
        return .58 + .22 * math.sin(time * .8 + index * 1.71)

    def _paint_window(self, p, rect, wood):
        p.save(); p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(74, 49, 33, 25))
        p.drawRoundedRect(rect.adjusted(-10, -6, 13, 14), 17, 17)
        p.setPen(ink(4)); p.setBrush(QColor(wood)); p.drawRoundedRect(rect.adjusted(-7, -7, 7, 7), 13, 13)
        p.save(); glass = QPainterPath(); glass.addRoundedRect(rect, 7, 7); p.setClipPath(glass)
        sky = QLinearGradient(rect.topLeft(), rect.bottomRight())
        sky.setColorAt(0, QColor("#b8dbe6" if self.daytime else "#30395b"))
        sky.setColorAt(1, QColor("#f2f5df" if self.daytime else "#6d7296")); p.fillRect(rect, sky)
        p.setPen(Qt.PenStyle.NoPen)
        if self.daytime:
            glow = QRadialGradient(rect.topRight() + QPointF(-38, 35), 36)
            glow.setColorAt(0, QColor(255, 242, 178, 180)); glow.setColorAt(1, QColor(255, 242, 178, 0))
            p.setBrush(glow); p.drawEllipse(rect.topRight() + QPointF(-38, 35), 36, 36)
            p.setBrush(QColor("#fff0ab")); p.drawEllipse(rect.topRight() + QPointF(-38, 35), 19, 19)
            p.setBrush(QColor(255, 255, 250, 230))
            for x, y in self.cloud_centers(self.environment_time, rect.width()):
                center = rect.topLeft() + QPointF(x, y)
                cloud = QPainterPath(); cloud.setFillRule(Qt.FillRule.WindingFill)
                for dx, dy, rx, ry in ((-17, 1, 17, 10), (0, -5, 21, 15), (20, 2, 20, 10)):
                    cloud.addEllipse(center + QPointF(dx, dy), rx, ry)
                p.drawPath(cloud.simplified())
        else:
            moon = QPainterPath(); moon.addEllipse(rect.topRight() + QPointF(-39, 34), 20, 20)
            cut = QPainterPath(); cut.addEllipse(rect.topRight() + QPointF(-30, 27), 19, 19)
            p.setBrush(QColor("#fff0bc")); p.drawPath(moon.subtracted(cut))
            for index, (x, y) in enumerate(((23, 25), (57, 62), (89, 31), (39, 119), (140, 126), (112, 96), (21, 86))):
                color = QColor("#fff6d8"); color.setAlphaF(self.star_opacity(index, self.environment_time))
                p.setBrush(color); p.drawEllipse(rect.topLeft() + QPointF(x, y), 1.8, 1.8)
                if index % 3 == 0:
                    p.setPen(QPen(color, .8)); c = rect.topLeft() + QPointF(x, y)
                    p.drawLine(c + QPointF(-3, 0), c + QPointF(3, 0)); p.drawLine(c + QPointF(0, -3), c + QPointF(0, 3)); p.setPen(Qt.PenStyle.NoPen)
        p.restore(); p.setBrush(Qt.BrushStyle.NoBrush); p.setPen(ink(2)); p.drawRoundedRect(rect, 7, 7)
        for line in ((QPointF(rect.center().x(), rect.top()), QPointF(rect.center().x(), rect.bottom())),
                     (QPointF(rect.left(), rect.center().y()), QPointF(rect.right(), rect.center().y()))):
            p.setPen(ink(8)); p.drawLine(*line); p.setPen(QPen(QColor(wood), 4)); p.drawLine(*line)
        p.setBrush(QColor("#f1d6b4")); p.setPen(ink(2.4))
        p.drawRoundedRect(QRectF(rect.left() - 16, rect.bottom() + 7, rect.width() + 32, 10), 4, 4); p.restore()

    def _paint_corner(self, p, width, height):
        if self._slot("corner"):
            self._shadow(p, QPointF(width * .17, height - 69), 73, 13)
        super()._paint_corner(p, width, height)

    def _paint_bowl(self, p, width, height):
        # A separate side table gives the baked-in yellow character bowl room.
        x, y = width * .85, height - 70
        self._shadow(p, QPointF(x, y + 32), 71, 12)
        p.save(); p.translate(x, y); p.setPen(ink(3))
        p.setBrush(QColor("#bd8f64"))
        for lx in (-43, 43): p.drawRoundedRect(QRectF(lx - 5, 1, 10, 33), 3, 3)
        wood = QLinearGradient(0, -14, 0, 12); wood.setColorAt(0, QColor("#f2d4a3")); wood.setColorAt(1, QColor("#c99b70"))
        p.setBrush(wood); p.drawRoundedRect(QRectF(-64, -12, 128, 23), 10, 10)
        p.setPen(ink(1.4)); p.drawLine(QPointF(-47, -2), QPointF(43, -2))
        p.translate(0, -18)
        porcelain = self._slot("bowl") == "porcelain_bowl"
        p.setPen(ink(2.8)); p.setBrush(QColor("#e3edf3" if porcelain else "#cda175"))
        bowl = QPainterPath(QPointF(-28, -7)); bowl.cubicTo(-24, 21, 24, 21, 28, -7); bowl.closeSubpath(); p.drawPath(bowl)
        p.setBrush(QColor("#fffdf4" if porcelain else "#f6dbb3")); p.drawEllipse(QRectF(-29, -14, 58, 15))
        if porcelain:
            p.setPen(QPen(QColor("#527b9b"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for xx in (-15, -4, 7, 18): p.drawArc(QRectF(xx - 4, 0, 8, 9), 0, 160 * 16)
        if monotonic() < self._food_until:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor({"sesame": "#777079", "strawberry": "#e89dae", "matcha": "#a1bc7c", "chili": "#d67a57", "water": "#afd5e3"}.get(self._food_id, "#f1d596")))
            p.drawEllipse(QRectF(-22, -11, 44, 9))
            p.drawPixmap(QRectF(29, -37, 35, 35), self.atlas.pixmap(self._food_id), QRectF(0, 0, 80, 80))
        p.restore()

    def _paint_gains(self, p):
        center = self.pet_center()
        pet = self.pet_bounds()
        head = pet.top()
        for index, (text, started) in enumerate(self._floating):
            age = monotonic() - started
            if not 0 <= age <= 1.2: continue
            opacity = min(1, age * 12, (1.2 - age) / .35)
            p.save(); p.setOpacity(max(0, opacity)); p.setFont(QFont("Microsoft YaHei UI", 12, QFont.Weight.Bold))
            # Use the side of the head; the centered lane belongs to dialogue.
            if pet.right() + 165 < self.width():
                rect = QRectF(pet.right() + 10, max(114, head - 12 - age * 32 + index * 27), 150, 26)
            elif pet.left() > 165:
                rect = QRectF(pet.left() - 160, max(114, head - 12 - age * 12), 150, 26)
            else:
                rect = QRectF(center.x() - 75, max(114, head + 14 - age * 24 + index * 27), 150, 26)
            p.setPen(QPen(QColor(OUTLINE), 3.2)); path_text = QPainterPath()
            metrics = p.fontMetrics(); path_text.addText(rect.center().x() - metrics.horizontalAdvance(text) / 2, rect.bottom() - 5, p.font(), text)
            p.drawPath(path_text); p.fillPath(path_text, QColor("#d7f0ac" if "饱食" in text else "#ffe097" if "糯米币" in text else "#ffccd8")); p.restore()

    @staticmethod
    def _note(p, point, color, tilt=0):
        p.save(); p.translate(point); p.rotate(tilt); p.setPen(QPen(QColor(color), 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(QColor(color)); p.drawEllipse(QRectF(-7, -1, 10, 7)); p.drawLine(QPointF(2, 2), QPointF(2, -17))
        p.drawLine(QPointF(2, -17), QPointF(9, -13)); p.restore()

    def _paint_gift(self, p, width, height):
        perf = self.performance
        # Gift props belong only to their active performance, including particles.
        if perf is None or not perf.active:
            return
        item, t = perf.item_id, perf.age
        x, y = width * .735, height - 86
        opacity = min(1, max(.0, (perf.duration - t) / .7), t / .35)
        p.save(); p.setOpacity(opacity)
        if item == "spinning_top":
            x = width * perf.top_x
            self._shadow(p, QPointF(x, y + 12), 42, 8)
            p.translate(x, y); p.rotate(math.sin(t * 7) * 4)
            p.setPen(ink(2.8)); p.setBrush(QColor("#c8945d"))
            tip = QPainterPath(QPointF(-27, -4)); tip.quadTo(-17, 21, 0, 29); tip.quadTo(17, 21, 27, -4); tip.closeSubpath(); p.drawPath(tip)
            p.save(); p.scale(1, .48); p.rotate(perf.angle)
            colors = ("#e8b571", "#afc8a1", "#cc9794", "#edcf95")
            for n, color in enumerate(colors):
                p.setBrush(QColor(color)); p.setPen(ink(2)); p.drawPie(QRectF(-30, -30, 60, 60), n * 90 * 16, 90 * 16)
            p.restore(); p.setPen(ink(3)); p.setBrush(QColor("#f7dcab")); p.drawRoundedRect(QRectF(-4, -25, 8, 26), 3, 3)
            p.setPen(QPen(QColor("#e0b573"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for n in range(3): p.drawArc(QRectF(-45 - n * 3, -15 - n * 3, 90 + n * 6, 36 + n * 4), int((perf.angle + n * 97) * 16), 45 * 16)
        elif item in ("tes_guitar", "tes_microphone"):
            point=self.pet_center(); scale,_,_=self._geometry()
            p.save(); p.translate(point.x()/scale+74,point.y()/scale+35)
            p.rotate(math.sin(t*7)*9 if item=="tes_guitar" else 0)
            p.drawPixmap(QRectF(-35,-68,70,70),self.atlas.pixmap(item),QRectF(0,0,80,80))
            if item=="tes_guitar":
                p.setPen(QPen(QColor("#e4b25e"),2)); p.drawArc(QRectF(-44,-32,88,42),int(t*260)*16,80*16)
            p.restore()
            for n,color in enumerate(("#cb8c94","#88b89b","#b5a2ce","#dfa95f")):
                phase=(t*.32+n*.25)%1
                self._note(p,QPointF(point.x()/scale+math.sin(t+n)*35,point.y()/scale-60-phase*100),color,math.sin(t+n)*14)
        elif item == "music_box":
            self._shadow(p, QPointF(x, y + 18), 60, 10); p.translate(x, y)
            p.setPen(ink(3)); p.setBrush(QColor("#b78c73")); p.drawRoundedRect(QRectF(-43, -22, 86, 45), 9, 9)
            p.setBrush(QColor("#eed4b0")); p.drawRoundedRect(QRectF(-40, -66, 80, 47), 8, 8)
            p.setBrush(QColor("#f6e7c4")); p.drawRoundedRect(QRectF(-36, -60, 72, 33), 6, 6)
            p.setBrush(QColor("#e8b5ac")); p.drawEllipse(QRectF(-32, -30, 64, 18))
            p.setBrush(QColor("#f9e3a3")); p.drawEllipse(QRectF(-11, -40, 22, 22))
            p.save(); p.translate(0, -29); p.scale(1, .4); p.rotate(t * 145)
            p.setPen(ink(1.8)); p.setBrush(QColor("#d9b969")); p.drawEllipse(QPointF(), 19, 19)
            for n in range(8):
                p.drawLine(QPointF(math.cos(n * math.pi / 4) * 11, math.sin(n * math.pi / 4) * 11), QPointF(math.cos(n * math.pi / 4) * 20, math.sin(n * math.pi / 4) * 20))
            p.restore()
            p.setPen(ink(2)); p.drawLine(QPointF(-12, 10), QPointF(12, 10)); p.drawEllipse(QPointF(0, 8), 3, 3)
            for n, color in enumerate(("#b77e9c", "#8ba978", "#7398ad", "#cf9e58", "#ac8fb3", "#b59b58")):
                phase = (t * .24 + n / 6) % 1
                p.save(); p.setOpacity(opacity * math.sin(phase * math.pi))
                self._note(p, QPointF(math.sin(t * 1.4 + n) * (28 + phase * 45), -40 - phase * 124), color, math.sin(t + n) * 16); p.restore()
        elif item == "paper_star":
            self._shadow(p, QPointF(x, y + 15), 42, 8)
            for n in range(5):
                phase = t * .8 + n * math.tau / 5
                point = QPointF(x + math.cos(phase) * 45, y - 45 + math.sin(phase) * 24)
                p.save(); p.translate(point); p.rotate(t * 55 + n * 37)
                p.setPen(ink(1.8)); p.setBrush(QColor("#f6d58a" if n % 2 else "#e6b8b3"))
                star = QPolygonF([QPointF(math.sin(i * math.pi / 5) * (14 if i % 2 == 0 else 6), -math.cos(i * math.pi / 5) * (14 if i % 2 == 0 else 6)) for i in range(10)])
                p.drawPolygon(star); p.restore()
        elif item == "flower_bouquet":
            self._shadow(p, QPointF(x, y + 17), 47, 9); p.translate(x, y)
            p.rotate(math.sin(t * 2) * 3); p.setPen(ink(2.4)); p.setBrush(QColor("#e6ca9e"))
            p.drawPolygon(QPolygonF([QPointF(-34, -29), QPointF(34, -29), QPointF(8, 23), QPointF(-8, 23)]))
            p.setPen(QPen(QColor("#75875a"), 3))
            for n in range(5):
                xx = (n - 2) * 13; yy = -47 - (1 - abs(n - 2) / 2) * 18
                p.drawLine(QPointF(), QPointF(xx, yy)); p.setPen(ink(1.7)); p.setBrush(QColor("#e9b7b0" if n % 2 else "#f3d083"))
                for a in range(5): p.drawEllipse(QPointF(xx + math.sin(a * math.tau / 5) * 8, yy + math.cos(a * math.tau / 5) * 8), 7, 7)
                p.setBrush(QColor("#a77b50")); p.drawEllipse(QPointF(xx, yy), 4, 4); p.setPen(QPen(QColor("#75875a"), 3))
            for n in range(6):
                phase = (t * .25 + n / 6) % 1
                p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(231, 165, 164, int(math.sin(phase * math.pi) * 180)))
                p.drawEllipse(QPointF(math.sin(t + n) * (30 + phase * 35), -55 - phase * 70), 4, 7)
        p.restore()
