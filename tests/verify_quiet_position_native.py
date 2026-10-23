"""Native Windows check and separate-process pinned/free position restoration."""
from datetime import datetime
from pathlib import Path
import json
import sys
from unittest.mock import patch

from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from main import PetApplication
from pet_window import ProceduralAudio

app = QApplication([])
app.setQuitOnLastWindowClosed(False)
app.setStyleSheet((ROOT / 'styles/theme.qss').read_text(encoding='utf8'))
stage = sys.argv[1] if len(sys.argv) > 1 else 'exercise'
profile = (Path(sys.argv[2]).resolve() if len(sys.argv) > 2 else
           ROOT / 'tests/artifacts' / datetime.now().strftime('quiet-position-native-%Y%m%d-%H%M%S-%f'))
assert profile.is_relative_to(ROOT / 'tests/artifacts')
profile.mkdir(parents=True, exist_ok=True)
report = {'stage': stage, 'platform': app.platformName(), 'checks': []}

with patch.object(ProceduralAudio, 'play') as sound:
    c = PetApplication(app, profile / 'save_data.json', skins_root=profile / 'skins', dev_mode=True)
    e, r, m, p = c.window.engine, c.dashboard.room, c.model, c.dashboard
    c.tick_timer.stop()
    c.window.timer.stop()
    r._animation_timer.stop()
    try:
        assert app.platformName() == 'windows'
        if stage == 'exercise':
            p.resize(1240, 760)
            app.processEvents()
            m.set_muted(False)
            sound.reset_mock()
            m.data.affection_exp = m.exp_required - 1
            m.advance(m.rules.gift_seconds * 4 + .01)
            assert not sound.called
            assert m.data.stats['total_gifts'] == 4 and m.data.affection_level == 2
            report['checks'].append('passive income/level/achievement never call audio.play')
            m.data.coins = 50000
            m.data.affection_level = 15
            m.set_debug_unlock(True, authorized=True)
            assert m.buy_trick('screen_roll')
            c._select_skin('team_s16_tes')
            e.set_pinned(True)
            for key in ('music_box', 'flower_bouquet', 'tes_guitar', 'tes_microphone', 'paper_star', 'spinning_top'):
                r.life.x = .64
                r.life.interact()
                assert m.buy_item(key, True)
                r.advance_scene(1.5)
                assert r.performance is not None
                r.advance_scene(5.51)
                assert r.performance is None and abs(r.life.x - .64) < 1e-8
                assert abs(r._render_foot().x() - r._geometry()[1] * .64) < 1e-7
            report['checks'].append('six real gift transactions finish at their individual origins')
            assert m.buy_item('flower_bouquet', True)
            r.advance_scene(1.5)
            before = r.performance.pet_x
            assert c._perform_trick('screen_roll')
            assert r.performance is None
            e.advance(5)
            c.window._sync_window()
            e.advance(7.01)
            c.window._sync_window()
            r.advance_scene(.01)
            assert not r._room_trick and m.trick_busy == 0
            assert abs(r.life.x - before) < 1e-8
            for flag in ('held', 'starving'):
                setattr(e, flag, True)
                assert abs(r._render_foot().x() - r._geometry()[1] * before) < 1e-7
                setattr(e, flag, False)
            report['checks'].append('gift interrupted by real controller roll, completion and busy states keep room anchor')
            for side in (-1, 1):
                c.window.set_pinned(False)
                area = e.area
                x = area.left + 83 if side < 0 else area.right - 83
                e.place(x, area.bottom)
                e.grounded = True
                for _ in range(3):
                    e.click()
                    for _ in range(384):
                        e.advance(1 / 120)
                    assert abs(e.x - x) < 1e-7
                    assert abs(e.y - area.bottom) < 1e-7
                    c.window._sync_window()
                    local = c.window.local_foot()
                    mapped = c.window.mapToGlobal(local)
                    assert abs(mapped.x() - e.x) < 1e-7
            report['checks'].append('native window logical foot remains stable after six edge click/landing cycles')
            # Save a pinned position for the next independent process.
            c.window.set_pinned(True)
            area = e.area
            e.place(area.left + area.width * .43, area.top + area.height * .62)
            c.window._sync_window()
            m.set_muted(True)
            expected = {'pinned': c.window.capture_position()}
            (profile / 'expected.json').write_text(json.dumps(expected, indent=2), encoding='utf8')
            p.grab().save(str(profile / 'room-after-actions.png'))
        else:
            expected_file = profile / 'expected.json'
            expected = json.loads(expected_file.read_text(encoding='utf8'))
            key = 'pinned' if stage == 'read-pinned' else 'free'
            state = expected[key]
            restored = c.window.capture_position()
            assert restored['screen'] == state['screen']
            assert restored['pinned'] == state['pinned']
            for field in ('x_ratio', 'y_ratio'):
                assert abs(restored[field] - state[field]) < 1e-7, (restored, state)
            report['checks'].append('separate process restored ' + key + ' desktop location')
            if stage == 'read-pinned':
                c.window.set_pinned(False)
                area = e.area
                e.place(area.left + area.width * .36, area.top + area.height * .6)
                c.window._sync_window()
                expected['free'] = c.window.capture_position()
                expected_file.write_text(json.dumps(expected, indent=2), encoding='utf8')
            else:
                y = e.y
                e.advance(1 / 60)
                assert e.y > y
                report['checks'].append('free pet resumes gravity at remembered x without resetting to primary corner')
        c._dirty = True
        c._save()
        report['status'] = 'OK'
    finally:
        c.stop()
        (profile / (stage + '-report.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')

print(json.dumps(report, ensure_ascii=False))
print('Evidence: ' + str(profile))
