"""Five-tab dashboard bound to the same PetModel as the desktop overlay."""
from __future__ import annotations

import math
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QCloseEvent, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QProgressBar, QPushButton, QScrollArea, QSlider, QStyle, QStyleOptionTab,
    QStylePainter, QTabBar, QTabWidget, QVBoxLayout, QWidget,
)
from models import PetModel


def label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
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


class NavigationTabBar(QTabBar):
    """Keep QSS shapes while painting each caption once at fractional Windows DPI."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setExpanding(True)
        self.setDrawBase(False)

    def paintEvent(self, event) -> None:
        painter = QStylePainter(self)
        painter.fillRect(self.rect(), QColor("#faf3ed"))
        for index in range(self.count()):
            option = QStyleOptionTab()
            self.initStyleOption(option, index)
            painter.drawControl(QStyle.ControlElement.CE_TabBarTabShape, option)
            painter.setFont(self.font())
            painter.setPen(QColor("#74475d" if index == self.currentIndex() else "#8e737c"))
            area = self.tabRect(index).adjusted(8, 0, -8, 0)
            text = self.fontMetrics().elidedText(self.tabText(index), Qt.TextElideMode.ElideRight, area.width())
            painter.drawText(area, Qt.AlignmentFlag.AlignCenter, text)
        painter.end()


class DashboardWindow(QMainWindow):
    pin_requested = Signal(bool)
    dev_requested = Signal(bool)
    flat_requested = Signal(bool)
    reset_requested = Signal()
    hunger_zero_requested = Signal()
    hunger_full_requested = Signal()
    gift_requested = Signal()
    reload_requested = Signal()
    accessory_requested = Signal(str, str)
    offset_requested = Signal(int)
    trick_requested = Signal(str)
    skin_requested = Signal(str)
    import_image_requested = Signal(str, bool)
    import_pack_requested = Signal(str)
    export_template_requested = Signal(str)
    import_unlock_requested = Signal()
    debug_unlock_requested = Signal(bool)

    def __init__(self, model: PetModel) -> None:
        super().__init__()
        self.model = model
        self._skin_entries = [{"id": "default", "name": "白汤圆", "author": "默认皮肤"}]
        self._phase4_dev_mode = False
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
        self.nav_divider = QFrame()
        self.nav_divider.setObjectName("navDivider")
        self.nav_divider.setFixedHeight(1)
        layout.addWidget(self.nav_divider)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("mainTabs")
        self.tabs.setTabBar(NavigationTabBar(self.tabs))
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setAutoFillBackground(True)
        layout.addWidget(self.tabs, 1)
        self.inventory_widgets = {}
        self.shop_buttons = {}
        self.shop_details = {}
        self.achievement_widgets = {}
        self.tier_groups = {}
        self._build_status()
        self._build_shop()
        self._build_achievements()
        self._build_customization()
        self._build_settings()
        self.notice = label("所有商品仅消耗游戏内糯米币 · 本地离线保存", "muted")
        layout.addWidget(self.notice)
        model.state_changed.connect(self._model_changed)
        model.feedback.connect(self._feedback)
        self.refresh()

    def _page(self, title: str, tabs: QTabWidget | None = None) -> QVBoxLayout:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        content.setObjectName("page")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 16, 0, 12)
        layout.setSpacing(14)
        scroll.setWidget(content)
        (self.tabs if tabs is None else tabs).addTab(scroll, title)
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
        self.empty_inventory = label("背包还是空的，去商城挑选食物或一份心意礼物吧～", "muted")
        page.addWidget(self.empty_inventory)
        for item_id, item in self.model.catalog.items.items():
            row, content = card()
            line = QHBoxLayout()
            text = label("")
            line.addWidget(text, 1)
            button = QPushButton("赠送" if item["category"] == "gift" else "投喂")
            button.clicked.connect(lambda checked=False, key=item_id: self.model.use_item(key))
            line.addWidget(button)
            content.addLayout(line)
            page.addWidget(row)
            self.inventory_widgets[item_id] = (row, text, button)
        self.unknown_inventory = label("", "muted")
        page.addWidget(self.unknown_inventory)
        page.addStretch()

    def _build_shop(self) -> None:
        shop = QWidget()
        shop.setObjectName("page")
        page = QVBoxLayout(shop)
        page.setContentsMargins(0, 12, 0, 0)
        page.setSpacing(12)
        page.addWidget(label("食物补充饱食度 · 礼物积累好感", "sectionTitle"))
        self.shop_tabs = QTabWidget()
        self.shop_tabs.setObjectName("shopTabs")
        self.shop_tabs.setTabBar(NavigationTabBar(self.shop_tabs))
        self.shop_tabs.setDocumentMode(True)
        self.shop_tabs.tabBar().setExpanding(True)
        self.shop_tabs.tabBar().setDrawBase(False)
        self.shop_tabs.tabBar().setAutoFillBackground(True)
        page.addWidget(self.shop_tabs, 1)
        self.tabs.addTab(shop, "免费商城")
        self.shop_groups = {}
        for category, title in (("food", "食物"), ("gift", "礼物")):
            section = self._page(title, self.shop_tabs)
            explanation = ("分三级恢复饱食度，食物不增加好感。可买进背包或立即投喂。" if category == "food"
                           else "分三级增加好感，礼物不恢复饱食度。可买进背包或立即赠送。")
            section.addWidget(label(explanation, "muted"))
            group = QWidget()
            group_layout = QVBoxLayout(group)
            group_layout.setContentsMargins(0, 0, 0, 0)
            group_layout.setSpacing(14)
            definitions = self.model.catalog.food_tiers if category == "food" else self.model.catalog.gift_tiers
            for tier in (1, 2, 3):
                definition = definitions[str(tier)]
                group_layout.addWidget(label(f"{('Ⅰ', 'Ⅱ', 'Ⅲ')[tier - 1]}级 · {definition['name']}", "sectionTitle"))
                grid = QGridLayout()
                grid.setSpacing(12)
                items = [(key, item) for key, item in self.model.catalog.items.items()
                         if item["category"] == category and item["tier"] == tier]
                for index, (item_id, item) in enumerate(items):
                    panel, content = card()
                    content.addWidget(label(f"{item['icon']} {item['name']}", "sectionTitle"))
                    details = label("")
                    self.shop_details[item_id] = details
                    content.addWidget(details)
                    buff = item.get("buff")
                    description = (f"【{buff['name']}】{buff['description']}" if buff else
                                   item.get("description", "把心意送给汤圆，慢慢积累好感。") if category == "gift"
                                   else "安心补充能量，饱食度最多恢复到 100。")
                    content.addWidget(label(description, "muted"), 1)
                    time_label = label("", "muted")
                    content.addWidget(time_label)
                    actions = QHBoxLayout()
                    buy = QPushButton("购买")
                    use = QPushButton("购买并赠送" if category == "gift" else "购买并投喂")
                    use.setProperty("primary", True)
                    buy.clicked.connect(lambda checked=False, key=item_id: self.model.buy_item(key))
                    use.clicked.connect(lambda checked=False, key=item_id: self.model.buy_item(key, feed_now=True))
                    actions.addWidget(buy)
                    actions.addWidget(use)
                    content.addLayout(actions)
                    grid.addWidget(panel, index // 2, index % 2)
                    self.shop_buttons[item_id] = (buy, use, time_label)
                grid.setColumnStretch(0, 1)
                grid.setColumnStretch(1, 1)
                group_layout.addLayout(grid)
            section.addWidget(group)
            section.addStretch()
            self.shop_groups[category] = group
        special = QGroupBox("🎪 永久特技 · 购买一次永久拥有")
        special_layout = QVBoxLayout(special)
        self.shop_trick_buttons = {}
        for trick_id, product in self.model.catalog.trick_products.items():
            line = QHBoxLayout()
            name = label(f"{product['icon']} {product['name']}", "sectionTitle")
            name.setToolTip(product["description"])
            line.addWidget(name, 1)
            buy = QPushButton("购买特技")
            buy.setProperty("primary", True)
            buy.clicked.connect(lambda checked=False, key=trick_id: self.model.buy_trick(key))
            perform = QPushButton("立即表演")
            perform.clicked.connect(lambda checked=False, key=trick_id: self.trick_requested.emit(key))
            line.addWidget(buy)
            line.addWidget(perform)
            special_layout.addLayout(line)
            status = label("", "muted")
            special_layout.addWidget(status)
            self.shop_trick_buttons[trick_id] = (buy, perform, status)
        page.addWidget(special)
        self.shop_groups["trick"] = special

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

    def _build_customization(self) -> None:
        self.dress_tabs = QTabWidget()
        self.dress_tabs.setObjectName("dressTabs")
        self.dress_tabs.setTabBar(NavigationTabBar(self.dress_tabs))
        self.dress_tabs.setDocumentMode(True)
        self.dress_tabs.tabBar().setExpanding(True)
        self.dress_tabs.tabBar().setDrawBase(False)
        self.dress_tabs.tabBar().setAutoFillBackground(True)
        dressing = QWidget()
        dressing_layout = QVBoxLayout(dressing)
        dressing_layout.setContentsMargins(0, 12, 0, 0)
        dressing_layout.addWidget(self.dress_tabs)
        self.tabs.addTab(dressing, "装扮")
        page = self._page("皮肤衣橱", self.dress_tabs)
        wardrobe, content = card()
        content.addWidget(label("🎨 皮肤衣橱与自定义导入", "sectionTitle"))
        content.addWidget(label("本地 PNG / 动态 GIF 和多状态动作包，都能共享果冻形变、风味染色、挂件与特技。", "muted"))
        line = QHBoxLayout()
        line.addWidget(label("当前外观"))
        self.skin_combo = QComboBox()
        self.skin_combo.setObjectName("skinCombo")
        self.skin_combo.setMinimumWidth(240)
        self.skin_combo.currentIndexChanged.connect(self._skin_selected)
        line.addWidget(self.skin_combo, 1)
        content.addLayout(line)
        self.skin_details = label("", "muted")
        content.addWidget(self.skin_details)
        unlock_line = QHBoxLayout()
        self.import_status = label("")
        unlock_line.addWidget(self.import_status, 1)
        self.import_unlock_button = QPushButton("50 糯米币提前解锁")
        self.import_unlock_button.setProperty("primary", True)
        self.import_unlock_button.clicked.connect(lambda checked=False: self.import_unlock_requested.emit())
        unlock_line.addWidget(self.import_unlock_button)
        content.addLayout(unlock_line)
        self.white_background_check = QCheckBox("自动移除纯白背景（PNG，保留主体内部白色）")
        self.white_background_check.setChecked(True)
        content.addWidget(self.white_background_check)
        actions = QHBoxLayout()
        self.import_buttons = {}
        for key, title, handler in (
            ("image", "📂 导入本地图片 / GIF", self._pick_image),
            ("folder", "📁 导入动作包文件夹", self._pick_folder),
            ("zip", "🗜 导入 ZIP 动作包", self._pick_zip),
        ):
            button = QPushButton(title)
            button.setObjectName(f"import_{key}")
            button.clicked.connect(handler)
            actions.addWidget(button, 1)
            self.import_buttons[key] = button
        content.addLayout(actions)
        self.export_template_button = QPushButton("📄 导出皮肤包模板")
        self.export_template_button.clicked.connect(self._export_template)
        content.addWidget(self.export_template_button)
        content.addWidget(label("单个文件不超过 20 MB；导入后复制到本地皮肤沙箱，原文件保持原样。GIF 保留动画，大图按比例限制纹理尺寸。", "muted"))
        self.skin_disclaimer = label("ℹ️ 免责声明：本软件为纯本地渲染工具，自定义导入的图片/GIF仅保存在您的电脑本地，不会上传至任何服务器。请确保所导入素材仅供个人学习欣赏或已取得合法授权。", "disclaimer")
        content.addWidget(self.skin_disclaimer)
        page.addWidget(wardrobe)
        page.addStretch()

        page = self._page("挂件装扮", self.dress_tabs)
        accessories, body = card()
        body.addWidget(label("👑 独立挂件与周身特效", "sectionTitle"))
        body.addWidget(label("挂件随外观一起呼吸、回弹、旋转；头顶、面部、周身三个位置可同时搭配。", "muted"))
        line = QHBoxLayout()
        line.addWidget(label("头顶挂件"))
        self.head_combo = QComboBox()
        self.head_combo.setObjectName("headAccessory")
        for title, item in (("不佩戴", ""), ("🌱 呆毛嫩芽 · Lv.2", "sprout"),
                            ("👑 迷你金皇冠 · Lv.3", "crown"), ("🎀 樱粉蝴蝶结 · Lv.6", "bow")):
            self.head_combo.addItem(title, item)
        self.head_combo.currentIndexChanged.connect(self._head_selected)
        line.addWidget(self.head_combo, 1)
        body.addLayout(line)
        self.face_check = QCheckBox("🕶️ 酷盖墨镜 · Lv.5")
        self.effect_check = QCheckBox("♨️ 暖心热气 / 星光 · Lv.4")
        self.face_check.toggled.connect(lambda enabled: self.accessory_requested.emit("face", "sunglasses" if enabled else ""))
        self.effect_check.toggled.connect(lambda enabled: self.accessory_requested.emit("effect", "steam" if enabled else ""))
        body.addWidget(self.face_check)
        body.addWidget(self.effect_check)
        offset = QHBoxLayout()
        offset.addWidget(label("挂件垂直微调"))
        self.offset_slider = QSlider(Qt.Orientation.Horizontal)
        self.offset_slider.setObjectName("accessoryOffset")
        self.offset_slider.setRange(-30, 30)
        self.offset_slider.setSingleStep(1)
        self.offset_slider.setTickInterval(10)
        self.offset_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.offset_slider.valueChanged.connect(self._offset_changed)
        offset.addWidget(self.offset_slider, 1)
        self.offset_value = label("0 px")
        self.offset_value.setMinimumWidth(52)
        offset.addWidget(self.offset_value)
        reset_offset = QPushButton("归零")
        reset_offset.clicked.connect(lambda checked=False: self.offset_slider.setValue(0))
        offset.addWidget(reset_offset)
        body.addLayout(offset)
        body.addWidget(label("负值向上，正值向下；范围 -30～+30 px，适配不同高矮的自定义图片。", "muted"))
        page.addWidget(accessories)
        page.addStretch()

        page = self._page("特技与等级奖励", self.dress_tabs)
        tricks, body = card()
        body.addWidget(label("🎪 表演特技", "sectionTitle"))
        body.addWidget(label("也可以右键桌宠，在“表演特技”中触发。双击仍然打开主面板。", "muted"))
        self.trick_buttons = {}
        self.trick_descriptions = {
            "flip": ("🌀 原地 360° 空翻", "Lv.2 · 冷却 5 秒 · 每次表演好感 +5"),
            "clone": ("✨ Q弹影分身", "Lv.4 · 两个分身弹跳 2.5 秒后合体"),
            "ball": ("⚽ 玩芝麻弹力球", "Lv.5 · 顶球互动 5 秒"),
        }
        for key, product in self.model.catalog.trick_products.items():
            self.trick_descriptions[key] = (self.model.trick_name(key),
                                            f"商城永久解锁 · {product['cost']} 糯米币 · 约12秒 · 冷却20秒")
        for key, (title, description) in self.trick_descriptions.items():
            row = QHBoxLayout()
            row.addWidget(label(description, "muted"), 1)
            button = QPushButton(title)
            button.setProperty("primary", True)
            button.setMinimumWidth(205)
            button.clicked.connect(lambda checked=False, trick=key: self.trick_requested.emit(trick))
            self.trick_buttons[key] = button
            row.addWidget(button)
            body.addLayout(row)
        self.trick_status = label("", "muted")
        body.addWidget(self.trick_status)
        page.addWidget(tricks)

        milestones, body = card()
        body.addWidget(label("✨ 好感等级奖励", "sectionTitle"))
        self.perk_summary = label("", "muted")
        body.addWidget(self.perk_summary)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.milestone_widgets = {}
        for level in range(1, 7):
            item = label("", "milestone")
            item.setMinimumHeight(68)
            grid.addWidget(item, (level - 1) // 2, (level - 1) % 2)
            self.milestone_widgets[level] = item
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        body.addLayout(grid)
        self.debug_unlock_check = QCheckBox("🧪 一键解锁全部等级特权 / 挂件（开发模式）")
        self.debug_unlock_check.setObjectName("debugPerks")
        self.debug_unlock_check.toggled.connect(self.debug_unlock_requested.emit)
        self.debug_unlock_check.hide()
        body.addWidget(self.debug_unlock_check)
        page.addWidget(milestones)
        page.addStretch()

    def _build_settings(self) -> None:
        page = self._page("设置")
        settings, content = card()
        content.addWidget(label("桌面陪伴设置", "sectionTitle"))
        self.pin_check = QCheckBox("固定当前位置（仍可拖动调整）")
        self.dev_check = QCheckBox("开发测试加速（饱食度 2 秒 / 点；正常模式满值持续 8 小时）")
        self.flat_check = QCheckBox("手动测试饿扁（不改变真实饥饿）")
        self.pin_check.toggled.connect(self.pin_requested.emit)
        self.dev_check.toggled.connect(self.dev_requested.emit)
        self.flat_check.toggled.connect(self.flat_requested.emit)
        for widget in (self.pin_check, self.dev_check, self.flat_check):
            content.addWidget(widget)
        buttons = QGridLayout()
        for index, (title, signal) in enumerate((("重置回主屏幕右下角", self.reset_requested),
                                               ("调试：饥饿归零", self.hunger_zero_requested),
                                               ("调试：恢复满饥饿", self.hunger_full_requested),
                                               ("调试：立即结算在线糯米币", self.gift_requested),
                                               ("重新加载当前皮肤", self.reload_requested))):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, output=signal: output.emit())
            buttons.addWidget(button, index // 2, index % 2)
        content.addLayout(buttons)
        page.addWidget(settings)
        page.addStretch()

    def set_phase4_context(self, skins: list[dict], dev_mode: bool = False) -> None:
        """Refresh locally validated wardrobe metadata supplied by the controller."""
        entries = [{"id": "default", "name": "白汤圆", "author": "默认皮肤"}]
        known = {"default"}
        for entry in skins:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or entry["id"] in known:
                continue
            known.add(entry["id"])
            entries.append({"id": entry["id"], "name": str(entry.get("name", entry["id"]))[:120],
                            "author": str(entry.get("author", "本地导入"))[:120]})
        self._skin_entries = entries
        self._phase4_dev_mode = bool(dev_mode)
        self.debug_unlock_check.setVisible(self._phase4_dev_mode)
        self._refresh_phase4()

    def _has_perk(self, perk_id: str) -> bool:
        return bool(self.model.has_perk(perk_id))

    def _skin_selected(self, index: int) -> None:
        if index >= 0:
            self.skin_requested.emit(str(self.skin_combo.itemData(index)))

    def _head_selected(self, index: int) -> None:
        if index >= 0:
            self.accessory_requested.emit("head", str(self.head_combo.itemData(index)))

    def _offset_changed(self, value: int) -> None:
        self.offset_value.setText(f"{value:+d} px" if value else "0 px")
        self.offset_requested.emit(value)

    def _pick_image(self) -> None:
        filename, _selected = QFileDialog.getOpenFileName(self, "导入本地图片 / GIF", "", "图片 (*.png *.gif)")
        if filename:
            self.import_image_requested.emit(filename, self.white_background_check.isChecked())

    def _pick_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择包含 manifest.json 的动作包文件夹")
        if folder:
            self.import_pack_requested.emit(folder)

    def _pick_zip(self) -> None:
        filename, _selected = QFileDialog.getOpenFileName(self, "导入 ZIP 动作包", "", "皮肤动作包 (*.zip)")
        if filename:
            self.import_pack_requested.emit(filename)

    def _export_template(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "选择皮肤包模板导出位置")
        if folder:
            self.export_template_requested.emit(folder)

    def _refresh_phase4(self) -> None:
        data = self.model.data
        selected = data.selected_skin_id
        entries = list(self._skin_entries)
        if selected not in {entry["id"] for entry in entries}:
            entries.append({"id": selected, "name": "暂不可用的已选皮肤", "author": "请重新导入或切换默认外观"})
        self.skin_combo.blockSignals(True)
        signature = [(entry["id"], entry["name"]) for entry in entries]
        current = [(self.skin_combo.itemData(i), self.skin_combo.itemText(i)) for i in range(self.skin_combo.count())]
        if signature != current:
            self.skin_combo.clear()
            for entry in entries:
                self.skin_combo.addItem(entry["name"], entry["id"])
        self.skin_combo.setCurrentIndex(self.skin_combo.findData(selected))
        self.skin_combo.blockSignals(False)
        metadata = next((entry for entry in entries if entry["id"] == selected), entries[0])
        self.skin_details.setText(f"作者：{metadata['author']} · 外观 ID：{selected}")
        allowed = self._has_perk("custom_import")
        self.import_status.setText("✅ 自定义导入已解锁" if allowed else "🔒 好感 Lv.3 免费解锁，也可以提前开启")
        self.import_unlock_button.setVisible(not allowed)
        self.import_unlock_button.setEnabled(not allowed and data.coins >= 50)
        for button in self.import_buttons.values():
            button.setEnabled(allowed)
        self.white_background_check.setEnabled(allowed)
        self.skin_combo.setEnabled(allowed or selected != "default")
        head = data.accessories.get("head", "")
        self.head_combo.blockSignals(True)
        for index in range(1, self.head_combo.count()):
            item_id = self.head_combo.itemData(index)
            self.head_combo.model().item(index).setEnabled(self._has_perk(f"accessory_{item_id}"))
        self.head_combo.setCurrentIndex(max(0, self.head_combo.findData(head)))
        self.head_combo.blockSignals(False)
        for checkbox, value, perk in ((self.face_check, data.accessories.get("face") == "sunglasses", "accessory_sunglasses"),
                                      (self.effect_check, data.accessories.get("effect") == "steam", "effect_steam"),
                                      (self.debug_unlock_check, self.model.debug_unlock_all, "")):
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(value))
            checkbox.blockSignals(False)
            if perk:
                checkbox.setEnabled(self._has_perk(perk) or bool(value))
        self.offset_slider.blockSignals(True)
        value = int(data.accessories.get("offset_y", 0))
        self.offset_slider.setValue(value)
        self.offset_value.setText(f"{value:+d} px" if value else "0 px")
        self.offset_slider.blockSignals(False)
        for key, button in self.trick_buttons.items():
            unlocked = self.model.has_trick(key)
            cooldown = float(self.model.trick_cooldowns.get(key, 0))
            title = self.trick_descriptions[key][0]
            suffix = f" · {math.ceil(cooldown)} 秒" if cooldown > 0 else " · 未解锁" if not unlocked else ""
            button.setText(title + suffix)
            button.setEnabled(self.model.can_perform_trick(key))
        for key, (buy, perform, status) in self.shop_trick_buttons.items():
            product = self.model.catalog.trick_products[key]
            owned = key in data.purchased_tricks
            buy.setText("✅ 已永久解锁" if owned else f"购买特技 · {product['cost']} 币")
            buy.setEnabled(not owned and data.coins >= product["cost"])
            perform.setEnabled(self.model.can_perform_trick(key))
            remaining = math.ceil(self.model.trick_cooldowns[key])
            status.setText("已学会 · 随时从商城、装扮特技页或右键菜单发动" if owned else f"{product['cost']} 糯米币 · 购买一次永久拥有")
            if owned and remaining:
                status.setText(f"休息中 · 还需 {remaining} 秒；表演中点击汤圆可提前回家")
        self.trick_status.setText("肚子饿扁啦，投喂恢复后就能表演。" if self.model.starving else "正在表演中，稍候再来一个～" if self.model.trick_busy > 0 else "当前外观可以使用所有已解锁特技；绕屏后回到原位，途中点击可结束。")
        self.perk_summary.setText(f"当前好感 Lv.{data.affection_level} / 30 · 六级领齐基础奖励，后续继续积累陪伴。" + (" 开发模式已临时解锁全部特权。" if self.model.debug_unlock_all else ""))
        milestones = {milestone["level"]: milestone for milestone in self.model.perk_status()}
        for level, widget in self.milestone_widgets.items():
            milestone = milestones.get(level, {})
            names = [self.model.catalog.perks[perk]["name"] for perk in milestone.get("perks", []) if perk in self.model.catalog.perks]
            description = "、".join(names) or "白汤圆皮肤 · 基础互动"
            unlocked = bool(milestone.get("unlocked", data.affection_level >= level))
            widget.setText(f"{'✅' if unlocked else '🔒'} Lv.{level}  {milestone.get('label', '')}\n{description}")
            widget.setProperty("unlocked", unlocked)
            widget.style().unpolish(widget)
            widget.style().polish(widget)

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
        self.hunger_bar.setFormat(f"饱食度 {data.hunger:g} / 100" + (" · 饿扁啦，喂一口就恢复" if self.model.starving else ""))
        buff = self.model.buff_view()
        self.buff_label.setText(f"{buff['name']} · 剩余 {math.ceil(buff['remaining_seconds'])} 秒" + (f" · 狂奔 / 跺脚 {math.ceil(buff['behavior_remaining'])} 秒" if buff.get("behavior_remaining") else "") if buff else "原味白汤圆 · 当前没有风味 Buff")
        stats = data.stats
        self.stats_label.setText(f"累计戳戳 {stats['total_clicks']} 次  ·  投喂 {stats['total_feeds']} 次  ·  在线入账 {stats['total_gifts']} 次  ·  赠礼 {stats['total_presents']} 次\n在线陪伴 {int(stats['total_idle_seconds'] // 60)} 分钟  ·  摸头 {stats['total_pets']} 次  ·  高空落地 {stats['total_drops']} 次")
        owned = False
        for item_id, (row, text, button) in self.inventory_widgets.items():
            item, count = self.model.item(item_id), data.inventory.get(item_id, 0)
            row.setVisible(count > 0)
            button.setEnabled(count > 0)
            effect = f"好感 +{item['exp']}" if item["category"] == "gift" else f"饱食度 +{item['hunger']:g}"
            text.setText(f"{item['icon']} {item['name']} × {count}  ·  {item['tier']}级{'礼物' if item['category'] == 'gift' else '食物'}\n{effect}")
            owned = owned or count > 0
        self.empty_inventory.setVisible(not owned)
        unknown = [f"{key} ×{count}" for key, count in data.inventory.items() if key not in self.model.catalog.items and count > 0]
        self.unknown_inventory.setText("保留的扩展物品：" + "、".join(unknown) if unknown else "")
        self.unknown_inventory.setVisible(bool(unknown))
        for item_id, (buy, feed, text) in self.shop_buttons.items():
            item = self.model.item(item_id)
            effect = f"好感 +{item['exp']}" if item["category"] == "gift" else f"饱食度 +{item['hunger']:g}"
            self.shop_details[item_id].setText(f"{item['cost']} 糯米币   ·   {effect}")
            buy.setEnabled(data.coins >= item["cost"])
            feed.setEnabled(data.coins >= item["cost"])
            text.setText(f"风味持续 {self.model.rules.buff_seconds:g} 秒" if "buff" in item else "赠送只增加好感，不影响饱食度" if item["category"] == "gift" else "食物只恢复饱食度，不增加好感")
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

        self._refresh_phase4()

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
