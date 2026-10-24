"""Game home, illustrated inventory books and visual dressing slots."""
from __future__ import annotations

import math
from pathlib import Path
from PySide6.QtCore import QEvent, QEasingCurve, QPoint, QPropertyAnimation, QPointF, QRectF, QSize, Qt, QTimer, Signal, Property
from PySide6.QtGui import QColor, QCloseEvent, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QLinearGradient, QRadialGradient, QIcon, QPixmap
from PySide6.QtWidgets import (QFileDialog, QFrame, QGridLayout, QHBoxLayout, QInputDialog,
    QLabel, QMainWindow, QProgressBar, QPushButton, QScrollArea, QSlider, QSizePolicy,
    QTabBar, QTabWidget, QVBoxLayout, QWidget, QGraphicsOpacityEffect, QAbstractButton, QApplication, QProxyStyle, QStyle, QMessageBox)
from models import PetModel, TEAM_SKIN_IDS
from pet_engine import PetEngine, SkinRenderer, WorkArea
from home_scene import IllustratedRoomCanvas
from illustrated_assets import IconAtlas, plain_text
from release_support import APP_VERSION, timestamp


def label(text: str, role: str = "") -> QLabel:
    widget = QLabel(plain_text(text))
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if role:
        widget.setObjectName(role)
    return widget


def card():
    widget = QFrame(); widget.setObjectName("gameCard")
    layout = QVBoxLayout(widget); layout.setContentsMargins(8, 7, 8, 8); layout.setSpacing(4)
    return widget, layout


class FocusFreeStyle(QProxyStyle):
    """Keep native control behavior while omitting Windows dotted focus frames."""
    def drawPrimitive(self, element, option, painter, widget=None):
        if element != QStyle.PrimitiveElement.PE_FrameFocusRect:
            super().drawPrimitive(element, option, painter, widget)


def install_game_style():
    app = QApplication.instance()
    if app is not None and not app.property("gameFocusStyle"):
        style = FocusFreeStyle(app.style().objectName()); style.setParent(app)
        app.setStyle(style); app.setProperty("gameFocusStyle", True)


class AdaptiveGrid(QGridLayout):
    """Reflow cards to the actual scroll viewport, including sparse inventories."""
    def __init__(self, host, minimum=174, maximum=3):
        super().__init__()
        self.host, self.minimum, self.maximum = host, minimum, maximum
        self.cards = []; self.columns = 1; self._signature = None
        self.setSpacing(7); host.installEventFilter(self)

    def addWidget(self, widget, *position):
        if widget not in self.cards: self.cards.append(widget)
        self.reflow()

    def removeWidget(self, widget):
        if widget in self.cards: self.cards.remove(widget)
        super().removeWidget(widget); self._signature = None

    def eventFilter(self, watched, event):
        if watched is self.host and event.type() == QEvent.Type.Resize:
            self.reflow()
        return False

    def reflow(self):
        margins = self.host.layout().contentsMargins() if self.host.layout() else self.contentsMargins()
        width = max(1, self.host.width() - margins.left() - margins.right())
        visible = [w for w in self.cards if w.property("gridVisible") is not False]
        columns = max(1, min(self.maximum, (width + self.spacing()) // (self.minimum + self.spacing())))
        signature = columns, tuple(id(w) for w in visible)
        if signature == self._signature: return
        self._signature = signature; self.columns = columns
        for widget in self.cards: super().removeWidget(widget)
        for index, widget in enumerate(visible): super().addWidget(widget, index // columns, index % columns)
        for column in range(self.maximum): super().setColumnStretch(column, int(column < columns))


class NavigationTabBar(QTabBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setExpanding(True); self.setDrawBase(False)
        self.setElideMode(Qt.TextElideMode.ElideRight)


class IconTile(QPushButton):
    """A real pixmap slot; its checked state is a worn/placed game badge."""
    def __init__(self, title, icon_id, atlas, parent=None):
        super().__init__(plain_text(title), parent)
        self.setProperty("icon_id", icon_id)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setIcon(atlas.icon(icon_id)); self.setIconSize(QSize(80, 80))
        self.setMinimumSize(108, 124)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.badge = ""
        self.setObjectName("iconTile")

    def sizeHint(self):
        return QSize(128, 124)

    def minimumSizeHint(self):
        return QSize(108, 124)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = self.isChecked() or bool(self.property("selected"))
        area = QRectF(self.rect()).adjusted(3, 2, -3, -5)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(104, 73, 43, 18)); p.drawRoundedRect(area.translated(0, 3), 15, 15)
        gradient = QLinearGradient(area.topLeft(), area.bottomRight())
        gradient.setColorAt(0, QColor("#fff7df" if not checked else "#eef1cd"))
        gradient.setColorAt(1, QColor("#f0dfc0" if not checked else "#d6dfb5"))
        p.setBrush(gradient); p.setPen(QPen(QColor("#8b9a64" if checked else "#c5a37b"), 2.5 if checked else 1.5))
        p.drawRoundedRect(area, 15, 15)
        if not self.isEnabled(): p.setOpacity(.46)
        self.icon().paint(p, int((self.width() - 72) / 2), 4, 72, 72)
        p.setPen(QColor("#684e37")); font = QFont("Microsoft YaHei UI", 10); font.setBold(True); p.setFont(font)
        p.drawText(QRectF(5, 77, self.width() - 10, 40), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, self.text())
        if self.badge or checked:
            text = self.badge or "已选择"
            p.setOpacity(1); p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor("#899764" if checked else "#c09b6e"))
            width = max(34, min(self.width() - 10, p.fontMetrics().horizontalAdvance(text) + 14))
            badge = QRectF(self.width() - width - 5, 6, width, 20); p.drawRoundedRect(badge, 7, 7)
            p.setPen(QColor("#fff9e7")); p.setFont(QFont("Microsoft YaHei UI", 8))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, text)
        p.end()


class NavigationButton(IconTile):
    """A small suspended wooden badge, with its own soft hover animation."""
    def __init__(self, title, icon_id, atlas):
        super().__init__(title, icon_id, atlas)
        self.setObjectName("dockNavigation")
        self.setMinimumSize(48, 78); self.setMaximumHeight(78); self.setIconSize(QSize(42, 42))
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setToolTip(self.text())
        self._hover_lift = 0.0
        self.hover_animation = QPropertyAnimation(self, b"hover_lift", self)
        self.hover_animation.setDuration(160); self.hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _set_hover_lift(self, value):
        self._hover_lift = float(value); self.update()
    hover_lift = Property(float, lambda self: self._hover_lift, _set_hover_lift)

    def enterEvent(self, event):
        self.hover_animation.stop(); self.hover_animation.setStartValue(self._hover_lift)
        self.hover_animation.setEndValue(5.0); self.hover_animation.start(); super().enterEvent(event)

    def leaveEvent(self, event):
        self.hover_animation.stop(); self.hover_animation.setStartValue(self._hover_lift)
        self.hover_animation.setEndValue(0.0); self.hover_animation.start(); super().leaveEvent(event)

    def sizeHint(self): return QSize(68, 78)
    def minimumSizeHint(self): return QSize(48, 78)
    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lift = self._hover_lift - (2 if self.isDown() else 0)
        area = QRectF(3, 7 - lift, self.width() - 6, self.height() - 15)
        shadow = QRadialGradient(QPointF(self.width() / 2, self.height() - 8), self.width() * .54)
        shadow.setColorAt(0, QColor(65, 39, 25, 64)); shadow.setColorAt(1, QColor(65, 39, 25, 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(shadow)
        p.drawEllipse(QRectF(0, self.height() - 18, self.width(), 17))
        p.setBrush(QColor("#8c9970" if self.isChecked() else "#a7774e"))
        p.drawRoundedRect(area.translated(0, 4), 19, 19)
        gradient = QLinearGradient(area.topLeft(), area.bottomRight())
        gradient.setColorAt(0, QColor("#eef3dc" if self.isChecked() else "#fff2d4"))
        gradient.setColorAt(.65, QColor("#d8e2bd" if self.isChecked() else "#e9c99c"))
        gradient.setColorAt(1, QColor("#c1cf9f" if self.isChecked() else "#d8af7c"))
        p.setBrush(gradient); p.setPen(QPen(QColor("#74845d" if self.isChecked() else "#a47c55"), 1.15))
        p.drawRoundedRect(area, 19, 19)
        p.setPen(QPen(QColor(255, 252, 228, 175), 1.2))
        p.drawArc(area.adjusted(3, 2, -3, -3), 35 * 16, 110 * 16)
        side = min(41, area.width() - 8)
        self.icon().paint(p, QRectF(area.center().x() - side / 2, area.top() + 1, side, side).toRect())
        p.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.DemiBold)); p.setPen(QColor("#634a34"))
        available = max(0, int(area.width() - 5))
        text = p.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight, available)
        p.drawText(QRectF(area.left() + 2, area.bottom() - 23, area.width() - 4, 20),
                   Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextSingleLine, text)
        p.end()


