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
import re
import time
import unicodedata
from typing import Callable

from PySide6.QtCore import QObject, Signal

from content_registry import (ACCESSORY_SLOTS, BUILTIN_REGISTRY, HISTORY_EVENTS,
                              BUILTIN_FURNITURE_SLOTS, FURNITURE_SLOTS,
                              ContentRegistry, strict_json_object, valid_content_id)


DEFAULT_DIALOGUES = {
    "poke": [
        "急咯急咯"
    ],
    "feed_full": [
        "别吃，别吃，饿吗，饿死了吗。"
    ],
    "feed": [
        "吃一点，慢慢来。",
        "这口糯米，舒服了。"
    ],
    "feed_recover": [
        "这波有救了，我又能弹了！"
    ],
    "pet_head": [
        "太舒服了！",
        "这个摸摸头，可以的。"
    ],
    "gift": [
        "礼物收到啦，陪我坐一会儿。",
        "心意收下，今天也一起玩吧。"
    ],
    "gift_music_box": [
        "听见你说~"
    ],
    "gift_top": [
        "陀螺收到，突然就想转起来了！"
    ],
    "drag": [
        "你们是来抓我的吗？"
    ],
    "drop": [
        "这波完美呀，哦"
    ],
    "dizzy": [
        "阿一古，头都转晕啦！"
    ],
    "hungry": [
        "这波真的饿了，给我留一口。"
    ],
    "trick_flip": [
        "看我操作，先转一圈！"
    ],
    "trick_clone": [
        "分身拉开，快乐加倍。"
    ],
    "trick_ball": [
        "接住这颗芝麻球！"
    ],
    "trick_screen_roll": [
        "绕屏走位，转一圈就回来。"
    ]
}


EXP_PER_LEVEL = 500
PRACTICE_EXPERIENCES = frozenset(("gnar_workbook", "practice_hourglass", "training_dummy"))
TEAM_SKIN_IDS = frozenset("team_s16_" + team for team in ("al", "blg", "tes", "ig", "gen", "hle", "t1", "dk"))


def valid_skin_id(value) -> bool:
    return isinstance(value, str) and (value == "default" or value in TEAM_SKIN_IDS
                                      or re.fullmatch(r"user_[0-9a-f]{32}", value) is not None)


GUARDIAN_TITLE = "阿一古"
LEGACY_GUARDIAN_TITLES = {"\u2728 汤圆守护神", "汤圆守护神"}


# Compatibility exports; model operations use their own catalogue's registry.
ACCESSORY_CHOICES = dict(BUILTIN_REGISTRY.accessory_choices)

DEFAULT_FURNITURE = {"theme": "cheese_room", "rug": "cloud_cushion",
                     "wall": "", "corner": "", "bowl": "wood_bowl", "window": "", "companion": ""}
FURNITURE_SLOT_BY_ID = BUILTIN_FURNITURE_SLOTS


