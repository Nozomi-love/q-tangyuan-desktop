"""Windows hotfix check: horizontal spin, no leftover prop, home-position return."""
from pathlib import Path
from datetime import datetime
import json,sys,hashlib
from PySide6.QtCore import QPointF,Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from main import PetApplication
from verify_phase4_native import make_gif
ART=ROOT/'tests/artifacts'/datetime.now().strftime('spin-return-native-%Y%m%d-%H%M%S-%f');ART.mkdir(parents=True,exist_ok=False)
app=QApplication.instance() or QApplication([]);app.setQuitOnLastWindowClosed(False)
app.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf8'))
c=PetApplication(app,save_path=ART/'save_data.json',skins_root=ART/'skins',dev_mode=True)
e,r,m,p=c.window.engine,c.dashboard.room,c.model,c.dashboard
c.tick_timer.stop();c.window.timer.stop();c.save_timer.stop();r._animation_timer.stop()
p.resize(1240,760);p.show_section('home',animate=False);app.processEvents()
m.data.coins=10000;m.data.affection_level=10;m._publish(m.starving);m.set_muted(True);m.buy_trick('screen_roll')
c.window.set_pinned(True);m.set_overlay_visible(True)
report={'platform':app.platformName(),'dpr':p.devicePixelRatioF(),'checks':[]}
def close(a,b):return (a-b).manhattanLength()<.00001
def prop_visible():
    image=QImage(1000,600,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
    paint=QPainter(image);r._paint_gift(paint,1000,600);paint.end()
    rgba=image.convertToFormat(QImage.Format.Format_RGBA8888)
    return any(bytes(rgba.constBits())[3::4])
try:
    assert app.platformName()=='windows'
    desktop=(e.x,e.y,e.pinned);r.life.x=.62;m.buy_item('spinning_top',True);origin=r._render_foot()
    matrices=[]
    for i,age in enumerate((1.1,1.4,1.8,2.2,2.8,3.3,4.0,5.1,6.4)):
        r.performance.age=age;assert close(r._render_foot(),origin)
        view=r._view();assert view.visual_angle==e.visual_angle==0
        matrices.append(view.yaw_scale)
        if i in (0,1,4):p.grab().save(str(ART/('01-horizontal-'+str(i)+'.png')))
    assert min(matrices)<0<max(matrices)
    r.advance_scene(1);assert r.performance is None and r._last_toy=='' and not prop_visible()
    assert close(r._render_foot(),origin);p.grab().save(str(ART/'02-no-leftover.png'))
    report['checks'].append('stationary horizontal spin + no leftover prop')
    gif=ART/'my-animation.gif';gif.write_bytes(make_gif());c._import_image(str(gif),False);c._confirm_preview()
    m.equip_accessory('head','crown');m.set_skin_scale(1.5);m.buy_item('sesame',True);r._food_age=100
    r.life.x=.60;m.buy_item('spinning_top',True);r.performance.age=3.4
    movie=next(iter(c.window.renderer.movies.values()));frames=[];movie.frameChanged.connect(frames.append)
    QTest.qWait(600);assert len(frames)>=3
    assert r._view().visual_angle==0;r.grab().save(str(ART/'03-gif-crown-yaw.png'))
    r.interact(cancel_gift=True);assert not prop_visible()
    # Return is checked through the real controller and window finish signal.
    for section,x in (('home',.61),('shop',.66)):
        p.show_section(section,animate=False);app.processEvents()
        r.life.x=x;r.life.interact();start=r._render_foot();saved=c.window.capture_position()
        m.trick_cooldowns['screen_roll']=0
        assert c._perform_trick('screen_roll');assert close(r._render_foot()+e.visual_offset,start)
        e.advance(5);c.window._sync_window();r.advance_scene(.1)
        e.elapsed=e._trick_started+12
        assert close(r._render_foot()+e.visual_offset,start)
        e.advance(.001);c.window._sync_window()
        assert close(r._render_foot(),start);assert c.window.capture_position()==saved
        assert m.trick_busy==0 and not r._room_trick
        p.grab().save(str(ART/('04-return-'+section+'.png')))
    report['checks'].extend(['animated GIF + crown + 1.5x skin + Buff','real room route start/end + desktop saved position + model finish'])
    assert (e.x,e.y,e.pinned)==desktop
    report.update(status='OK',gif_frames=len(frames),horizontal_samples=matrices)
finally:
    c.stop();(ART/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print('SPIN_RETURN_NATIVE_OK '+json.dumps(report,ensure_ascii=False));print('Evidence: '+str(ART))
