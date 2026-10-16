"""Shared, signal-driven growth model. No widgets, file writes or offline decay."""
from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import date
import json
import math
from pathlib import Path
import random
import time
from typing import Callable

from PySide6.QtCore import QObject, Signal


def _number(value, name: str, low: float = 0, high: float = math.inf) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} 必须为数值")
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"{name} 超出允许范围")
    return float(value)


def _integer(value, name: str, low: int = 0, high: int | None = None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        raise ValueError(f"{name} 必须为允许范围内的整数")
    return value


@dataclass(frozen=True)
class GameRules:
    hunger_seconds: float = 180.0
    gift_seconds: float = 90.0
    hungry_notice_seconds: float = 45.0
    gift_lifetime: float = 30.0
    sugar_cost: int = 10
    sugar_hunger: float = 25.0
    sugar_exp: int = 10
    pet_cooldown: float = 10.0
    buff_seconds: float = 60.0

    def __post_init__(self) -> None:
        for key in ("hunger_seconds", "gift_seconds", "hungry_notice_seconds", "gift_lifetime", "pet_cooldown"):
            _number(getattr(self, key), key, 0.1, 86400)
        _number(self.gift_lifetime, "gift_lifetime", 0.1, 30)
        _number(self.buff_seconds, "buff_seconds", 1, 3600)
        _integer(self.sugar_cost, "sugar_cost", 1)
        _integer(self.sugar_exp, "sugar_exp", 1)
        _number(self.sugar_hunger, "sugar_hunger", 1, 100)

    @classmethod
    def from_catalog(cls, path: Path, accelerated: bool = False) -> GameRules:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict) or config.get("schema_version") != 1:
            raise ValueError("catalog 需要 schema_version=1")
        timing = config["development_timing" if accelerated else "timing"]
        sugar = config.get("items", {}).get("sugar", config.get("white_sugar", {}))
        return cls(hunger_seconds=timing["hunger_seconds"], gift_seconds=timing["gift_seconds"],
                   hungry_notice_seconds=timing["hungry_notice_seconds"],
                   sugar_cost=sugar["cost"], sugar_hunger=sugar["hunger"], sugar_exp=sugar["exp"],
                   buff_seconds=config.get("development_buff_seconds" if accelerated else "buff_seconds", 15 if accelerated else 60))


class Catalog:
    """Validated, data-driven food and achievement definitions."""
    def __init__(self, source: dict) -> None:
        self.items = deepcopy(source["items"])
        self.achievements = deepcopy(source["achievements"])
        self.interactions = dict(source["interactions"])
        if not isinstance(self.items, dict) or not self.items:
            raise ValueError("items 必须是商品对象")
        for item_id, item in self.items.items():
            if not isinstance(item_id, str) or not isinstance(item, dict):
                raise ValueError("商品配置无效")
            for key in ("name", "icon"):
                if not isinstance(item.get(key), str) or not item[key]:
                    raise ValueError("商品名称和图标不能为空")
            _integer(item["cost"], "商品价格", 1)
            _integer(item["exp"], "商品经验", 0)
            _number(item["hunger"], "商品饥饿恢复", 0, 100)
            if "buff" in item:
                buff = item["buff"]
                if not isinstance(buff, dict) or not isinstance(buff.get("name"), str):
                    raise ValueError("Buff 配置无效")
                color = buff.get("color", "")
                if not isinstance(color, str) or len(color) != 7 or not color.startswith("#"):
                    raise ValueError("Buff 颜色需要 #RRGGBB")
                int(color[1:], 16)
                _number(buff.get("scale", 1), "Buff 缩放", 0.5, 1.2)
                _number(buff.get("behavior_seconds", 0), "行为时长", 0, 12)
        if "sugar" not in self.items:
            raise ValueError("商品中必须包含 sugar")
        ids = set()
        metrics = {"total_clicks", "total_drops", "total_feeds", "total_pets", "flavors_seen",
                   "total_gifts", "affection_level", "rapid_poke_peak", "total_shakes", "starvation_recoveries"}
        for achievement in self.achievements:
            aid = achievement["id"]
            if not isinstance(aid, str) or aid in ids or achievement["metric"] not in metrics:
                raise ValueError("成就 ID 或指标无效")
            ids.add(aid)
            _integer(achievement["tier"], "成就阶数", 1, 3)
            _integer(achievement["target"], "成就目标", 1)
            _integer(achievement["coins"], "成就奖励", 0)
            if not isinstance(achievement["name"], str) or not isinstance(achievement.get("title", ""), str):
                raise ValueError("成就名称或称号无效")
        for key in ("rapid_window_seconds", "rapid_target", "shake_min_speed", "shake_distance", "shake_reversals"):
            _number(self.interactions[key], key, 1, 10000)

    @classmethod
    def load(cls, path: Path | None = None) -> Catalog:
        path = path or Path(__file__).resolve().parent / "config" / "catalog.json"
        return cls(json.loads(path.read_text(encoding="utf-8-sig")))


