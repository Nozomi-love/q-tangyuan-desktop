"""Native two-tab shop, real silent income, dialogue and independent restart."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import random
import subprocess
import sys
import traceback
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def worker(mode,file):
    from PySide6.QtCore import QEvent,QPointF,Qt,QTimer
    from PySide6.QtGui import QGuiApplication,QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication,QScrollArea
    from main import PetApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app=QApplication(['shop-dialogue-native']);app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf-8'))
    controller=PetApplication(app,save_path=file,skins_root=file.parent/'skins',accelerated=mode=='write')
    pet,model,panel=controller.window,controller.model,controller.dashboard
    errors=[];result=dict(mode=mode,platform=QGuiApplication.platformName(),dpr=pet.devicePixelRatioF())
    sys.excepthook=lambda typ,val,tb:(errors.append(''.join(traceback.format_exception(typ,val,tb))),app.exit(1))
    def capture(name,widget):
        QTest.qWait(50)
        assert widget.grab().save(str(file.parent/(name+'.png')))
    def click(button):
        for tabs in (panel.tabs,panel.shop_tabs,panel.dress_tabs):
            for i in range(tabs.count()):
                if tabs.widget(i).isAncestorOf(button):tabs.setCurrentIndex(i);break
        node=button
        while node.parentWidget() is not None:
            node=node.parentWidget()
            if isinstance(node,QScrollArea):node.ensureWidgetVisible(button)
        QTest.qWait(30)
        assert button.isEnabled() and button.isVisible()
        QTest.mouseClick(button,Qt.MouseButton.LeftButton)
    def begin():
        try:
            assert result['platform']=='windows'
            assert not model.has_collectible and not pet.bubble._showing_gift
            if mode=='read':
                expected=json.loads((file.parent/'expected.json').read_text(encoding='utf-8'))
                for key in ('coins','hunger','affection_level','affection_exp','inventory','stats','pending_reward'):
                    assert model.snapshot()[key]==expected[key],key
                assert model.data.inventory['spinning_top']==1
                assert model.data.pending_reward=={'coins':0,'remaining_seconds':0.0}
                before=model.data.coins;assert not model.claim_collectible();assert model.data.coins==before
                result['inventory_dialogue_stats_and_income_not_repeated_after_restart']=True
                return
            assert model.data.coins==1012 and model.data.stats['total_gifts']==1
            # Ten real seconds in accelerated mode: no click, no gift bubble.
            coins=model.data.coins
            QTest.qWait(10300)
            assert model.data.stats['total_gifts']==2
            assert 10<=model.data.coins-coins<=20
            assert not model.has_collectible and not pet.bubble._showing_gift
            assert not pet.bubble.isVisible()
            result['real_timer_auto_income_silent']=True
            controller.tick_timer.stop()
            panel.summon();panel.tabs.setCurrentIndex(1)
            assert [panel.shop_tabs.tabText(i) for i in range(2)]==['食物','礼物']
            result['shop_nav_edges']=[]
            for width in (700,900,1100):
                panel.resize(width,760);QTest.qWait(50)
                bar=panel.shop_tabs.tabBar()
                assert bar.tabRect(0).left()==0
                assert abs(bar.tabRect(1).right()-panel.shop_tabs.width()+1)<=2
                result['shop_nav_edges'].append([width,bar.tabRect(1).right(),panel.shop_tabs.width()])
            panel.resize(900,760);panel.shop_tabs.setCurrentIndex(0)
            capture('01-shop-food',panel)
            panel.shop_tabs.setCurrentIndex(1)
            click(panel.shop_buttons['spinning_top'][0])
            capture('02-shop-gift-top',panel)
            assert model.data.inventory['spinning_top']==1
            exp=model.data.affection_exp;hunger=model.data.hunger
            click(panel.inventory_widgets['spinning_top'][2])
            assert model.data.affection_exp==exp+240 and model.data.hunger==hunger
            assert pet.bubble._text=='陀螺收到，突然就想转起来了！'
            capture('03-gift-dialogue',pet.bubble)
            click(panel.shop_buttons['spinning_top'][0])
            panel.hide();model.rng=random.Random(1)
            body=pet.renderer.body_transform(pet.engine,pet.local_foot()).map(QPointF(0,-50)).toPoint()
            coins=model.data.coins
            QTest.mouseClick(pet,Qt.MouseButton.LeftButton,pos=body);QTest.qWait(240)
            assert model.data.coins==coins+2
            assert pet.bubble._text=='别急别急。'
            capture('04-poke-dialogue',pet.bubble)
            model.set_hunger(100);exp=model.data.affection_exp
            controller.feed_action.trigger()
            assert pet.bubble._text=='别吃，别吃，饿吗，饿死了吗。'
            assert model.data.hunger==100 and model.data.affection_exp==exp
            area=pet.active_screen.availableGeometry()
            assert area.contains(pet.bubble.geometry())
            capture('05-full-feed-dialogue',pet.bubble)
            # Actual pointer events cross the drag threshold and select its line.
            local=pet.renderer.body_transform(pet.engine,pet.local_foot()).map(QPointF(0,-50))
            origin=pet.mapToGlobal(local)
            for kind,delta in ((QEvent.Type.MouseButtonPress,QPointF()),(QEvent.Type.MouseMove,QPointF(-40,-35)),(QEvent.Type.MouseButtonRelease,QPointF(-40,-35))):
                pos=origin+delta
                button=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseMove else Qt.MouseButton.LeftButton
                buttons=Qt.MouseButton.NoButton if kind==QEvent.Type.MouseButtonRelease else Qt.MouseButton.LeftButton
                event=QMouseEvent(kind,pet.mapFromGlobal(pos),pos,button,buttons,Qt.KeyboardModifier.NoModifier)
                app.sendEvent(pet,event)
            assert pet.bubble._text=='你们是来抓我的吗？'
            capture('06-drag-dialogue',pet.bubble)
            controller._save()
            (file.parent/'expected.json').write_text(json.dumps(model.snapshot(),ensure_ascii=False,indent=2),encoding='utf-8')
            result.update(two_shop_tabs_and_independent_tricks=True,spinning_top_native_buy_give=True,
                          daily_coins_do_not_override_poke=True,full_feed_quote_no_exp=True,
                          drag_quote=True,legacy_pending_amount_settled_once=True)
        except Exception:errors.append(traceback.format_exc())
        finally:controller.quit_action.trigger()
    QTimer.singleShot(250,begin)
    QTimer.singleShot(22000,lambda:(errors.append('native watchdog timeout'),controller.quit_action.trigger()))
    code=app.exec();result['errors']=errors
    result['clean_shutdown']=controller._stopped and not any(t.isActive() for t in (pet.timer,pet.bubble.timer,pet.click_timer,controller.tick_timer,controller.save_timer,controller.autosave_timer))
    (file.parent/(mode+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return int(bool(errors) or not result['clean_shutdown']) or code

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--worker',choices=('write','read'));parser.add_argument('--save-file',type=Path)
    args=parser.parse_args()
    if args.worker:return worker(args.worker,args.save_file)
    destination=ROOT/'tests/artifacts'/datetime.now().strftime('shop-dialogue-native-%Y%m%d-%H%M%S-%f');destination.mkdir(parents=True,exist_ok=False)
    from PySide6.QtWidgets import QApplication
    app=QApplication(['native-screen-name']);file=destination/'save_data.json'
    original={'schema_version':5,'coins':1000,'affection_level':6,'pending_reward':{'coins':12,'remaining_seconds':18},
              'window':{'pinned':True,'screen':app.primaryScreen().name(),'x_ratio':.55,'y_ratio':.5}}
    file.write_text(json.dumps(original),encoding='utf-8')
    runs=[]
    for mode in ('write','read'):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'--worker',mode,'--save-file',str(file)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        runs.append(dict(mode=mode,code=process.returncode,stdout=process.stdout,stderr=process.stderr))
        if process.returncode:break
    report=dict(passed=len(runs)==2 and all(r['code']==0 for r in runs),artifact_directory=str(destination),runs=runs)
    (destination/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('SHOP_DIALOGUE_NATIVE '+json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
