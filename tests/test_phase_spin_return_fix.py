"""Horizontal stationary gift spin, no leftover prop and room trick return anchors."""
from datetime import datetime
from pathlib import Path
import math, sys, unittest
from PySide6.QtCore import QEvent,QPointF,Qt
from PySide6.QtGui import QImage,QPainter
from PySide6.QtWidgets import QApplication
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dashboard import DashboardWindow
from home_scene import GiftPerformance,RoomPetView
from models import PetModel,PetData
from pet_engine import PetEngine,WorkArea,SkinRenderer
from verify_phase4_native import make_gif
APP=QApplication.instance() or QApplication(['spin-return-fix'])
APP.setQuitOnLastWindowClosed(False)
ART=ROOT/'tests/artifacts'/datetime.now().strftime('spin-return-unit-%Y%m%d-%H%M%S-%f');ART.mkdir(parents=True,exist_ok=False)

class SpinReturnTests(unittest.TestCase):
    def setUp(self):
        self.e=PetEngine(WorkArea(0,0,1800,1200));self.e.set_pinned(True)
        self.m=PetModel(PetData(coins=5000,affection_level=10,purchased_tricks=['screen_roll']))
        self.p=DashboardWindow(self.m,self.e);self.p.show();APP.processEvents()
        self.r=self.p.room;self.r._animation_timer.stop();self.r.life._blend_age=1
    def tearDown(self):
        self.p.stop();self.p.hide();self.p.deleteLater();APP.sendPostedEvents(None,QEvent.Type.DeferredDelete)
    def assertPoint(self,a,b):
        self.assertAlmostEqual(a.x(),b.x(),places=5);self.assertAlmostEqual(a.y(),b.y(),places=5)
    def prop_pixels(self):
        image=QImage(1000,600,QImage.Format.Format_ARGB32);image.fill(Qt.GlobalColor.transparent)
        p=QPainter(image);self.r._paint_gift(p,1000,600);p.end()
        rgba=image.convertToFormat(QImage.Format.Format_RGBA8888)
        return any(bytes(rgba.constBits())[3::4])
    def test_top_keeps_position_and_height_through_eight_horizontal_turns(self):
        self.r.life.x=.64;self.m.buy_item('spinning_top',True)
        before=self.r._render_foot();desktop=(self.e.x,self.e.y,self.e.elapsed,self.e.visual_angle)
        signs=set()
        for i in range(140):
            self.r.performance.age=i*.05
            self.assertPoint(self.r._render_foot(),before)
            self.assertEqual(self.r._view().visual_angle,self.e.visual_angle)
            self.assertEqual(self.r._local_pose(),(1,1,0,0))
            signs.add(self.r._view().yaw_scale>0)
        self.assertEqual(signs,{True,False});self.assertEqual(desktop,(self.e.x,self.e.y,self.e.elapsed,self.e.visual_angle))
    def test_yaw_transform_changes_x_without_tipping_or_flipping_vertically(self):
        renderer=self.r.renderer_provider();foot=QPointF(300,400)
        front=SkinRenderer.body_transform(RoomPetView(self.e),foot)
        for sx in (1,.065,-.065,-1):
            view=RoomPetView(self.e,yaw_scale=sx);transform=renderer.body_transform(view,foot)
            self.assertEqual(transform.m12(),0);self.assertEqual(transform.m21(),0)
            for point in (QPointF(-25,-20),QPointF(25,-100),QPointF(0,0)):
                self.assertAlmostEqual(transform.map(point).y(),front.map(point).y())
            self.assertEqual(transform.determinant()<0,sx<0)
    def test_spin_fit_is_constant_across_front_side_and_back(self):
        self.m.buy_item('spinning_top',True);self.p.resize(820,650);self.p.show_section('shop',animate=False);APP.processEvents()
        scales=[]
        for i in range(1,60):
            self.r.performance.age=i*.1;scales.append(self.r._pet_transform().m11())
            bounds=self.r.pet_bounds()
            self.assertGreaterEqual(bounds.left(),5);self.assertLessEqual(bounds.right(),self.r.width()-5)
        self.assertLess(max(scales)-min(scales),1e-8)
    def test_finished_top_does_not_leave_any_floor_icon_or_start_a_return_walk(self):
        self.r.life.x=.62;self.m.buy_item('spinning_top',True);self.r.advance_scene(1)
        self.assertTrue(self.prop_pixels());self.r.advance_scene(7)
        self.assertIsNone(self.r.performance);self.assertEqual(self.r._last_toy,'')
        self.assertFalse(self.prop_pixels());self.assertEqual(self.r.life.x,.62)
        self.assertEqual(self.r.life.state,'idle')
    def test_interrupted_top_leaves_no_prop(self):
        self.m.buy_item('spinning_top',True);self.r.advance_scene(2);self.r.interact(cancel_gift=True)
        self.assertFalse(self.prop_pixels());self.assertEqual(self.r._last_toy,'')
    def test_stale_top_marker_from_an_old_scene_is_not_painted(self):
        self.r._last_toy='spinning_top';self.assertFalse(self.prop_pixels())
    def test_queued_music_still_plays_after_top_without_moving_top_pet(self):
        self.r.life.x=.57;self.m.buy_item('spinning_top',True);self.m.buy_item('music_box',True)
        self.r.advance_scene(7.1)
        self.assertEqual(self.r.performance.item_id,'music_box')
        self.assertEqual(self.r.performance.start_x,.57);self.assertEqual(self.r._message,'听见你说~')
    def test_room_roll_route_approaches_and_returns_to_its_real_start_anchor(self):
        for x in (.34,.48,.61,.68):
            with self.subTest(x=x):
                self.r.life.x=x;self.r.life.interact();before=self.r._render_foot()
                self.assertTrue(self.e.perform_trick('screen_roll'))
                self.assertPoint(self.r._render_foot()+self.e.visual_offset,before)
                self.e.elapsed=self.e._trick_started+12
                self.assertPoint(self.r._render_foot()+self.e.visual_offset,before)
                self.e.advance(.001)
                self.assertPoint(self.r._render_foot(),before)
                self.r.advance_scene(1);self.assertPoint(self.r._render_foot(),before)
    def test_roll_cancellation_restores_current_room_position(self):
        for t in (.7,4,9,11.7):
            self.r.life.x=.63;before=self.r._render_foot();self.assertTrue(self.e.perform_trick('screen_roll'))
            self.r._render_foot();self.e.elapsed=self.e._trick_started+t;self.r._render_foot()
            self.e.cancel_trick();self.assertPoint(self.r._render_foot(),before)
    def test_other_explicit_tricks_also_keep_the_room_start_position(self):
        for trick in ('flip','clone','ball','disco'):
            self.r.life.x=.65;before=self.r._render_foot();self.assertTrue(self.e.perform_trick(trick))
            self.assertAlmostEqual(self.r._render_foot().x(),before.x())
            self.e.advance(self.e._trick_duration+.01)
            self.assertPoint(self.r._render_foot(),before)
    def test_room_location_returns_for_pinned_and_free_desktop_modes(self):
        for pinned in (True,False):
            self.e.set_pinned(pinned);self.e.grounded=True;self.e.x=900;self.e.y=self.e.area.bottom
            self.r.life.x=.60;before=self.r._render_foot();desktop=(self.e.x,self.e.y)
            self.assertTrue(self.e.perform_trick('screen_roll'));self.r._render_foot()
            for i in range(720):self.e.advance(1/60);self.r.advance_scene(1/60)
            self.e.advance(.01)
            self.assertPoint(self.r._render_foot(),before);self.assertEqual((self.e.x,self.e.y),desktop)
    def test_gif_crown_and_buff_share_horizontal_transform_and_fit(self):
        directory=ART/'animated';directory.mkdir()
        (directory/'idle.gif').write_bytes(make_gif())
        (directory/'manifest.json').write_text('{"name":"test","states":{"idle":"idle.gif"}}',encoding='utf8')
        renderer=SkinRenderer(directory);old=self.r.renderer_provider;self.r.renderer_provider=lambda:renderer
        try:
            renderer.set_accessories({'head':'crown','offset_y':-30})
            self.e.skin_scale=1.5;self.e.set_buff({'scale':1.2,'remaining_seconds':60,'color':'#f3a8b6'})
            self.m.buy_item('spinning_top',True)
            for i in range(1,60):
                self.r.performance.age=i*.1;bounds=self.r.pet_bounds()
                self.assertGreaterEqual(bounds.top(),self.p.hud.geometry().bottom()+4);self.assertLessEqual(bounds.bottom(),self.r.height()-10)
                self.assertTrue(self.r._hit_pet(self.r.pet_center()));self.r.grab()
            self.assertTrue(renderer.movies)
        finally:self.r.renderer_provider=old;renderer.stop()

if __name__=='__main__':unittest.main()
