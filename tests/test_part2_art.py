"""Part 2 illustrations and transient practice stories, independent of game settlement."""
from __future__ import annotations

from datetime import datetime
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QTransform
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from illustrated_assets import ICON_IDS, IconAtlas
from item_expansion import (ALL_FOODS, ALL_GIFTS, NEW_FOODS, NEW_GIFTS, PART2_FOODS,
    PART2_GIFTS, PART2_ICONS, food_pose, gift_hit_rect, gift_pose, paint_food_extra,
    paint_gift_props)

APP = QApplication.instance() or QApplication(["part2-art-tests"])
APP.setQuitOnLastWindowClosed(False)
ART = ROOT / "tests/artifacts" / datetime.now().strftime("part2-art-%Y%m%d-%H%M%S-%f")
ART.mkdir(parents=True, exist_ok=False)


def digest(image):
    return hashlib.sha256(bytes(image.constBits())).hexdigest()


def nonempty(image):
    return sum(image.pixelColor(x, y).alpha() > 0 for y in range(image.height())
               for x in range(image.width()))


def perf(item, age, **kwargs):
    return SimpleNamespace(item_id=item, age=age, duration=7., fist_bumped=False,
                           fist_bump_age=-1., practice_combo=False, summit_combo=False,
                           training_theme=False, **kwargs)