@dataclass
class PetData:
    name: str = "白汤圆"
    equipped_title: str = "糯米团子"
    titles: list[str] = field(default_factory=lambda: ["糯米团子"])
    inventory: dict = field(default_factory=dict)
    flavors_seen: list[str] = field(default_factory=list)
    unlocked_achievements: list[str] = field(default_factory=list)
    claimed_achievements: list[str] = field(default_factory=list)
    active_buff: dict = field(default_factory=dict)
    coins: int = 100
    hunger: float = 80.0
    affection_level: int = 1
    affection_exp: int = 0
    daily_stats: dict = field(default_factory=lambda: {
        "date": date.today().isoformat(), "poke_attempts": 0, "poke_coin_drops": 0,
    })
    stats: dict = field(default_factory=lambda: {
        "total_clicks": 0, "total_feeds": 0, "total_idle_seconds": 0.0,
        "total_gifts": 0, "total_pets": 0, "total_drops": 0, "total_shakes": 0,
        "starvation_recoveries": 0, "rapid_poke_peak": 0,
    })
    timers: dict = field(default_factory=lambda: {
        "hunger_elapsed": 0.0, "coin_elapsed": 0.0,
        "hungry_notice_elapsed": 0.0, "pet_cooldown_remaining": 0.0,
    })
    pending_reward: dict = field(default_factory=lambda: {"coins": 0, "remaining_seconds": 0.0})

    @classmethod
    def from_dict(cls, raw: dict) -> PetData:
        if not isinstance(raw, dict):
            raise ValueError("养成数据必须是对象")
        defaults = asdict(cls())
        for key in defaults:
            if key in raw:
                if isinstance(defaults[key], dict):
                    if not isinstance(raw[key], dict):
                        raise ValueError(f"{key} 必须是对象")
                    defaults[key].update(deepcopy(raw[key]))
                else:
                    defaults[key] = raw[key]
        item = cls(**defaults)
        for key in ("name", "equipped_title"):
            if not isinstance(getattr(item, key), str) or not 1 <= len(getattr(item, key)) <= 40:
                raise ValueError(f"{key} 需要 1～40 个字符")
        for key in ("titles", "flavors_seen", "unlocked_achievements", "claimed_achievements"):
            value = getattr(item, key)
            if (not isinstance(value, list) or not all(isinstance(v, str) for v in value)
                    or len(set(value)) != len(value)):
                raise ValueError(f"{key} 必须为不重复的字符串列表")
        if "糯米团子" not in item.titles or item.equipped_title not in item.titles:
            raise ValueError("佩戴称号需要先解锁")
        if not set(item.claimed_achievements).issubset(item.unlocked_achievements):
            raise ValueError("不能领取尚未达成的成就")
        for key, count in item.inventory.items():
            if not isinstance(key, str):
                raise ValueError("背包物品 ID 必须为字符串")
            _integer(count, "背包数量")
        if item.active_buff:
            if not isinstance(item.active_buff.get("item_id"), str):
                raise ValueError("Buff 需要物品 ID")
            _number(item.active_buff.get("remaining_seconds"), "Buff 剩余时间", 0, 3600)
            _number(item.active_buff.get("behavior_remaining", 0), "行为剩余时间", 0, 12)
        _integer(item.coins, "coins")
        item.hunger = _number(item.hunger, "hunger", 0, 100)
        _integer(item.affection_level, "affection_level", 1, 30)
        _integer(item.affection_exp, "affection_exp", 0,
                 item.affection_level * 50 - 1 if item.affection_level < 30 else 0)
        today = item.daily_stats.get("date")
        if not isinstance(today, str) or date.fromisoformat(today).isoformat() != today:
            raise ValueError("每日日期需要 YYYY-MM-DD")
        attempts = _integer(item.daily_stats["poke_attempts"], "poke_attempts", 0, 20)
        _integer(item.daily_stats["poke_coin_drops"], "poke_coin_drops", 0, attempts)
        for key in ("total_clicks", "total_feeds", "total_gifts", "total_pets", "total_drops", "total_shakes", "starvation_recoveries", "rapid_poke_peak"):
            _integer(item.stats[key], key)
        _number(item.stats["total_idle_seconds"], "total_idle_seconds")
        for key in ("hunger_elapsed", "coin_elapsed", "hungry_notice_elapsed", "pet_cooldown_remaining"):
            _number(item.timers[key], key)
        amount = _integer(item.pending_reward["coins"], "pending_reward.coins", 0, 20)
        remaining = _number(item.pending_reward["remaining_seconds"], "remaining_seconds", 0, 30)
        if amount and amount < 10:
            raise ValueError("拾币礼包数量应为 10～20")
        if not amount and remaining:
            raise ValueError("不存在礼包时不能保留倒计时")
        return item

    def to_dict(self) -> dict:
        return asdict(self)