class ShelfFoodButton(QPushButton):
    """Food sits directly on the scene's foreground table, without a UI card."""
    def __init__(self, item_id, atlas):
        super().__init__()
        self.setObjectName("shelfFood"); self.setProperty("icon_id", item_id)
        self.setIcon(atlas.icon(item_id)); self.setIconSize(QSize(48, 48))
        self.setFixedSize(62, 62); self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        shadow = QRadialGradient(QPointF(29, 48), 29)
        shadow.setColorAt(0, QColor(70, 38, 20, 85)); shadow.setColorAt(1, QColor(70, 38, 20, 0))
        p.setBrush(shadow); p.setPen(Qt.PenStyle.NoPen); p.drawEllipse(QRectF(2, 40, 55, 15))
        up = 2 if self.underMouse() and not self.isDown() else 0
        self.icon().paint(p, QRectF(4, 1 - up, 49, 49).toRect())
        p.setFont(QFont("Microsoft YaHei UI", 9, QFont.Weight.DemiBold))
        text_width = max(22, p.fontMetrics().horizontalAdvance(self.text()) + 9)
        plate = QRectF(61 - text_width, 42, text_width, 18)
        p.setBrush(QColor(255, 243, 210, 224)); p.setPen(QPen(QColor(143, 104, 66, 145), .8)); p.drawRoundedRect(plate, 7, 7)
        p.setPen(QColor("#765233")); p.drawText(plate, Qt.AlignmentFlag.AlignCenter, self.text()); p.end()


class FoodShelfScroll(QScrollArea):
    def wheelEvent(self, event):
        amount = event.pixelDelta().x() or event.pixelDelta().y() or event.angleDelta().y() / 2
        self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - round(amount))
        event.accept()


