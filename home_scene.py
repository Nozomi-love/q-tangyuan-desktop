"""Illustrated room view; the desktop engine remains the only physics clock."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QPolygonF, QRadialGradient, QTransform)
from pet_engine import RoomCanvas, PetState, Pose, PresentationLifecycle, clamp
from illustrated_assets import IconAtlas, plain_text, Brush
from item_expansion import (ALL_GIFTS, PART2_FOODS, gift_pose, paint_gift_props,
                            gift_hit_rect, food_pose, paint_food_extra, paint_collection_icon)
from room_art import StorybookRoomArt, LAYER_ORDER, gradient, line, polygon, soft_shadow



OUTLINE = "#70513b"


def ink(width=3.0):
    return QPen(QColor(OUTLINE), width, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)


class RoomLife:
    """Room-only activity clock. Input cancels a pose through a short blend."""
    KINDS = ("bowl", "window", "nap", "hum", "hop")
    HOME_X = .48
    RETURN_DELAY = 1.5
    RETURN_SPEED = .09

    def __init__(self, rng=None):
        self.rng = rng or random.Random()
        self.accelerated = False
        self.elapsed = self.phase_time = self.quiet = 0.0
        self.state = "idle"
        self.x = self.target = self.HOME_X
        self.wait = self.rng.uniform(12, 25)
        self.last_line = -80.0
        self.cycle = 0
        self.toy_available = False
        self._nap_announced = False
        self._previous_kind = ""
        self._blend_from = (1, 1, 0, 0)
        self._blend_age = .22
        self._return_delay = self.RETURN_DELAY
        self._was_blocked = False

    def _next_wait(self):
        return self.rng.uniform(2, 4) if self.accelerated else self.rng.uniform(12, 25)

    def interact(self):
        if self.state != "idle":
            self._blend_from = self.pose; self._blend_age = 0.0
        self.state = "idle"
        self.phase_time = self.quiet = 0.0
        self.wait = self._next_wait()
        # Interrupt at the current position, then recover independently of the
        # random activity timer. A stopped walk is never a new permanent home.
        self._return_delay = self.RETURN_DELAY

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

    def advance(self, dt, *, hunger=80, level=1, hour=12, blocked=False, return_allowed=True):
        if blocked and not self._was_blocked:
            self.interact()
        self._was_blocked = blocked
        messages = []; remaining = max(0.0, min(float(dt), 60.0))
        while remaining > 1e-9:
            step = min(.05, remaining); remaining -= step; self.elapsed += step
            self._blend_age += step
            away = abs(self.x - self.HOME_X) > 1e-6
            if self.state == "idle" and away and return_allowed:
                self._return_delay -= step
                if self._return_delay <= 1e-8:
                    self.state = "return"; self.target = self.HOME_X; self.phase_time = 0.0
            if blocked and (not return_allowed or self.state != "return"):
                continue
            self.quiet += step; self.phase_time += step
            if self.state == "idle":
                self.wait -= step
                if not away and not blocked and self.wait <= 0 and self.quiet >= (1 if self.accelerated else 6):
                    options = list(self.KINDS) + (["toy"] if self.toy_available else [])
                    options = [kind for kind in options if kind != self._previous_kind]
                    choice = "bowl" if hunger < 35 and self._previous_kind != "bowl" else self.rng.choice(options)
                    self.cycle += 1; self.start_activity(choice)
            elif self.state.startswith("walk_") or self.state == "return":
                difference = self.target - self.x
                speed = self.RETURN_SPEED if self.state == "return" else .055
                self.x += clamp(difference, -step * speed, step * speed)
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
                if self.phase_time >= 2: self.state = "return"; self.target = self.HOME_X; self.phase_time = 0.0
            elif self.phase_time >= (1.3 if self.state == "hop" else 3.5):
                self.state = "return"; self.target = self.HOME_X; self.phase_time = 0.0
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
    dice_faces: tuple = field(default_factory=lambda: tuple(random.sample((3,6,9),3)))
    fist_bumped: bool = False
    fist_bump_age: float = -1.0
    practice_combo: bool = False
    summit_combo: bool = False
    training_theme: bool = False

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
        if self.item_id == "training_dummy":
            u=clamp(self.age/self.duration,0,1)
            approach=clamp(u/.2,0,1) if u<.8 else clamp((1-u)/.2,0,1)
            approach=approach*approach*(3-2*approach)
            hit=max(0,math.sin(clamp((u-.2)/.6,0,1)*math.pi*6))*.015 if .2<u<.8 else 0
            return self.start_x+(.30-self.start_x)*approach-hit
        if self.item_id == "kiting_rope":
            u=clamp(self.age/self.duration,0,1)
            return self.start_x + math.sin(u*math.pi*6)*.055*math.sin(u*math.pi)**2
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
        if self.item_id in ALL_GIFTS: return gift_pose(self.item_id,t,self.duration,self.dice_faces)
        if self.item_id == "training_dummy":
            e=math.sin(clamp(t/self.duration,0,1)*math.pi)**2
            return 1.,1.,math.sin(t*math.tau*3/self.duration)*8*e,-abs(math.sin(t*math.pi*3/self.duration))*7*e
        if self.item_id == "esports_chair": return 1.,1.,math.sin(t*3)*5*math.sin(clamp(t/self.duration,0,1)*math.pi)**2,0.
        if self.item_id in ("music_box", "tes_guitar", "tes_microphone"):
            wave = .035 * math.sin(t * 7)
            return 1 + wave, 1 - wave, math.sin(t * 7) * 10, -abs(math.sin(t * 3.5)) * 6
        if self.item_id == "spinning_top":
            return 1.0, 1.0, 0.0, 0.0
        if self.item_id == "paper_star": return 1.0, 1.0, math.sin(t * 3) * 6, -abs(math.sin(t * 3)) * 9
        return 1.03, .97, math.sin(t * 2) * 4, -2.0


class RoomPetView:
    """Read-only pose adapter for the shared skin and ornament pipeline."""
    def __init__(self, engine, local_pose=(1, 1, 0, 0), yaw_scale=1.0, cooling=False, flash_distance=None):
        self.engine, self.local_pose = engine, local_pose
        self.yaw_scale = yaw_scale
        self.cooling = cooling
        if flash_distance is not None: self.flash_distance = flash_distance
    @property
    def visual_angle(self): return self.engine.visual_angle
    @property
    def visual_offset(self):
        if self.engine.active_trick == "reverse_flash":
            return self.engine.reverse_flash_offset(distance=getattr(self, "flash_distance", None), pinned=False)
        return self.engine.visual_offset
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
    presentation_event = Signal(dict)
    furniture_interacted = Signal(str)

    THEMES = dict(RoomCanvas.THEMES, camp_room=("#bbb9d0", "#ada4bd", "#877664", "#d0b9a4", "#a18b7a"),
                  postmatch_studio=("#d0bdba", "#ae959c", "#8e7163", "#cfae8c", "#a18774"),
                  practice_room=("#e8eddd", "#c9d2b8", "#a58d69", "#d3bf98", "#a79773"))

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
        self.presentation = PresentationLifecycle(self)
        self.presentation.changed.connect(self.presentation_event.emit)
        self.performance: GiftPerformance | None = None
        self._gift_queue = []
        self._floating = []
        self._last_scene_tick = monotonic()
        self._chew_started = -100.0
        self._last_toy = ""
        self._room_trick = ""
        self._room_trick_origin = self.life.x
        self._prepared_trick = None
        self._flash_camera = None
        self._flash_recovery = None
        self._ignored_trick = ""
        self._ignored_trick_token = 0
        self._suppress_trick_sync = False
        self._settle_offset = QPointF()
        self._settle_age = 1.0
        self._food_age = 100.0
        self._food_queue = []
        self._food_arrived = False
        self._pending_hunger = 0.0
        self._food_gain = 0.0
        self._next_food_origin = None
        self.environment_time = 0.0
        self._chime_rang_at = -100.0
        self.recent_interactions = []
        self._furniture_started = -100.0
        self._furniture_active = ""
        self._trail_until = -100.0
        self._interaction_age = 100.0
        self._art = StorybookRoomArt()
        self._reserved_bottom = 122
        self.poke_requested.connect(lambda: self.cancel_presentation("input", cancel_engine=True))
        self.pet_requested.connect(lambda: self.cancel_presentation("input", cancel_engine=True))

    def _food_duration(self):
        return self.FLIGHT_SECONDS + (3.0 if self._food_id in PART2_FOODS else self.CHEW_SECONDS)

    @property
    def foreground_kind(self):
        if self.engine.active_trick and self.engine.active_trick != self._ignored_trick:
            return "trick"
        if self.performance:
            return "gift"
        if self._food_age < self._food_duration():
            return "food"
        return ""

    def set_home_state(self, snapshot, furniture_catalog=None):
        super().set_home_state(snapshot, furniture_catalog)
        # History is the model's bounded settlement log, never a second source
        # of truth maintained by painting or by a developer preview.
        fallback = {"poke": "avatar", "pet": "crown", "feed": "water",
                    "gift": "paper_star", "trick": "flip", "drop": "ball",
                    "shake": "spinning_top"}
        self.recent_interactions = [row.get("item_id") or fallback.get(row.get("event"), "avatar")
            for row in snapshot.get("interaction_history", [])[-3:]
            if isinstance(row, dict)]

    def cancel_presentation(self, reason="cancelled", preserve_current=True, *, cancel_engine=False):
        """Exit every transient layer once, then let the independent life return.

        Capture the *painted* foot before a controller cancels shared physics.
        Residual jump/camera offsets blend out locally; they never enter a save
        or the desktop engine's coordinates.
        """
        recovering_flash = self._flash_camera is not None or self._flash_recovery is not None
        old_flash_zoom = self._flash_camera.m11() if self._flash_camera is not None else (
            self._flash_recovery["zoom"] if self._flash_recovery else 1.)
        active = bool(self.foreground_kind or self._room_trick or self._gift_queue
                      or self._food_queue or self._furniture_active or recovering_flash)
        current = None
        self._suppress_trick_sync = True
        try:
            if preserve_current and (active or self.life.state != "idle"):
                current = self._pet_transform().map(self._render_foot() + self._view().visual_offset)
        finally:
            self._suppress_trick_sync = False
        if self.performance:
            self.life.x = self.performance.pet_x
        self.performance = None
        self._gift_queue.clear()
        self._food_queue.clear()
        self._food_age = 100.0
        self._food_arrived = False
        self._food_gain = self._pending_hunger = 0.0
        self._food_id = ""
        self._food_until = 0.0
        self._fly_from = self._next_food_origin = None
        self._fly_started = self._chew_started = -100.0
        self._last_toy = self._furniture_active = ""
        self._interaction_age = 100.0
        self._furniture_started = self._trail_until = -100.0
        self._room_trick = ""
        self._prepared_trick = None
        self._flash_camera = None
        self._flash_recovery = None
        self._ignored_trick = self.engine.active_trick
        self._ignored_trick_token = (self.engine.presentation.active or {}).get("token", 0)
        self.presentation.cancel(reason)
        self.life.interact()
        if current is not None:
            _scale, width, _height = self._geometry()
            ratio = clamp(current.x() / width, .28, .70)
            if abs(self.life.x - ratio) > 1e-10:
                self.life.x = ratio
            # RoomLife already blends a cancelled walk/hop. Subtract that live
            # local hop instead of applying it again through the residual.
            self._settle_offset = current - QPointF(width * self.life.x,
                                                   self._base_foot().y() + self.life.pose[3])
            self._settle_age = 0.0
            if recovering_flash:
                self._flash_recovery = {"origin": self.life.x, "point": QPointF(current), "zoom": old_flash_zoom}
        elif not preserve_current:
            self._settle_offset = QPointF()
            self._settle_age = 1.0
        if cancel_engine:
            self.engine.cancel_trick(reason)
        self.update()
        return active

    def hideEvent(self, event):
        self.cancel_presentation("hidden", cancel_engine=True)
        super().hideEvent(event)

    def _mood(self, duration):
        self.mood_requested.emit(duration)

    def interact(self, cancel_gift=False):
        if cancel_gift:
            if self.performance or self._room_trick:
                self.cancel_presentation("input")
            self._gift_queue.clear()
            self._last_toy = ""
            self.update()
        self.life.interact()

    def stop(self):
        self.cancel_presentation("shutdown", preserve_current=False, cancel_engine=True)
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
        if 0 <= self._interaction_age < .6:
            pose=(*pose[:3],pose[3]-16*math.sin(self._interaction_age/.6*math.pi))
        age = self._food_age - self.FLIGHT_SECONDS
        if self._food_arrived:
            sx, sy, angle, hop = food_pose(self._food_id, age)
            pose = (pose[0]*sx, pose[1]*sy, pose[2]+angle, pose[3]+hop)
        if self._food_arrived and 0 <= age <= self.CHEW_SECONDS:
            # Three closed squash/stretch cycles, then exactly the neutral pose.
            wave = -.12 * math.sin(age / self.CHEW_SECONDS * math.pi * 3) ** 2
            return pose[0] / (1 + wave), pose[1] * (1 + wave), pose[2], pose[3]
        return pose

    def prepare_trick(self):
        """Capture the old camera before shared physics changes its envelope."""
        transform = self._pet_transform()
        point = transform.map(self._render_foot() + self._view().visual_offset)
        self._prepared_trick = {"origin": self.life.x, "point": QPointF(point), "zoom": transform.m11()}
        return self._prepared_trick

    def begin_trick(self, trick_id):
        if self._room_trick == trick_id: return
        prepared = self._prepared_trick
        if trick_id == "reverse_flash" and prepared is not None:
            self.cancel_presentation("replaced", preserve_current=False)
            self.life.x = self._room_trick_origin = prepared["origin"]
            self._ignored_trick = ""
            self._room_trick = trick_id
            self.life.interact()
            self._flash_camera = self._fit_flash_camera(prepared)
            return
        # A standalone view may discover an engine trick on the next tick,
        # rather than through the controller's pre-start cancellation hook.
        # Adopt the gift's *current* position before the new busy pose hides it.
        gift_hop = self.performance.pose[3] if self.performance else 0.0
        if self.performance:
            self.life.x = self.performance.pet_x
        self._room_trick_origin = self.life.x
        self.cancel_presentation("replaced")
        if gift_hop:
            self._settle_offset += QPointF(0, gift_hop)
        self._room_trick_origin = self.life.x
        self._ignored_trick = ""
        self._room_trick = trick_id
        self.life.interact()

    def finish_trick(self, trick_id):
        if trick_id != self._room_trick: return
        flash_recovery = None
        if trick_id == "reverse_flash" and self._flash_camera is not None:
            origin_foot = self._base_foot()
            origin_foot.setX(self._geometry()[1] * self._room_trick_origin)
            flash_recovery = {"origin": self._room_trick_origin,
                "point": self._flash_camera.map(origin_foot), "zoom": self._flash_camera.m11()}
        self._flash_camera = None
        self._prepared_trick = None
        if not self.performance: self.life.x = self._room_trick_origin
        self._room_trick = ""
        self._settle_offset = QPointF()
        self._settle_age = 0.0 if flash_recovery else 1.0
        self._flash_recovery = flash_recovery
        self.life.interact()

    def _sync_room_trick(self):
        if self._suppress_trick_sync:
            return
        current = self.engine.active_trick
        if self._ignored_trick:
            if (current == self._ignored_trick and (self.engine.presentation.active or {}).get("token", 0)
                    == self._ignored_trick_token):
                return
            self._ignored_trick = ""
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
        flash_distance = None
        if self.engine.active_trick == "reverse_flash":
            scale, width, _height = self._geometry()
            # The scene camera may enlarge the body. Bound *painted* travel in
            # widget pixels, not the desktop's unrelated availableGeometry.
            zoom_limit = self._pet_zoom * min(1.9, max(1.0, 900 / max(1, self.width())))
            flash_distance = min(60 / max(.01, scale * zoom_limit), width * .08 / max(1, zoom_limit))
        view = RoomPetView(self.engine, self._local_pose(), yaw,
            cooling=self._slot("wall")=="air_conditioner" and self._home.get("air_conditioner_on",True),
            flash_distance=flash_distance)
        view.trail_flash = self.environment_time < self._trail_until
        return view

    def _repaint_if_visible(self):
        now = monotonic(); dt = clamp(now - getattr(self, "_last_scene_tick", now), 0, .1)
        self._last_scene_tick = now
        if not self.isVisible(): return
        # Expression deadlines change for mood, rewards and our own nap/gifts.
        # Only actual input and busy-state transitions may interrupt movement.
        self.advance_scene(dt)
        self._advance_message(); self.update()

    def advance_scene(self, dt, hour=None):
        """One visible-scene tick, exposed for deterministic animation tests."""
        self._sync_room_trick()
        self.environment_time += clamp(float(dt), 0, 60)
        self._settle_age += clamp(float(dt), 0, 60)
        self._interaction_age += clamp(float(dt), 0, 60)
        if self.environment_time - self._furniture_started >= 3:
            self._furniture_active = ""
        busy = self._busy()
        spicy = self.engine.buff.get("behavior_remaining", 0) > 0 and not self.engine.flat
        if busy and self.performance:
            self.interact(cancel_gift=True)
        self.life.toy_available = any(self._home.get("inventory", {}).get(k, 0)
            for k in ALL_GIFTS | {"spinning_top", "music_box", "paper_star", "flower_bouquet", "tes_guitar", "tes_microphone"})
        old_state = self.life.state
        messages = self.life.advance(dt, hunger=self._home.get("hunger", 80),
            level=self._home.get("affection_level", 1), hour=datetime.now().hour if hour is None else hour,
            blocked=busy or spicy or bool(self.performance) or self._food_age < self._food_duration(),
            return_allowed=not (self.engine.held or self.engine.dragging or self.engine.active_trick
                or spicy or self.performance or self._food_age < self._food_duration()))
        if old_state != "nap" and self.life.state == "nap": self.mood_requested.emit(5.0)
        for text in messages:
            self.show_message(text, "ambient", 2.7)
        if self.performance and not busy:
            self.performance.advance(dt)
            if not self.performance.active:
                finished = self.performance
                if finished.item_id=="summit_pickaxe": self._trail_until=self.environment_time+1.4
                self.life.x = finished.start_x
                self.performance = None
                self.presentation.finish()
                self._last_toy = ""
                self.life.interact()
        if (not self.performance and self._gift_queue and not busy
                and self._food_age >= self._food_duration()):
            self._begin_gift(*self._gift_queue.pop(0))
        self._advance_food(dt)
        self._floating = [f for f in self._floating if monotonic() - f[1] < 1.2]

    def _begin_gift(self, item_id, duration, dialogue=""):
        if self._food_age < self._food_duration():
            self.cancel_presentation("replaced")
        accessories = self.renderer_provider().accessories
        self.performance = GiftPerformance(item_id, duration, start_x=self.life.x,
            practice_combo=accessories.get("head") == "mini_gnar_hat" and self._slot("corner") == "training_dummy",
            summit_combo=accessories.get("back") == "summit_backpack" and self._slot("wall") == "summit_wall",
            training_theme=self._slot("theme") == "practice_room")
        self.presentation.begin("gift", item_id, self._render_foot())
        self._last_toy = ""
        if dialogue: self.show_message(dialogue, "interaction")
        self.mood_requested.emit(duration)
        if item_id in ("music_box", "tes_guitar", "tes_microphone"): self.sound_requested.emit("music_box")

    def record_interaction(self, kind):
        if kind in ("poke", "pet", "drag"):
            self.cancel_presentation("input")
        else:
            self.interact(cancel_gift=kind == "food")
        if kind in ("poke","pet"): self._interaction_age=0.0

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
            if item_id in ALL_GIFTS | {"spinning_top", "music_box", "paper_star", "flower_bouquet", "tes_guitar", "tes_microphone"}:
                if self._food_age < self._food_duration():
                    self.cancel_presentation("replaced")
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
        # Desktop falls/drags use global work-area coordinates. They must not
        # become room height: room hops and explicit tricks have local offsets.
        foot = self._base_foot()
        if self.engine.active_trick:
            foot.setX(self._trick_home_foot().x())
        else:
            _scale, width, _height = self._geometry()
            ratio = self.performance.pet_x if self.performance else self.life.x
            # Busy states override the pose, never the room's saved location.
            # Preserve the separate spicy-running displacement from the base view.
            foot.setX(width * ratio + foot.x() - self._base_foot().x())
            if self.engine.buff.get("behavior_remaining",0)>0 and not self.engine.pinned and not self.engine.flat:
                remaining=self.engine.buff["behavior_remaining"]
                mix=clamp(min((12-remaining)/.6,remaining/.8),0,1)
                mix=mix*mix*(3-2*mix)
                foot.setX(foot.x()+math.sin(self.engine.elapsed*3.4)*110*mix)
        if not self._busy():
            foot.setY(foot.y() + self._local_pose()[3])
        if self._settle_age < .28:
            t = clamp(self._settle_age / .28, 0, 1)
            foot += self._settle_offset * (1 - t * t * (3 - 2 * t))
        return foot

    def _base_foot(self):
        _scale, width, height = self._geometry()
        # Reserve foreground controls in widget pixels, not scene units. The
        # normalised home and independent return state machine remain unchanged.
        reserve = 192 if self.width() < 780 else self._reserved_bottom
        return QPointF(width * .48, max(height*.72, height-reserve/_scale))

    def set_foreground_reserved(self, height=122):
        self._reserved_bottom = max(100, min(240, int(height)))
        self.update()

    def foreground_table_rect(self):
        w, h = self.width(), self.height()
        if w < 780:
            return QRectF(w*.04, h-184, w*.92, 76)
        return QRectF(w*.035, h-114, min(w*.48, 540), 78)

    def foreground_navigation_rect(self):
        w, h = self.width(), self.height()
        width = min(390, w*.92 if w < 780 else w*.45)
        return QRectF((w-width)/2 if w < 780 else w-width-14, h-90, width, 80)

    @property
    def scene_controls_stacked(self):
        return self.width() < 780

    def _fit_flash_camera(self, prepared):
        foot = self._trick_home_foot()
        _scale, width, height = self._geometry()
        target = prepared["point"]
        bounds = self.renderer_provider().scene_bounds(self._view(), foot)
        top = max(112., 112. / _scale)
        zoom = max(.01, min(prepared["zoom"],
            max(1., target.x()-25)/max(1., foot.x()-bounds.left()),
            max(1., width-25-target.x())/max(1., bounds.right()-foot.x()),
            max(1., target.y()-top)/max(1., foot.y()-bounds.top()),
            max(1., height-23-target.y())/max(1., bounds.bottom()-foot.y())))
        transform = QTransform()
        transform.translate(target.x(), target.y()); transform.scale(zoom, zoom)
        transform.translate(-foot.x(), -foot.y())
        return transform

    def _pet_transform(self):
        if self.engine.active_trick == "reverse_flash" and self._room_trick == "reverse_flash" and self._flash_camera is not None:
            return QTransform(self._flash_camera)
        foot = self._render_foot() + self._view().visual_offset
        scale, width, height = self._geometry()
        top = max(112.0, 112.0 / scale)
        renderer = self.renderer_provider(); view = self._view()
        bounds = renderer.scene_bounds(view, self._render_foot())
        if self.performance and self.performance.item_id == "drama_clapper" and not self._busy():
            bounds=bounds.adjusted(-115,0,115,0)
        if self.performance and self.performance.item_id == "spinning_top" and not self._busy():
            # Fit both faces at full width so a thin side view never zooms in.
            front = RoomPetView(self.engine, self._local_pose())
            back = RoomPetView(self.engine, self._local_pose(), -1.0)
            bounds = renderer.scene_bounds(front, self._render_foot()).united(
                renderer.scene_bounds(back, self._render_foot()))
        # The HUD occupies widget pixels while the room uses logical scene
        # units. Fit the full accessory/trick envelope beneath it on small views.
        zoom = min(self._pet_zoom * min(1.9, max(1.0, 900 / max(1, self.width()))),
                   max(20.0, width - 50) / max(1.0, bounds.width()),
                   max(12.0, foot.y()-top) / max(1.0, foot.y()-bounds.top()),
                   max(12.0, height-23-foot.y()) / max(1.0, bounds.bottom()-foot.y()))
        if self.engine.active_trick != "screen_roll":
            # Fit left/right around the actual feet, rather than fitting the
            # full width then panning the character away from its home anchor.
            zoom = min(zoom,
                max(1., foot.x()-25)/max(1., foot.x()-bounds.left()),
                max(1., width-25-foot.x())/max(1., bounds.right()-foot.x()))
        transform = QTransform()
        transform.translate(foot.x(), foot.y())
        transform.scale(zoom, zoom)
        transform.translate(-foot.x(), -foot.y())
        rect = transform.mapRect(bounds)
        dx = max(0.0, 25 - rect.left()) - max(0.0, rect.right() - width + 25)
        # Camera fitting changes the scale around the current feet, never their
        # floor contact. Only an explicit perimeter tour can need a camera pan.
        dy = (max(0.0, top - rect.top()) - max(0.0, rect.bottom() - height + 23)) if self.engine.active_trick == "screen_roll" else 0.0
        result = transform * QTransform.fromTranslate(dx, dy)
        recovery = self._flash_recovery
        if recovery and not self.engine.active_trick:
            distance = abs(recovery["origin"] - self.life.HOME_X)
            weight = min(1., abs(self.life.x-self.life.HOME_X)/distance) if distance > 1e-8 else 0.
            if weight <= 1e-8:
                self._flash_recovery = None
                return result
            home = self._base_foot()
            zoom = result.m11() + (recovery["zoom"]-result.m11())*weight
            age = clamp(self._settle_age/.28, 0, 1); blend = age*age*(3-2*age)
            target_x = home.x() + (recovery["point"].x()-home.x())*weight
            target_y = home.y() + (recovery["point"].y()-home.y())*(1-blend)
            if self.life.state == "return": target_y += self.life.pose[3]*zoom
            result = QTransform()
            result.translate(target_x, target_y); result.scale(zoom, zoom)
            result.translate(-foot.x(), -foot.y())
        return result

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
        self.presentation.begin("food", item_id, self._render_foot())

    def show_food(self, item_id, gain=0):
        self.interact(cancel_gift=True)
        origin = self._next_food_origin
        self._next_food_origin = None
        if self._food_age < self._food_duration():
            if len(self._food_queue) < 6: self._food_queue.append((item_id, gain, origin))
            else:
                key, amount, point = self._food_queue[-1]
                self._food_queue[-1] = (key, amount + gain, point)
        else: self._begin_food(item_id, gain, origin)

    def launch_food(self, item_id, origin: QPointF):
        self._next_food_origin = QPointF(origin)
        self.show_food(item_id)

    def _advance_food(self, dt):
        was_active = self._food_age < self._food_duration()
        self._food_age += max(0, dt)
        if not self._food_arrived and self._food_age >= self.FLIGHT_SECONDS and self._food_age < 100:
            self._food_arrived = True
            self.mood_requested.emit(1.2)
            if not self._food_audio_already: self.sound_requested.emit("eat")
            self.show_gains({"hunger": self._food_gain})
        if self._food_age >= self._food_duration():
            if was_active:
                self.presentation.finish()
                self._food_id = ""
                self._food_until = 0.0
            if self._food_queue:
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
        scale, width, height = self._geometry()
        painter.save(); painter.scale(scale, scale)
        theme = self._slot("theme")
        room_rect = QRectF(0, 0, width, height)
        # Each stage can be replaced by a transparent artist layer. Furniture
        # overrides remain independent, so changing decor never replaces a pet.
        self._paint_room(painter, width, height)
        self._paint_wall_decoration(painter, width, height)
        foreground_dummy = (self._slot("corner") == "training_dummy" and self.performance
                            and self.performance.item_id == "training_dummy")
        if not foreground_dummy: self._paint_corner(painter, width, height)
        self._paint_ambient(painter, width, height)
        if not self._art.layer(painter, theme, "middle_furniture", room_rect):
            foot = self._base_foot()
            self._paint_rug(painter, foot)
            self._paint_bowl(painter, width, height)
        foreground_gift = self.performance and self.performance.item_id in {"tes_guitar", "tes_microphone"}
        if not foreground_gift: self._paint_gift(painter, width, height)
        self._paint_companion(painter)
        contact = self._pet_transform().map(self._render_foot())
        self._shadow(painter, QPointF(contact.x(), self._base_foot().y()+3), 80, 11)
        painter.save(); painter.setTransform(self._pet_transform(), combine=True)
        if self.performance and self.performance.item_id == "drama_clapper" and not self._busy():
            perf=self.performance; u=clamp(perf.age/perf.duration,0,1)
            envelope=math.sin(u*math.pi)**2
            for side in (-1,1):
                painter.save(); painter.setOpacity(.42*envelope)
                pose=(1,1,math.sin(perf.age*7)*12*envelope if side<0 else 0,0)
                self.renderer_provider().paint(painter,RoomPetView(self.engine,pose),
                    self._render_foot()+QPointF(side*115*envelope,0))
                painter.restore()
        self.renderer_provider().paint(painter, self._view(), self._render_foot())
        painter.restore()
        if foreground_gift: self._paint_gift(painter, width, height)
        if foreground_dummy: self._paint_corner(painter, width, height)
        # A very light final glaze joins the PNG character to room colour.
        painter.fillRect(room_rect, QColor(255,230,183,3) if self.daytime else QColor(47,58,90,11))
        table = self.foreground_table_rect()
        table = QRectF(table.x()/scale,table.y()/scale,table.width()/scale,table.height()/scale)
        if not self._art.layer(painter, theme, "foreground", room_rect):
            self._art.foreground(painter, width, height, table, self.environment_time)
        painter.restore()
        self._paint_life_particles(painter)
        self._paint_food_flight(painter)
        paint_food_extra(painter,self.atlas,self._food_id,self._food_age-self.FLIGHT_SECONDS,self.pet_bounds())
        self._paint_gains(painter)
        self._advance_message(); self._paint_message(painter)
        painter.end()

    def _paint_room(self, p, width, height):
        theme = self._slot("theme")
        rect = QRectF(0, 0, width, height)
        palette = self.THEMES.get(theme, self.THEMES["cheese_room"])
        window = self.window_rect(width, height)
        if self._art.layers.paint(p, theme, rect, stretch=True):
            self._paint_chime(p,window)
            if theme == "practice_room": self._paint_practice_counter(p, width, height)
            return
        if not self._art.layer(p, theme, "outdoors", rect):
            self._art.outdoors(p, window, self.daytime, self.environment_time)
        if not self._art.layer(p, theme, "walls_floor", rect):
            self._art.architecture(p,width,height,palette,theme,window)
        if not self._art.layer(p, theme, "back_furniture", rect):
            if not self._art.layers.paint(p, "window_frame", window.adjusted(-27,-25,30,35)):
                self._art.window_frame(p,window,palette[2]); self._curtains(p,window)
            # Low cabinet occupies the far-left plane, never the wall picture.
            cabinet_x=width*.115; cabinet_y=self._art.floor_y(height)+52
            cabinet_rect=QRectF(cabinet_x-79,cabinet_y-147,167,163)
            if not self._art.layers.paint(p,"low_bookcase",cabinet_rect):
                self._art.bookcase(p,cabinet_x,cabinet_y,.82)
        self._paint_chime(p, window)
        if theme == "practice_room": self._paint_practice_counter(p, width, height)
        if not self._slot("wall"):
            self._little_landscape(p,self._wall_art_rect(width,height))

    def _paint_practice_counter(self, p, width, height):
        rect = QRectF(width*.52-38, max(145, self._art.floor_y(height)*.32), 76, 40)
        p.save(); p.setPen(line("#8f8d6b",1.1)); p.setBrush(gradient(0,rect.top(),0,rect.bottom(),"#faf3d9","#e2d5b2")); p.drawRoundedRect(rect,5,5)
        perf = self.performance
        count = 0
        if perf and perf.active and perf.item_id in {"gnar_workbook", "practice_hourglass"}:
            u = perf.age / perf.duration
            thresholds = (.34, .53, .72) if perf.item_id == "practice_hourglass" else tuple((n+1)/3-.035 for n in range(3))
            count = sum(u >= threshold for threshold in thresholds)
        p.setFont(QFont("Microsoft YaHei UI",9,QFont.Weight.Bold)); p.setPen(QColor("#7c795b"))
        p.drawText(rect.adjusted(2,0,-2,-16), Qt.AlignmentFlag.AlignCenter, "本组练习")
        for n in range(3):
            p.setBrush(QColor("#92a57a" if n<count else "#d4cbae")); p.drawEllipse(QPointF(rect.left()+23+n*15,rect.bottom()-11),4,4)
        p.restore()

    def _wall_art_rect(self,width,height):
        # The rear wall begins at 22%; the picture is well right of the lamp.
        y=max(145, min(height*.31, self._art.floor_y(height)-150))
        return QRectF(width*.35-56,y,112,91)

    def _corner_point(self,width,height):
        return QPointF(width*.228,self._base_foot().y()-8)

    def _paint_rug(self,p,foot):
        key=self._slot("rug")
        rect=QRectF(foot.x()-155,foot.y()-34,310,89)
        if not self._art.layers.paint(p,key,rect): self._art.rug(p,foot,key)

    def lamp_rect(self):
        if self._slot("corner") != "warm_lamp": return QRectF()
        scale,width,height=self._geometry(); at=self._corner_point(width,height)
        return QRectF((at.x()-56)*scale,(at.y()-206)*scale,112*scale,222*scale)

    def chime_rect(self):
        scale, width, height = self._geometry()
        window = self.window_rect(width, height)
        return QRectF((window.right() + 7) * scale, window.top() * scale,
                      48 * scale, 105 * scale)

    def fist_bump_rect(self):
        perf = self.performance
        if not perf or perf.item_id != "fist_bump_glove" or self._busy(): return QRectF()
        scale, width, _height = self._geometry()
        rect = gift_hit_rect(perf, QPointF(width * perf.pet_x, self._base_foot().y()-3))
        return QRectF(rect.x()*scale, rect.y()*scale, rect.width()*scale, rect.height()*scale)

    def acknowledge_fist(self):
        perf = self.performance
        if (not perf or perf.item_id != "fist_bump_glove" or self._busy()
                or perf.fist_bumped or not .3 <= perf.age < 4.8): return False
        perf.fist_bumped = True; perf.fist_bump_age = perf.age
        self._mood(1.5); self.show_message("碰一下，这波配合到了。", "interaction")
        self.update()
        return True

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        if self.fist_bump_rect().contains(event.position()):
            self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if (event.button() == Qt.MouseButton.LeftButton and self._pressed is not None
                and (event.position()-self._pressed).manhattanLength() <= 8
                and self.fist_bump_rect().contains(event.position()) and self.acknowledge_fist()):
            self._pressed = None; event.accept(); return
        if event.button() == Qt.MouseButton.LeftButton:
            for slot, key in (("corner","esports_chair"),("corner","training_dummy"),("wall","tactics_screen")):
                if self._slot(slot)==key and self.furniture_rect(key).contains(event.position()):
                    self.activate_furniture(key); event.accept(); return
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

    def furniture_rect(self, key):
        scale,width,height=self._geometry()
        if key=="tactics_screen":
            rect=self._wall_art_rect(width,height).adjusted(-32,-5,32,8)
        else:
            at=self._corner_point(width,height)
            rect=QRectF(at.x()-61,at.y()-130,122,146)
        return QRectF(rect.x()*scale,rect.y()*scale,rect.width()*scale,rect.height()*scale)

    def activate_furniture(self,key):
        slot="wall" if key=="tactics_screen" else "corner"
        if self._slot(slot)!=key or self._busy(): return False
        self.interact(cancel_gift=True)
        self._furniture_active=key; self._furniture_started=self.environment_time
        lines={"esports_chair":"这个位置留给高手。","training_dummy":"这次练习算数。","tactics_screen":"上一波，我们再看一眼。"}
        self.show_message(lines[key],"interaction")
        if key!="tactics_screen": self._begin_gift(key,3.,"")
        self.furniture_interacted.emit(key)
        return True

    def _paint_chime(self, p, window):
        if self._slot("window") != "sunny_chime":
            return
        if self._art.layers.paint(p,"sunny_chime",QRectF(window.right()+7,window.top(),48,105)):
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
        if self._art.layers.paint(p,"sesame_friend",QRectF(foot.x()-29,foot.y()-48,58,54)):
            return
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
        scale=self._geometry()[0]
        top=max(122,112/scale+7)
        floor=self._art.floor_y(height)
        return QRectF(width*.74-80,top,166,max(100,min(180,floor-top-23)))

    def _paint_ambient(self, p, width, height):
        rect=QRectF(0,0,width,height)
        if self._art.layer(p,self._slot("theme"),"lighting",rect): return
        at=self._corner_point(width,height)
        lamp=(at.x(),at.y()) if self._slot("corner")=="warm_lamp" and self._home.get("lamp_on",True) else None
        self._art.ambience(p,width,height,self.window_rect(width,height),self.daytime,self.environment_time,lamp)

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

    def _little_landscape(self, p, rect):
        self._art.wall_decoration(p,rect,"landscape")

    def _paint_wall_decoration(self, p, width, height):
        key=self._slot("wall")
        art=self._wall_art_rect(width,height)
        if key == "summit_wall":
            rect = art.adjusted(-24, -8, 24, 16)
            if not self._art.layers.paint(p, key, rect): self._art.summit_wall(p, rect)
            perf = self.performance
            if perf and perf.active and perf.item_id == "summit_pickaxe":
                u = clamp(perf.age / perf.duration, 0, 1)
                fade = min(1, perf.age/.3, max(0, (perf.duration-perf.age)/.7))
                p.save(); p.setOpacity(fade)
                for n, point in enumerate(self._art.summit_holds(rect)):
                    if u >= (n+1)*.16:
                        glow = QRadialGradient(point, 14); glow.setColorAt(0,QColor(255,221,134,190)); glow.setColorAt(1,QColor(255,221,134,0))
                        p.setPen(Qt.PenStyle.NoPen); p.setBrush(glow); p.drawEllipse(point,14,14)
                        p.setBrush(QColor("#ffe2a0")); p.drawEllipse(point,3,3)
                p.restore()
            return
        if key in {"sunflower_painting","rice_clock"}:
            if not self._art.layers.paint(p,key,art):
                self._art.wall_decoration(p,art,key,self.clock_angles())
            return
        if self._slot("wall")=="tactics_screen":
            rect=art.adjusted(-32,-5,32,8)
            if self._art.layers.paint(p,key,rect): return
            soft_shadow(p,rect.adjusted(-2,3,7,8),30)
            p.save(); p.setPen(line("#886b51",1.1)); p.setBrush(gradient(rect.left(),0,rect.right(),0,"#b19a7e","#d2b595")); p.drawRoundedRect(rect,8,8)
            p.setBrush(QColor("#3e565c")); p.drawRoundedRect(rect.adjusted(6,6,-6,-6),5,5)
            recent=self.recent_interactions[-3:]
            for i in range(3):
                box=QRectF(rect.left()+12+i*56,rect.top()+18,49,63)
                p.setPen(QPen(QColor("#a4bbae"),1.5)); p.setBrush(QColor("#c9d6bd")); p.drawRoundedRect(box,5,5)
                if i<len(recent): p.drawPixmap(box.adjusted(2,5,-2,-12),self.atlas.pixmap(recent[i]),QRectF(0,0,80,80))
                else:
                    p.setPen(QColor("#748b82")); p.drawText(box,Qt.AlignmentFlag.AlignCenter,"待记录")
            p.restore(); return
        if self._slot("wall") == "air_conditioner":
            scale, _w, _h = self._geometry()
            rect = self.air_conditioner_rect()
            rect = QRectF(rect.x()/scale,rect.y()/scale,rect.width()/scale,rect.height()/scale)
            if self._art.layers.paint(p,key,rect): return
            soft_shadow(p,rect.adjusted(-3,3,8,10),25)
            p.save(); p.setPen(line("#9caaa7",1.1)); p.setBrush(gradient(0,rect.top(),0,rect.bottom(),"#f4f4e9","#d9e2de"))
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

    def air_conditioner_rect(self):
        scale,width,height=self._geometry()
        art=self._wall_art_rect(width,height)
        return QRectF((art.center().x()-72)*scale,art.top()*scale,144*scale,54*scale)

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
        # Compatibility seam; main rendering separates outside and frame stages.
        self._art.outdoors(p,rect,self.daytime,self.environment_time)
        self._art.window_frame(p,rect,wood)

    def _paint_corner(self, p, width, height):
        key=self._slot("corner"); at=self._corner_point(width,height)
        if not key: return
        rect=QRectF(at.x()-76,at.y()-211,152,229)
        if self._art.layers.paint(p,key,rect): return
        if key=="warm_lamp":
            self._art.lamp(p,at.x(),at.y(),self._home.get("lamp_on",True)); return
        if key=="ficus_plant":
            self._art.plant(p,at.x(),at.y(),1.0); return
        if key in {"esports_chair","training_dummy"}:
            self._shadow(p,at+QPointF(0,7),58,10)
            age=self.environment_time-self._furniture_started
            active=self.performance and self.performance.item_id==key
            angle=(math.sin(age*8)*math.exp(-age*1.1)*8 if key=="esports_chair" else math.sin(age*math.tau)*7*math.sin(min(1,age/3)*math.pi)**2) if active else 0
            p.save(); p.translate(at); p.rotate(angle); p.scale(1.55,1.55); p.translate(-40,-73)
            paint_collection_icon(Brush(p),key); p.restore(); return

    def _paint_bowl(self, p, width, height):
        x,y=width*.84,self._base_foot().y()-5
        key=self._slot("bowl")
        rect=QRectF(x-81,y-64,165,106)
        if self._art.layers.paint(p,key,rect): return
        food=None
        if monotonic()<self._food_until:
            food={"sesame":"#777079","strawberry":"#e89dae","matcha":"#a1bc7c","chili":"#d67a57","water":"#afd5e3"}.get(self._food_id,"#f1d596")
        self._art.tea_table(p,x,y,key=="porcelain_bowl",food)

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
        if perf.item_id in ALL_GIFTS:
            paint_gift_props(p,self.atlas,perf,QPointF(width*perf.pet_x,self._base_foot().y()-3),width,height)
            return
        item, t = perf.item_id, perf.age
        x, y = width * .735, self._base_foot().y()-3
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
