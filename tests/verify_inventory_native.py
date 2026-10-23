"""Windows native walkthrough of the unified inventory; isolated saves only."""
from datetime import datetime
from pathlib import Path
import json
import sys

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from main import PetApplication
from models import PetData
from save_manager import SaveManager

app=QApplication([]);app.setQuitOnLastWindowClosed(False)
app.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf8'))
art=ROOT/'tests/artifacts'/datetime.now().strftime('inventory-native-%Y%m%d-%H%M%S-%f')
art.mkdir(parents=True,exist_ok=False)
profile=art/'save_data.json';saves=SaveManager(profile);saves.load_all()
saves.update_game(PetData(affection_level=15,coins=4000,hunger=68,muted=True,
    inventory={'sugar':3,'sesame':2,'tes_guitar':1,'tes_microphone':1}).to_dict())
c=PetApplication(app,save_path=profile,skins_root=art/'skins',dev_mode=False)
p=c.dashboard;c.window.timer.stop();c.tick_timer.stop();c.autosave_timer.stop()
p.room._animation_timer.stop();p.resize(1240,760);p.show();app.processEvents()

def capture(name):
    app.processEvents();image=p.grab()
    for target in (art/name,ROOT/'docs/images'/name):
        assert not target.exists(),target
        assert image.save(str(target),'PNG')
    assert p.room.isVisible() and p.drawer.isVisible() and not p.drawer.isWindow()
    print(str(ROOT/'docs/images'/name),flush=True)

try:
    c._select_skin('team_s16_tes')
    p.show_section('bag',animate=False);p.bag_tabs.setCurrentIndex(0);capture('inventory-bag.png')
    p.bag_tabs.setCurrentIndex(1);p.dress_tabs.setCurrentIndex(1)
    p.head_combo.buttons[p.head_combo.findData('crown')].click();p.offset_slider.setValue(-8)
    assert c.model.data.accessories['head']=='crown' and c.model.data.accessories['offset_y']==-8
    capture('inventory-dress.png')
    p.dress_tabs.setCurrentIndex(2);p.title_combo.setCurrentText('世一汤')
    assert c.model.data.equipped_title=='世一汤'
    assert c.model.buy_furniture('air_conditioner')
    p.bag_tabs.setCurrentIndex(2);p.furniture_buttons['air_conditioner'].click()
    assert c.model.data.equipped_furniture['wall']=='air_conditioner'
    assert p.furniture_buttons['air_conditioner'].text()=='空调'
    capture('inventory-furniture.png')
    p.show_section('achievements',animate=False);p.progress_tabs.setCurrentIndex(1)
    capture('inventory-growth.png')
    for index in range(p.progress_tabs.count()):
        p.progress_tabs.setCurrentIndex(index);app.processEvents();assert p.room.isVisible()
    p.nav_buttons['settings'].click();p.drawer_animation.setCurrentTime(220);app.processEvents()
    assert p.pin_check.isVisible() and p.room.isVisible()
    c._save();data,_=SaveManager(profile).load_all()
    assert data.equipped_furniture['wall']=='air_conditioner' and data.equipped_title=='世一汤'
    assert data.accessories['head']=='crown' and data.accessories['offset_y']==-8
    report={'platform':app.platformName(),'room_visible':p.room.isVisible(),'drawer_inside':not p.drawer.isWindow(),
        'main_pages':[p.tabs.tabText(i) for i in range(p.tabs.count())],
        'inventory':[p.bag_tabs.tabText(i) for i in range(p.bag_tabs.count())],
        'dressing':[p.dress_tabs.tabText(i) for i in range(p.dress_tabs.count())],
        'growth':[p.progress_tabs.tabText(i) for i in range(p.progress_tabs.count())],
        'saved':True,'private_profile':str(profile)}
    with (art/'report.json').open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print('NATIVE_INVENTORY_OK '+json.dumps(report,ensure_ascii=False),flush=True)
finally:
    c.stop();p.deleteLater();c.window.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
