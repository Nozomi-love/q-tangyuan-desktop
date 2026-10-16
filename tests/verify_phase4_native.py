"""Native GIF wardrobe, universal tricks and independent-process restart proof."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import struct
import subprocess
import sys
import time
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def make_gif():
    size=48
    data=b'GIF89a'+struct.pack('<HH',size,size)+b'\x81\x00\x00'+bytes([0,0,0,255,246,228,244,173,202,60,48,55])
    data+=b'\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00'
    for phase in range(2):
        data+=b'\x21\xf9\x04\x09\x0c\x00\x00\x00'
        data+=b'\x2c'+struct.pack('<HHHH',0,0,size,size)+b'\x00\x02'
        codes=[]
        for y in range(size):
            for x in range(size):
                inside=((x-23.5)/21)**2+((y-24)/20)**2<1
                color=(1+phase) if inside else 0
                if inside and ((x in (17,18,30,31) and y in (22,23,24)) or (21<=x<=26 and y==30)):
                    color=3
                codes.extend((4,color))
        codes.append(5)
        bits=0; count=0; compressed=bytearray()
        for code in codes:
            bits|=code<<count; count+=3
            while count>=8:
                compressed.append(bits&255);bits>>=8;count-=8
        if count: compressed.append(bits&255)
        for start in range(0,len(compressed),255):
            part=compressed[start:start+255];data+=bytes([len(part)])+part
        data+=b'\x00'
    return data+b'\x3b'

def worker(mode,file):
    from PySide6.QtCore import Qt,QTimer
    from PySide6.QtGui import QGuiApplication,QImage
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from main import PetApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication(['phase4-native'])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf-8'))
    controller=PetApplication(app,save_path=file,skins_root=file.parent/'skins',dev_mode=mode=='write')
    pet,model,panel=controller.window,controller.model,controller.dashboard
    result={'mode':mode,'platform':QGuiApplication.platformName(),'dpr':pet.devicePixelRatioF()}
    errors=[]
    sys.excepthook=lambda typ,val,tb:(errors.append(''.join(traceback.format_exception(typ,val,tb))),app.exit(1))
    def capture(name,widget):
        QTest.qWait(80)
        assert widget.grab().save(str(file.parent/(name+'.png')))
    def click(button):
        panel.tabs.currentWidget().ensureWidgetVisible(button)
        QTest.qWait(30)
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
    def begin():
        try:
            assert QGuiApplication.platformName()=='windows'
            assert pet.engine.pinned
            if mode=='read':
                saved=json.loads((file.parent/'expected.json').read_text(encoding='utf-8'))
                assert model.data.selected_skin_id==saved['selected_skin_id']
                assert model.effective_accessories()==saved['accessories']
                assert model.data.equipped_title=='百变星君'
                assert abs(pet.capture_position()['x_ratio']-.55)<.002
                assert abs(pet.capture_position()['y_ratio']-.55)<.002
                assert pet.renderer.movies
                QTest.qWait(350)
                assert any(m.state().name=='Running' for m in pet.renderer.movies.values())
                assert model.data.coins==saved['coins']
                panel.summon(); panel.tabs.setCurrentIndex(3)
                capture('restart-wardrobe',panel)
                capture('restart-gif-crown',pet)
                assert not model.claim_achievement('soul_infusion')
                result['custom_skin_gif_crown_offset_title_pin_restart']=True
                return
            panel.summon();panel.tabs.setCurrentIndex(3)
            assert panel.debug_unlock_check.isVisible() or panel.debug_unlock_check.parentWidget().isVisible()
            panel.debug_unlock_check.setChecked(True)
            assert model.debug_unlock_all
            assert model.data.affection_level==6
            gif=file.parent/'two-frame-pet.gif'
            gif.write_bytes(make_gif())
            panel.import_image_requested.emit(str(gif),False)
            assert model.data.selected_skin_id.startswith('user_')
            assert pet.renderer.movies
            frames=[]
            for movie in pet.renderer.movies.values(): movie.frameChanged.connect(frames.append)
            QTest.qWait(500)
            assert len(set(frames))>=2,frames
            panel.head_combo.setCurrentIndex(panel.head_combo.findData('crown'))
            panel.face_check.setChecked(True)
            panel.effect_check.setChecked(True)
            panel.offset_slider.setValue(-12)
            assert model.effective_accessories()=={'head':'crown','face':'sunglasses','effect':'steam','offset_y':-12}
            assert 'soul_infusion' in model.data.unlocked_achievements
            panel.tabs.setCurrentIndex(2)
            click(panel.achievement_widgets['soul_infusion'][2])
            model.equip_title('百变星君')
            panel.tabs.setCurrentIndex(3)
            panel.tabs.currentWidget().verticalScrollBar().setValue(0)
            capture('01-gif-wardrobe',panel)
            capture('02-gif-crown',pet)
            anchor=(pet.engine.x,pet.engine.y)
            before_exp=model.data.affection_exp
            click(panel.trick_buttons['flip'])
            assert pet.engine.active_trick=='flip'
            QTest.qWait(400)
            assert pet.engine.active_trick=='flip'
            capture('03-gif-flip',pet)
            assert (pet.engine.x,pet.engine.y)==anchor
            QTest.qWait(850)
            assert pet.engine.active_trick==''
            assert model.data.affection_exp==before_exp+5
            model.advance(5)
            controller.trick_actions['clone'].trigger()
            assert pet.engine.active_trick=='clone'
            QTest.qWait(500)
            capture('04-gif-clones',pet)
            QTest.qWait(2200)
            model.advance(5)
            controller.trick_actions['ball'].trigger()
            assert pet.engine.active_trick=='ball'
            QTest.qWait(700)
            capture('05-gif-ball',pet)
            QTest.qWait(4400)
            assert pet.engine.active_trick==''
            assert (pet.engine.x,pet.engine.y)==anchor
            model.buy_item('sesame',True)
            capture('06-gif-sesame-1.2-crown',pet)
            assert pet.engine.buff['scale']==1.2
            controller._save()
            with (file.parent/'expected.json').open('x',encoding='utf-8') as stream:
                json.dump(model.snapshot(),stream,ensure_ascii=False,indent=2)
            panel.close()
            assert not panel.isVisible() and pet.isVisible()
            result.update(gif_frames_advance=True,all_three_universal_tricks=True,
                          pinned_anchor_unchanged=True,soul_achievement_claim_once=True,
                          wardrobe_buttons_connected=True,frames=pet.frame_count)
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            controller.quit_action.trigger()
    QTimer.singleShot(250,begin)
    QTimer.singleShot(30000,lambda:(errors.append('native watchdog timeout'),app.quit()))
    code=app.exec()
    result['errors']=errors
    result['shutdown_clean']=controller._stopped and not any(t.isActive() for t in (pet.timer,pet.click_timer,pet.bubble.timer,controller.tick_timer,controller.save_timer,controller.autosave_timer))
    result['movies_stopped']=all(m.state().name=='NotRunning' for m in pet.renderer.movies.values())
    (file.parent/(mode+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return int(bool(errors) or not result['shutdown_clean'] or not result['movies_stopped']) or code

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',choices=['write','read']);parser.add_argument('--save-file',type=Path)
    args=parser.parse_args()
    if args.worker:return worker(args.worker,args.save_file)
    destination=ROOT/'tests/artifacts'/datetime.now().strftime('phase4-native-%Y%m%d-%H%M%S-%f')
    destination.mkdir(parents=True,exist_ok=False)
    from PySide6.QtWidgets import QApplication
    app=QApplication(['screen-name'])
    file=destination/'save_data.json'
    initial={'schema_version':3,'coins':1000,'affection_level':6,'window':{'pinned':True,'screen':app.primaryScreen().name(),'x_ratio':.55,'y_ratio':.55}}
    file.write_text(json.dumps(initial),encoding='utf-8')
    runs=[]
    for mode in ('write','read'):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'--worker',mode,'--save-file',str(file)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=40,creationflags=subprocess.CREATE_NO_WINDOW)
        runs.append({'mode':mode,'code':process.returncode,'stdout':process.stdout,'stderr':process.stderr})
        if process.returncode:break
    result={'passed':len(runs)==2 and all(r['code']==0 for r in runs),'artifact_directory':str(destination),'runs':runs}
    (destination/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PHASE4_NATIVE '+json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
