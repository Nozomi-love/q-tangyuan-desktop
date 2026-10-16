"""Four-tab dashboard bound to the same PetModel as the desktop overlay."""
from __future__ import annotations

import math
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QProgressBar, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)
from models import PetModel


def label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setWordWrap(True)
    if role:
        widget.setObjectName(role)
    return widget


def card() -> tuple[QFrame, QVBoxLayout]:
    widget = QFrame()
    widget.setObjectName("card")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    return widget, layout


class DashboardWindow(QMainWindow):
    pin_requested = Signal(bool)
    dev_requested = Signal(bool)
    flat_requested = Signal(bool)
    reset_requested = Signal()
    hunger_zero_requested = Signal()
    hunger_full_requested = Signal()
    gift_requested = Signal()
    reload_requested = Signal()

    def __init__(self, model: PetModel) -> None:
        super().__init__()
        self.model = model
        self.setWindowTitle("Q弹汤圆 · 养成小屋")
        self.setObjectName("dashboard")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.resize(900, 760)
        self.setMinimumSize(700, 520)
        root = QWidget()
        root.setObjectName("dashboardRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        header = QHBoxLayout()
        words = QVBoxLayout()
        words.addWidget(label("🍡 汤圆的陪伴小屋", "hero"))
        words.addWidget(label("慢慢长大，每一次陪伴都算数", "muted"))
        header.addLayout(words, 1)
        self.balance = label("", "balance")
        self.balance.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.balance)
        layout.addLayout(header)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)
        self.inventory_widgets = {}
        self.shop_buttons = {}
        self.shop_details = {}
        self.achievement_widgets = {}
        self.tier_groups = {}
        self._build_status()
        self._build_shop()
        self._build_achievements()
        self._build_settings()
        self.notice = label("所有商品仅消耗游戏内糯米币 · 本地离线保存", "muted")
        layout.addWidget(self.notice)
        model.state_changed.connect(self._model_changed)
        model.feedback.connect(self._feedback)
        self.refresh()

    def _page(self, title: str) -> QVBoxLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("page")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 16, 10, 12)
        layout.setSpacing(14)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, title)
        return layout

    def _build_status(self) -> None:
        page = self._page("状态与背包")
        profile, profile_layout = card()
        top = QHBoxLayout()
        self.pet_name = label("", "sectionTitle")
        top.addWidget(self.pet_name, 1)
        self.title_combo = QComboBox()
        self.title_combo.setMinimumWidth(170)
        self.title_combo.currentTextChanged.connect(self.model.equip_title)
        top.addWidget(label("佩戴称号", "muted"))
        top.addWidget(self.title_combo)
        profile_layout.addLayout(top)
        self.level_label = label("")
        profile_layout.addWidget(self.level_label)
        self.exp_bar = QProgressBar()
        profile_layout.addWidget(self.exp_bar)
        self.hunger_bar = QProgressBar()
        self.hunger_bar.setObjectName("hungerBar")
        self.hunger_bar.setRange(0, 100)
        profile_layout.addWidget(self.hunger_bar)
        self.buff_label = label("", "buffBadge")
        profile_layout.addWidget(self.buff_label)
        self.stats_label = label("", "muted")
        profile_layout.addWidget(self.stats_label)
        page.addWidget(profile)
        page.addWidget(label("我的背包", "sectionTitle"))
        self.empty_inventory = label("背包还是空的，去免费商城挑一份甜甜的食物吧～", "muted")
        page.addWidget(self.empty_inventory)
        for item_id, item in self.model.catalog.items.items():
            row, content = card()
            line = QHBoxLayout()
            text = label("")
            line.addWidget(text, 1)
            button = QPushButton("投喂 / 使用")
            button.clicked.connect(lambda checked=False, key=item_id: self.model.use_item(key))
            line.addWidget(button)
            content.addLayout(line)
            page.addWidget(row)
            self.inventory_widgets[item_id] = (row, text, button)
        self.unknown_inventory = label("", "muted")
        page.addWidget(self.unknown_inventory)
        page.addStretch()

    def _build_shop(self) -> None:
        page = self._page("免费商城")
        page.addWidget(label("一口甜甜，换一整天好心情", "sectionTitle"))
        page.addWidget(label("购买会放进背包；购买并投喂会立即使用。风味之间互相替换，同种风味刷新倒计时。", "muted"))
        grid = QGridLayout()
        grid.setSpacing(14)
        for index, (item_id, item) in enumerate(self.model.catalog.items.items()):
            panel, content = card()
            content.addWidget(label(f"{item['icon']} {item['name']}", "sectionTitle"))
            details = label("")
            self.shop_details[item_id] = details
            content.addWidget(details)
            buff = item.get("buff")
            description = f"【{buff['name']}】{buff['description']}" if buff else "温柔补充能量，没有额外风味效果。"
            description_label = label(description, "muted")
            description_label.setMinimumHeight(58)
            content.addWidget(description_label, 1)
            time_label = label("", "muted")
            content.addWidget(time_label)
            actions = QHBoxLayout()
            buy = QPushButton("购买")
            feed = QPushButton("购买并投喂")
            feed.setProperty("primary", True)
            buy.clicked.connect(lambda checked=False, key=item_id: self.model.buy_item(key))
            feed.clicked.connect(lambda checked=False, key=item_id: self.model.buy_item(key, feed_now=True))
            actions.addWidget(buy)
            actions.addWidget(feed)
            content.addLayout(actions)
            grid.addWidget(panel, index // 2, index % 2)
            self.shop_buttons[item_id] = (buy, feed, time_label)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        page.addLayout(grid)
        page.addStretch()

    def _build_achievements(self) -> None:
        page = self._page("成就图鉴")
        header = QHBoxLayout()
        self.achievement_summary = label("", "sectionTitle")
        header.addWidget(self.achievement_summary, 1)
        self.tier_filter = QComboBox()
        self.tier_filter.addItems(["全部成就", "一阶 · 初识汤圆", "二阶 · 渐入佳境", "三阶 · 隐藏彩蛋"])
        self.tier_filter.currentIndexChanged.connect(self._filter_tiers)
        header.addWidget(self.tier_filter)
        page.addLayout(header)
        for tier, title in enumerate(("一阶 · 初识汤圆", "二阶 · 渐入佳境", "三阶 · 隐藏彩蛋"), 1):
            group = QGroupBox(title)
            content = QVBoxLayout(group)
            content.setSpacing(12)
            self.tier_groups[tier] = group
            for achievement in self.model.catalog.achievements:
                if achievement["tier"] != tier:
                    continue
                aid = achievement["id"]
                panel, body = card()
                body.addWidget(label(f"🏆 《{achievement['name']}》", "sectionTitle"))
                body.addWidget(label(achievement.get("description", ""), "muted"))
                title_reward = f" + 称号【{achievement['title']}】" if achievement.get("title") else ""
                body.addWidget(label(f"奖励：{achievement['coins']} 糯米币{title_reward}", "muted"))
                bar = QProgressBar()
                bar.setRange(0, achievement["target"])
                body.addWidget(bar)
                line = QHBoxLayout()
                status = label("")
                line.addWidget(status, 1)
                claim = QPushButton("")
                claim.setProperty("primary", True)
                claim.clicked.connect(lambda checked=False, key=aid: self.model.claim_achievement(key))
                line.addWidget(claim)
                equip = QPushButton("佩戴称号")
                equip.clicked.connect(lambda checked=False, title=achievement.get("title", ""): self.model.equip_title(title))
                line.addWidget(equip)
                body.addLayout(line)
                content.addWidget(panel)
                self.achievement_widgets[aid] = (bar, status, claim, equip)
            page.addWidget(group)
        page.addStretch()

    def _filter_tiers(self, index: int) -> None:
        for tier, group in self.tier_groups.items():
            group.setVisible(index == 0 or index == tier)

    def _build_settings(self) -> None:
        page = self._page("装扮与设置")
        settings, content = card()
        content.addWidget(label("桌面陪伴设置", "sectionTitle"))
        self.pin_check = QCheckBox("固定当前位置（仍可拖动调整）")
        self.dev_check = QCheckBox("开发测试加速（饥饿 / 礼包加速；新风味 15 秒）")
        self.flat_check = QCheckBox("手动测试饿扁（不改变真实饥饿）")
        self.pin_check.toggled.connect(self.pin_requested.emit)
        self.dev_check.toggled.connect(self.dev_requested.emit)
        self.flat_check.toggled.connect(self.flat_requested.emit)
        for widget in (self.pin_check, self.dev_check, self.flat_check):
            content.addWidget(widget)
        for title, signal in (("重置回主屏幕右下角", self.reset_requested),
                              ("调试：饥饿归零", self.hunger_zero_requested),
                              ("调试：恢复满饥饿", self.hunger_full_requested),
                              ("调试：立即生成拾币气泡", self.gift_requested),
                              ("重新加载默认表情 PNG", self.reload_requested)):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, output=signal: output.emit())
            content.addWidget(button)
        page.addWidget(settings)
        for title, description in (
            ("✨ 好感等级特权预览", "Phase 4 开放等级动作与特权。当前好感等级持续累计，后续可沿用现有进度。"),
            ("👑 独立挂件穿戴", "Phase 4 开放皇冠、爱心与粒子挂件；饰品将使用独立图层，兼容自定义外观。"),
            ("🎨 本地自定义皮肤", "当前使用默认四表情汤圆。Phase 4 在此接入本地 PNG / GIF 和 manifest 动作包。"),
        ):
            section, body = card()
            body.addWidget(label(title, "sectionTitle"))
            body.addWidget(label(description, "muted"))
            page.addWidget(section)
        page.addStretch()

    def set_settings(self, pinned: bool, accelerated: bool, flat: bool) -> None:
        for checkbox, value in ((self.pin_check, pinned), (self.dev_check, accelerated), (self.flat_check, flat)):
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(False)

    def _model_changed(self, _state: dict) -> None:
        if self.isVisible():
            self.refresh()

    def refresh(self, _state: dict | None = None) -> None:
        data = self.model.data
        self.balance.setText(f"🪙 {data.coins} 糯米币")
        self.pet_name.setText(f"{data.name}  ·  {data.equipped_title}")
        current = [self.title_combo.itemText(i) for i in range(self.title_combo.count())]
        self.title_combo.blockSignals(True)
        if current != data.titles:
            self.title_combo.clear()
            self.title_combo.addItems(data.titles)
        self.title_combo.setCurrentText(data.equipped_title)
        self.title_combo.blockSignals(False)
        required = self.model.exp_required
        self.level_label.setText(f"好感 Lv.{data.affection_level} / 30" + (" · 已满级" if data.affection_level == 30 else f" · {data.affection_exp}/{required} EXP"))
        self.exp_bar.setRange(0, required)
        self.exp_bar.setValue(required if data.affection_level == 30 else data.affection_exp)
        self.exp_bar.setFormat("满级 · 陪伴仍在继续" if data.affection_level == 30 else f"好感经验 {data.affection_exp} / {required}")
        self.hunger_bar.setValue(round(data.hunger))
        self.hunger_bar.setFormat(f"饥饿 {data.hunger:g} / 100" + (" · 饿扁啦，喂一口就恢复" if self.model.starving else ""))
        buff = self.model.buff_view()
        self.buff_label.setText(f"{buff['name']} · 剩余 {math.ceil(buff['remaining_seconds'])} 秒" + (f" · 狂奔 / 跺脚 {math.ceil(buff['behavior_remaining'])} 秒" if buff.get("behavior_remaining") else "") if buff else "原味白汤圆 · 当前没有风味 Buff")
        stats = data.stats
        self.stats_label.setText(f"累计戳戳 {stats['total_clicks']} 次  ·  投喂 {stats['total_feeds']} 次  ·  挂机收礼 {stats['total_gifts']} 次\n在线陪伴 {int(stats['total_idle_seconds'] // 60)} 分钟  ·  摸头 {stats['total_pets']} 次  ·  高空落地 {stats['total_drops']} 次")
        owned = False
        for item_id, (row, text, button) in self.inventory_widgets.items():
            item, count = self.model.item(item_id), data.inventory.get(item_id, 0)
            row.setVisible(count > 0)
            button.setEnabled(count > 0)
            text.setText(f"{item['icon']} {item['name']} × {count}\n饥饿 +{item['hunger']:g} · 好感 +{item['exp']}")
            owned = owned or count > 0
        self.empty_inventory.setVisible(not owned)
        unknown = [f"{key} ×{count}" for key, count in data.inventory.items() if key not in self.model.catalog.items and count > 0]
        self.unknown_inventory.setText("保留的扩展物品：" + "、".join(unknown) if unknown else "")
        self.unknown_inventory.setVisible(bool(unknown))
        for item_id, (buy, feed, text) in self.shop_buttons.items():
            item = self.model.item(item_id)
            self.shop_details[item_id].setText(f"{item['cost']} 糯米币   ·   饥饿 +{item['hunger']:g}   ·   好感 +{item['exp']}")
            buy.setEnabled(data.coins >= item["cost"])
            feed.setEnabled(data.coins >= item["cost"])
            text.setText(f"风味持续 {self.model.rules.buff_seconds:g} 秒" if "buff" in item else "可随时投喂，饥饿最多恢复到 100")
        ready = set(data.unlocked_achievements) - set(data.claimed_achievements)
        self.achievement_summary.setText(f"成就 {len(data.unlocked_achievements)}/{len(self.model.catalog.achievements)} · 待领取 {len(ready)}")
        for achievement in self.model.catalog.achievements:
            aid = achievement["id"]
            bar, status, claim, equip = self.achievement_widgets[aid]
            value, target = self.model.achievement_progress(achievement), achievement["target"]
            bar.setValue(value)
            bar.setFormat(f"{value} / {target}")
            claimed = aid in data.claimed_achievements
            unlocked = aid in data.unlocked_achievements
            status.setText("✅ 已领取" if claimed else "🎉 已达成，记得领奖" if unlocked else "慢慢来，一起探索")
            claim.setText("✅ 已领取" if claimed else "🎁 领取奖励" if unlocked else "未达成")
            claim.setEnabled(unlocked and not claimed)
            title = achievement.get("title")
            equip.setVisible(bool(title) and claimed)
            equip.setEnabled(bool(title) and title in data.titles and title != data.equipped_title)
            if title and title == data.equipped_title:
                equip.setText("正在佩戴")
            else:
                equip.setText("佩戴称号")

    def _feedback(self, text: str, _tone: str) -> None:
        self.notice.setText(text)

    def summon(self) -> None:
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.resize(min(self.width(), area.width() - 32), min(self.height(), area.height() - 32))
            if not area.intersects(self.frameGeometry()):
                self.move(area.center() - self.rect().center())
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.refresh()

    def closeEvent(self, event: QCloseEvent) -> None:
        # Accepting closes/hides without deletion; ignoring would veto app.quit().
        event.accept()
        self.hide()
