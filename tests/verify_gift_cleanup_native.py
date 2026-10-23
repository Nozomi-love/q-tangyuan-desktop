"""Verify six gift lifecycles, neutral HUD and nickname-only skins on Windows."""
from pathlib import Path
from datetime import datetime
import json,sys
from PySide6.QtCore import Qt,QEvent
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from main import PetApplication
from models import PetData
from save_manager import SaveManager

app=QApplication([]);app.setQuitOnLastWindowClosed(False)
app.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf8'))
art=ROOT/'tests/artifacts'/datetime.now().strftime('gift-cleanup-native-%Y%m%d-%H%M%S-%f')
art.mkdir(parents=True,exist_ok=False)
save=SaveManager(art/'save_data.json');save.load_all()
save.update_game(PetData(affection_level=15,coins=5000,hunger=80,muted=True).to_dict())
c=PetApplication(app,save_path=save.path,skins_root=art/'skins',dev_mode=False)
p=c.dashboard;r=p.room
c.window.timer.stop();c.tick_timer.stop();c.autosave_timer.stop();r._animation_timer.stop()
c.window.engine.set_pinned(True);p.resize(1240,760);p.show();app.processEvents();r.life.wait=1000

def props_visible():
    image=QImage(1400,850,QImage.Format.Format_RGBA8888);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);r._paint_gift(painter,1400,850);painter.end()
    return any(bytes(image.constBits())[3::4])

def capture(name):
    app.processEvents();image=p.grab()
    for target in (art/name,ROOT/'docs/images'/name):
        if target.exists():
            continue
        assert image.save(str(target),'PNG')
    print('CAPTURE '+str(ROOT/'docs/images'/name),flush=True)

try:
    assert c._select_skin('team_s16_tes');p.show_section('home',animate=False)
    assert p.hud_buff.isHidden() and p.hud_buff.text()==''
    checked=[]
    for key in ('paper_star','flower_bouquet','music_box','spinning_top','tes_guitar','tes_microphone'):
        assert c.model.buy_item(key,True),key
        r.advance_scene(1.5);assert r.performance and props_visible(),key
        for _ in range(120):c.window.engine.advance(1/120)
        if key=='tes_guitar':capture('gift-cleanup-guitar.png')
        r.advance_scene(7);assert r.performance is None and not props_visible(),key
        assert r._last_toy=='';checked.append(key)
    capture('gift-cleanup-after.png')
    c.model.buy_item('sesame',True);p.refresh()
    assert p.hud_buff.isVisible() and '芝麻胖团' in p.hud_buff.text()
    c.model.advance(61);p.refresh();assert p.hud_buff.isHidden()
    r.advance_scene(3)
    for _ in range(120):c.window.engine.advance(1/120)
    QTest.qWait(3000)
    p.show_section('dress',animate=False);p.dress_tabs.setCurrentIndex(0)
    labels=[p.skin_combo.itemText(i) for i in range(p.skin_combo.count())]
    for sid,row in c.model.catalog.team_skins.items():
        assert row['name'] in labels and not row['name'].startswith(row['team'])
    capture('gift-cleanup-skins-stable.png')
    report={'platform':app.platformName(),'gifts_cleared':checked,'skin_names':labels,'neutral_hud_hidden':True,
            'real_buff_countdown_preserved':True,'save':str(save.path)}
    with (art/'report.json').open('x',encoding='utf8') as f:json.dump(report,f,ensure_ascii=False,indent=2)
    print('NATIVE_GIFT_CLEANUP_OK '+json.dumps(report,ensure_ascii=False),flush=True)
finally:
    c.stop();p.deleteLater();c.window.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