class PetModel(QObject):
    state_changed = Signal(dict)
    starvation_changed = Signal(bool)
    upgraded = Signal(int)
    feedback = Signal(str, str)
    collectible_changed = Signal(bool)
    fed = Signal()
    achievement_unlocked = Signal(dict)
    buff_changed = Signal(dict)
    dizzy_requested = Signal()
    MAX_LEVEL = 30

    def __init__(self, data: PetData | None = None, rules: GameRules | None = None,
                 rng: random.Random | None = None, today: Callable[[], date] = date.today,
                 parent: QObject | None = None, catalog: Catalog | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        super().__init__(parent)
        self.data = PetData.from_dict((data or PetData()).to_dict())
        self.rules = rules or GameRules()
        self.rng = rng or random.Random()
        self.catalog = catalog or Catalog.load()
        self._clock = clock
        self._poke_times: deque[float] = deque()
        self._dizzy_until = 0.0
        self._today = today
        self._roll_day()
        self.set_rules(self.rules)
        self.initial_achievements = self._detect_achievements()

    @property
    def starving(self) -> bool:
        return self.data.hunger == 0

    @property
    def has_collectible(self) -> bool:
        return self.data.pending_reward["coins"] > 0

    @property
    def exp_required(self) -> int:
        return self.data.affection_level * 50

    def snapshot(self) -> dict:
        return self.data.to_dict()

    def set_rules(self, rules: GameRules) -> None:
        self.rules = rules
        for key, interval in (("hunger_elapsed", rules.hunger_seconds),
                              ("coin_elapsed", rules.gift_seconds),
                              ("hungry_notice_elapsed", rules.hungry_notice_seconds)):
            self.data.timers[key] %= interval

    def _roll_day(self) -> bool:
        value = self._today().isoformat()
        if self.data.daily_stats["date"] == value:
            return False
        self.data.daily_stats.update(date=value, poke_attempts=0, poke_coin_drops=0)
        return True

    def _add_exp(self, amount: int) -> list[int]:
        levels = []
        if self.data.affection_level >= self.MAX_LEVEL:
            return levels
        self.data.affection_exp += amount
        while self.data.affection_level < self.MAX_LEVEL and self.data.affection_exp >= self.exp_required:
            self.data.affection_exp -= self.exp_required
            self.data.affection_level += 1
            self.data.coins += 30
            levels.append(self.data.affection_level)
        if self.data.affection_level == self.MAX_LEVEL:
            self.data.affection_exp = 0
        return levels

    def _publish(self, previous_starving: bool, levels: list[int] | None = None,
                 message: str = "", tone: str = "normal") -> None:
        unlocked = self._detect_achievements()
        self.state_changed.emit(self.snapshot())
        if self.starving != previous_starving:
            self.starvation_changed.emit(self.starving)
        if message:
            self.feedback.emit(message, tone)
        for level in levels or []:
            self.upgraded.emit(level)
        for achievement in unlocked:
            self.achievement_unlocked.emit(achievement)

    def _take_collectible(self) -> tuple[int, list[int]]:
        amount = self.data.pending_reward["coins"]
        if not amount:
            return 0, []
        self.data.coins += amount
        self.data.stats["total_gifts"] += 1
        self.data.pending_reward.update(coins=0, remaining_seconds=0.0)
        levels = self._add_exp(5)
        self.collectible_changed.emit(False)
        return amount, levels

    def claim_collectible(self, automatic: bool = False) -> bool:
        if not self.has_collectible:
            return False
        previous = self.starving
        amount, levels = self._take_collectible()
        prefix = "礼包已自动收好" if automatic else "捡到糯米币啦"
        self._publish(previous, levels, f"🎁 {prefix}：+{amount} 币，好感 +5", "reward")
        return True

    def poke(self) -> None:
        previous = self.starving
        self._roll_day()
        self.data.stats["total_clicks"] += 1
        now = self._clock()
        self._poke_times.append(now)
        while self._poke_times and self._poke_times[0] < now - self.catalog.interactions["rapid_window_seconds"]:
            self._poke_times.popleft()
        self.data.stats["rapid_poke_peak"] = max(self.data.stats["rapid_poke_peak"], len(self._poke_times))
        trigger_dizzy = len(self._poke_times) >= self.catalog.interactions["rapid_target"] and now >= self._dizzy_until
        if trigger_dizzy:
            self._dizzy_until = now + 3
        amount, levels = self._take_collectible()
        exp = 2 if self.data.hunger >= 50 else 1
        levels.extend(self._add_exp(exp))
        message = f"好喜欢你戳戳我～ 好感 +{exp}" if exp == 2 else "肚子有点饿啦… 好感 +1"
        tone = "normal"
        daily = self.data.daily_stats
        if daily["poke_attempts"] < 20:
            daily["poke_attempts"] += 1
            if self.rng.random() < 0.35:
                daily["poke_coin_drops"] += 1
                self.data.coins += 2
                message = f"✨ 戳出 2 枚糯米币！好感 +{exp}"
                tone = "reward"
        if amount:
            message = f"🎁 已领取 {amount} 币！礼包好感 +5，戳戳好感 +{exp}"
            tone = "reward"
        self._publish(previous, levels, message, tone)
        if trigger_dizzy:
            self.dizzy_requested.emit()

    def item(self, item_id: str) -> dict | None:
        item = deepcopy(self.catalog.items.get(item_id))
        if item is not None and item_id == "sugar":
            item.update(cost=self.rules.sugar_cost, hunger=self.rules.sugar_hunger, exp=self.rules.sugar_exp)
        return item

    def buy_item(self, item_id: str, feed_now: bool = False) -> bool:
        item = self.item(item_id)
        if item is None:
            self.feedback.emit("这件食物暂时没有上架。", "normal")
            return False
        if self.data.coins < item["cost"]:
            self.feedback.emit("糯米币不够啦，戳戳或等一会儿拾币吧～", "hungry")
            return False
        previous = self.starving
        self.data.coins -= item["cost"]
        if feed_now:
            self._consume(item_id, item, previous)
        else:
            self.data.inventory[item_id] = self.data.inventory.get(item_id, 0) + 1
            self._publish(previous, message=f"{item['icon']} 已购买 {item['name']}，放进背包啦")
        return True

    def use_item(self, item_id: str) -> bool:
        item = self.item(item_id)
        if item is None or self.data.inventory.get(item_id, 0) <= 0:
            self.feedback.emit("背包里还没有这件食物。", "normal")
            return False
        previous = self.starving
        self.data.inventory[item_id] -= 1
        self._consume(item_id, item, previous)
        return True

    def feed_sugar(self) -> bool:
        return self.buy_item("sugar", feed_now=True)

    def _consume(self, item_id: str, item: dict, previous: bool) -> None:
        gained = min(item["hunger"], 100 - self.data.hunger)
        self.data.hunger = min(100.0, self.data.hunger + item["hunger"])
        self.data.stats["total_feeds"] += 1
        if previous and not self.starving:
            self.data.stats["starvation_recoveries"] += 1
            self.data.timers["hungry_notice_elapsed"] = 0.0
        if "buff" in item:
            self.data.active_buff = {"item_id": item_id, "remaining_seconds": self.rules.buff_seconds,
                                     "behavior_remaining": item["buff"].get("behavior_seconds", 0)}
            if item_id not in self.data.flavors_seen:
                self.data.flavors_seen.append(item_id)
            self.buff_changed.emit(self.buff_view())
        levels = self._add_exp(item["exp"])
        self._publish(previous, message=f"{item['icon']} {item['name']}甜甜香香！饥饿 +{gained:g}，好感 +{item['exp']}")
        self.fed.emit()
        for level in levels:
            self.upgraded.emit(level)

    def buff_view(self) -> dict:
        buff = self.data.active_buff
        item = self.item(buff.get("item_id", ""))
        if not buff or not item or "buff" not in item:
            return {}
        return {**deepcopy(item["buff"]), **deepcopy(buff)}

    def achievement_progress(self, achievement: dict) -> int:
        metric = achievement["metric"]
        if metric == "affection_level":
            value = self.data.affection_level
        elif metric == "flavors_seen":
            value = len(self.data.flavors_seen)
        else:
            value = self.data.stats.get(metric, 0)
        return min(achievement["target"], int(value))

    def _detect_achievements(self) -> list[dict]:
        unlocked = []
        for achievement in self.catalog.achievements:
            aid = achievement["id"]
            if aid not in self.data.unlocked_achievements and self.achievement_progress(achievement) >= achievement["target"]:
                self.data.unlocked_achievements.append(aid)
                unlocked.append(deepcopy(achievement))
        return unlocked

    def claim_achievement(self, achievement_id: str) -> bool:
        achievement = next((a for a in self.catalog.achievements if a["id"] == achievement_id), None)
        if (achievement is None or achievement_id not in self.data.unlocked_achievements
                or achievement_id in self.data.claimed_achievements):
            return False
        self.data.claimed_achievements.append(achievement_id)
        self.data.coins += achievement["coins"]
        title = achievement.get("title")
        if title and title not in self.data.titles:
            self.data.titles.append(title)
        self._publish(self.starving, message=f"🎁 已领取《{achievement['name']}》奖励：{achievement['coins']} 币" + (f"，称号【{title}】" if title else ""), tone="reward")
        return True

    def equip_title(self, title: str) -> bool:
        if title not in self.data.titles:
            return False
        self.data.equipped_title = title
        self._publish(self.starving)
        return True

    def record_drop(self) -> None:
        self.data.stats["total_drops"] += 1
        self._publish(self.starving)

    def record_shake(self) -> None:
        self.data.stats["total_shakes"] += 1
        self._publish(self.starving)

    def pet_head(self) -> bool:
        remaining = self.data.timers["pet_cooldown_remaining"]
        if remaining > 0:
            self.feedback.emit(f"刚摸过啦，再等 {math.ceil(remaining)} 秒～", "normal")
            return False
        self.data.timers["pet_cooldown_remaining"] = self.rules.pet_cooldown
        self.data.stats["total_pets"] += 1
        levels = self._add_exp(3)
        self._publish(self.starving, levels, "👋 摸摸头，今天也有你陪着真好～ 好感 +3")
        return True

    def set_hunger(self, value: float) -> None:
        value = _number(value, "hunger", 0, 100)
        previous = self.starving
        self.data.hunger = value
        self.data.timers["hunger_elapsed"] = 0.0
        self.data.timers["hungry_notice_elapsed"] = 0.0
        text = "好饿呀…要变成糯米饼了 T_T" if value == 0 else f"🍙 饥饿值恢复至 {value:g}"
        self._publish(previous, message=text, tone="hungry" if value == 0 else "normal")

    def offer_collectible(self) -> bool:
        if self.has_collectible:
            return False
        self.data.pending_reward.update(coins=self.rng.randint(10, 20),
                                        remaining_seconds=self.rules.gift_lifetime)
        self.collectible_changed.emit(True)
        self.state_changed.emit(self.snapshot())
        return True

    def advance(self, seconds: float) -> None:
        """Advance online time at event boundaries; no wall-clock/offline catch-up."""
        if not math.isfinite(seconds) or seconds <= 0:
            return
        previous = self.starving
        self._roll_day()
        if self.data.active_buff:
            buff = self.data.active_buff
            buff["remaining_seconds"] = max(0.0, buff["remaining_seconds"] - seconds)
            buff["behavior_remaining"] = max(0.0, buff.get("behavior_remaining", 0) - seconds)
            if buff["remaining_seconds"] == 0:
                self.data.active_buff = {}
            self.buff_changed.emit(self.buff_view())
        remaining = seconds
        timers = self.data.timers
        while remaining > 1e-8:
            wait = min(remaining,
                       max(0.0, self.rules.hunger_seconds - timers["hunger_elapsed"]),
                       max(0.0, self.rules.gift_seconds - timers["coin_elapsed"]))
            if self.has_collectible:
                wait = min(wait, self.data.pending_reward["remaining_seconds"])
            if self.starving:
                wait = min(wait, max(0.0, self.rules.hungry_notice_seconds - timers["hungry_notice_elapsed"]))
            timers["hunger_elapsed"] += wait
            timers["coin_elapsed"] += wait
            timers["pet_cooldown_remaining"] = max(0.0, timers["pet_cooldown_remaining"] - wait)
            self.data.stats["total_idle_seconds"] += wait
            if self.starving:
                timers["hungry_notice_elapsed"] += wait
            if self.has_collectible:
                self.data.pending_reward["remaining_seconds"] = max(0.0, self.data.pending_reward["remaining_seconds"] - wait)
            remaining -= wait
            if timers["hunger_elapsed"] >= self.rules.hunger_seconds - 1e-8:
                timers["hunger_elapsed"] = 0.0
                was_starving = self.starving
                self.data.hunger = max(0.0, self.data.hunger - 1)
                if self.starving and not was_starving:
                    self.feedback.emit("好饿呀…要变成糯米饼了 T_T", "hungry")
            if self.has_collectible and self.data.pending_reward["remaining_seconds"] <= 1e-8:
                self.claim_collectible(automatic=True)
            if timers["coin_elapsed"] >= self.rules.gift_seconds - 1e-8:
                timers["coin_elapsed"] = 0.0
                self.offer_collectible()
            if self.starving and timers["hungry_notice_elapsed"] >= self.rules.hungry_notice_seconds - 1e-8:
                timers["hungry_notice_elapsed"] = 0.0
                self.feedback.emit("好饿呀…要变成糯米饼了 T_T", "hungry")
        self._publish(previous)
