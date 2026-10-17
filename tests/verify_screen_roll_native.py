"""Two native Windows processes prove purchase, real 12s lap and restart ownership."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def worker(mode,file):
    from PySide6.QtCore import QElapsedTimer,QPointF,QRectF,Qt,QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from main import PetApplication
    from verify_phase4_native import make_gif
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication(['screen-roll-native']);app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf-8'))
    controller=PetApplication(app,save_path=file,skins_root=file.parent/'skins')
    pet,model,panel=controller.window,controller.model,controller.dashboard
    errors=[];result=dict(mode=mode,platform=QGuiApplication.platformName(),dpr=pet.devicePixelRatioF())
    sys.excepthook=lambda typ,val,tb:(errors.append(''.join(traceback.format_exception(typ,val,tb))),app.exit(1))
    def click(button):
        for tabs in (panel.tabs,panel.shop_tabs,panel.dress_tabs):
            for index in range(tabs.count()):
                if tabs.widget(index).isAncestorOf(button):tabs.setCurrentIndex(index);break
        node=button
        while node.parentWidget() is not None:
            node=node.parentWidget()
            if hasattr(node,'ensureWidgetVisible'):node.ensureWidgetVisible(button)
        QTest.qWait(40)
        assert button.isVisible() and button.isEnabled()
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
    def begin():
        try:
            assert result['platform']=='windows'
            home=pet.capture_position();native_home=pet.pos()
            if mode=='read':
                saved=json.loads((file.parent/'expected.json').read_text(encoding='utf-8'))
                for key in ('coins','purchased_tricks','selected_skin_id','accessories'):
                    assert model.snapshot()[key]==saved[key],key
                assert model.data.purchased_tricks==['screen_roll']
                assert model.has_trick('screen_roll') and controller.trick_actions['screen_roll'].isEnabled()
                before=model.data.coins;assert not model.buy_trick('screen_roll');assert model.data.coins==before
                assert pet.engine.active_trick=='' and pet.engine.pinned
                assert abs(home['x_ratio']-.55)<.001 and abs(home['y_ratio']-.5)<.001
                assert pet.renderer.movies
                result['permanent_purchase_gif_accessory_and_home_restored']=True
                return
            panel.summon();panel.tabs.setCurrentIndex(1);panel.shop_tabs.setCurrentIndex(0)
            buy,perform,status=panel.shop_trick_buttons['screen_roll']
            assert not perform.isEnabled()
            click(buy);assert model.data.coins==80;assert not buy.isEnabled();assert perform.isEnabled()
            assert panel.grab().save(str(file.parent/'01-screen-roll-shop.png'))
            gif=file.parent/'roll-pet.gif';gif.write_bytes(make_gif())
            panel.import_image_requested.emit(str(gif),False)
            assert pet.renderer.movies
            panel.head_combo.setCurrentIndex(panel.head_combo.findData('crown'))
            panel.offset_slider.setValue(-20)
            model.buy_item('sesame',True)
            assert model.data.coins==55 and pet.engine.buff['scale']==1.2
            click(perform);panel.hide()
            assert pet.engine.active_trick=='screen_roll'
            lands=pet.engine.landing_count;rect=pet.engine._roll_rect
            area=QRectF(pet.engine.area.left,pet.engine.area.top,pet.engine.area.width,pet.engine.area.height)
            trail=[];seen=set();frames=[]
            for movie in pet.renderer.movies.values():movie.frameChanged.connect(frames.append)
            watch=QElapsedTimer();watch.start()
            while pet.engine.active_trick and watch.elapsed()<15000:
                QTest.qWait(30)
                assert pet.capture_position()==home
                if pet.engine.active_trick!='screen_roll':break
                bounds=pet.renderer.scene_bounds(pet.engine,pet.local_foot())
                assert QRectF(pet.rect()).contains(bounds),bounds
                progress=pet.engine.trick_progress
                if 1/12<=progress<=11/12:
                    world=pet.renderer.scene_bounds(pet.engine,QPointF(pet.engine.x,pet.engine.y))
                    assert area.contains(world),(world,area)
                    center=pet.renderer.body_transform(pet.engine,QPointF(pet.engine.x,pet.engine.y)).map(QPointF(0,-58))
                    trail.append([center.x(),center.y()])
                    sides={'top':abs(center.y()-rect.top()),'right':abs(center.x()-rect.right()),
                           'bottom':abs(center.y()-rect.bottom()),'left':abs(center.x()-rect.left())}
                    for side,distance in sides.items():
                        if distance<.01 and side not in seen:
                            seen.add(side);assert pet.grab().save(str(file.parent/('roll-'+side+'.png')))
            assert pet.engine.active_trick=='' and 11500<=watch.elapsed()<15000
            assert seen=={'left','right','top','bottom'},seen
            assert pet.pos()==native_home and pet.capture_position()==home
            assert pet.engine.landing_count==lands and model.trick_busy==0
            assert len(set(frames))>=2
            result.update(real_lap_milliseconds=watch.elapsed(),visited_edges=sorted(seen),samples=len(trail),
                          gif_crown_and_1_2_buff_fit=True,home_restored=True,permanent_purchase_once=True)
            (file.parent/'trace.json').write_text(json.dumps(trail),encoding='utf-8')
            # A second native UI trigger verifies click-to-return, with no poke or drag.
            model.advance(21)
            panel.summon();panel.tabs.setCurrentIndex(3);panel.dress_tabs.setCurrentIndex(2)
            click(panel.trick_buttons['screen_roll']);panel.hide();QTest.qWait(1300)
            assert pet.engine.active_trick=='screen_roll'
            point=pet.renderer.body_transform(pet.engine,pet.local_foot()).map(QPointF(0,-58)).toPoint()
            pokes=model.data.stats['total_clicks']
            QTest.mouseClick(pet,Qt.MouseButton.LeftButton,pos=point)
            assert pet.engine.active_trick=='' and model.trick_busy==0
            assert pet.pos()==native_home and model.data.stats['total_clicks']==pokes
            assert pet.capture_position()==home
            controller._save()
            (file.parent/'expected.json').write_text(json.dumps(model.snapshot(),ensure_ascii=False,indent=2),encoding='utf-8')
            result['native_click_cancel_returns_without_poke']=True
        except Exception:errors.append(traceback.format_exc())
        finally:controller.quit_action.trigger()
    QTimer.singleShot(250,begin)
    QTimer.singleShot(24000,lambda:(errors.append('native watchdog timeout'),controller.quit_action.trigger()))
    code=app.exec();result['errors']=errors
    result['clean_shutdown']=controller._stopped and not any(t.isActive() for t in (pet.timer,pet.bubble.timer,pet.click_timer,controller.tick_timer,controller.save_timer,controller.autosave_timer))
    (file.parent/(mode+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return int(bool(errors) or not result['clean_shutdown']) or code

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',choices=('write','read'));parser.add_argument('--save-file',type=Path)
    args=parser.parse_args()
    if args.worker:return worker(args.worker,args.save_file)
    destination=ROOT/'tests/artifacts'/datetime.now().strftime('screen-roll-native-%Y%m%d-%H%M%S-%f');destination.mkdir(parents=True,exist_ok=False)
    from PySide6.QtWidgets import QApplication
    app=QApplication(['roll-screen-name']);file=destination/'save_data.json'
    original={'schema_version':5,'coins':200,'affection_level':6,'window':{'pinned':True,'screen':app.primaryScreen().name(),'x_ratio':.55,'y_ratio':.5}}
    file.write_text(json.dumps(original),encoding='utf-8')
    runs=[]
    for mode in ('write','read'):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'--worker',mode,'--save-file',str(file)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        runs.append(dict(mode=mode,code=process.returncode,stdout=process.stdout,stderr=process.stderr))
        if process.returncode:break
    report=dict(passed=len(runs)==2 and all(r['code']==0 for r in runs),artifact_directory=str(destination),runs=runs)
    (destination/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SCREEN_ROLL_NATIVE '+json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