def _valid_pet_name(value) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= 40 and bool(value.strip())
            and not any(unicodedata.category(char) in ("Cc", "Cs") for char in value))


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
    hunger_seconds: float = 288.0
    gift_seconds: float = 90.0
    hungry_notice_seconds: float = 45.0
    gift_lifetime: float = 30.0
    sugar_cost: int = 30
    sugar_hunger: float = 15.0
    sugar_exp: int = 0
    pet_cooldown: float = 10.0
    buff_seconds: float = 60.0

    def __post_init__(self) -> None:
        for key in ("hunger_seconds", "gift_seconds", "hungry_notice_seconds", "gift_lifetime", "pet_cooldown"):
            _number(getattr(self, key), key, 0.1, 86400)
        _number(self.gift_lifetime, "gift_lifetime", 0.1, 30)
        _number(self.buff_seconds, "buff_seconds", 1, 3600)
        _integer(self.sugar_cost, "sugar_cost", 1)
        _integer(self.sugar_exp, "食物好感经验", 0, 0)
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
    def __init__(self, source: dict, registry: ContentRegistry | None = None) -> None:
        if not isinstance(source, dict):
            raise ValueError("catalog 根节点必须为对象")
        self.registry = registry if registry is not None else BUILTIN_REGISTRY
        if not isinstance(self.registry, ContentRegistry):
            raise ValueError("内容注册表无效")
        self.trick_definitions = self.registry.tricks
        self.accessory_definitions = self.registry.accessories
        self.accessory_choices = self.registry.accessory_choices
        self.items = deepcopy(source["items"])
        self.dialogues = deepcopy(DEFAULT_DIALOGUES)
        configured_dialogues = source.get("dialogues", {})
        if not isinstance(configured_dialogues, dict):
            raise ValueError("互动台词必须为对象")
        self.dialogues.update(deepcopy(configured_dialogues))
        for event, lines in self.dialogues.items():
            if (not isinstance(event, str) or not isinstance(lines, list) or not lines
                    or len(lines) > 20 or any(not isinstance(line, str) or not 1 <= len(line) <= 80 for line in lines)):
                raise ValueError("互动台词需要1～20句、每句1～80字")
        self.food_tiers = deepcopy(source.get("food_tiers", {}))
        self.gift_tiers = deepcopy(source.get("gift_tiers", {}))
        for tiers, metric in ((self.food_tiers, "hunger"), (self.gift_tiers, "exp")):
            if set(tiers) != {"1", "2", "3"}:
                raise ValueError("食物和礼物均需要三个等级")
            for tier in tiers.values():
                if not isinstance(tier.get("name"), str):
                    raise ValueError("等级名称无效")
                _integer(tier["cost"], "等级价格", 1)
                _integer(tier[metric], "等级效果", 1, 100 if metric == "hunger" else 10000)
        self.furniture = deepcopy(source.get("furniture", {}))
        if not isinstance(self.furniture, dict):
            raise ValueError("家具配置必须为对象")
        for furniture_id, product in self.furniture.items():
            if (not isinstance(furniture_id, str) or re.fullmatch(r"[a-z][a-z0-9_]{0,63}", furniture_id) is None
                    or not isinstance(product, dict) or product.get("id") != furniture_id
                    or product.get("slot") not in FURNITURE_SLOTS):
                raise ValueError("家具 ID 或槽位无效")
            if self.registry.furniture_slots.get(furniture_id) != product["slot"]:
                raise ValueError("家具必须先注册已实现的绘制与槽位")
            for key in ("name", "description", "emoji"):
                if not isinstance(product.get(key), str) or not product[key]:
                    raise ValueError("家具名称、说明和图标不能为空")
            if type(product.get("default")) is not bool:
                raise ValueError("家具默认拥有标记需要布尔值")
            _integer(product.get("price"), "家具价格", 0 if product["default"] or product.get("unlock_perk") else 1)
            if product["default"] and (product["price"] != 0 or DEFAULT_FURNITURE.get(product["slot"]) != furniture_id):
                raise ValueError("初始家具必须与默认房间对应且免费")
        if any(value and (value not in self.furniture or self.furniture[value]["slot"] != slot)
               for slot, value in DEFAULT_FURNITURE.items()):
            raise ValueError("家具配置缺少初始房间必需品")
        self.achievements = deepcopy(source["achievements"])
        self.interactions = dict(source["interactions"])
        self.perks = deepcopy(source.get("perks", {}))
        self.milestones = deepcopy(source.get("milestones", []))
        self.trick_products = deepcopy(source.get("trick_products", {}))
        self.team_skins = deepcopy(source.get("team_skins", {}))
        self.accessory_products = deepcopy(source.get("accessory_products", {}))
        if not isinstance(self.accessory_products, dict):
            raise ValueError("装扮商品配置无效")
        for accessory_id, product in self.accessory_products.items():
            definition = self.accessory_definitions.get(accessory_id)
            if (definition is None or not isinstance(product, dict)
                    or product.get("slot") != definition.slot):
                raise ValueError("装扮商品槽位无效")
            _integer(product.get("cost"), "装扮价格", 1)
            for key in ("name", "icon", "description"):
                if not isinstance(product.get(key), str) or not product[key]:
                    raise ValueError("装扮商品资料无效")
        if not isinstance(self.team_skins, dict):
            raise ValueError("战队皮肤配置必须为对象")
        for skin_id, product in self.team_skins.items():
            if skin_id not in TEAM_SKIN_IDS or not isinstance(product, dict):
                raise ValueError("战队皮肤 ID 无效")
            for key in ("name", "team", "region", "description"):
                if not isinstance(product.get(key), str) or not product[key]:
                    raise ValueError("战队皮肤资料不完整")
            if product["region"] not in ("LPL", "LCK"):
                raise ValueError("战队皮肤赛区无效")
            _integer(product.get("cost"), "战队皮肤价格", 1)
            _integer(product.get("level"), "战队皮肤等级", 1, 30)
        if not isinstance(self.trick_products, dict):
            raise ValueError("特技商品必须为对象")
        for trick_id, product in self.trick_products.items():
            if trick_id not in self.trick_definitions or not isinstance(product, dict):
                raise ValueError("商城特技配置无效")
            for key in ("name", "icon", "description"):
                if not isinstance(product.get(key), str) or not product[key]:
                    raise ValueError("特技商品名称、图标和说明不能为空")
            _integer(product.get("cost"), "特技价格", 1)
            if self.trick_definitions[trick_id].exp != 0:
                raise ValueError("商城永久特技不能反复获取经验")
        for perk_id, perk in self.perks.items():
            if not valid_content_id(perk_id) or not isinstance(perk, dict) or not isinstance(perk.get("name"), str):
                raise ValueError("等级特权配置无效")
            _integer(perk["level"], "特权等级", 1, 30)
        self._validate_registration_references()
        for milestone in self.milestones:
            _integer(milestone["level"], "里程碑等级", 1, 30)
            if not isinstance(milestone["label"], str) or any(p not in self.perks for p in milestone["perks"]):
                raise ValueError("里程碑配置无效")
        if not isinstance(self.items, dict) or not self.items:
            raise ValueError("items 必须是商品对象")
        for item_id, item in self.items.items():
            if not valid_content_id(item_id) or not isinstance(item, dict):
                raise ValueError("商品配置无效")
            if item_id not in self.registry.item_ids:
                raise ValueError("消费品必须先注册已实现的表现")
            for key in ("name", "icon"):
                if not isinstance(item.get(key), str) or not item[key]:
                    raise ValueError("商品名称和图标不能为空")
            _integer(item["cost"], "商品价格", 1)
            _integer(item["exp"], "商品经验", 0)
            _number(item["hunger"], "商品饥饿恢复", 0, 100)
            category = item.get("category")
            if "required_skin" in item and item["required_skin"] not in TEAM_SKIN_IDS:
                raise ValueError("专属道具的皮肤限制无效")
            if category not in ("food", "gift"):
                raise ValueError("商品类型必须为 food 或 gift")
            tier = _integer(item.get("tier"), "商品等级", 1, 3)
            definition = (self.food_tiers if category == "food" else self.gift_tiers)[str(tier)]
            metric = "hunger" if category == "food" else "exp"
            if item["cost"] != definition["cost"] or item[metric] != definition[metric]:
                raise ValueError("商品价格和效果必须与等级配置一致")
            if (category == "food" and item["exp"] != 0) or (category == "gift" and (item["hunger"] != 0 or "buff" in item)):
                raise ValueError("食物只恢复饱食度，礼物只增加好感度")
            if "dialogue" in item and (not isinstance(item["dialogue"], str) or item["dialogue"] not in self.dialogues):
                raise ValueError("商品互动台词事件不存在")
            if "description" in item and not isinstance(item["description"], str):
                raise ValueError("商品说明必须为文本")
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
                   "total_gifts", "affection_level", "rapid_poke_peak", "total_shakes", "starvation_recoveries", "customizations", "furniture_placements"}
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

        groups = (set(self.items), set(self.furniture), set(self.team_skins),
                  set(self.accessory_definitions), set(self.trick_definitions))
        seen = set()
        for group in groups:
            if group & seen:
                raise ValueError("不同内容类型不能使用重复 ID")
            seen.update(group)
        self.content_ids = frozenset(seen)
        icon_ids = set(self.registry.icon_ids)
        for mapping in (self.items, self.furniture, self.accessory_products, self.trick_products):
            icon_ids.update(product.get("icon", product.get("emoji", key)) for key, product in mapping.items())
        icon_ids.update(a["id"] for a in self.achievements)
        icon_ids.update(perk["icon"] for perk in self.perks.values() if "icon" in perk)
        if any(not valid_content_id(icon) for icon in icon_ids):
            raise ValueError("内容图标需要安全 ID")
        self.icon_ids = frozenset(icon_ids)

    def _validate_registration_references(self) -> None:
        """Metadata points to real, correctly typed catalogue definitions."""
        accessory_refs, trick_refs = set(), set()
        for perk_id, perk in self.perks.items():
            kind = perk.get("kind")
            if kind == "accessory":
                item_id = perk.get("item")
                definition = self.accessory_definitions.get(item_id)
                if (definition is None or definition.perk_id != perk_id or definition.slot != perk.get("slot")
                        or item_id in accessory_refs):
                    raise ValueError("装扮特权与已实现注册槽位不一致")
                accessory_refs.add(item_id)
            elif kind == "trick":
                definitions = [row for row in self.trick_definitions.values() if row.perk_id == perk_id]
                if len(definitions) != 1 or definitions[0].id in trick_refs:
                    raise ValueError("特技特权必须引用一个已实现特技")
                trick_refs.add(definitions[0].id)
            elif kind == "furniture":
                product = self.furniture.get(perk.get("item"))
                if product is None or product["slot"] != perk.get("slot"):
                    raise ValueError("家具特权引用的商品或槽位不存在")
            elif kind == "team_skin" and perk.get("item") not in self.team_skins:
                raise ValueError("皮肤特权引用不存在")
        for accessory_id in self.accessory_products:
            if accessory_id not in accessory_refs:
                raise ValueError("装扮商品需要对应已注册权限")
        for definition in self.trick_definitions.values():
            if definition.perk_id and definition.perk_id not in self.perks:
                raise ValueError("已实现特技缺少对应等级权限")
        for product in self.furniture.values():
            if product.get("unlock_perk"):
                perk = self.perks.get(product["unlock_perk"], {})
                if (perk.get("kind") != "furniture" or perk.get("item") != product["id"]
                        or perk.get("slot") != product["slot"]):
                    raise ValueError("等级家具引用不存在或不匹配的权限")
        for mapping in (self.items, self.furniture, self.accessory_products, self.trick_products):
            for product in mapping.values():
                icon = product.get("icon", product.get("emoji", ""))
                if not valid_content_id(icon):
                    raise ValueError("内容图标需要安全 ID，不能包含路径")

    @classmethod
    def load(cls, path: Path | None = None) -> Catalog:
        path = path or Path(__file__).resolve().parent / "config" / "catalog.json"
        return cls(json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=strict_json_object))


