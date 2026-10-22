"""Native PNG/GIF gift spin and updated store prices; isolated data only."""
from datetime import datetime
from pathlib import Path
import json,sys,traceback
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from PySide6.QtCore import QEvent
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from main import PetApplication
from verify_phase4_native import make_gif


def main():
    folder=ROOT/'tests/artifacts'/datetime.now().strftime('gift-spin-native-%Y%m%d-%H%M%S-%f');folder.mkdir(parents=True)
    save=folder/'save_data.json';save.write_text(json.dumps({'schema_version':5,'coins':10000,'affection_level':6,
        'muted':True,'window':{'pinned':True,'x_ratio':.55,'y_ratio':.5}}),encoding='utf8')
    app=QApplication(['gift-spin-native']);app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf8'))
    c=PetApplication(app,save,skins_root=folder/'skins',dev_mode=True)
    p,r,m,e=c.dashboard,c.dashboard.room,c.model,c.window.engine
    result={'platform':QGuiApplication.platformName(),'dpr':p.devicePixelRatioF()}
    try:
        assert result['platform']=='windows'
        c.tick_timer.stop();c.window.timer.stop();r._animation_timer.stop();p.resize(1240,760)
        app.processEvents();p.show_section('shop',animate=False);p.shop_tabs.setCurrentIndex(1);app.processEvents()
        assert '540' in p.shop_details['spinning_top'].text()
        assert '540' in p.shop_details['music_box'].text()
        assert '-30' in c.feed_action.text()
        desktop=(e.x,e.y,e.pinned,e.elapsed);paid=m.data.coins
        p.shop_buttons['spinning_top'][1].click()
        assert m.data.coins==paid-540 and m.data.stats['total_presents']==1
        r.advance_scene(3.3);assert r._view().yaw_scale!=1 and r._view().visual_angle==0 and e.visual_angle==0
        QTest.qWait(250);p.grab().save(str(folder/'01-png-spinning.png'))
        assert desktop==(e.x,e.y,e.pinned,e.elapsed)
        r.performance=None;m.set_overlay_visible(True);paid=m.data.coins;p.shop_buttons['music_box'][1].click()
        assert m.data.coins==paid-540
        result['music_room_text']=r._message;result['music_overlay_text']=c.window.bubble._text
        assert r._message=='听见你说~' and c.window.bubble._text=='听见你说~'
        QTest.qWait(250);p.grab().save(str(folder/'02-music-caption.png'))
        result['price_and_exact_music_caption']=True
        gif=folder/'friend.gif';gif.write_bytes(make_gif());c._import_image(str(gif),False);c._confirm_preview()
        m.equip_accessory('head','crown');m.buy_item('sesame',True);r._food_age=100
        r.performance=None;m.buy_item('spinning_top',True)
        p.resize(820,650);p.show_section('shop',animate=False);app.processEvents()
        frames=[];bounds_checked=0
        for index,age in enumerate((1.0,1.8,2.6,3.3,3.37,4.4,5.5,6.5)):
            r.performance.age=age;rect=r.pet_bounds()
            assert rect.top()>=147 and rect.bottom()<=r.height()-10,(age,rect)
            assert rect.left()>=5 and rect.right()<=r.width()-5,(age,rect)
            image=r.grab().toImage();frames.append(bytes(image.constBits()));bounds_checked+=1
            if index in (3,4):p.grab().save(str(folder/f'03-gif-spin-{index}.png'))
        assert frames[3]!=frames[4]
        r.performance.age=2;m.set_overlay_visible(True)
        movie=next(iter(c.window.renderer.movies.values()));seen=[];movie.frameChanged.connect(seen.append)
        c.window._schedule_frame();r._animation_timer.start();QTest.qWait(850)
        assert len(seen)>=4,seen
        assert (e.x,e.y,e.pinned)==desktop[:3]
        result.update({'png_body_really_rotates':True,'gif_crown_sesame_spin_frames_differ':True,
            'gif_frames_with_both_views':len(seen),'clip_checks':bounds_checked,'pinned_position_preserved':True,'passed':True})
    except BaseException:result['error']=traceback.format_exc()
    finally:
        c.stop();p.deleteLater();c.window.deleteLater();app.sendPostedEvents(None,QEvent.Type.DeferredDelete)
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(result,ensure_ascii=False));print('Evidence: '+str(folder))
    return 0 if result.get('passed') else 1


if __name__=='__main__':raise SystemExit(main())
