"""Native navigation, tiered commerce and schema-5 independent-process restart."""
from __future__ import annotations
import argparse
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import traceback
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def worker(mode, file):
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QScrollArea
    from main import PetApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(['balance-native'])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet((ROOT/'styles/theme.qss').read_text(encoding='utf-8'))
    controller = PetApplication(app, save_path=file, skins_root=file.parent/'skins')
    pet, model, panel = controller.window, controller.model, controller.dashboard
    errors = []
    result = dict(mode=mode, platform=QGuiApplication.platformName(), dpr=pet.devicePixelRatioF())
    sys.excepthook = lambda typ, value, tb: (errors.append(''.join(traceback.format_exception(typ,value,tb))), app.exit(1))
    def capture(name):
        QTest.qWait(80)
        assert panel.grab().save(str(file.parent/(name+'.png')))
    def choose(tabs, index):
        QTest.mouseClick(tabs.tabBar(), Qt.MouseButton.LeftButton, pos=tabs.tabBar().tabRect(index).center())
        QTest.qWait(20)
        assert tabs.currentIndex() == index
    def click(button):
        for tabs in (panel.tabs, panel.dress_tabs):
            for index in range(tabs.count()):
                if tabs.widget(index).isAncestorOf(button):
                    tabs.setCurrentIndex(index)
                    break
        widget = button
        while widget.parentWidget() is not None:
            widget = widget.parentWidget()
            if isinstance(widget, QScrollArea): widget.ensureWidgetVisible(button)
        QTest.qWait(30)
        assert button.isVisible()
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    def begin():
        try:
            assert result['platform'] == 'windows'
            assert model.rules.hunger_seconds == 288
            assert model.data.equipped_title == '阿一古'
            assert pet.engine.pinned
            panel.summon()
            assert [panel.tabs.tabText(i) for i in range(5)] == ['状态与背包','免费商城','成就图鉴','装扮','设置']
            if mode == 'read':
                expected = json.loads((file.parent/'expected.json').read_text(encoding='utf-8'))
                for key in ('coins','hunger','affection_level','affection_exp','inventory','titles','equipped_title','stats','accessories'):
                    if key == 'stats':
                        for field in ('total_feeds','total_presents','total_gifts'): assert model.snapshot()[key][field] == expected[key][field]
                    else: assert model.snapshot()[key] == expected[key], key
                assert model.data.inventory['flower_bouquet'] == 1
                assert model.data.stats['total_presents'] == 4
                assert model.data.stats['total_feeds'] == 1
                assert model.data.stats['total_gifts'] == 0
                assert model.data.affection_level == 7 and model.data.affection_exp == 19
                assert model.effective_accessories()['head'] == 'crown'
                assert model.effective_accessories()['offset_y'] == -9
                assert json.loads(file.read_text(encoding='utf-8'))['future'] == {'preserve':True}
                capture('08-restart-status')
                result['new_balance_inventory_gifts_title_and_accessory_restart'] = True
                return
            assert (model.data.affection_level, model.data.affection_exp) == (6,287)
            assert model.exp_required == 3000
            assert '✨ 汤圆守护神' not in model.data.titles
            for _ in range(4):
                for index in range(5): choose(panel.tabs,index)
            result['twenty_native_tab_switches'] = True
            result['navigation_edges'] = []
            for width in (700,900,1100):
                panel.resize(width,760); QTest.qWait(60)
                bar, line = panel.tabs.tabBar(), panel.nav_divider
                left = bar.mapTo(panel,bar.tabRect(0).topLeft()).x()
                right = bar.mapTo(panel,bar.tabRect(4).topRight()).x()
                a = line.mapTo(panel,line.rect().topLeft()).x()
                b = line.mapTo(panel,line.rect().topRight()).x()
                assert abs(left-a)<=2 and abs(right-b)<=2
                result['navigation_edges'].append([width,left,right,a,b])
            panel.resize(900,760)
            choose(panel.tabs,3)
            for index in range(3): choose(panel.dress_tabs,index)
            choose(panel.dress_tabs,0); capture('01-dressing-wardrobe')
            choose(panel.dress_tabs,1)
            panel.head_combo.setCurrentIndex(panel.head_combo.findData('crown'))
            panel.offset_slider.setValue(-9)
            capture('02-dressing-accessories')
            choose(panel.dress_tabs,2); capture('03-dressing-tricks-rewards')
            choose(panel.tabs,4); capture('04-settings')
            choose(panel.tabs,1); panel.shop_filter.setCurrentIndex(1)
            capture('05-food-tiers')
            panel.shop_filter.setCurrentIndex(2)
            capture('06-gift-tiers-top')
            page=panel.tabs.currentWidget();page.verticalScrollBar().setValue(page.verticalScrollBar().maximum())
            capture('07-gift-tiers-bottom')
            hunger, exp, coins = model.data.hunger, model.data.affection_exp, model.data.coins
            click(panel.shop_buttons['paper_star'][0])
            assert model.data.inventory['paper_star'] == 1
            assert model.data.affection_exp == exp and model.data.coins == coins-20
            click(panel.inventory_widgets['paper_star'][2])
            assert model.data.affection_exp == exp+20 and model.data.hunger == hunger
            click(panel.shop_buttons['music_box'][1])
            assert model.data.affection_exp == exp+260 and model.data.hunger == hunger
            controller.hunger_zero_action.trigger()
            assert pet.engine.flat
            click(panel.shop_buttons['paper_star'][1])
            assert pet.engine.flat and model.data.hunger == 0
            before_food = model.data.affection_exp
            panel.shop_filter.setCurrentIndex(1)
            click(panel.shop_buttons['water'][1])
            assert model.data.hunger == 15 and not pet.engine.flat
            assert model.data.affection_exp == before_food
            model.data.affection_exp = 2999
            panel.refresh();panel.shop_filter.setCurrentIndex(2)
            before_coins=model.data.coins
            click(panel.shop_buttons['paper_star'][1])
            assert (model.data.affection_level,model.data.affection_exp)==(7,19)
            assert model.data.coins == before_coins-20+30
            click(panel.shop_buttons['flower_bouquet'][0])
            model.equip_title('阿一古')
            controller._save()
            saved=json.loads(file.read_text(encoding='utf-8'))
            assert saved['schema_version']==5
            assert len(list(file.parent.glob('save_data.json.bak.*'))) == 1
            (file.parent/'expected.json').write_text(json.dumps(model.snapshot(),ensure_ascii=False,indent=2),encoding='utf-8')
            result.update(three_food_and_gift_tiers=True,native_buy_and_give_buttons=True,
                          food_zero_exp_rescues=True,gift_exp_only=True,
                          legacy_level_exp_title_migration=True,upgrade_reward_once=True)
        except Exception:
            errors.append(traceback.format_exc())
        finally:
            controller.quit_action.trigger()
    QTimer.singleShot(250,begin)
    QTimer.singleShot(20000,lambda:(errors.append('native watchdog timeout'),controller.quit_action.trigger()))
    code=app.exec()
    result['errors']=errors
    result['clean_shutdown']=controller._stopped and not any(t.isActive() for t in (pet.timer,pet.click_timer,pet.bubble.timer,controller.tick_timer,controller.save_timer,controller.autosave_timer))
    (file.parent/(mode+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return int(bool(errors) or not result['clean_shutdown']) or code

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--worker',choices=('write','read'));parser.add_argument('--save-file',type=Path)
    args=parser.parse_args()
    if args.worker:return worker(args.worker,args.save_file)
    destination=ROOT/'tests/artifacts'/datetime.now().strftime('balance-native-%Y%m%d-%H%M%S-%f')
    destination.mkdir(parents=True,exist_ok=False)
    from PySide6.QtWidgets import QApplication
    app=QApplication(['balance-native-screen'])
    file=destination/'save_data.json'
    original={'schema_version':4,'coins':1000,'hunger':55,'affection_level':6,'affection_exp':287,
              'titles':['糯米团子','✨ 汤圆守护神'],'equipped_title':'✨ 汤圆守护神','future':{'preserve':True},
              'window':{'pinned':True,'screen':app.primaryScreen().name(),'x_ratio':.55,'y_ratio':.48}}
    file.write_text(json.dumps(original,ensure_ascii=False),encoding='utf-8')
    runs=[]
    for mode in ('write','read'):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(Path(__file__).resolve()),'--worker',mode,'--save-file',str(file)],cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        runs.append(dict(mode=mode,code=process.returncode,stdout=process.stdout,stderr=process.stderr))
        if process.returncode:break
    report=dict(passed=len(runs)==2 and all(r['code']==0 for r in runs),artifact_directory=str(destination),runs=runs)
    (destination/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BALANCE_NATIVE '+json.dumps(report,ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