@dataclass
class PetData:
    name: str = "白汤圆"
    equipped_title: str = "糯米团子"
    titles: list[str] = field(default_factory=lambda: ["糯米团子"])
    inventory: dict = field(default_factory=dict)
    purchased_tricks: list[str] = field(default_factory=list)
    interaction_history: list[dict] = field(default_factory=list)
    practice_experiences: list[str] = field(default_factory=list)
    flavors_seen: list[str] = field(default_factory=list)
    unlocked_achievements: list[str] = field(default_factory=list)
    claimed_achievements: list[str] = field(default_factory=list)
    active_buff: dict = field(default_factory=dict)
    selected_skin_id: str = "default"
    owned_team_skins: list[str] = field(default_factory=list)
    purchased_accessories: list[str] = field(default_factory=list)
    skin_configs: dict = field(default_factory=dict)
    archived_skins: list[str] = field(default_factory=list)
    custom_import_unlocked: bool = False
    accessories: dict = field(default_factory=lambda: {"head": "", "face": "", "effect": "", "offset_y": 0})
    owned_furniture: list[str] = field(default_factory=lambda: ["cheese_room", "cloud_cushion", "wood_bowl"])
    equipped_furniture: dict = field(default_factory=lambda: dict(DEFAULT_FURNITURE))
    placed_furniture: list[str] = field(default_factory=list)
    lamp_on: bool = True
    air_conditioner_on: bool = True
    overlay_visible: bool = False
    muted: bool = False
    coins: int = 100
    hunger: float = 80.0
    affection_level: int = 1
    affection_exp: int = 0
    daily_stats: dict = field(default_factory=lambda: {
        "date": date.today().isoformat(), "poke_attempts": 0, "poke_coin_drops": 0,
    })
    stats: dict = field(default_factory=lambda: {
        "total_clicks": 0, "total_feeds": 0, "total_idle_seconds": 0.0,
        "total_gifts": 0, "total_presents": 0, "total_pets": 0, "total_drops": 0, "total_shakes": 0,
        "starvation_recoveries": 0, "rapid_poke_peak": 0, "customizations": 0,
        "furniture_purchases": 0, "furniture_placements": 0,
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
                    defaults[key] = deepcopy(raw[key])
        item = cls(**defaults)
        if not valid_skin_id(item.selected_skin_id):
            raise ValueError("皮肤 ID 无效")
        if not isinstance(item.skin_configs, dict) or len(item.skin_configs) > 1000:
            raise ValueError("单皮肤配置数量无效")
        for skin_id, config in item.skin_configs.items():
            if not valid_skin_id(skin_id) or not isinstance(config, dict):
                raise ValueError("单皮肤配置 ID 无效")
            _number(config.get("scale_multiplier", 1.0), "角色大小", .6, 1.5)
            _integer(config.get("accessory_offset_y", 0), "独立挂件高度", -30, 30)
        for config in item.skin_configs.values():
            config.setdefault("scale_multiplier", 1.0)
            config.setdefault("accessory_offset_y", 0)
        _integer(item.accessories.get("offset_y", 0), "旧挂件高度", -30, 30)
        item.skin_configs.setdefault(item.selected_skin_id, {"scale_multiplier": 1.0,
            "accessory_offset_y": item.accessories.get("offset_y", 0)})
        item.accessories["offset_y"] = item.skin_configs[item.selected_skin_id].get("accessory_offset_y", 0)
        if (not isinstance(item.archived_skins, list) or any(not isinstance(sid, str) or not re.fullmatch(r"user_[0-9a-f]{32}", sid) for sid in item.archived_skins)
                or len(item.archived_skins) != len(set(item.archived_skins))):
            raise ValueError("衣橱回收区无效")
        if item.selected_skin_id in item.archived_skins:
            raise ValueError("不能选择回收区皮肤")
        if type(item.custom_import_unlocked) is not bool:
            raise ValueError("导入权限需要布尔值")
        # Schema-5 snapshots from early builds used one Boolean face switch.
        # Only that exact legacy representation is migrated; arbitrary values fail.
        if type(item.accessories.get("face")) is bool:
            item.accessories["face"] = "sunglasses" if item.accessories["face"] else ""
        if "sunglasses" in item.accessories:
            legacy = item.accessories.pop("sunglasses")
            if type(legacy) is not bool:
                raise ValueError("旧墨镜开关需要布尔值")
            if "face" not in raw.get("accessories", {}):
                item.accessories["face"] = "sunglasses" if legacy else ""
        for slot in ACCESSORY_SLOTS:
            value = item.accessories.get(slot, "")
            if not valid_content_id(value, empty=True):
                raise ValueError("挂件配置无效")
            known = BUILTIN_REGISTRY.accessories.get(value)
            if known is not None and known.slot != slot:
                raise ValueError("已知挂件不能存入错误槽位")
        if set(item.accessories) - {*ACCESSORY_SLOTS, "offset_y"}:
            raise ValueError("挂件槽位无效")
        _integer(item.accessories["offset_y"], "挂件垂直偏移", -30, 30)
        for key in ("name", "equipped_title"):
            if not isinstance(getattr(item, key), str) or not 1 <= len(getattr(item, key)) <= 40:
                raise ValueError(f"{key} 需要 1～40 个字符")
        if not _valid_pet_name(item.name):
            raise ValueError("宠物名字需要 1～40 个字符且不能含控制字符")
        for key in ("titles", "flavors_seen", "unlocked_achievements", "claimed_achievements", "purchased_tricks",
                    "owned_furniture", "placed_furniture", "owned_team_skins", "purchased_accessories"):
            value = getattr(item, key)
            if (not isinstance(value, list) or not all(isinstance(v, str) for v in value)
                    or len(set(value)) != len(value)):
                raise ValueError(f"{key} 必须为不重复的字符串列表")
        if not set(item.owned_team_skins).issubset(TEAM_SKIN_IDS):
            raise ValueError("已拥有战队皮肤 ID 无效")
        if any(not valid_content_id(value) for value in item.purchased_accessories):
            raise ValueError("已购装扮 ID 无效")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", trick) for trick in item.purchased_tricks):
            raise ValueError("已购特技 ID 无效")
        for key in ("lamp_on", "air_conditioner_on", "overlay_visible", "muted"):
            if type(getattr(item, key)) is not bool:
                raise ValueError(f"{key} 需要布尔值")
        for furniture_id in item.owned_furniture + item.placed_furniture:
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", furniture_id):
                raise ValueError("家具 ID 无效")
        # Existing saves gain the three starter furnishings without spending coins.
        for furniture_id in DEFAULT_FURNITURE.values():
            if furniture_id and furniture_id not in item.owned_furniture:
                item.owned_furniture.append(furniture_id)
        if not set(item.placed_furniture).issubset(item.owned_furniture):
            raise ValueError("布置记录只能包含已拥有家具")
        for slot in FURNITURE_SLOTS:
            furniture_id = item.equipped_furniture[slot]
            if (not isinstance(furniture_id, str) or (furniture_id and furniture_id not in item.owned_furniture)
                    or (furniture_id in FURNITURE_SLOT_BY_ID and FURNITURE_SLOT_BY_ID[furniture_id] != slot)
                    or (slot in ("theme", "rug", "bowl") and not furniture_id)):
                raise ValueError("家具槽位与已拥有家具不匹配")
        item.titles = list(dict.fromkeys(GUARDIAN_TITLE if title in LEGACY_GUARDIAN_TITLES else title for title in item.titles))
        if item.equipped_title in LEGACY_GUARDIAN_TITLES:
            item.equipped_title = GUARDIAN_TITLE
        if "糯米团子" not in item.titles or item.equipped_title not in item.titles:
            raise ValueError("佩戴称号需要先解锁")
        if not set(item.claimed_achievements).issubset(item.unlocked_achievements):
            raise ValueError("不能领取尚未达成的成就")
        for key, count in item.inventory.items():
            if not valid_content_id(key):
                raise ValueError("背包物品 ID 必须为字符串")
            _integer(count, "背包数量")
        if item.active_buff:
            if not valid_content_id(item.active_buff.get("item_id")):
                raise ValueError("Buff 需要物品 ID")
            _number(item.active_buff.get("remaining_seconds"), "Buff 剩余时间", 0, 3600)
            _number(item.active_buff.get("behavior_remaining", 0), "行为剩余时间", 0, 12)
        _integer(item.coins, "coins")
        item.hunger = _number(item.hunger, "hunger", 0, 100)
        _integer(item.affection_level, "affection_level", 1, 30)
        _integer(item.affection_exp, "affection_exp", 0,
                 item.affection_level * EXP_PER_LEVEL - 1 if item.affection_level < 30 else 0)
        today = item.daily_stats.get("date")
        if not isinstance(today, str) or date.fromisoformat(today).isoformat() != today:
            raise ValueError("每日日期需要 YYYY-MM-DD")
        attempts = _integer(item.daily_stats["poke_attempts"], "poke_attempts", 0, 20)
        _integer(item.daily_stats["poke_coin_drops"], "poke_coin_drops", 0, attempts)
        for key in ("total_clicks", "total_feeds", "total_gifts", "total_presents", "total_pets", "total_drops", "total_shakes", "starvation_recoveries", "rapid_poke_peak", "customizations",
                    "furniture_purchases", "furniture_placements"):
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
        if (not isinstance(item.practice_experiences, list)
                or any(not isinstance(value, str) or value not in PRACTICE_EXPERIENCES
                       for value in item.practice_experiences)
                or len(set(item.practice_experiences)) != len(item.practice_experiences)):
            raise ValueError("练习体验只能保存练习册、沙漏和训练假人，且不能重复")
        if not isinstance(item.interaction_history, list) or len(item.interaction_history) > 3:
            raise ValueError("本机互动摘要只能保留最近3条")
        for event in item.interaction_history:
            if (not isinstance(event, dict) or set(event) != {"event", "item_id"}
                    or not isinstance(event.get("event"), str) or event.get("event") not in HISTORY_EVENTS
                    or not valid_content_id(event.get("item_id"), empty=True)):
                raise ValueError("本机互动摘要只能保存受限事件与安全物品 ID")
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
    food_consumed = Signal(str)
    gifted = Signal()
    presentation_requested = Signal(dict)
    gains_received = Signal(dict)
    reward_sound_requested = Signal()
    interaction_started = Signal(str)
    achievement_unlocked = Signal(dict)
    buff_changed = Signal(dict)
    dizzy_requested = Signal()
    appearance_changed = Signal(dict)
    perks_unlocked = Signal(list)
    trick_lifecycle = Signal(dict)
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
        self._dialogue_cursors = {}
        self._clock = clock
        self._poke_times: deque[float] = deque()
        self._dizzy_until = 0.0
        self._today = today
        self._roll_day()
        self.set_rules(self.rules)
        self.debug_unlock_all = False
        # A process-only spending override; never inflate or serialize the real balance.
        self._unlimited_coins = False
        self._presentation_managed = False
        self.trick_cooldowns = dict.fromkeys(self.catalog.trick_definitions, 0.0)
        self.trick_busy = 0.0
        self._active_trick_id = ""
        self._known_perks = set()
        # Old saves may contain a waiting coin gift. Settle its original amount
        # once before the first save/UI; new online income never waits for a click.
        self.restored_income_levels = []
        if self.has_collectible:
            _amount, self.restored_income_levels = self._take_collectible()
        self._refresh_perks(announce=False)
        self.initial_achievements = self._detect_achievements()

    @property
    def starving(self) -> bool:
        return self.data.hunger == 0

    @property
    def has_collectible(self) -> bool:
        return self.data.pending_reward["coins"] > 0

    @property
    def exp_required(self) -> int:
        return self.data.affection_level * EXP_PER_LEVEL

    def snapshot(self) -> dict:
        return self.data.to_dict()

    def _remember_interaction(self, event: str, item_id: str = "") -> None:
        """Only model-accepted actions enter this bounded, local-only journal."""
        if event not in HISTORY_EVENTS or not valid_content_id(item_id, empty=True):
            raise ValueError("互动摘要事件无效")
        self.data.interaction_history = (self.data.interaction_history +
                                         [{"event": event, "item_id": item_id}])[-3:]

    def set_presentation_managed(self, enabled: bool) -> bool:
        """The live controller finishes accepted tricks after the physical view does.

        Standalone models retain timer-based completion for simulations and tests.
        This process flag never becomes player data or changes a cooldown.
        """
        if type(enabled) is not bool:
            return False
        self._presentation_managed = enabled
        return True

    @property
    def unlimited_coins(self) -> bool:
        return self._unlimited_coins

    def set_unlimited_coins(self, enabled: bool, *, authorized: bool = False) -> bool:
        """Enable free spending only for a controller explicitly in developer mode."""
        if type(enabled) is not bool or (enabled and authorized is not True):
            return False
        if self._unlimited_coins != enabled:
            self._unlimited_coins = enabled
            self.state_changed.emit(self.snapshot())
        return True

    def can_afford(self, cost: int) -> bool:
        # Reject malformed prices even while testing; no negative-price credits.
        return type(cost) is int and cost >= 0 and (self.unlimited_coins or self.data.coins >= cost)

    def spend_coins(self, cost: int) -> bool:
        """Apply one transaction's cost; callers publish their final state afterward."""
        if not self.can_afford(cost):
            return False
        if not self.unlimited_coins:
            self.data.coins -= cost
        return True

    def set_rules(self, rules: GameRules) -> None:
        self.rules = rules
        for key, interval in (("hunger_elapsed", rules.hunger_seconds),
                              ("coin_elapsed", rules.gift_seconds),
                              ("hungry_notice_elapsed", rules.hungry_notice_seconds)):
            self.data.timers[key] %= interval

    def dialogue(self, event: str) -> str:
        lines = self.catalog.dialogues.get(event, ["今天也一起玩吧。"])
        index = self._dialogue_cursors.get(event, 0)
        self._dialogue_cursors[event] = index + 1
        return lines[index % len(lines)]

    def _roll_day(self) -> bool:
        value = self._today().isoformat()
        if self.data.daily_stats["date"] == value:
            return False
        self.data.daily_stats.update(date=value, poke_attempts=0, poke_coin_drops=0)
        return True

    def _credit_coins(self, amount: int, *, audible: bool = True) -> None:
        self.data.coins += amount
        if amount > 0:
            self.gains_received.emit({"coins": amount})
            if audible:
                self.reward_sound_requested.emit()

    def set_muted(self, enabled: bool) -> None:
        if type(enabled) is bool and self.data.muted != enabled:
            self.data.muted = enabled
            self._publish(self.starving)

    def _add_exp(self, amount: int, *, audible: bool = True) -> list[int]:
        before = self._lifetime_exp()
        levels = []
        if self.data.affection_level >= self.MAX_LEVEL:
            return levels
        self.data.affection_exp += amount
        while self.data.affection_level < self.MAX_LEVEL and self.data.affection_exp >= self.exp_required:
            self.data.affection_exp -= self.exp_required
            self.data.affection_level += 1
            self._credit_coins(30, audible=audible)
            levels.append(self.data.affection_level)
        if self.data.affection_level == self.MAX_LEVEL:
            self.data.affection_exp = 0
        actual = self._lifetime_exp() - before
        if actual > 0:
            self.gains_received.emit({"exp": actual})
        return levels

    def _publish(self, previous_starving: bool, levels: list[int] | None = None,
                 message: str = "", tone: str = "normal") -> None:
        self._refresh_perks()
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
        self._credit_coins(amount, audible=False)
        self.data.stats["total_gifts"] += 1
        self.data.pending_reward.update(coins=0, remaining_seconds=0.0)
        levels = self._add_exp(5, audible=False)
        self.collectible_changed.emit(False)
        return amount, levels

    def claim_collectible(self, automatic: bool = False) -> bool:
        if not self.has_collectible:
            return False
        previous = self.starving
        amount, levels = self._take_collectible()
        # Currency goes straight to the status panel, leaving the head bubble
        # available for dialogue. Level/achievement signals still run normally.
        self._publish(previous, levels)
        return True

    def poke(self) -> None:
        self.interaction_started.emit("poke")
        self._remember_interaction("poke")
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
        message = self.dialogue("poke")
        tone = "interaction"
        daily = self.data.daily_stats
        if daily["poke_attempts"] < 20:
            daily["poke_attempts"] += 1
            if self.rng.random() < 0.35:
                daily["poke_coin_drops"] += 1
                self._credit_coins(2)
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
            self.feedback.emit("这件商品暂时没有上架。", "normal")
            return False
        if feed_now and not self.can_use_item(item_id):
            self.feedback.emit("这件道具是TES专属，请先换上TES皮肤；没有扣币。", "normal")
            return False
        if not self.spend_coins(item["cost"]):
            self.feedback.emit("糯米币不够啦，戳戳或等一会儿拾币吧～", "hungry")
            return False
        previous = self.starving
        if feed_now:
            self._consume(item_id, item, previous)
        else:
            self.data.inventory[item_id] = self.data.inventory.get(item_id, 0) + 1
            self._publish(previous, message=f"已购买 {item['name']}，放进背包啦")
        return True

    def use_item(self, item_id: str) -> bool:
        item = self.item(item_id)
        if item is None or self.data.inventory.get(item_id, 0) <= 0:
            self.feedback.emit("背包里还没有这件物品。", "normal")
            return False
        if not self.can_use_item(item_id):
            self.feedback.emit("请先换上TES皮肤再开演，道具仍在背包里。", "normal")
            return False
        previous = self.starving
        self.data.inventory[item_id] -= 1
        self._consume(item_id, item, previous)
        return True

    def can_use_item(self, item_id: str) -> bool:
        item = self.catalog.items.get(item_id)
        if item is None:
            return False
        required = item.get("required_skin")
        return not required or (self.data.selected_skin_id == required and self.can_use_skin(required))

    def feed_sugar(self) -> bool:
        return self.buy_item("sugar", feed_now=True)

    def _consume(self, item_id: str, item: dict, previous: bool) -> None:
        self.interaction_started.emit(item["category"])
        self._remember_interaction("gift" if item["category"] == "gift" else "feed", item_id)
        if item["category"] == "gift":
            self.data.stats["total_presents"] += 1
            before_exp = self._lifetime_exp()
            levels = self._add_exp(item["exp"])
            actual_exp = self._lifetime_exp() - before_exp
            message = self.dialogue(item.get("dialogue", "gift"))
            if item_id in {"gnar_workbook", "practice_hourglass"} and item_id not in self.data.practice_experiences:
                self.data.practice_experiences.append(item_id)
            titles = self._unlock_practice_titles(item_id)
            feedback = message + (" 新称号：" + "、".join(titles) if titles else "")
            self._publish(previous, levels, feedback, "achievement" if titles else "interaction")
            self.gifted.emit()
            self.presentation_requested.emit({"item_id": item_id, "category": "gift",
                "effect": item.get("room_effect", item_id),
                "duration": item.get("performance_seconds", 10.0), "hunger_gain": 0, "exp_gain": actual_exp,
                "dialogue": message})
            return
        before_hunger = self.data.hunger
        was_full = self.data.hunger >= 100
        self.data.hunger = min(100.0, self.data.hunger + item["hunger"])
        gain = self.data.hunger - before_hunger
        if gain > 0:
            self.gains_received.emit({"hunger": gain})
        self.data.stats["total_feeds"] += 1
        if previous and not self.starving:
            self.data.stats["starvation_recoveries"] += 1
            self.data.timers["hungry_notice_elapsed"] = 0.0
        if item_id == "iced_cola" and self.data.active_buff.get("item_id") == "chili":
            self.data.active_buff = {}
            self.buff_changed.emit({})
        if "buff" in item:
            self.data.active_buff = {"item_id": item_id, "remaining_seconds": self.rules.buff_seconds,
                                     "behavior_remaining": item["buff"].get("behavior_seconds", 0)}
            if item_id not in self.data.flavors_seen:
                self.data.flavors_seen.append(item_id)
            self.buff_changed.emit(self.buff_view())
        event = "feed_full" if was_full else "feed_recover" if previous and not self.starving else "feed"
        self._publish(previous, message=self.dialogue(item.get("dialogue", event) if event == "feed" else event), tone="interaction")
        self.food_consumed.emit(item_id)
        self.fed.emit()
        self.presentation_requested.emit({"item_id": item_id, "category": "food",
            "hunger_gain": self.data.hunger - before_hunger, "exp_gain": 0})

    def _unlock_practice_titles(self, item_id: str = "") -> list[str]:
        """Accepted actions award collection titles once; animation never settles data."""
        unlocked = []
        if PRACTICE_EXPERIENCES.issubset(self.data.practice_experiences):
            unlocked.append("这次真练好了")
        if item_id == "summit_pickaxe" and self.data.equipped_furniture.get("wall") == "summit_wall":
            unlocked.append("登峰造圆")
        granted = [title for title in unlocked if title not in self.data.titles]
        self.data.titles.extend(granted)
        return granted

    def record_furniture_interaction(self, furniture_id: str) -> bool:
        """A real click on the installed dummy records experience, without rewards.

        Repeated valid clicks are accepted no-ops.  A development preview or a
        hidden/uninstalled prop has no authority to add a practice experience.
        """
        if (furniture_id != "training_dummy"
                or self.data.equipped_furniture.get("corner") != furniture_id):
            return False
        if furniture_id in self.data.practice_experiences:
            return True
        self.data.practice_experiences.append(furniture_id)
        titles = self._unlock_practice_titles()
        self._publish(self.starving, message="获得称号：" + "、".join(titles) if titles else "",
                      tone="achievement" if titles else "normal")
        return True

    def _lifetime_exp(self) -> int:
        level = self.data.affection_level
        return 500 * (level - 1) * level // 2 + self.data.affection_exp

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
        self._credit_coins(achievement["coins"])
        title = achievement.get("title")
        if title and title not in self.data.titles:
            self.data.titles.append(title)
        self._publish(self.starving, message=f" 已领取《{achievement['name']}》奖励：{achievement['coins']} 币" + (f"，称号【{title}】" if title else ""), tone="reward")
        return True

    def rename_pet(self, name: str) -> bool:
        if not isinstance(name, str) or any(unicodedata.category(char) in ("Cc", "Cs") for char in name):
            return False
        name = name.strip()
        if not _valid_pet_name(name):
            self.feedback.emit("名字请填写 1～40 个字符，不包含换行或控制字符。", "normal")
            return False
        if name == self.data.name:
            return True
        self.data.name = name
        self._publish(self.starving, message=f"以后就叫我{name}啦！", tone="interaction")
        return True

    def set_overlay_visible(self, visible: bool) -> bool:
        if type(visible) is not bool:
            return False
        if self.data.overlay_visible != visible:
            self.data.overlay_visible = visible
            self._publish(self.starving)
        return True

    def set_lamp_on(self, enabled: bool) -> bool:
        if type(enabled) is not bool:
            return False
        if self.data.lamp_on != enabled:
            self.data.lamp_on = enabled
            self._publish(self.starving)
        return True

    def buy_furniture(self, furniture_id: str) -> bool:
        product = self.catalog.furniture.get(furniture_id) if isinstance(furniture_id, str) else None
        if product is None:
            self.feedback.emit("这件家具还没有上架。", "normal")
            return False
        if furniture_id in self.data.owned_furniture:
            self.feedback.emit("这件家具已经在小窝里啦，无需重复购买。", "normal")
            return False
        if product.get("unlock_perk"):
            self.feedback.emit("这件家具是好感等级专属奖励。", "normal")
            return False
        if not self.spend_coins(product["price"]):
            self.feedback.emit("糯米币还差一点，先攒一攒再布置吧～", "normal")
            return False
        self.data.owned_furniture.append(furniture_id)
        if product["price"] > 0:
            self.data.stats["furniture_purchases"] += 1
        self._publish(self.starving, message=f"已买下{product['name']}，去家具装修布置吧！")
        return True

    def equip_furniture(self, slot: str, furniture_id: str) -> bool:
        if slot not in FURNITURE_SLOTS or not isinstance(furniture_id, str):
            return False
        if not furniture_id:
            if slot not in ("wall", "corner", "window", "companion"):
                return False
        else:
            product = self.catalog.furniture.get(furniture_id)
            if product is None or product["slot"] != slot or furniture_id not in self.data.owned_furniture:
                return False
        if self.data.equipped_furniture[slot] == furniture_id:
            return True
        self.data.equipped_furniture[slot] = furniture_id
        if furniture_id and product["price"] > 0 and furniture_id not in self.data.placed_furniture:
            self.data.placed_furniture.append(furniture_id)
            self.data.stats["furniture_placements"] += 1
        self._publish(self.starving)
        return True

    def equip_title(self, title: str) -> bool:
        if title not in self.data.titles:
            return False
        self.data.equipped_title = title
        self._publish(self.starving)
        return True

    def has_perk(self, perk_id: str) -> bool:
        perk = self.catalog.perks.get(perk_id)
        return bool(perk and (self.debug_unlock_all or (not perk.get("store_only") and self.data.affection_level >= perk["level"])
                              or (perk.get("kind") == "team_skin" and perk.get("item") in self.data.owned_team_skins)
                              or (perk.get("kind") == "accessory" and perk.get("item") in self.data.purchased_accessories)
                              or (perk_id == "custom_import" and self.data.custom_import_unlocked)))

    def perk_status(self) -> list[dict]:
        return [dict(deepcopy(row), unlocked=all(self.has_perk(p) for p in row["perks"]))
                for row in self.catalog.milestones]

    def _refresh_perks(self, announce: bool = True) -> None:
        available = {key for key, perk in self.catalog.perks.items() if not perk.get("retired") and self.has_perk(key)}
        newly = available - self._known_perks
        self._known_perks = available
        for key in available:
            perk = self.catalog.perks[key]
            if perk.get("kind") == "title" and perk["title"] not in self.data.titles:
                self.data.titles.append(perk["title"])
            if perk.get("kind") == "furniture" and perk["item"] not in self.data.owned_furniture:
                self.data.owned_furniture.append(perk["item"])
            # Debug trial must not permanently grant the collection.
            if (perk.get("kind") == "team_skin" and self.data.affection_level >= perk["level"]
                    and perk["item"] not in self.data.owned_team_skins):
                self.data.owned_team_skins.append(perk["item"])
        if newly and announce:
            self.perks_unlocked.emit([self.catalog.perks[key]["name"] for key in self.catalog.perks if key in newly])

    def set_debug_unlock(self, enabled: bool, *, authorized: bool = False) -> bool:
        # Only the controller started with --dev-mode authorizes this runtime override.
        if not authorized or type(enabled) is not bool:
            return False
        self.debug_unlock_all = enabled
        if (not enabled and self.data.selected_skin_id in TEAM_SKIN_IDS
                and not self.has_team_skin(self.data.selected_skin_id)):
            self.data.selected_skin_id = "default"
            self.data.accessories["offset_y"] = self.skin_config()["accessory_offset_y"]
        self._publish(self.starving, message=" 全部特权试用已" + ("开启" if enabled else "关闭"))
        self.appearance_changed.emit(self.effective_accessories())
        return True

    def unlock_custom_import(self) -> bool:
        if self.has_perk("custom_import"):
            return True
        if not self.spend_coins(50):
            self.feedback.emit("提前打开衣橱需要 50 糯米币，Lv.3 可免费开启。", "hungry")
            return False
        self.data.custom_import_unlocked = True
        self._publish(self.starving, message=" 衣橱已提前开启，试试导入自己的小伙伴吧！")
        return True

    def effective_accessories(self) -> dict:
        result = deepcopy(self.data.accessories)
        for slot in ACCESSORY_SLOTS:
            value = result.get(slot, "")
            definition = self.catalog.accessory_definitions.get(value)
            if value and (definition is None or definition.slot != slot or not self.has_perk(definition.perk_id)):
                result[slot] = ""
        return result

    def equip_accessory(self, slot: str, item: str) -> bool:
        choices = self.catalog.accessory_choices
        if slot not in choices or item not in choices[slot]:
            return False
        definition = self.catalog.accessory_definitions.get(item)
        perk_id = definition.perk_id if definition else ""
        if (item and (not definition.newly_selectable or self.catalog.perks.get(perk_id, {}).get("retired"))
                and self.data.accessories.get(slot) != item):
            self.feedback.emit("这件旧装扮已下架，已穿戴的收藏仍会保留。", "normal")
            return False
        if item and not self.has_perk(perk_id):
            self.feedback.emit("再陪伴一阵子，就能解锁这个装扮啦～", "normal")
            return False
        if self.data.accessories.get(slot, "") == item:
            return True
        self.data.accessories[slot] = item
        if item:
            self.data.stats["customizations"] += 1
        self._publish(self.starving)
        self.appearance_changed.emit(self.effective_accessories())
        return True

    def buy_accessory(self, accessory_id: str) -> bool:
        product = self.catalog.accessory_products.get(accessory_id)
        if product is None:
            return False
        definition = self.catalog.accessory_definitions[accessory_id]
        if self.has_perk(definition.perk_id):
            return True
        if not self.spend_coins(product["cost"]):
            self.feedback.emit("糯米币还不够，攒一攒再来吧。", "normal")
            return False
        self.data.purchased_accessories.append(accessory_id)
        self._publish(self.starving, message=f"已收藏{product['name']}，到背包的挂件页穿戴吧。", tone="reward")
        return True

    def set_air_conditioner_on(self, enabled: bool) -> bool:
        if type(enabled) is not bool or self.data.equipped_furniture.get("wall") != "air_conditioner":
            return False
        self.data.air_conditioner_on = enabled
        self._publish(self.starving, message="空调已就位，这波降降温。" if enabled else "空调先歇会儿，别急着红温。", tone="interaction")
        return True

    def set_accessory_offset(self, offset_y: int) -> bool:
        if type(offset_y) is not int or not -30 <= offset_y <= 30:
            return False
        self.skin_config()["accessory_offset_y"] = offset_y
        self.data.accessories["offset_y"] = offset_y
        self._publish(self.starving)
        self.appearance_changed.emit(self.effective_accessories())
        return True

    def skin_config(self) -> dict:
        return self.data.skin_configs.setdefault(self.data.selected_skin_id,
            {"scale_multiplier": 1.0, "accessory_offset_y": 0})

    def set_skin_scale(self, scale: float) -> bool:
        try:
            value = _number(scale, "角色大小", .6, 1.5)
        except ValueError:
            return False
        self.skin_config()["scale_multiplier"] = value
        self._publish(self.starving)
        self.appearance_changed.emit(self.effective_accessories())
        return True

    def archive_skin(self, skin_id: str, archived: bool = True) -> bool:
        if not isinstance(skin_id, str) or not re.fullmatch(r"user_[0-9a-f]{32}", skin_id) or type(archived) is not bool:
            return False
        if archived and skin_id not in self.data.archived_skins:
            if self.data.selected_skin_id == skin_id:
                self.select_skin("default")
            self.data.archived_skins.append(skin_id)
        elif not archived and skin_id in self.data.archived_skins:
            self.data.archived_skins.remove(skin_id)
        self._publish(self.starving)
        return True

    def next_milestone(self) -> dict:
        row = next((m for m in self.catalog.milestones if m["level"] > self.data.affection_level), None)
        if row is None:
            return {"text": "满级传说已达成，今天也一起陪伴。", "remaining_exp": 0}
        remaining = EXP_PER_LEVEL * row["level"] * (row["level"] - 1) // 2 - self._lifetime_exp()
        return {**deepcopy(row), "remaining_exp": remaining,
            "text": f"距离下一阶段奖励（Lv.{row['level']}：{row['label']}）还差 {remaining} 点好感"}

    def replace_data(self, data: PetData) -> None:
        previous = self.starving
        replacement = PetData.from_dict(data.to_dict())
        active = self._active_trick_id
        self.data = replacement
        self._poke_times.clear()
        self.trick_busy = 0.0
        self._active_trick_id = ""
        self.trick_cooldowns = dict.fromkeys(self.trick_cooldowns, 0.0)
        if active:
            self.trick_lifecycle.emit({"phase": "interrupted", "trick_id": active, "reason": "restore"})
        self._known_perks.clear()
        self._refresh_perks(announce=False)
        self._publish(previous)
        self.buff_changed.emit(self.buff_view())
        self.appearance_changed.emit(self.effective_accessories())

    def has_team_skin(self, skin_id: str) -> bool:
        return skin_id in self.catalog.team_skins and (skin_id in self.data.owned_team_skins or self.debug_unlock_all)

    def can_use_skin(self, skin_id: str) -> bool:
        if not valid_skin_id(skin_id) or skin_id in self.data.archived_skins:
            return False
        if skin_id in TEAM_SKIN_IDS:
            return self.has_team_skin(skin_id)
        return skin_id == "default" or self.has_perk("custom_import")

    def buy_team_skin(self, skin_id: str) -> bool:
        product = self.catalog.team_skins.get(skin_id) if isinstance(skin_id, str) else None
        if product is None:
            return False
        if skin_id in self.data.owned_team_skins:
            return True
        if not self.spend_coins(product["cost"]):
            self.feedback.emit("糯米币还不够，达到对应等级也能免费获得这款皮肤。", "normal")
            return False
        self.data.owned_team_skins.append(skin_id)
        self._publish(self.starving, message=f"已获得{product['name']}，可以在衣橱换上。", tone="reward")
        return True

    def select_skin(self, skin_id: str, *, imported: bool = False) -> bool:
        if not self.can_use_skin(skin_id):
            return False
        changed = skin_id != self.data.selected_skin_id
        self.data.selected_skin_id = skin_id
        self.data.accessories["offset_y"] = self.skin_config()["accessory_offset_y"]
        if skin_id != "default" and (changed or imported):
            self.data.stats["customizations"] += 1
        message = (self.dialogue("team_history") if skin_id in TEAM_SKIN_IDS
                   else "已换上新外观，挂件和小特技也能一起用哦～") if changed else ""
        self._publish(self.starving, message=message, tone="interaction" if skin_id in TEAM_SKIN_IDS else "normal")
        return True

    def has_trick(self, trick_id: str) -> bool:
        definition = self.catalog.trick_definitions.get(trick_id)
        if definition is None:
            return False
        if trick_id in self.catalog.trick_products:
            return trick_id in self.data.purchased_tricks
        return bool(definition.perk_id and self.has_perk(definition.perk_id))

    def trick_name(self, trick_id: str) -> str:
        product = self.catalog.trick_products.get(trick_id)
        if product:
            return str(product["name"])
        definition = self.catalog.trick_definitions.get(trick_id)
        return self.catalog.perks.get(definition.perk_id, {}).get("name", definition.name) if definition else trick_id

    def buy_trick(self, trick_id: str) -> bool:
        product = self.catalog.trick_products.get(trick_id)
        if product is None or trick_id not in self.trick_cooldowns:
            self.feedback.emit("这项特技暂未上架。", "normal")
            return False
        if trick_id in self.data.purchased_tricks:
            self.feedback.emit("这项特技已经永久解锁啦，无需重复购买。", "normal")
            return False
        if not self.spend_coins(product["cost"]):
            self.feedback.emit("糯米币不够啦，再攒一点就能学会这个特技～", "normal")
            return False
        self.data.purchased_tricks.append(trick_id)
        self._publish(self.starving, message=f" 已永久学会【{product['name']}】，现在可以表演啦！", tone="reward")
        return True

    def finish_trick(self, trick_id: str, reason: str = "completed") -> bool:
        if (reason not in {"completed", "replaced", "input", "hidden", "skin_changed", "shutdown",
                           "restore", "starving", "cancelled"} or trick_id != self._active_trick_id or not trick_id):
            return False
        self.trick_busy = 0.0
        self._active_trick_id = ""
        self.trick_lifecycle.emit({"phase": "finished" if reason == "completed" else "interrupted",
                                   "trick_id": trick_id, "reason": reason})
        self._publish(self.starving)
        return True

    def can_perform_trick(self, trick_id: str, *, replacing: bool = False) -> bool:
        return (trick_id in self.trick_cooldowns and self.has_trick(trick_id)
                and self.trick_cooldowns[trick_id] <= 0 and (self.trick_busy <= 0 or replacing is True) and not self.starving)

    def record_trick(self, trick_id: str) -> bool:
        if not self.can_perform_trick(trick_id):
            return False
        definition = self.catalog.trick_definitions[trick_id]
        self.trick_busy = definition.duration
        self._active_trick_id = trick_id
        self.trick_cooldowns[trick_id] = definition.cooldown
        self._remember_interaction("trick", trick_id)
        self.trick_lifecycle.emit({"phase": "started", "trick_id": trick_id, "reason": "accepted"})
        levels = self._add_exp(definition.exp) if definition.exp else []
        self._publish(self.starving, levels, self.dialogue("trick_" + trick_id), "interaction")
        return True

    def record_drop(self) -> None:
        self._remember_interaction("drop")
        self.data.stats["total_drops"] += 1
        self._publish(self.starving, message=self.dialogue("drop"), tone="interaction")

    def record_shake(self) -> None:
        self._remember_interaction("shake")
        self.data.stats["total_shakes"] += 1
        self._publish(self.starving)

    def pet_head(self) -> bool:
        remaining = self.data.timers["pet_cooldown_remaining"]
        if remaining > 0:
            self.feedback.emit(f"刚摸过啦，再等 {math.ceil(remaining)} 秒～", "normal")
            return False
        self.data.timers["pet_cooldown_remaining"] = self.rules.pet_cooldown
        self.data.stats["total_pets"] += 1
        self.interaction_started.emit("pet")
        self._remember_interaction("pet")
        levels = self._add_exp(3)
        self._publish(self.starving, levels, self.dialogue("pet_head"), "interaction")
        return True

    def set_hunger(self, value: float) -> None:
        value = _number(value, "hunger", 0, 100)
        previous = self.starving
        self.data.hunger = value
        self.data.timers["hunger_elapsed"] = 0.0
        self.data.timers["hungry_notice_elapsed"] = 0.0
        text = self.dialogue("hungry") if value == 0 else f" 饥饿值恢复至 {value:g}"
        self._publish(previous, message=text, tone="hungry" if value == 0 else "normal")

    def offer_collectible(self) -> bool:
        """Credit one online reward now; retained name for older integrations."""
        if self.has_collectible:
            return self.claim_collectible(automatic=True)
        self.data.pending_reward.update(coins=self.rng.randint(10, 20), remaining_seconds=0.0)
        return self.claim_collectible(automatic=True)

    def advance(self, seconds: float) -> None:
        """Advance online time at event boundaries; no wall-clock/offline catch-up."""
        if not math.isfinite(seconds) or seconds <= 0:
            return
        previous = self.starving
        self.trick_busy = max(1e-9 if self._presentation_managed and self._active_trick_id else 0.0,
                              self.trick_busy - seconds)
        if not self._presentation_managed and self._active_trick_id and self.trick_busy == 0:
            self.finish_trick(self._active_trick_id)
        for trick_id in self.trick_cooldowns:
            self.trick_cooldowns[trick_id] = max(0.0, self.trick_cooldowns[trick_id] - seconds)
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
                    self.feedback.emit(self.dialogue("hungry"), "interaction")
            if self.has_collectible and self.data.pending_reward["remaining_seconds"] <= 1e-8:
                self.claim_collectible(automatic=True)
            if timers["coin_elapsed"] >= self.rules.gift_seconds - 1e-8:
                timers["coin_elapsed"] = 0.0
                self.offer_collectible()
            if self.starving and timers["hungry_notice_elapsed"] >= self.rules.hungry_notice_seconds - 1e-8:
                timers["hungry_notice_elapsed"] = 0.0
                self.feedback.emit(self.dialogue("hungry"), "interaction")
        self._publish(previous)
