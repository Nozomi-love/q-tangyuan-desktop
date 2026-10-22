"""Native Windows release walkthrough in an isolated retained profile."""
from pathlib import Path
import json,sys
from uuid import uuid4
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage,QColor
from PySide6.QtCore import QPointF,Qt
from PySide6.QtTest import QTest
from main import PetApplication
from test_phase4_skins import gif_bytes
work=Path(sys.argv[1]).resolve()
if not work.is_relative_to((ROOT/'tests/artifacts').resolve()):raise SystemExit('sandbox required')
work.mkdir(parents=True,exist_ok=False)
app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
app.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf-8'))
c=PetApplication(app,save_path=work/'save_data.json',skins_root=work/'skins',dev_mode=False)
c.tick_timer.stop();c.autosave_timer.stop();c.save_timer.stop();c.window.timer.stop()
assert not c.debug_menu.menuAction().isVisible()
c.dashboard.resize(1240,760);c.dashboard.summon();QTest.qWait(300)
report={'platform':app.platformName(),'dpr':c.dashboard.devicePixelRatioF(),'normal_debug_hidden':True,'checks':[]}
def shot(name):
    QTest.qWait(100);c.dashboard.grab().save(str(work/(name+'.png')))
try:
    c.dev_mode=True;c.dashboard.set_phase4_context(c.skin_manager.list_skins(),True)
    c._dev_level(30);c.model.set_overlay_visible(True);c.window.set_pinned(True)
    for slot,key in [('theme','camp_room'),('rug','royal_rug'),('window','sunny_chime'),('companion','sesame_friend')]:assert c.model.equip_furniture(slot,key)
    assert c.model.equip_accessory('head','orange');assert c.model.equip_accessory('effect','fireflies')
    c.dashboard.show_section('home',animate=False);shot('01-star-camp-companion')
    sounds=[];c.dashboard.room.sound_requested.connect(sounds.append)
    QTest.mouseClick(c.dashboard.room,Qt.MouseButton.LeftButton,pos=c.dashboard.room.chime_rect().center().toPoint());assert 'chime' in sounds
    c.window.engine.fireworks_until=0;c.window.engine.cancel_trick();assert c._perform_trick('disco')
    c.window.engine.advance(.8);c.dashboard.room.advance_scene(.8);c.window._sync_window();shot('02-disco')
    c.window.engine.cancel_trick();c.model.finish_trick('disco')
    png=work/'my-blue-pet.png';image=QImage(80,100,QImage.Format.Format_ARGB32);image.fill(QColor('#4d7899'));assert image.save(str(png))
    c._prepare_preview(str(png));assert c.model.data.selected_skin_id=='default'
    QTest.qWait(350);shot('03-import-preview');c._confirm_preview();first=c.model.data.selected_skin_id
    c.model.set_skin_scale(.7);c.model.set_accessory_offset(-21)
    gif=work/'my-dancing-pet.gif';gif.write_bytes(gif_bytes())
    c._prepare_preview(str(gif));c._confirm_preview();second=c.model.data.selected_skin_id
    c.model.set_skin_scale(1.5);c.model.set_accessory_offset(30);c.model.equip_accessory('head','crown')
    c._select_skin(first);assert c.model.skin_config()['scale_multiplier']==.7;assert c.model.data.accessories['offset_y']==-21
    c._select_skin(second);assert c.model.skin_config()['scale_multiplier']==1.5;assert c.model.data.accessories['offset_y']==30
    c.window.set_buff({'scale':1.2,'remaining_seconds':60,'color':'#ef9ab2','item_id':'sesame'})
    c.dashboard.show_section('dress',animate=False);shot('04-real-thumbnails-and-sliders')
    frames=set()
    for i in range(5):
        QTest.qWait(90)
        source=c.window.renderer.source_state(c.window.engine.state)
        frames.add(c.window.renderer.pixmaps[source].cacheKey())
    assert len(frames)>=2
    for trick in ('flip','clone','ball','disco'):
        c.window.engine.cancel_trick();c.model.trick_busy=0;c.model.trick_cooldowns[trick]=0
        assert c._perform_trick(trick)
        for progress in (.1,.25,.5,.75,.9):
            c.window.engine.elapsed=c.window.engine._trick_started+progress*c.window.engine._trick_duration
            c.window._sync_window()
            bounds=c.window.renderer.scene_bounds(c.window.engine,c.window.local_foot())
            assert c.window.rect().toRectF().contains(bounds), (trick,progress,bounds,c.window.rect())
        c.window.engine.cancel_trick();c.model.finish_trick(trick)
    c._rename_skin(second,'会跳舞的企鹅');c._archive_skin(second,True)
    assert c.model.data.selected_skin_id=='default';assert second in c.model.data.archived_skins
    c._archive_skin(second,False);assert c._select_skin(second)
    c.model.set_muted(True);c._save();backup=work/'my-backup.zip';c._export_backup(str(backup));assert backup.is_file()
    c.model.rename_pet('临时名字');c._save();c._restore_backup(str(backup))
    assert c.model.data.name=='白汤圆';assert c.model.data.selected_skin_id==second;assert c.model.data.muted
    c.dashboard.show_section('settings',animate=False);shot('05-about-backup')
    c.dashboard.hide();c.model.set_overlay_visible(False);c.wake();assert c.dashboard.isVisible() and c.window.isVisible()
    report['checks']=['window chime + sound','Lv30 furniture + companion','disco','PNG/GIF preview + real thumbnails','per-skin restore','animated GIF + crown + 1.5x + Buff + four tricks unclipped','rename + recycle + restore','backup + live restore + mute','wake both views']
    report['gif_frames']=len(frames);report['status']='OK'
finally:
    c.stop();(work/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('V2_FINAL_NATIVE_OK '+json.dumps(report,ensure_ascii=False))