def picture(draw):
    image = QImage(600, 440, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    try:
        draw(painter)
    finally:
        painter.end()
    return image


class IllustrationTests(unittest.TestCase):
    def test_ten_new_assets_are_unique_transparent_80px_illustrations(self):
        digests = set()
        for key in PART2_ICONS:
            with self.subTest(item=key):
                self.assertIn(key, ICON_IDS)
                image = QImage(str(ROOT / "assets/item_icons" / (key + ".png")))
                self.assertFalse(image.isNull())
                self.assertEqual((image.width(), image.height()), (80, 80))
                self.assertTrue(image.hasAlphaChannel())
                self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                self.assertEqual(image.pixelColor(79, 79).alpha(), 0)
                self.assertGreater(nonempty(image), 900)
                self.assertLess(nonempty(image), 5600)
                colors = {image.pixelColor(x, y).rgba() for y in range(80) for x in range(80)
                          if image.pixelColor(x, y).alpha() > 200}
                self.assertGreater(len(colors), 30)
                digests.add(digest(image))
        self.assertEqual(len(digests), 10)

    def test_vector_renderer_and_pngs_share_distinct_silhouettes(self):
        rendered = [IconAtlas.render(key).toImage() for key in PART2_ICONS]
        self.assertEqual(len({digest(image) for image in rendered}), 10)
        for image in rendered:
            self.assertEqual((image.width(), image.height()), (80, 80))
            self.assertGreater(nonempty(image), 900)

    def test_atlas_respects_an_artist_override_without_rewriting_bytes(self):
        folder = ART / "override"; folder.mkdir()
        target = folder / "seven_goggles.png"
        image = QImage(80, 80, QImage.Format.Format_ARGB32)
        image.fill(QColor("#39ab87")); self.assertTrue(image.save(str(target)))
        raw = target.read_bytes(); atlas = IconAtlas(folder)
        loaded = atlas.pixmap("seven_goggles").toImage()
        self.assertEqual(loaded.pixelColor(40, 40), QColor("#39ab87"))
        self.assertEqual(target.read_bytes(), raw)
        atlas.pixmap("seven_goggles", 160)
        self.assertEqual(target.read_bytes(), raw)

    def test_invalid_existing_png_is_preserved_and_uses_memory_fallback(self):
        folder = ART / "damaged"; folder.mkdir()
        target = folder / "practice_hourglass.png"; target.write_bytes(b"not-png")
        self.assertFalse(IconAtlas(folder).pixmap("practice_hourglass").isNull())
        self.assertEqual(target.read_bytes(), b"not-png")

    def test_historical_collections_remain_four_and_part_two_is_explicit(self):
        self.assertEqual(len(NEW_GIFTS), 4)
        self.assertEqual(len(NEW_FOODS), 4)
        self.assertFalse(NEW_GIFTS & PART2_GIFTS)
        self.assertFalse(NEW_FOODS & PART2_FOODS)
        self.assertEqual(ALL_GIFTS, NEW_GIFTS | PART2_GIFTS)
        self.assertEqual(ALL_FOODS, NEW_FOODS | PART2_FOODS)


class TransientStoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.atlas = IconAtlas(ROOT / "assets/item_icons")
        cls.foot = QPointF(235, 315)

    def props(self, state):
        return picture(lambda p: paint_gift_props(p, self.atlas, state, self.foot, 600, 440))

    def test_practice_poses_start_and_end_neutral_without_invalid_or_unbounded_values(self):
        for key in PART2_GIFTS:
            self.assertEqual(gift_pose(key, 0, 7), (1., 1., 0., 0.))
            self.assertEqual(gift_pose(key, 7, 7), (1., 1., 0., 0.))
            self.assertEqual(gift_pose(key, 8, 7), (1., 1., 0., 0.))
            for frame in range(421):
                sx, sy, angle, hop = gift_pose(key, frame/60, 7)
                self.assertTrue(all(math.isfinite(v) for v in (sx, sy, angle, hop)))
                self.assertTrue(.8 < sx < 1.2 and .8 < sy < 1.2)
                self.assertLessEqual(abs(angle), 12)
                self.assertTrue(-24 <= hop <= 0)

    def test_hourglass_has_three_bounded_jumps_and_then_settles(self):
        airborne = [gift_pose("practice_hourglass", i/60, 7)[3] < -.1 for i in range(421)]
        starts = sum(now and not previous for previous, now in zip([False] + airborne[:-1], airborne))
        self.assertEqual(starts, 3)
        self.assertEqual(gift_pose("practice_hourglass", 6.8, 7)[3], 0)

    def test_distinct_gifts_animate_but_are_empty_at_and_after_the_endpoint(self):
        middle = []
        for key in PART2_GIFTS:
            early, late = self.props(perf(key, 1.2)), self.props(perf(key, 5.5))
            self.assertGreater(nonempty(early), 700)
            self.assertGreater(nonempty(late), 400)
            self.assertNotEqual(digest(early), digest(late))
            self.assertEqual(nonempty(self.props(perf(key, 0))), 0)
            self.assertEqual(nonempty(self.props(perf(key, 7))), 0)
            self.assertEqual(nonempty(self.props(perf(key, 8))), 0)
            middle.append(digest(early))
            early.save(str(ART / (key + "-early.png")))
            late.save(str(ART / (key + "-late.png")))
        self.assertEqual(len(set(middle)), 3)

    def test_gift_painting_preserves_painter_state_and_never_mutates_performance(self):
        for key in PART2_GIFTS:
            state = perf(key, 3.1); original = dict(vars(state))
            def draw(p):
                p.translate(3, 4); p.setOpacity(.7)
                transform, opacity = p.transform(), p.opacity()
                paint_gift_props(p, self.atlas, state, self.foot, 600, 440)
                self.assertEqual(p.transform(), transform)
                self.assertAlmostEqual(p.opacity(), opacity)
            picture(draw)
            self.assertEqual(vars(state), original)

    def test_glove_invitation_hit_area_only_exists_until_it_is_used_or_auto_completed(self):
        self.assertTrue(gift_hit_rect(perf("fist_bump_glove", .2), self.foot).isEmpty())
        hit = gift_hit_rect(perf("fist_bump_glove", 1), self.foot)
        self.assertTrue(hit.contains(self.foot + QPointF(100, -60)))
        state = perf("fist_bump_glove", 2); state.fist_bumped = True; state.fist_bump_age = 1.9
        self.assertTrue(gift_hit_rect(state, self.foot).isEmpty())
        self.assertTrue(gift_hit_rect(perf("fist_bump_glove", 4.8), self.foot).isEmpty())
        self.assertTrue(gift_hit_rect(perf("gnar_workbook", 1), self.foot).isEmpty())

    def test_manual_and_automatic_fist_bumps_have_visual_responses_without_data_changes(self):
        clicked = perf("fist_bump_glove", 1.6)
        clicked.fist_bumped = True; clicked.fist_bump_age = 1.3
        automatic = perf("fist_bump_glove", 5.1)
        waiting = perf("fist_bump_glove", 1.6)
        before = (dict(vars(clicked)), dict(vars(automatic)))
        self.assertNotEqual(digest(self.props(clicked)), digest(self.props(waiting)))
        self.assertNotEqual(digest(self.props(automatic)), digest(self.props(waiting)))
        self.assertEqual((vars(clicked), vars(automatic)), before)

    def test_practice_combination_adds_only_transient_graphics(self):
        plain = perf("gnar_workbook", 5)
        combined = perf("gnar_workbook", 5); combined.practice_combo = True
        self.assertNotEqual(digest(self.props(plain)), digest(self.props(combined)))
        self.assertEqual(nonempty(self.props(perf("gnar_workbook", 7))), 0)

    def test_food_stories_are_distinct_and_end_with_no_remaining_pixels(self):
        bounds = QRectF(150, 170, 180, 150)
        frames = []
        for key in PART2_FOODS:
            def draw(age):
                return picture(lambda p: paint_food_extra(p, self.atlas, key, age, bounds))
            first, second = draw(.4), draw(1.4)
            self.assertGreater(nonempty(first), 400)
            self.assertNotEqual(digest(first), digest(second))
            self.assertEqual(nonempty(draw(0)), 0)
            self.assertEqual(nonempty(draw(3)), 0)
            self.assertEqual(nonempty(draw(7)), 0)
            frames.append(digest(second))
            second.save(str(ART / (key + ".png")))
        self.assertEqual(len(set(frames)), 2)

    def test_food_arrival_pose_is_optional_endpoint_neutral_and_cannot_move_the_pet(self):
        for key in (*PART2_FOODS, "sugar"):
            for age in (0, 3, 5):
                self.assertEqual(food_pose(key, age), (1., 1., 0., 0.))
            for age in (.1, .3, 1.3, 2.5):
                sx, sy, angle, hop = food_pose(key, age)
                self.assertTrue(all(math.isfinite(v) for v in (sx, sy, angle, hop)))
                self.assertLessEqual(abs(angle), 6)
                self.assertGreaterEqual(hop, -2)
        self.assertGreater(food_pose("late_practice_snack", .25)[2], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
