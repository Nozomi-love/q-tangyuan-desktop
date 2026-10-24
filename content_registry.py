"""Explicit metadata for implemented content; a catalogue cannot invent a renderer.

New content is registered in code alongside its real handler.  The runtime catalogue
selects prices and progression, while this immutable registry owns technical IDs,
slots, icons and trick timings.  Draft designs never enter this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Iterable


CONTENT_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
ACCESSORY_SLOTS = ("head", "face", "back", "effect")
HISTORY_EVENTS = frozenset(("poke", "pet", "feed", "gift", "trick", "drop", "shake"))
FURNITURE_SLOTS = ("theme", "rug", "wall", "corner", "bowl", "window", "companion")
BUILTIN_ITEM_IDS = frozenset((
    "water", "sugar", "osmanthus", "sesame", "strawberry", "matcha", "chili", "paper_star",
    "flower_bouquet", "music_box", "spinning_top", "egg", "gragas_barrel", "tes_guitar",
    "tes_microphone", "form_dice", "kiting_rope", "summit_pickaxe", "drama_clapper",
    "iced_cola", "early_champagne", "summit_lunch", "watchparty_popcorn",
    "gnar_workbook", "practice_hourglass", "fist_bump_glove", "postmatch_noodles", "late_practice_snack",
))
BUILTIN_FURNITURE_SLOTS = MappingProxyType({
    "esports_chair": "corner", "training_dummy": "corner", "tactics_screen": "wall",
    "postmatch_studio": "theme", "air_conditioner": "wall", "cheese_room": "theme",
    "sakura_room": "theme", "matcha_room": "theme", "cloud_cushion": "rug",
    "lotus_cushion": "rug", "cat_paw_rug": "rug", "sunflower_painting": "wall",
    "rice_clock": "wall", "ficus_plant": "corner", "warm_lamp": "corner",
    "wood_bowl": "bowl", "porcelain_bowl": "bowl", "sunny_chime": "window",
    "camp_room": "theme", "sesame_friend": "companion", "royal_rug": "rug",
    "practice_room": "theme", "summit_wall": "wall",
})


def valid_content_id(value: object, *, empty: bool = False) -> bool:
    return isinstance(value, str) and ((empty and value == "") or CONTENT_ID_PATTERN.fullmatch(value) is not None)


def _id(value: str, label: str) -> None:
    if not valid_content_id(value):
        raise ValueError(f"{label} 必须为安全的内容 ID")


@dataclass(frozen=True)
class TrickDefinition:
    id: str
    name: str
    icon: str
    duration: float
    cooldown: float
    perk_id: str = ""
    exp: int = 0

    def __post_init__(self) -> None:
        _id(self.id, "特技 ID")
        _id(self.icon, "特技图标")
        if not isinstance(self.perk_id, str):
            raise ValueError("特技特权必须为字符串")
        if self.perk_id:
            _id(self.perk_id, "特技特权")
        if not isinstance(self.name, str) or not 1 <= len(self.name) <= 40:
            raise ValueError("特技名称需要1～40字")
        for value in (self.duration, self.cooldown):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not .1 <= value <= 120:
                raise ValueError("特技时长与冷却需要0.1～120秒")
        if self.cooldown < self.duration:
            raise ValueError("特技冷却不能短于演出时长")
        if type(self.exp) is not int or not 0 <= self.exp <= 5:
            raise ValueError("特技经验需要0～5整数；新商城特技须为0")


@dataclass(frozen=True)
class AccessoryDefinition:
    id: str
    slot: str
    icon: str
    perk_id: str
    name: str = ""
    newly_selectable: bool = True

    def __post_init__(self) -> None:
        for value, label in ((self.id, "装扮 ID"), (self.icon, "装扮图标"), (self.perk_id, "装扮特权")):
            _id(value, label)
        if self.slot not in ACCESSORY_SLOTS:
            raise ValueError("装扮槽位无效")
        if not isinstance(self.name, str) or len(self.name) > 40 or type(self.newly_selectable) is not bool:
            raise ValueError("装扮名称或选择标记无效")


class ContentRegistry:
    """Immutable definitions shared by model, views and build allowlists."""

    def __init__(self, *, tricks: Iterable[TrickDefinition] = (),
                 accessories: Iterable[AccessoryDefinition] = (), item_ids: Iterable[str] = BUILTIN_ITEM_IDS,
                 furniture_slots: dict | None = None) -> None:
        trick_rows = tuple(tricks.values()) if hasattr(tricks, "values") else tuple(tricks)
        accessory_rows = tuple(accessories.values()) if hasattr(accessories, "values") else tuple(accessories)
        for rows, expected in ((trick_rows, TrickDefinition), (accessory_rows, AccessoryDefinition)):
            if any(not isinstance(row, expected) for row in rows):
                raise ValueError("注册表只接收已校验的内容定义")
            if len({row.id for row in rows}) != len(rows):
                raise ValueError("注册表包含重复内容 ID")
        if {row.id for row in trick_rows} & {row.id for row in accessory_rows}:
            raise ValueError("特技和装扮 ID 不能重名")
        if len({row.perk_id for row in accessory_rows}) != len(accessory_rows):
            raise ValueError("装扮特权不能重复引用")
        trick_perks = [row.perk_id for row in trick_rows if row.perk_id]
        if len(set(trick_perks)) != len(trick_perks) or set(trick_perks) & {row.perk_id for row in accessory_rows}:
            raise ValueError("特技特权不能重复引用")
        item_rows = tuple(item_ids)
        furniture_rows = dict(BUILTIN_FURNITURE_SLOTS if furniture_slots is None else furniture_slots)
        if any(not valid_content_id(value) for value in item_rows) or len(set(item_rows)) != len(item_rows):
            raise ValueError("已实现消费品 ID 重复或无效")
        if any(not valid_content_id(key) or value not in FURNITURE_SLOTS for key, value in furniture_rows.items()):
            raise ValueError("已实现家具 ID 或槽位无效")
        used = set()
        for group in ({row.id for row in trick_rows}, {row.id for row in accessory_rows}, set(item_rows), set(furniture_rows)):
            if group & used:
                raise ValueError("不同注册类型不能使用重复内容 ID")
            used.update(group)
        self.tricks = MappingProxyType({row.id: row for row in trick_rows})
        self.accessories = MappingProxyType({row.id: row for row in accessory_rows})
        self.accessory_choices = MappingProxyType({slot: ("", *(row.id for row in accessory_rows if row.slot == slot))
                                                   for slot in ACCESSORY_SLOTS})
        self.icon_ids = frozenset(row.icon for row in (*trick_rows, *accessory_rows))
        self.item_ids = frozenset(item_rows)
        self.furniture_slots = MappingProxyType(furniture_rows)

    def with_tricks(self, *rows: TrickDefinition) -> ContentRegistry:
        return ContentRegistry(tricks=(*self.tricks.values(), *rows), accessories=self.accessories.values(),
                               item_ids=self.item_ids, furniture_slots=self.furniture_slots)

    def with_accessories(self, *rows: AccessoryDefinition) -> ContentRegistry:
        return ContentRegistry(tricks=self.tricks.values(), accessories=(*self.accessories.values(), *rows),
                               item_ids=self.item_ids, furniture_slots=self.furniture_slots)

    def with_items(self, *item_ids: str) -> ContentRegistry:
        return ContentRegistry(tricks=self.tricks.values(), accessories=self.accessories.values(),
                               item_ids=(*self.item_ids, *item_ids), furniture_slots=self.furniture_slots)

    def with_furniture(self, furniture_id: str, slot: str) -> ContentRegistry:
        if furniture_id in self.furniture_slots:
            raise ValueError("家具注册 ID 已存在")
        return ContentRegistry(tricks=self.tricks.values(), accessories=self.accessories.values(),
                               item_ids=self.item_ids, furniture_slots={**self.furniture_slots, furniture_id: slot})


BUILTIN_TRICKS = MappingProxyType({row.id: row for row in (
    TrickDefinition("flip", "原地空翻", "flip", 1.1, 5.0, "trick_flip", 5),
    TrickDefinition("clone", "Q弹影分身", "clone", 2.5, 5.0, "trick_clone"),
    TrickDefinition("ball", "芝麻弹力球", "ball", 5.0, 5.0, "trick_ball"),
    TrickDefinition("screen_roll", "绕屏滚一圈", "screen_roll", 12.0, 20.0),
    TrickDefinition("disco", "迪斯科蹦迪", "disco", 6.0, 6.0, "trick_disco"),
    TrickDefinition("reverse_flash", "反向闪现", "reverse_flash", 2.6, 12.0),
)})

BUILTIN_ACCESSORIES = MappingProxyType({row.id: row for row in (
    AccessoryDefinition("sprout", "head", "sprout", "accessory_sprout", "呆毛嫩芽", False),
    AccessoryDefinition("crown", "head", "crown", "accessory_crown", "迷你金皇冠"),
    AccessoryDefinition("bow", "head", "bow", "accessory_bow", "樱粉蝴蝶结", False),
    AccessoryDefinition("orange", "head", "cleanse_orange", "accessory_orange", "解控橘子帽"),
    AccessoryDefinition("cooling_cap", "head", "cooling_cap", "accessory_cooling_cap", "红温散热帽"),
    AccessoryDefinition("demon_hood", "head", "demon_hood", "accessory_demon_hood", "大魔王兜帽"),
    AccessoryDefinition("mini_gnar_hat", "head", "mini_gnar_hat", "accessory_mini_gnar_hat", "小纳尔耳帽"),
    AccessoryDefinition("sunglasses", "face", "sunglasses", "accessory_sunglasses", "酷盖墨镜"),
    AccessoryDefinition("seven_goggles", "face", "seven_goggles", "accessory_seven_goggles", "七号护目镜"),
    AccessoryDefinition("phoenix_wings", "back", "phoenix_wings", "accessory_phoenix_wings", "凤凰翅膀"),
    AccessoryDefinition("summit_backpack", "back", "summit_backpack", "accessory_summit_backpack", "登峰小背包"),
    AccessoryDefinition("kiting_scarf", "back", "kiting_scarf", "accessory_kiting_scarf", "拉扯围巾"),
    AccessoryDefinition("steam", "effect", "red_steam", "effect_steam", "红温热气"),
    AccessoryDefinition("fireflies", "effect", "fireflies", "effect_fireflies", "流光萤火虫", False),
    AccessoryDefinition("rainbow", "effect", "champion_spotlight", "effect_rainbow", "冠军聚光灯"),
)})

BUILTIN_REGISTRY = ContentRegistry(tricks=BUILTIN_TRICKS.values(), accessories=BUILTIN_ACCESSORIES.values())


def strict_json_object(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate JSON keys instead of silently using the last definition."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"JSON 包含重复键：{key}")
        result[key] = value
    return result