class IconChoice(QWidget):
    """Visible tile collection with a small selection API for controller clients."""
    currentIndexChanged = Signal(int)
    currentTextChanged = Signal(str)

    def __init__(self, atlas, icon_id="avatar", parent=None, compact=False):
        super().__init__(parent)
        self.atlas, self.icon_id, self.compact = atlas, icon_id, compact
        self.entries = []; self.buttons = []; self._index = -1
        self.grid = AdaptiveGrid(self, 108, 4); self.setLayout(self.grid); self.grid.setContentsMargins(0, 0, 0, 0); self.grid.setSpacing(7)
        for i in range(3): self.grid.setColumnStretch(i, 1)

    def addItem(self, title, data=None, icon_id=None):
        title = plain_text(title)
        index = len(self.entries); self.entries.append((title, title if data is None else data))
        tile = (NavigationButton if self.compact else IconTile)(title, icon_id or self.icon_id, self.atlas)
        tile.setCheckable(True); tile.clicked.connect(lambda checked=False, i=index: self.setCurrentIndex(i))
        self.grid.addWidget(tile, index // 3, index % 3); self.buttons.append(tile)
        if self._index < 0: self.setCurrentIndex(0)

    def addItems(self, values):
        for value in values: self.addItem(value)

    def clear(self):
        for button in self.buttons:
            self.grid.removeWidget(button); button.hide(); button.deleteLater()
        self.entries, self.buttons, self._index = [], [], -1

    def count(self): return len(self.entries)
    def itemText(self, index): return self.entries[index][0]
    def itemData(self, index): return self.entries[index][1]
    def currentIndex(self): return self._index
    def currentText(self): return self.itemText(self._index) if self._index >= 0 else ""
    def currentData(self): return self.itemData(self._index) if self._index >= 0 else None
    def findData(self, value): return next((i for i, row in enumerate(self.entries) if row[1] == value), -1)
    def findText(self, value): return next((i for i, row in enumerate(self.entries) if row[0] == value), -1)
    def setCurrentText(self, value): self.setCurrentIndex(self.findText(plain_text(value)))
    def model(self): return self
    def item(self, index): return self.buttons[index]

    def setCurrentIndex(self, index):
        if not 0 <= index < len(self.entries): return
        previous, self._index = self._index, index
        for i, button in enumerate(self.buttons):
            button.setChecked(i == index); button.update()
        if previous != index:
            self.currentIndexChanged.emit(index); self.currentTextChanged.emit(self.currentText())


class GameToggle(QPushButton):
    def __init__(self, title, icon_id, atlas):
        super().__init__(plain_text(title))
        self.setProperty("icon_id", icon_id)
        self.setIcon(atlas.icon(icon_id)); self.setIconSize(QSize(40, 40)); self.setCheckable(True)
        self.setMinimumHeight(56); self.setObjectName("gameToggle")
        self.toggled.connect(lambda enabled: self.setProperty("selected", enabled))


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
    scale_requested = Signal(float)
    backup_requested = Signal(str)
    restore_requested = Signal(str)
    dev_level_requested = Signal(int)
    trick_requested = Signal(str)
    skin_requested = Signal(str)
    debug_unlock_requested = Signal(bool)
    rename_requested = Signal(str)
    overlay_requested = Signal(bool)
    mute_requested = Signal(bool)
    furniture_requested = Signal(str, str)
    poke_requested = Signal()
    pet_requested = Signal()
    foreground_cancel_requested = Signal(str)

    def __init__(self, model: PetModel, engine: PetEngine | None = None, renderer_provider=None):
        super().__init__()
        install_game_style()
        self.model = model; self.atlas = IconAtlas(); self.atlas.warm(self.model.catalog)
        self._skin_entries = [{"id": "default", "name": "白汤圆", "author": "默认皮肤"}]
        self._phase4_dev_mode = False
        self._home_engine_owned = engine is None
        self._home_engine = engine or PetEngine(WorkArea(0, 0, 1000, 600))
        self._home_renderer = None
        if renderer_provider is None:
            self._home_renderer = SkinRenderer(Path(__file__).resolve().parent / "assets/skins/default")
            renderer_provider = lambda: self._home_renderer
        self._renderer_provider = renderer_provider
        self.setWindowTitle("Q弹汤圆 · 汤圆的家")
        self.setObjectName("dashboard")
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.resize(1240, 760); self.setMinimumSize(780, 610)
        self.home_scroll = QScrollArea(); self.home_scroll.setWidgetResizable(False)
        self.home_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.home_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setCentralWidget(self.home_scroll)
        root = QWidget(); root.setObjectName("dashboardRoot")
        self.home_scroll.setWidget(root)
        self.home_scroll.viewport().installEventFilter(self)
        layout = QVBoxLayout(root); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(0)
        self.scene_row = QHBoxLayout(); self.scene_row.setSpacing(0); layout.addLayout(self.scene_row, 1)
        self.room = IllustratedRoomCanvas(self._home_engine, renderer_provider, self, self.atlas)
        self.room.setMinimumHeight(420); self.room.installEventFilter(self)
        self.room.setMinimumWidth(300); self.scene_row.addWidget(self.room, 1)
        self.room.poke_requested.connect(self.poke_requested.emit)
        self.room.pet_requested.connect(self.pet_requested.emit)
        self.room.lamp_toggle_requested.connect(lambda: self.model.set_lamp_on(not self.model.data.lamp_on))
        self.room.air_conditioner_toggle_requested.connect(lambda: self.model.set_air_conditioner_on(not self.model.data.air_conditioner_on))
        self._build_hud()
        if self._home_engine_owned:
            self.preview_timer = QTimer(self); self.preview_timer.setInterval(16)
            self.preview_timer.timeout.connect(lambda: self._home_engine.advance(.016)); self.preview_timer.start()
            self.poke_requested.connect(self._preview_poke); self.pet_requested.connect(self._preview_pet)
            self.model.feedback.connect(self.room.show_message); self.model.fed.connect(self._home_engine.rebound)
            self.model.presentation_requested.connect(
                lambda event: self._home_engine.enjoy_interaction(event.get("duration", 2.5)))
        self.drawer = QFrame(root)
        self.drawer.setObjectName("inventoryBook"); self.drawer.setWindowTitle("汤圆图鉴")
        self.drawer.setMinimumHeight(420)
        self.scene_row.addWidget(self.drawer)
        drawer_layout = QVBoxLayout(self.drawer); drawer_layout.setContentsMargins(10, 8, 10, 10); drawer_layout.setSpacing(5)
        header = QHBoxLayout(); self.drawer_title = label("", "bookTitle"); header.addWidget(self.drawer_title, 1)
        close = QPushButton("回房间"); close.setIcon(self.atlas.icon("home")); close.setIconSize(QSize(28, 28))
        close.clicked.connect(lambda: self.show_section("home")); header.addWidget(close); drawer_layout.addLayout(header)
        self.nav_divider = QFrame(); self.nav_divider.setObjectName("navDivider"); self.nav_divider.setFixedHeight(2)
        drawer_layout.addWidget(self.nav_divider)
        self.tabs = QTabWidget(); self.tabs.setObjectName("bookPages"); self.tabs.setTabBar(NavigationTabBar())
        self.tabs.setDocumentMode(True); drawer_layout.addWidget(self.tabs, 1)
        self.inventory_widgets = {}; self.shop_buttons = {}; self.shop_details = {}; self.achievement_widgets = {}; self.tier_groups = {}
        self._build_status(); self._build_shop(); self._build_achievements(); self._build_customization()
        self._build_furniture(); self._build_tricks(); self._build_rewards(); self._build_settings()
        self.tabs.tabBar().hide(); self.tabs.currentChanged.connect(self._drawer_selected)
        self.drawer_opacity = QGraphicsOpacityEffect(self.drawer); self.drawer.setGraphicsEffect(self.drawer_opacity)
        self._drawer_extent = 0.0; self._drawer_target = 400
        self.drawer_animation = QPropertyAnimation(self, b"drawer_width", self)
        self.drawer_animation.setDuration(220); self.drawer_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.drawer_animation.finished.connect(self._finish_drawer)
        self.drawer.hide(); self.current_section = "home"
        self._build_shelf(layout); self._build_navigation(layout)
        self.notice = label("左键戳戳，右键摸摸头。今天也陪你慢慢长大。", "muted"); self.notice.setMaximumHeight(0); self.notice.hide()
        model.state_changed.connect(self._model_changed); model.feedback.connect(self._feedback)
        self.model.presentation_requested.connect(self.room.present_item)
        self.model.gains_received.connect(self.room.receive_gains)
        self.model.interaction_started.connect(self.room.record_interaction)
        self.room.mood_requested.connect(self._home_engine.enjoy_interaction)
        for control in self.findChildren(QAbstractButton):
            control.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._fit_home()
        self.refresh()

    def _use_item(self, item_id, purchase=False, source=None):
        button = source if source is not None else self.sender()
        if isinstance(button, QWidget):
            local = self.room.mapFromGlobal(button.mapToGlobal(button.rect().center()))
            self.room._next_food_origin = QPointF(max(26, min(self.room.width() - 26, local.x())),
                                                  max(120, min(self.room.height() - 20, local.y())))
        try:
            return self.model.buy_item(item_id, feed_now=True) if purchase else self.model.use_item(item_id)
        finally:
            self.room._next_food_origin = None

    def _button(self, text, icon_id=None):
        button = QPushButton(plain_text(text))
        if icon_id:
            button.setProperty("icon_id", icon_id)
            button.setIcon(self.atlas.icon(icon_id)); button.setIconSize(QSize(26, 26))
        return button

    def _build_hud(self):
        self.hud = QFrame(self.room); self.hud.setObjectName("floatingHud")
        outer = QHBoxLayout(self.hud); outer.setContentsMargins(0, 0, 0, 0); outer.setSpacing(8)
        self.hud_profile = QFrame(); self.hud_profile.setObjectName("hudProfile")
        content = QVBoxLayout(self.hud_profile); content.setContentsMargins(9, 6, 9, 6); content.setSpacing(2)
        top = QHBoxLayout(); top.setSpacing(4)
        self.hud_avatar = QLabel(); self.hud_avatar.setFixedSize(32, 32)
        self.hud_avatar.setPixmap(self.atlas.pixmap("avatar", 32)); top.addWidget(self.hud_avatar)
        self.hud_name = label("", "petName"); self.hud_name.setWordWrap(False)
        self.hud_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); top.addWidget(self.hud_name, 1)
        self.level_badge = label("Lv.1", "levelBadge"); top.addWidget(self.level_badge)
        self.rename_button = self._button("", "title"); self.rename_button.setFixedSize(24, 26)
        self.rename_button.setToolTip("给汤圆命名"); self.rename_button.clicked.connect(self._rename); top.addWidget(self.rename_button)
        content.addLayout(top)
        self.hud_hunger_bar = QProgressBar(); self.hud_hunger_bar.setRange(0, 100); self.hud_hunger_bar.setObjectName("hungerBar")
        self.hud_exp_bar = QProgressBar(); self.hud_exp_bar.setObjectName("affectionBar")
        content.addWidget(self.hud_hunger_bar); content.addWidget(self.hud_exp_bar)
        self.hud_title = label("", "titlePlaque"); self.hud_title.setWordWrap(False); content.addWidget(self.hud_title)
        outer.addWidget(self.hud_profile); outer.addStretch(1)
        self.hud_right = QWidget(); right = QVBoxLayout(self.hud_right); right.setContentsMargins(0, 0, 0, 0); right.setSpacing(4)
        self.coin_capsule = QFrame(); self.coin_capsule.setObjectName("coinCapsule")
        coins = QHBoxLayout(self.coin_capsule); coins.setContentsMargins(5, 3, 7, 3); coins.setSpacing(2)
        coin = QLabel(); coin.setPixmap(self.atlas.pixmap("coin", 27)); coins.addWidget(coin)
        self.balance = label("", "coinAmount"); self.balance.setWordWrap(False)
        self.balance.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred); coins.addWidget(self.balance, 1); right.addWidget(self.coin_capsule)
        self.overlay_button = self._button("", "desktop"); self.overlay_button.setFixedSize(34, 30)
        self.overlay_button.setCheckable(True); self.overlay_button.toggled.connect(self.overlay_requested.emit)
        lower = QHBoxLayout(); lower.setContentsMargins(0, 0, 0, 0); lower.setSpacing(3)
        lower.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.hud_buff = label("", "buffBadge"); self.hud_buff.setWordWrap(False)
        self.hud_buff.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.mute_button = self._button("", "music_box"); self.mute_button.setObjectName("muteControl"); self.mute_button.setFixedSize(30, 30)
        self.mute_button.setCheckable(True); self.mute_button.setAccessibleName("静音开关")
        self.mute_button.toggled.connect(self.mute_requested.emit)
        lower.addWidget(self.hud_buff, 1); lower.addWidget(self.mute_button); lower.addWidget(self.overlay_button); right.addLayout(lower); right.addStretch()
        outer.addWidget(self.hud_right); self.hud.raise_()

    def _layout_hud(self):
        width = max(264, self.room.width() - 28)
        self.hud.setGeometry(14, 14, width, 94)
        right = max(88, min(178, int(width * .30)))
        self.hud_right.setFixedWidth(right)
        self.hud_profile.setFixedWidth(min(304, width - right - 8))
        self.hud.layout().activate()
        self.hud.raise_()

    def eventFilter(self, watched, event):
        if watched is self.home_scroll.viewport() and event.type() == QEvent.Type.Resize:
            self._fit_home()
        if watched is getattr(self, "room", None) and event.type() == QEvent.Type.Resize and hasattr(self, "hud"):
            self._layout_hud()
            self._layout_scene_controls()
        return super().eventFilter(watched, event)

    def _rename(self):
        name, ok = QInputDialog.getText(self, "给汤圆命名", "名字（1～40个字符）", text=plain_text(self.model.data.name))
        if ok: self.rename_requested.emit(name)

    def _preview_poke(self): self._home_engine.click(); self.model.poke()
    def _preview_pet(self):
        if self.model.pet_head(): self._home_engine.rebound()

    def _build_shelf(self, layout):
        self.feeding_shelf = QFrame(self.room); self.feeding_shelf.setObjectName("feedingShelf")
        self.feeding_shelf.setFrameShape(QFrame.Shape.NoFrame)
        self.feeding_shelf.setAutoFillBackground(False)
        self.feeding_shelf.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        row = QHBoxLayout(self.feeding_shelf); row.setContentsMargins(8, 0, 8, 0); row.setSpacing(4)
        self.shelf_empty = label("案几还空着\n带点好吃的回来", "shelfEmpty"); row.addWidget(self.shelf_empty, 1)
        self.feeding_scroll = FoodShelfScroll(); self.feeding_scroll.setWidgetResizable(True); self.feeding_scroll.setFixedHeight(64)
        self.feeding_scroll.setFrameShape(QFrame.Shape.NoFrame); self.feeding_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.feeding_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.feeding_scroll.setAutoFillBackground(False); self.feeding_scroll.viewport().setAutoFillBackground(False)
        content = QWidget(); foods = QHBoxLayout(content); foods.setContentsMargins(0, 0, 0, 0); foods.setSpacing(4)
        content.setObjectName("shelfFoodContents"); content.setAutoFillBackground(False)
        self.feeding_buttons = {}
        for key, item in self.model.catalog.items.items():
            if item["category"] != "food": continue
            button = ShelfFoodButton(key, self.atlas)
            button.clicked.connect(lambda checked=False, food=key, origin=button: self._use_item(food, source=origin)); button.setToolTip(item["name"])
            foods.addWidget(button); self.feeding_buttons[key] = button
        foods.addStretch(); self.feeding_scroll.setWidget(content); row.addWidget(self.feeding_scroll, 1)
        self.shelf_buy_button = self._button("去买粮", "shop"); self.shelf_buy_button.setObjectName("woodenFoodSign")
        self.shelf_buy_button.setFixedSize(76, 43); self.shelf_buy_button.setIconSize(QSize(23, 23))
        self.shelf_buy_button.clicked.connect(self._buy_food); row.addWidget(self.shelf_buy_button)

    def _buy_food(self):
        self.show_section("shop"); self.market_tabs.setCurrentIndex(0); self.shop_tabs.setCurrentIndex(0)

    def _build_navigation(self, layout):
        self.dock = QWidget(self.room); self.dock.setObjectName("floatingDock")
        self.dock.setAutoFillBackground(False)
        self.dock.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        row = QHBoxLayout(self.dock); row.setContentsMargins(0, 0, 0, 0); row.setSpacing(6); self.nav_buttons = {}
        for section, text, art in (("home", "小窝", "home"), ("bag", "背包", "bag"),
                                  ("shop", "商城", "shop"), ("achievements", "成长", "achievements"),
                                  ("settings", "设置", "settings")):
            button = NavigationButton(text, art, self.atlas)
            button.setCheckable(True); button.clicked.connect(lambda checked=False, key=section: self.show_section(key))
            if section == "achievements": button.setToolTip("成就与等级奖励")
            row.addWidget(button); self.nav_buttons[section] = button
        self.nav_buttons["home"].setChecked(True)
        self._layout_scene_controls()

    def _layout_scene_controls(self):
        if not hasattr(self, "dock"): return
        width, height = self.room.width(), self.room.height()
        stacked = width < 780
        self.room.setProperty("sceneControlsStacked", stacked)
        table_provider = getattr(self.room, "foreground_table_rect", None)
        table = table_provider() if callable(table_provider) else QRectF(
            width * (.04 if stacked else .035), height - (184 if stacked else 114),
            width * .92 if stacked else min(width * .48, 540), 76 if stacked else 78)
        self.feeding_shelf.setGeometry(table.adjusted(3, -6, -3, -12).toAlignedRect())
        dock_provider = getattr(self.room, "foreground_navigation_rect", None)
        navigation = dock_provider() if callable(dock_provider) else QRectF(
            8 if stacked else width * .55, height - 90,
            width - 16 if stacked else width * .42, 80)
        gap = 6 if navigation.width() >= 330 else 3
        button_width = max(48, min(68, int((navigation.width() - 4 * gap) / 5)))
        dock_width = button_width * 5 + 4 * gap
        self.dock.layout().setSpacing(gap)
        for button in self.nav_buttons.values(): button.setFixedSize(button_width, 78)
        self.dock.setGeometry(round(navigation.center().x() - dock_width / 2), round(navigation.top()), dock_width, 80)
        self.feeding_shelf.raise_(); self.dock.raise_(); self.hud.raise_()

    def _fit_home(self):
        if not hasattr(self, "drawer_animation"): return
        viewport = self.home_scroll.viewport()
        # Word-wrapped book pages report a large height-for-width. Fit the scene
        # explicitly so opening a book cannot push the permanent dock off-screen.
        self.home_scroll.widget().resize(viewport.size())
        self._place_drawer()

    def _set_drawer_width(self, width):
        self._drawer_extent = float(width); self.drawer.setFixedWidth(max(1, round(width)))
        self.drawer_opacity.setOpacity(min(1.0, .4 + width / max(1, self._drawer_target)))
    drawer_width = Property(float, lambda self: self._drawer_extent, _set_drawer_width)

    def _finish_drawer(self):
        if self.current_section == "home": self.drawer.hide()
        else: self.drawer_opacity.setOpacity(1)

    def _place_drawer(self):
        available = self.home_scroll.viewport().width()
        self._drawer_target = min(max(300, available - 300), max(400, min(660, int(available * .49))))
        if not self.drawer_animation.state() == QPropertyAnimation.State.Running:
            self._set_drawer_width(self._drawer_target if self.current_section != "home" else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "drawer_animation"): self._fit_home()

    def show_section(self, section, *, animate=True):
        # Old internal destinations still route to the unified inventory.
        target = {"dress": (1, None), "furniture": (2, None), "tricks": (3, None),
                  "titles": (1, 2), "levels": (None, None)}.get(section)
        if target is not None:
            if section == "levels":
                section = "achievements"; self.progress_tabs.setCurrentIndex(1)
            else:
                self.bag_tabs.setCurrentIndex(target[0])
                if target[1] is not None: self.dress_tabs.setCurrentIndex(target[1])
                section = "bag"
        pages = {"bag": (0, "背包"), "shop": (1, "商城"), "achievements": (2, "成就与等级奖励"),
                 "settings": (3, "设置")}
        if section != "home" and section not in pages: return
        was_hidden = self.drawer.isHidden(); old_width = 0 if was_hidden else self._drawer_extent
        self.drawer_animation.stop(); self.current_section = section; self.room.interact()
        if section != "home":
            index, title = pages[section]; self.tabs.blockSignals(True); self.tabs.setCurrentIndex(index); self.tabs.blockSignals(False)
            self.drawer_title.setText(title); self._place_drawer(); self.drawer.show()
        destination = 0 if section == "home" else self._drawer_target
        if animate and old_width != destination:
            self._set_drawer_width(old_width)
            self.drawer_animation.setStartValue(old_width); self.drawer_animation.setEndValue(destination); self.drawer_animation.start()
        else:
            self._set_drawer_width(destination); self._finish_drawer()
        if section == "home":
            self.home_scroll.verticalScrollBar().setValue(0); self.home_scroll.horizontalScrollBar().setValue(0)
        for key, button in self.nav_buttons.items():
            button.setChecked(key == section)
        self.refresh()

    def _drawer_selected(self, index):
        if hasattr(self, "nav_buttons"):
            if 0 <= index < 4: self.show_section(("bag", "shop", "achievements", "settings")[index], animate=False)

    def _page(self, title, tabs=None):
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget(); content.setObjectName("bookPage")
        body = QVBoxLayout(content); body.setContentsMargins(3, 8, 3, 10); body.setSpacing(12)
        scroll.setWidget(content); (self.tabs if tabs is None else tabs).addTab(scroll, plain_text(title))
        return body

    def _subtabs(self, name):
        tabs = QTabWidget(); tabs.setObjectName(name); tabs.setTabBar(NavigationTabBar(tabs)); tabs.setDocumentMode(True)
        tabs.tabBar().setExpanding(True); tabs.tabBar().setDrawBase(False)
        return tabs

    def _art(self, key, size=80):
        image = QLabel(); image.setAlignment(Qt.AlignmentFlag.AlignCenter); image.setPixmap(self.atlas.pixmap(key, size))
        image.setMinimumHeight(size); image.setObjectName("itemArtwork"); image.setProperty("icon_id", key); image.setProperty("art_size", size); return image

    def _item_card(self, key, title):
        frame, body = card(); body.addWidget(self._art(key, 72)); body.addWidget(label(title, "itemName"))
        return frame, body

    def _build_status(self):
        inventory = QWidget(); body = QVBoxLayout(inventory); body.setContentsMargins(0, 0, 0, 0)
        self.bag_tabs = self._subtabs("bagTabs"); body.addWidget(self.bag_tabs, 1)
        self.tabs.addTab(inventory, "背包")
        page = self._page("投喂与赠礼", self.bag_tabs)
        self.pet_name = label("", "sectionTitle"); page.addWidget(self.pet_name)
        self.level_label = label(""); self.exp_bar = QProgressBar(); self.hunger_bar = QProgressBar(); self.hunger_bar.setRange(0, 100)
        self.buff_label = label("", "buffBadge"); self.stats_label = label("", "muted")
        for widget in (self.level_label, self.exp_bar, self.hunger_bar, self.buff_label, self.stats_label):
            page.addWidget(widget)
            if widget is not self.stats_label: widget.hide()
        self.pet_name.hide()
        self.empty_inventory = label("背包还空着，给汤圆带点好吃的吧。", "muted"); page.addWidget(self.empty_inventory)
        grid = AdaptiveGrid(page.parentWidget()); grid.setSpacing(7)
        for i, (key, item) in enumerate(self.model.catalog.items.items()):
            frame, body = self._item_card(key, item["name"]); text = label("", "itemTag"); body.addWidget(text)
            use = self._button("赠送" if item["category"] == "gift" else "投喂")
            use.clicked.connect(lambda checked=False, k=key, origin=use: self._use_item(k, source=origin)); body.addWidget(use)
            grid.addWidget(frame, i // 2, i % 2); self.inventory_widgets[key] = frame, text, use
        self.inventory_grid = grid
        grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1); page.addLayout(grid)
        self.unknown_inventory = label("", "muted"); page.addWidget(self.unknown_inventory)
        page.addStretch()

    def _build_shop(self):
        shop = QWidget(); body = QVBoxLayout(shop); body.setContentsMargins(0, 0, 0, 0)
        self.market_description = label("挑一点喜欢的，带回家。", "muted"); body.addWidget(self.market_description)
        self.market_tabs = self._subtabs("marketTabs"); body.addWidget(self.market_tabs, 1)
        self.tabs.addTab(shop, "商城")
        self.shop_tabs = self._subtabs("shopTabs"); self.market_tabs.addTab(self.shop_tabs, "食品与礼物")
        self.shop_groups = {}
        for category, title in (("food", "食物"), ("gift", "礼物")):
            page = self._page(title, self.shop_tabs); grid = AdaptiveGrid(page.parentWidget()); grid.setSpacing(7)
            entries = sorted(((k, v) for k, v in self.model.catalog.items.items() if v["category"] == category), key=lambda row: row[1]["tier"])
            for i, (key, item) in enumerate(entries):
                frame, body = self._item_card(key, item["name"])
                details = label("", "itemTag"); self.shop_details[key] = details; body.addWidget(details)
                time = label("", "muted"); body.addWidget(time)
                line = QHBoxLayout(); buy = self._button("购买"); use = self._button("购买并赠送" if category == "gift" else "购买并投喂")
                use.setProperty("primary", True)
                buy.clicked.connect(lambda checked=False, k=key: self.model.buy_item(k))
                use.clicked.connect(lambda checked=False, k=key, origin=use: self._use_item(k, purchase=True, source=origin))
                line.addWidget(buy); line.addWidget(use); body.addLayout(line)
                grid.addWidget(frame, i // 2, i % 2); self.shop_buttons[key] = buy, use, time
            grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1); page.addLayout(grid); page.addStretch()
            self.shop_groups[category] = self.shop_tabs.widget(self.shop_tabs.count() - 1)
        self._furniture_market = self._page("家居家具", self.market_tabs)
        page = self._page("特技图鉴", self.market_tabs); self.shop_trick_buttons = {}
        for key, product in self.model.catalog.trick_products.items():
            frame, body = self._item_card(key, product["name"])
            body.addWidget(label("购买一次，永久学会", "itemTag")); status = label("", "muted"); body.addWidget(status)
            row = QHBoxLayout(); buy = self._button("学习特技"); perform = self._button("立即表演")
            buy.clicked.connect(lambda checked=False, k=key: self.model.buy_trick(k)); perform.clicked.connect(lambda checked=False, k=key: self.trick_requested.emit(k))
            row.addWidget(buy); row.addWidget(perform); body.addLayout(row); page.addWidget(frame)
            self.shop_trick_buttons[key] = buy, perform, status; self.shop_groups["trick"] = frame
        page.addStretch()

        page = self._page("战队与装扮", self.market_tabs)
        page.addWidget(label("等级免费解锁，也可提前购买；永久拥有。", "muted"))
        grid = AdaptiveGrid(page.parentWidget()); grid.setSpacing(7)
        self.team_skin_buttons = {}
        for index, (skin_id, product) in enumerate(self.model.catalog.team_skins.items()):
            frame, body = card()
            artwork = QLabel(); artwork.setObjectName("itemArtwork")
            artwork.setAlignment(Qt.AlignmentFlag.AlignCenter); artwork.setMinimumHeight(80)
            source = Path(__file__).resolve().parent / "assets/skins/teams_s16" / skin_id / "idle.png"
            pixmap = QPixmap(str(source))
            if not pixmap.isNull():
                artwork.setPixmap(pixmap.scaled(96, 80, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
            body.addWidget(artwork); body.addWidget(label(product["name"], "itemName"))
            body.addWidget(label(f"{product['region']} · Lv.{product['level']} 免费", "itemTag"))
            status = label("", "muted"); body.addWidget(status)
            row = QHBoxLayout(); buy = self._button("提前获得"); equip = self._button("换上")
            buy.clicked.connect(lambda checked=False, sid=skin_id: self.model.buy_team_skin(sid))
            equip.clicked.connect(lambda checked=False, sid=skin_id: self.skin_requested.emit(sid))
            row.addWidget(buy); row.addWidget(equip); body.addLayout(row)
            grid.addWidget(frame, index // 2, index % 2)
            self.team_skin_buttons[skin_id] = buy, equip, status
        page.addLayout(grid)
        self.accessory_shop_buttons = {}
        for accessory_id, product in self.model.catalog.accessory_products.items():
            frame, body = self._item_card(product["icon"], product["name"])
            body.addWidget(label(product["description"], "itemTag"))
            buy=self._button("永久收藏"); equip=self._button("穿戴")
            buy.clicked.connect(lambda checked=False, key=accessory_id:self.model.buy_accessory(key))
            equip.clicked.connect(lambda checked=False, key=accessory_id, slot=product["slot"]:self.accessory_requested.emit(slot,key))
            row=QHBoxLayout(); row.addWidget(buy); row.addWidget(equip); body.addLayout(row)
            page.addWidget(frame); self.accessory_shop_buttons[accessory_id]=(buy,equip)
        page.addStretch()

    def _build_achievements(self):
        progress = QWidget(); body = QVBoxLayout(progress); body.setContentsMargins(0, 0, 0, 0)
        self.progress_tabs = self._subtabs("progressTabs"); body.addWidget(self.progress_tabs, 1)
        self.tabs.addTab(progress, "成就与等级奖励")
        page = self._page("成就图鉴", self.progress_tabs)
        self.achievement_summary = label("", "sectionTitle"); page.addWidget(self.achievement_summary)
        self.tier_filter = IconChoice(self.atlas, "achievements", compact=True)
        # Filters use compact illustrated buttons, keeping the gallery itself large.
        self.tier_filter.addItems(["全部成就", "初识汤圆", "渐入佳境", "隐藏彩蛋"])
        self.tier_filter.currentIndexChanged.connect(self._filter_tiers)
        for index, art in enumerate(("achievements", "first_poke", "crown", "clone")):
            tile = self.tier_filter.buttons[index]
            tile.setIcon(self.atlas.icon(art)); tile.setProperty("icon_id", art)
            self.tier_filter.grid.removeWidget(tile); self.tier_filter.grid.addWidget(tile, 0, index)
        page.addWidget(self.tier_filter)
        for tier, title in enumerate(("初识汤圆", "渐入佳境", "隐藏彩蛋"), 1):
            group = QFrame(); group.setObjectName("achievementTier"); body = QVBoxLayout(group); body.setContentsMargins(0, 0, 0, 0)
            body.addWidget(label(title, "sectionTitle")); grid = AdaptiveGrid(body.parentWidget()); grid.setSpacing(7); self.tier_groups[tier] = group
            entries = [a for a in self.model.catalog.achievements if a["tier"] == tier]
            for i, achievement in enumerate(entries):
                aid = achievement["id"]; frame, content = self._item_card(aid, achievement["name"])
                frame.setToolTip(achievement["description"])
                reward = f"{achievement['coins']} 糯米币" + (f" / {achievement['title']}" if achievement.get("title") else "")
                content.addWidget(label(reward, "itemTag")); bar = QProgressBar(); bar.setRange(0, achievement["target"]); content.addWidget(bar)
                status = label("", "muted"); content.addWidget(status); claim = self._button(""); claim.setProperty("primary", True)
                claim.clicked.connect(lambda checked=False, a=aid: self.model.claim_achievement(a)); content.addWidget(claim)
                equip = self._button("前往背包换装"); equip.clicked.connect(lambda checked=False: self.show_section("titles")); content.addWidget(equip)
                grid.addWidget(frame, i // 2, i % 2); self.achievement_widgets[aid] = bar, status, claim, equip
            grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1); body.addLayout(grid); page.addWidget(group)
        page.addStretch()

    def _filter_tiers(self, index):
        for tier, group in self.tier_groups.items(): group.setVisible(index == 0 or index == tier)

    def _build_customization(self):
        dressing = QWidget(); body = QVBoxLayout(dressing); body.setContentsMargins(0, 0, 0, 0)
        self.dress_tabs = self._subtabs("dressTabs"); body.addWidget(self.dress_tabs, 1)
        self.bag_tabs.addTab(dressing, "换装")
        page = self._page("皮肤", self.dress_tabs)
        self.skin_combo = IconChoice(self.atlas); self.skin_combo.setObjectName("skinChoices")
        self.skin_combo.currentIndexChanged.connect(self._skin_selected); page.addWidget(self.skin_combo)
        self.skin_details = label("等级奖励和商城皮肤都收在这里。", "muted"); page.addWidget(self.skin_details)
        page.addWidget(label("皮肤大小（分别记忆）", "sectionTitle"))
        size_row = QHBoxLayout(); self.scale_slider = QSlider(Qt.Orientation.Horizontal); self.scale_slider.setRange(60, 150)
        self.scale_value = label("1.00x"); self.scale_slider.valueChanged.connect(lambda v: self.scale_requested.emit(v/100))
        size_row.addWidget(self.scale_slider, 1); size_row.addWidget(self.scale_value); page.addLayout(size_row); page.addStretch()
        page = self._page("挂件", self.dress_tabs)
        self.accessory_choices = {}
        for slot, title in (("head", "头部挂件"), ("face", "面部挂件"),
                            ("back", "背部挂件"), ("effect", "周身特效")):
            page.addWidget(label(title, "sectionTitle"))
            choice = IconChoice(self.atlas); choice.setObjectName(slot + "Choices")
            choice.currentIndexChanged.connect(
                lambda index, s=slot: self._accessory_selected(s, index))
            self.accessory_choices[slot] = choice; page.addWidget(choice)
        self.head_combo = self.head_choices = self.accessory_choices["head"]
        self.face_choices = self.accessory_choices["face"]
        self.back_choices = self.accessory_choices["back"]
        self.aura_choices = self.effect_choices = self.accessory_choices["effect"]
        # Compatibility adapters for existing controllers. Actual wardrobe choices
        # are the four registered slot grids above, with exactly one item per slot.
        self.face_check = IconTile("酷盖墨镜", "sunglasses", self.atlas, page.parentWidget())
        self.effect_check = IconTile("红温热气", "red_steam", self.atlas, page.parentWidget())
        for adapter in (self.face_check, self.effect_check):
            adapter.setCheckable(True); adapter.hide()
        self.face_check.toggled.connect(lambda on: self.accessory_requested.emit("face", "sunglasses" if on else ""))
        self.effect_check.toggled.connect(lambda on: self.accessory_requested.emit("effect", "steam" if on else ""))
        page.addWidget(label("挂件高度（每个皮肤独立记忆）", "sectionTitle")); line = QHBoxLayout()
        self.offset_slider = QSlider(Qt.Orientation.Horizontal); self.offset_slider.setRange(-30, 30); self.offset_slider.valueChanged.connect(self._offset_changed)
        self.offset_value = label("0 px"); line.addWidget(self.offset_slider, 1); line.addWidget(self.offset_value); page.addLayout(line)
        page.addStretch()
        page = self._page("称号", self.dress_tabs)
        self.title_combo = IconChoice(self.atlas, "title")
        self.title_combo.currentIndexChanged.connect(lambda i: self.model.equip_title(str(self.title_combo.itemData(i))))
        page.addWidget(self.title_combo); page.addStretch()

    def _build_tricks(self):
        page = self._page("特技", self.bag_tabs); grid = AdaptiveGrid(page.parentWidget(), 108, 4); self.trick_buttons = {}
        self.trick_descriptions = {}
        for i, (key, definition) in enumerate(self.model.catalog.trick_definitions.items()):
            perk = self.model.catalog.perks.get(definition.perk_id, {})
            product = self.model.catalog.trick_products.get(key, {})
            name = plain_text(product.get("name", perk.get("name", definition.name)))
            requirement = "商城永久学习" if product else f"Lv.{perk.get('level', 1)}"
            self.trick_descriptions[key] = (name, requirement)
            button = IconTile(name, definition.icon, self.atlas); button.badge = requirement
            button.clicked.connect(lambda checked=False, k=key: self.trick_requested.emit(k)); grid.addWidget(button, i // 2, i % 2); self.trick_buttons[key] = button
        page.addLayout(grid); self.trick_status = label("", "muted"); page.addWidget(self.trick_status)
        page.addStretch()

    def _build_rewards(self):
        page = self._page("等级奖励", self.progress_tabs)
        self.perk_summary = label("", "nextMilestone"); page.addWidget(self.perk_summary); grid = AdaptiveGrid(page.parentWidget()); self.milestone_widgets = {}
        for level in [m["level"] for m in self.model.catalog.milestones]:
            frame, body = self._item_card(f"level_{level}", f"Lv.{level}"); text = label("", "milestone"); body.addWidget(text)
            grid.addWidget(frame, (level - 1) // 2, (level - 1) % 2); self.milestone_widgets[level] = text
        page.addLayout(grid)
        self.debug_unlock_check = GameToggle("全部等级特权试用", "debug", self.atlas); self.debug_unlock_check.setObjectName("debugPerks")
        self.debug_unlock_check.toggled.connect(self.debug_unlock_requested.emit); self.debug_unlock_check.hide(); page.addWidget(self.debug_unlock_check); page.addStretch()

    def _build_settings(self):
        page = self._page("设置")
        self.dev_currency_label = label("开发模式：无限糯米币，购买不扣存档余额。", "muted")
        self.dev_currency_label.setWordWrap(True)
        page.addWidget(self.dev_currency_label)
        self.pin_check = GameToggle("固定桌宠位置", "desktop", self.atlas)
        self.dev_check = GameToggle("加速养成计时", "debug", self.atlas)
        self.flat_check = GameToggle("测试饿扁外观", "avatar", self.atlas)
        self.pin_check.toggled.connect(self.pin_requested.emit); self.dev_check.toggled.connect(self.dev_requested.emit); self.flat_check.toggled.connect(self.flat_requested.emit)
        self.release_debug_widgets=[self.dev_currency_label,self.dev_check,self.flat_check]
        for widget in (self.pin_check, self.dev_check, self.flat_check): page.addWidget(widget)
        for text, signal, art in (("重置桌宠位置", self.reset_requested, "desktop"), ("调试：饥饿归零", self.hunger_zero_requested, "avatar"),
            ("恢复满饱食度", self.hunger_full_requested, "sugar"), ("结算在线收入", self.gift_requested, "coin"), ("重新加载外观与图标", self.reload_requested, "dress")):
            button = self._button(text, art); button.clicked.connect(lambda checked=False, s=signal: s.emit()); page.addWidget(button)
            if signal != self.reset_requested: self.release_debug_widgets.append(button)
        self.room_debug = QFrame(); debug = QVBoxLayout(self.room_debug); debug.setContentsMargins(0, 4, 0, 0)
        debug.addWidget(label("房间日常预览（仅开发模式）", "sectionTitle"))
        self.activity_buttons = {}
        for key, text in (("window", "去看看窗外"), ("nap", "打盹与伸懒腰"), ("bowl", "去茶几闻一闻"), ("hum", "摇晃哼歌"), ("hop", "开心小跳")):
            button = self._button(text, "avatar")
            button.clicked.connect(lambda checked=False, k=key: self.room.start_activity(k)); debug.addWidget(button); self.activity_buttons[key] = button
        debug.addWidget(label("昼夜环境预览（仅本次运行）", "sectionTitle"))
        environment = QHBoxLayout(); self.environment_buttons = {}
        for key, text, mode in (("auto", "随电脑时间", None), ("day", "白天预览", True), ("night", "夜晚预览", False)):
            button = self._button(text); button.setCheckable(True); button.setChecked(key == "auto")
            button.clicked.connect(lambda checked=False, value=mode: self._preview_environment(value))
            environment.addWidget(button); self.environment_buttons[key] = button
        debug.addLayout(environment)
        self.preview_gift_buttons = {}
        debug.addWidget(label("礼物演出预览（不扣币、不加经验）", "sectionTitle"))
        for key, text in (("spinning_top", "试玩陀螺"), ("music_box", "试听八音盒"), ("paper_star", "看看折纸星星"), ("flower_bouquet", "闻闻花束"),
                          ("form_dice", "试玩状态骰子"), ("kiting_rope", "试玩拉扯弹力绳"),
                          ("summit_pickaxe", "试玩登山镐"), ("drama_clapper", "试玩短剧场记板"),
                          ("gnar_workbook", "翻翻纳尔练习册"), ("practice_hourglass", "试玩加练沙漏"),
                          ("fist_bump_glove", "试玩击拳手套")):
            button = self._button(text, key); self.preview_gift_buttons[key] = button
            button.clicked.connect(lambda checked=False, k=key: self.room.present_item({"item_id": k, "category": "gift", "duration": 7,
                "dialogue": self.model.dialogue(self.model.item(k).get("dialogue", "gift"))}))
            debug.addWidget(button)
        debug.addWidget(label("等级验收（仅演示存档建议使用）", "sectionTitle"))
        levels=QHBoxLayout()
        for level in (8,10,15,20,25,30):
            button=self._button(f"Lv.{level}"); button.clicked.connect(lambda checked=False,l=level:self.dev_level_requested.emit(l)); levels.addWidget(button)
        debug.addLayout(levels)
        self.room_debug.hide(); page.addWidget(self.room_debug)
        page.addWidget(label("数据安全与关于", "sectionTitle"))
        page.addWidget(label(APP_VERSION))
        self.data_directory_label=label("当前为独立预览；不写入正式存档。", "muted"); page.addWidget(self.data_directory_label)
        backup=self._button("一键备份存档", "bag"); backup.clicked.connect(self._pick_backup); page.addWidget(backup)
        restore=self._button("从备份恢复", "import_zip"); restore.clicked.connect(self._pick_restore); page.addWidget(restore)
        self.backup_status=label("恢复前会自动保留当前进度。", "muted"); page.addWidget(self.backup_status)
        for widget in self.release_debug_widgets: widget.hide()
        page.addStretch()

    def _pick_backup(self):
        filename,_=QFileDialog.getSaveFileName(self,"备份存档",f"汤圆备份-{timestamp()}.zip","汤圆备份 (*.zip)")
        if filename: self.backup_requested.emit(filename)

    def _pick_restore(self):
        filename,_=QFileDialog.getOpenFileName(self,"选择汤圆备份", "", "汤圆备份 (*.zip)")
        if filename and QMessageBox.question(self,"恢复进度","将使用备份中的进度和布置。当前进度会先自动备份。继续恢复？")==QMessageBox.StandardButton.Yes:
            self.restore_requested.emit(filename)

    def _preview_environment(self, mode):
        self.room.daytime_override = mode
        for key, button in self.environment_buttons.items():
            button.setChecked(key == ("auto" if mode is None else "day" if mode else "night"))
        self.room.update()

    def _build_furniture(self):
        page = self._page("装修", self.bag_tabs)
        self.furniture_buttons = {}; self.furniture_shop_buttons = {}
        for slot, title in (("theme", "房间主题"), ("rug", "坐垫与地毯"), ("wall", "墙面装饰"), ("corner", "角落摆件"), ("bowl", "茶几与食盆"), ("window", "窗边装饰"), ("companion", "小窝伴宠")):
            page.addWidget(label(title, "sectionTitle")); grid = AdaptiveGrid(page.parentWidget(), 108, 4); grid.setSpacing(7)
            entries = [(key, item) for key, item in self.model.catalog.furniture.items() if item["slot"] == slot]
            for i, (key, item) in enumerate(entries):
                tile = IconTile(item["name"], key, self.atlas); tile.setCheckable(True)
                tile.clicked.connect(lambda checked=False, s=slot, fid=key: self.furniture_requested.emit(s, fid))
                grid.addWidget(tile, i // 3, i % 3); self.furniture_buttons[key] = tile
            if slot in ("wall", "corner", "window", "companion"):
                clear = IconTile("收起装饰", "remove", self.atlas); clear.clicked.connect(lambda checked=False, s=slot: self.furniture_requested.emit(s, ""))
                grid.addWidget(clear, 0, len(entries))
            page.addLayout(grid)
        self.lamp_check = GameToggle("落地灯暖光", "lamp", self.atlas); self.lamp_check.toggled.connect(self.model.set_lamp_on); page.addWidget(self.lamp_check)
        to_shop = self._button("选购家具", "shop"); to_shop.clicked.connect(lambda: (self.show_section("shop"), self.market_tabs.setCurrentIndex(1))); page.addWidget(to_shop); page.addStretch()
        grid = AdaptiveGrid(page.parentWidget()); grid.setSpacing(7)
        for i, (key, item) in enumerate(self.model.catalog.furniture.items()):
            frame, body = self._item_card(key, item["name"]); body.addWidget(label("初始自带" if item["default"] else f"{item['price']} 糯米币", "itemTag"))
            button = self._button("购买家具"); button.clicked.connect(lambda checked=False, fid=key: self.model.buy_furniture(fid)); body.addWidget(button)
            grid.addWidget(frame, i // 2, i % 2); self.furniture_shop_buttons[key] = button
        grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1); self._furniture_market.addLayout(grid); self._furniture_market.addStretch()
    def set_phase4_context(self, skins: list[dict], dev_mode: bool = False) -> None:
        """Refresh locally validated wardrobe metadata supplied by the controller."""
        entries = [{"id": "default", "name": "白汤圆", "author": "默认皮肤"}]
        known = {"default"}
        for entry in skins:
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str) or entry["id"] in known:
                continue
            if entry["id"] not in TEAM_SKIN_IDS: continue
            known.add(entry["id"])
            entries.append({"id": entry["id"], "name": plain_text(entry.get("name", entry["id"]))[:120],
                            "author": plain_text(entry.get("author", "本地导入"))[:120], "directory": entry.get("directory")})
        self._skin_entries = entries
        self._skin_context_revision = getattr(self,"_skin_context_revision",0)+1
        self._phase4_dev_mode = bool(dev_mode)
        self.debug_unlock_check.setVisible(self._phase4_dev_mode)
        self.room_debug.setVisible(self._phase4_dev_mode)
        for widget in self.release_debug_widgets: widget.setVisible(self._phase4_dev_mode)
        self._refresh_phase4()

    def _has_perk(self, perk_id: str) -> bool:
        return bool(self.model.has_perk(perk_id))

    def _skin_selected(self, index: int) -> None:
        if index >= 0:
            self.skin_requested.emit(str(self.skin_combo.itemData(index)))

    def _head_selected(self, index: int) -> None:
        if index >= 0:
            self.accessory_requested.emit("head", str(self.head_combo.itemData(index)))

    def _accessory_selected(self, slot: str, index: int) -> None:
        choice = self.accessory_choices[slot]
        if 0 <= index < choice.count():
            self.accessory_requested.emit(slot, str(choice.itemData(index)))

    def _refresh_accessory_choices(self) -> None:
        """Only explicit renderer registrations can create wearable UI entries."""
        definitions = self.model.catalog.accessory_definitions
        for slot, choice in self.accessory_choices.items():
            selected = self.model.data.accessories.get(slot, "")
            entries = [("不佩戴", "", "remove", None, {})]
            for item_id, definition in definitions.items():
                if definition.slot != slot:
                    continue
                perk = self.model.catalog.perks.get(definition.perk_id, {})
                product = self.model.catalog.accessory_products.get(item_id, {})
                retired = bool(perk.get("retired") or product.get("retired") or not definition.newly_selectable)
                unavailable = (perk.get("enabled") is False or product.get("enabled") is False
                               or perk.get("available") is False or product.get("available") is False)
                if unavailable or (retired and item_id != selected):
                    continue
                name = plain_text(product.get("name", perk.get("name", definition.name or item_id)))
                entries.append((name, item_id, product.get("icon", perk.get("icon", definition.icon)), definition, perk))
            signature = [(entry[0], entry[1], entry[2]) for entry in entries]
            choice.blockSignals(True)
            try:
                if getattr(choice, "_registry_signature", None) != signature:
                    choice.clear()
                    for name, item_id, icon_id, _definition, _perk in entries:
                        choice.addItem(name, item_id, icon_id)
                    choice._registry_signature = signature
                choice.setCurrentIndex(max(0, choice.findData(selected)))
                for index, (_name, item_id, _icon, definition, perk) in enumerate(entries):
                    button = choice.buttons[index]
                    owned = not item_id or self._has_perk(definition.perk_id)
                    worn = bool(item_id and item_id == selected)
                    button.setEnabled(bool(owned))
                    button.badge = ("不佩戴" if not item_id else "已穿戴" if worn else "已拥有" if owned
                                    else "商城 / 等级奖励" if item_id in self.model.catalog.accessory_products
                                    else f"Lv.{perk.get('level', 1)}")
                    button.update()
            finally:
                choice.blockSignals(False)

    def _offset_changed(self, value: int) -> None:
        self.offset_value.setText(f"{value:+d} px" if value else "0 px")
        self.offset_requested.emit(value)

    def _refresh_phase4(self) -> None:
        data = self.model.data
        selected = data.selected_skin_id
        entries = [entry for entry in self._skin_entries if entry["id"] not in data.archived_skins]
        if selected in TEAM_SKIN_IDS and selected not in {entry["id"] for entry in entries}:
            entries.append({"id": selected, "name": "暂不可用的已选皮肤", "author": "请切换默认外观"})
        self.skin_combo.blockSignals(True)
        signature = [(entry["id"], entry["name"]) for entry in entries]
        current = [(self.skin_combo.itemData(i), self.skin_combo.itemText(i)) for i in range(self.skin_combo.count())]
        if signature != current or getattr(self,"_skin_rendered_revision",-1) != getattr(self,"_skin_context_revision",0):
            self._skin_rendered_revision=getattr(self,"_skin_context_revision",0)
            self.skin_combo.clear()
            for entry in entries:
                self.skin_combo.addItem(entry["name"], entry["id"], "avatar")
                if entry.get("directory"):
                    try:
                        renderer=SkinRenderer(Path(entry["directory"]))
                        frame=renderer.pixmaps.get(renderer.source_state(self._home_engine.state))
                        from pet_engine import PetState
                        frame=renderer.pixmaps.get(renderer.source_state(PetState.IDLE),frame)
                        if frame is not None: self.skin_combo.buttons[-1].setIcon(QIcon(frame))
                        renderer.stop()
                    except (OSError,ValueError,RuntimeError):
                        self.skin_combo.buttons[-1].setIcon(self.atlas.icon("avatar"))
        index = self.skin_combo.findData(selected)
        if index >= 0: self.skin_combo.setCurrentIndex(index)
        else:
            self.skin_combo._index = -1
            for button in self.skin_combo.buttons: button.setChecked(False)
        self.skin_combo.blockSignals(False)
        metadata = next((entry for entry in entries if entry["id"] == selected), entries[0])
        self.scale_slider.blockSignals(True); scale=self.model.skin_config()["scale_multiplier"]
        self.scale_slider.setValue(round(scale*100)); self.scale_value.setText(f"{scale:.2f}x"); self.scale_slider.blockSignals(False)
        self._refresh_accessory_choices()
        self.skin_combo.setEnabled(True)
        for index, button in enumerate(self.skin_combo.buttons):
            skin_id = self.skin_combo.itemData(index)
            button.setEnabled(self.model.can_use_skin(skin_id) or skin_id == selected)
            if skin_id in self.model.catalog.team_skins:
                product = self.model.catalog.team_skins[skin_id]
                button.badge = "已穿戴" if skin_id == selected else "已拥有" if self.model.has_team_skin(skin_id) else f"Lv.{product['level']}"
                button.update()
        for checkbox, value, perk in ((self.face_check, data.accessories.get("face") == "sunglasses", "accessory_sunglasses"),
                                      (self.effect_check, data.accessories.get("effect") == "steam", "effect_steam"),
                                      (self.debug_unlock_check, self.model.debug_unlock_all, "")):
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(value))
            checkbox.blockSignals(False)
            if perk:
                checkbox.setEnabled(self._has_perk(perk) or bool(value))
        self.face_check.badge = "已穿戴" if self.face_check.isChecked() else "Lv.5"
        self.effect_check.badge = "已穿戴" if self.effect_check.isChecked() else "Lv.4"
        self.face_check.update(); self.effect_check.update()
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
            button.setEnabled(self.model.can_perform_trick(key, replacing=True))
        for key, (buy, perform, status) in self.shop_trick_buttons.items():
            product = self.model.catalog.trick_products[key]
            owned = key in data.purchased_tricks
            buy.setText(" 已永久解锁" if owned else f"购买特技 · {product['cost']} 币")
            buy.setEnabled(not owned and self.model.can_afford(product["cost"]))
            perform.setEnabled(self.model.can_perform_trick(key, replacing=True))
            remaining = math.ceil(self.model.trick_cooldowns[key])
            status.setText("已学会 · 随时从商城、背包特技页或右键菜单发动" if owned else f"{product['cost']} 糯米币 · 购买一次永久拥有")
            if owned and remaining:
                status.setText(f"休息中 · 还需 {remaining} 秒；表演中点击汤圆可提前回家")
        self.trick_status.setText("肚子饿扁啦，投喂恢复后就能表演。" if self.model.starving else "正在表演，点击可结束，也可换一个已就绪的特技。" if self.model.trick_busy > 0 else "当前外观可以使用所有已解锁特技；绕屏后回到原位，途中点击可结束。")
        for skin_id, (buy, equip, status) in self.team_skin_buttons.items():
            product = self.model.catalog.team_skins[skin_id]
            owned = self.model.has_team_skin(skin_id)
            buy.setText("已拥有" if owned else f"{product['cost']} 币获得")
            buy.setEnabled(not owned and self.model.can_afford(product["cost"]))
            equip.setEnabled(owned and data.selected_skin_id != skin_id)
            equip.setText("已穿戴" if data.selected_skin_id == skin_id else "换上")
            status.setText("已永久收藏" if skin_id in data.owned_team_skins else "开发试用" if owned else f"Lv.{product['level']} 免费奖励")
        for accessory_id,(buy,equip) in self.accessory_shop_buttons.items():
            product=self.model.catalog.accessory_products[accessory_id]
            owned=self._has_perk("accessory_"+accessory_id)
            buy.setText("已拥有" if owned else f"{product['cost']} 币收藏")
            buy.setEnabled(not owned and self.model.can_afford(product["cost"]))
            equip.setEnabled(owned); equip.setText("已穿戴" if data.accessories.get(product["slot"])==accessory_id else "穿戴")
        self.perk_summary.setText(self.model.next_milestone()["text"] + (" 开发模式已临时解锁全部特权。" if self.model.debug_unlock_all else ""))
        milestones = {milestone["level"]: milestone for milestone in self.model.perk_status()}
        for level, widget in self.milestone_widgets.items():
            milestone = milestones.get(level, {})
            names = [self.model.catalog.perks[perk]["name"] for perk in milestone.get("perks", []) if perk in self.model.catalog.perks]
            description = "、".join(names) or "白汤圆皮肤 · 基础互动"
            unlocked = bool(milestone.get("unlocked", data.affection_level >= level))
            widget.setText(f"{'' if unlocked else ''} Lv.{level}  {milestone.get('label', '')}\n{description}")
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

    def refresh(self, _state=None):
        data = self.model.data
        self.balance.setText("无限" if self.model.unlimited_coins else str(data.coins))
        self.balance.setToolTip(f"开发模式：购买不扣币；存档实际余额 {data.coins} 糯米币" if self.model.unlimited_coins else f"{data.coins} 糯米币")
        self.pet_name.setText(plain_text(data.name))
        titles = [(plain_text(t), t) for t in data.titles]
        self.title_combo.blockSignals(True)
        if titles != self.title_combo.entries:
            self.title_combo.clear()
            for title, raw in titles: self.title_combo.addItem(title, raw)
        self.title_combo.setCurrentIndex(self.title_combo.findData(data.equipped_title)); self.title_combo.blockSignals(False)
        required = self.model.exp_required
        self.level_label.setText(f"Lv.{data.affection_level} · {data.affection_exp}/{required} EXP")
        self.exp_bar.setRange(0, required); self.exp_bar.setValue(required if data.affection_level == 30 else data.affection_exp)
        self.exp_bar.setFormat(f"好感 {data.affection_exp}/{required}")
        self.hunger_bar.setValue(round(data.hunger)); self.hunger_bar.setFormat(f"饱食度 {data.hunger:g}/100")
        buff = self.model.buff_view()
        self.buff_label.setText(f"{buff['name']} · {math.ceil(buff['remaining_seconds'])}秒" if buff else "")
        stats = data.stats
        self.stats_label.setText(f"戳戳 {stats['total_clicks']} · 投喂 {stats['total_feeds']} · 赠礼 {stats['total_presents']} 次 · 在线入账 {stats['total_gifts']}")
        owned = False
        for key, (frame, text, button) in self.inventory_widgets.items():
            item, count = self.model.item(key), data.inventory.get(key, 0)
            frame.setProperty("gridVisible", count > 0); frame.setVisible(count > 0); button.setEnabled(count > 0 and self.model.can_use_item(key)); owned |= count > 0
            effect = f"好感 +{item['exp']}" if item["category"] == "gift" else f"饱食度 +{item['hunger']:g}"
            text.setText(f"{item['tier']}级 · {effect} · 剩余 {count}" + (" · TES专属" if item.get("required_skin") else ""))
            button.setToolTip("请先换上TES皮肤" if item.get("required_skin") else "")
        self.inventory_grid.reflow()
        self.empty_inventory.setVisible(not owned)
        unknown = [f"{key} ×{count}" for key, count in data.inventory.items() if key not in self.model.catalog.items and count > 0]
        self.unknown_inventory.setText("保留物品：" + plain_text("、".join(unknown)) if unknown else ""); self.unknown_inventory.setVisible(bool(unknown))
        for key, (buy, use, time) in self.shop_buttons.items():
            item = self.model.item(key); effect = f"好感 +{item['exp']}" if item["category"] == "gift" else f"饱食度 +{item['hunger']:g}"
            self.shop_details[key].setText(f"{item['tier']}级 · {effect} · {item['cost']} 糯米币")
            buy.setEnabled(self.model.can_afford(item["cost"])); use.setEnabled(self.model.can_afford(item["cost"]) and self.model.can_use_item(key))
            use.setToolTip("先换上TES皮肤再演出" if item.get("required_skin") else "")
            time.setText("TES皮肤专属 · 7秒演出" if item.get("required_skin") else (f"{item['buff']['name']} · {self.model.rules.buff_seconds:g}秒") if "buff" in item else item.get("description", ""))
            time.setVisible("buff" in item or bool(item.get("required_skin")) or bool(item.get("description")))
        ready = set(data.unlocked_achievements) - set(data.claimed_achievements)
        self.achievement_summary.setText(f"收集 {len(data.unlocked_achievements)}/{len(self.model.catalog.achievements)} · 可领取 {len(ready)}")
        for achievement in self.model.catalog.achievements:
            aid = achievement["id"]; bar, status, claim, equip = self.achievement_widgets[aid]
            value, target = self.model.achievement_progress(achievement), achievement["target"]
            bar.setValue(value); bar.setFormat(f"{value}/{target}")
            claimed, unlocked = aid in data.claimed_achievements, aid in data.unlocked_achievements
            status.setText("已收集" if claimed else "达成了，领取礼物吧" if unlocked else "继续探索")
            claim.setText("已领取" if claimed else "领取奖励" if unlocked else "未达成"); claim.setEnabled(unlocked and not claimed)
            title = achievement.get("title"); equip.setVisible(bool(title) and claimed)
            equip.setEnabled(bool(title) and title in data.titles and title != data.equipped_title)
            equip.setText("已佩戴" if title == data.equipped_title else "前往背包换装")
        self._refresh_home(); self._refresh_phase4()

    def _refresh_home(self):
        data = self.model.data
        self.hud_name.setText(plain_text(data.name)); self.hud_name.setToolTip(plain_text(data.name))
        self.hud_title.setText(plain_text(data.equipped_title)); self.level_badge.setText(f"Lv.{data.affection_level}")
        required = self.model.exp_required
        self.hud_exp_bar.setRange(0, required); self.hud_exp_bar.setValue(required if data.affection_level == 30 else data.affection_exp)
        self.hud_exp_bar.setToolTip(self.model.next_milestone()["text"])
        self.exp_bar.setToolTip(self.model.next_milestone()["text"])
        self.hud_exp_bar.setFormat(f"好感 {data.affection_exp}/{required}" if data.affection_level < 30 else "好感满级")
        self.hud_hunger_bar.setValue(round(data.hunger)); self.hud_hunger_bar.setFormat(f"饱食 {data.hunger:g}/100")
        buff = self.model.buff_view()
        self.hud_buff.setText(f"{buff['name']} {math.ceil(buff['remaining_seconds'])}秒" if buff else "")
        self.hud_buff.setToolTip(self.hud_buff.text())
        self.hud_buff.setVisible(bool(buff))
        self.mute_button.blockSignals(True); self.mute_button.setChecked(data.muted)
        self.mute_button.setToolTip("已静音，点击开启音效" if data.muted else "音效开启，点击静音"); self.mute_button.blockSignals(False)
        self.overlay_button.blockSignals(True); self.overlay_button.setChecked(data.overlay_visible)
        self.overlay_button.setToolTip("隐藏桌面宠" if data.overlay_visible else "显示桌面宠"); self.overlay_button.blockSignals(False)
        any_food = False
        for key, button in self.feeding_buttons.items():
            count = data.inventory.get(key, 0); button.setText(f"×{count}"); button.setVisible(count > 0); button.setEnabled(count > 0); any_food |= count > 0
        self.shelf_empty.setVisible(not any_food); self.feeding_scroll.setVisible(any_food)
        for key, button in self.furniture_buttons.items():
            item = self.model.catalog.furniture[key]; owned = key in data.owned_furniture
            equipped = data.equipped_furniture.get(item["slot"]) == key
            button.blockSignals(True); button.setChecked(equipped); button.blockSignals(False)
            button.setEnabled(owned); button.badge = "已布置" if equipped else "未拥有" if not owned else "布置"; button.update()
        for key, button in self.furniture_shop_buttons.items():
            item = self.model.catalog.furniture[key]; owned = key in data.owned_furniture
            button.setText("已拥有" if owned else "等级奖励" if item.get("unlock_perk") else f"{item['price']} 币 · 购买"); button.setEnabled(not owned and not item.get("unlock_perk") and self.model.can_afford(item["price"]))
        self.lamp_check.blockSignals(True); self.lamp_check.setChecked(data.lamp_on); self.lamp_check.setEnabled(data.equipped_furniture.get("corner") == "warm_lamp"); self.lamp_check.blockSignals(False)
        if self._home_engine_owned:
            self._home_engine.skin_scale=self.model.skin_config()["scale_multiplier"]
            self._home_engine.set_starving(self.model.starving); self._home_engine.set_buff(self.model.buff_view()); self._home_renderer.set_accessories(self.model.effective_accessories())
        self._layout_hud()
        self.room.set_home_state(self.model.snapshot())
        accelerated = self.model.rules.hunger_seconds < 288
        if accelerated != self.room.life.accelerated:
            self.room.life.accelerated = accelerated
            self.room.life.wait = self.room.life._next_wait()
        renderer = self._renderer_provider(); source = renderer.source_state(self._home_engine.state)
        if source in renderer.pixmaps:
            self.hud_avatar.setPixmap(renderer.pixmaps[source].scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def reload_artwork(self):
        self.atlas._cache.clear(); self.atlas._stamps.clear()
        self._skin_rendered_revision=-1
        for widget in self.findChildren(QPushButton):
            key = widget.property("icon_id")
            if key: widget.setIcon(self.atlas.icon(key))
        for widget in self.findChildren(QLabel):
            key = widget.property("icon_id")
            if key: widget.setPixmap(self.atlas.pixmap(key, int(widget.property("art_size") or 80)))
        self.refresh(); self.room.update()

    def stop(self) -> None:
        self.room.stop()
        self.drawer_animation.stop()
        if self._home_engine_owned:
            self.preview_timer.stop()
        if self._home_renderer is not None:
            self._home_renderer.stop()

    def _feedback(self, text: str, _tone: str) -> None:
        self.notice.setText(plain_text(text))

    def summon(self):
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry(); width, height = max(1, area.width() - 24), max(1, area.height() - 40)
            self.setMinimumSize(min(580, width), min(500, height)); self.resize(min(self.width(), width), min(self.height(), height))
            frame = self.frameGeometry()
            self.move(max(area.left(), min(frame.left(), area.right() - frame.width() + 1)), max(area.top(), min(frame.top(), area.bottom() - frame.height() + 1)))
        self.show_section("home", animate=False)
        self.showNormal(); self.raise_(); self.activateWindow(); self.refresh()

    def hideEvent(self, event):
        if hasattr(self, "room"):
            self.foreground_cancel_requested.emit("dashboard_hidden")
        if hasattr(self, "drawer"): self.drawer.hide()
        super().hideEvent(event)

    def closeEvent(self, event: QCloseEvent):
        event.accept(); self.drawer.hide(); self.hide()
