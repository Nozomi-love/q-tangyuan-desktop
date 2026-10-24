"""First collection: reusable vector artwork and bounded room-only performances."""
from __future__ import annotations

import math
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainterPath, QPen, QPolygonF


NEW_GIFTS = frozenset(("form_dice", "kiting_rope", "summit_pickaxe", "drama_clapper"))
NEW_FOODS = frozenset(("iced_cola", "early_champagne", "summit_lunch", "watchparty_popcorn"))
PART2_GIFTS = frozenset(("gnar_workbook", "practice_hourglass", "fist_bump_glove"))
PART2_FOODS = frozenset(("postmatch_noodles", "late_practice_snack"))
ALL_GIFTS = NEW_GIFTS | PART2_GIFTS
ALL_FOODS = NEW_FOODS | PART2_FOODS
PART2_ICONS = ("gnar_workbook", "practice_hourglass", "fist_bump_glove",
               "postmatch_noodles", "late_practice_snack", "seven_goggles",
               "kiting_scarf", "practice_room", "summit_wall", "reverse_flash")


def _paint_part2_icon(b, key):
    """Ten compact illustrations, with distinct silhouettes and material faces."""
    p = b.p
    if key == "gnar_workbook":
        b.poly([(10,20),(37,16),(40,21),(43,16),(70,20),(69,66),(43,62),(40,66),(37,62),(11,66)],"#cba47f","#a8805e")
        b.poly([(12,17),(36,13),(40,20),(40,61),(35,57),(13,62)],"#fff9e7","#eee1bd")
        b.poly([(40,20),(45,13),(68,17),(67,62),(45,57),(40,61)],"#fffdf2","#eaddbc")
        b.pen("#ba9a72",1.1); b.line(40,21,40,58)
        for y in (37,44,51):
            b.pen("#b8c8bb",.9); b.line(17,y,32,y-2)
        p.save(); p.translate(54,33); p.rotate(-20)
        b.poly([(-10,-5),(0,-1),(10,-5),(5,4),(0,2),(-5,4)],"#b6c3cf","#839aae")
        p.restore(); b.pen("#98b7a3",1.2); p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(44,34,19,15),185*16,155*16)
        for x in (48,55,62):
            b.pen("#b39168",.8); b.ellipse(x-2,52,4,4,"#dba989")
        b.shine(17,21,3,7)
    elif key == "practice_hourglass":
        b.rect(16,9,48,8,"#ead0a2",3,"#be9469")
        b.rect(16,64,48,8,"#d4ac78",3,"#b38256")
        b.pen("#986c4e",4); b.line(21,18,21,63); b.line(59,18,59,63)
        shape=QPainterPath(QPointF(27,18)); shape.lineTo(53,18)
        shape.cubicTo(53,32,44,35,43,39); shape.cubicTo(44,46,53,48,53,62)
        shape.lineTo(27,62); shape.cubicTo(27,48,36,46,37,39); shape.cubicTo(36,35,27,32,27,18)
        b.pen("#91aca9",1.5); b.fill("#f3fbf2","#c8dfcf"); p.drawPath(shape)
        b.poly([(30,23),(50,23),(42,34),(38,34)],"#e3bc78","#ca9a5b")
        b.poly([(29,59),(40,49),(51,59)],"#f1d393","#d2ae6e")
        b.pen("#d3ad69",1.1)
        for y in (38,42,46): b.line(40,y,40,y+1)
        b.shine(29,21,2,10)
    elif key == "fist_bump_glove":
        p.save(); p.translate(29,37); p.rotate(17)
        b.rect(-17,-19,31,34,"#efb49c",12,"#d78374")
        b.rect(-13,11,25,14,"#f5d9b7",4,"#d9b78e")
        b.ellipse(7,-5,11,17,"#e6a18e","#ce7d6e")
        b.pen("#b47865",.9); b.line(-12,-6,6,-6); b.shine(-10,-12,3,8); p.restore()
        p.save(); p.translate(58,45); p.rotate(-22)
        b.rect(-13,-17,25,29,"#c3dde1",10,"#83acb9")
        b.rect(-11,9,21,12,"#f7e2bd",3,"#d3b991")
        b.ellipse(-17,-4,10,15,"#a7cbd3","#7ba2b1")
        b.shine(-8,-11,2,6); p.restore()
        b.pen("#d4ad62",2); b.line(39,15,41,22); b.line(48,19,45,24)
    elif key == "postmatch_noodles":
        b.poly([(16,28),(64,28),(59,68),(23,68)],"#f2c58c","#cd905c")
        b.poly([(19,35),(61,35),(58,58),(22,58)],"#d6876e","#b76d58")
        b.rect(25,40,30,13,"#fff1d0",4,"#e9d6ad")
        b.ellipse(15,22,50,13,"#fff3cf","#d8bb87")
        b.ellipse(19,24,42,8,"#bb9665")
        b.pen("#f8dc92",1.4)
        for x in (24,33,42,51):
            curve=QPainterPath(QPointF(x,28)); curve.cubicTo(x-5,22,x+5,18,x+2,14); p.drawPath(curve)
        b.pen("#c4af8c",1.2)
        for x in (28,48):
            curve=QPainterPath(QPointF(x,15)); curve.cubicTo(x-5,10,x+5,9,x,5); p.drawPath(curve)
        b.pen("#e8ba77",1); b.line(26,60,55,60); b.shine(22,35,3,13)
    elif key == "late_practice_snack":
        b.poly([(8,45),(61,36),(73,60),(19,72)],"#b98b5d","#90684a")
        b.poly([(7,40),(60,32),(73,55),(19,66)],"#efd4a3","#cda777")
        b.poly([(13,42),(58,36),(65,52),(22,59)],"#f9e5ba","#d9bb86")
        b.poly([(21,49),(30,30),(41,47)],"#fff8e4","#e4d5b5")
        b.poly([(26,48),(26,40),(33,39),(34,48)],"#7c9a78","#5d8066")
        b.rect(45,24,15,26,"#c0d9ce",4,"#8eaea5"); b.ellipse(45,22,15,6,"#f5edd4")
        b.pen("#a3b9a5",1.3); p.setBrush(Qt.BrushStyle.NoBrush); p.drawArc(QRectF(57,28,9,13),-90*16,180*16)
        b.poly([(10,22),(24,19),(27,33),(13,35)],"#c0c9b3","#8fa58f")
        b.pen("#eee8cd",1); b.line(14,25,22,23); b.line(15,29,23,27)
        b.shine(48,29,2,8)
    elif key == "seven_goggles":
        b.pen("#82715d",5); b.line(9,34,70,34)
        b.rect(9,21,28,33,"#e5bc7b",9,"#c4955a")
        b.rect(43,21,28,33,"#e5bc7b",9,"#c4955a")
        b.rect(14,26,18,23,"#c6e1df",6,"#81aeb9")
        b.rect(48,26,18,23,"#c6e1df",6,"#81aeb9")
        b.pen("#98764c",3); b.line(37,32,43,32)
        b.pen("#fff9df",2.5); b.line(18,29,28,29,22,40); b.line(51,31,62,38)
        b.shine(17,44,3,2); b.shine(51,42,3,2)
    elif key == "kiting_scarf":
        left=QPainterPath(QPointF(27,34)); left.cubicTo(19,40,12,50,17,66)
        left.lineTo(30,62); left.cubicTo(24,53,32,44,41,40); left.closeSubpath()
        b.fill("#dba29a","#b66f74"); p.drawPath(left)
        right=QPainterPath(QPointF(40,32)); right.cubicTo(50,40,66,45,64,61)
        right.lineTo(51,58); right.cubicTo(55,49,41,46,33,43); right.closeSubpath()
        b.fill("#b2c9d2","#779eaf"); p.drawPath(right)
        b.ellipse(18,16,45,27,"#db9f96","#b76c70"); b.ellipse(25,21,31,15,"#edd6b8","#cab492")
        b.rect(33,32,16,15,"#d99e8d",6,"#ba7773")
        b.pen("#f7d5bd",1); b.line(23,43,21,57)
        b.pen("#dbe7df",1); b.line(48,44,57,52)
        b.pen("#80665b",1)
        for x in (18,22,26): b.line(x,64,x,69)
        for x in (53,57,61): b.line(x,59,x+1,64)
    elif key == "practice_room":
        b.poly([(9,21),(29,13),(70,20),(70,57),(28,65),(9,54)],"#cfb998","#ae9676")
        b.poly([(29,13),(70,20),(70,49),(29,43)],"#e6e4cb","#bbc5b5")
        b.poly([(9,21),(29,13),(29,43),(9,52)],"#aab9ac","#8b9f94")
        b.poly([(9,52),(29,43),(70,49),(51,69)],"#e1c390","#b99363")
        b.pen("#ad8f68",.9); b.line(29,44,23,61); b.line(43,46,38,64); b.line(57,48,52,65)
        b.rect(36,22,25,17,"#617d76",2,"#405f58")
        b.pen("#c7d6aa",1); b.line(40,34,46,27,50,32,57,25)
        b.ellipse(17,32,9,11,"#ecd3a3","#bc8b62"); b.ellipse(20,35,3,4,"#c67b6c")
        b.rect(40,51,16,8,"#d5b183",2); b.shine(37,25,5,2)
    elif key == "summit_wall":
        b.poly([(11,15),(60,10),(70,19),(69,66),(20,72),(11,64)],"#b39370","#86664e")
        b.poly([(15,18),(62,13),(65,62),(21,68)],"#b8beb1","#8b9f98")
        b.pen("#dddfbc",1.1); b.line(26,57,38,44,31,34,48,23,56,33)
        for x,y,c in ((26,55,"#c6856b"),(39,44,"#dbc17b"),(31,34,"#8bb2a2"),(49,23,"#c89977")):
            b.pen("#806950",1.3); b.poly([(x-5,y),(x-1,y-5),(x+5,y-3),(x+6,y+2),(x,y+5)],c)
        b.pen("#e5ddc4",.8)
        for x,y in ((21,23),(57,52),(48,61)): b.line(x,y,x+2,y+1)
        b.shine(18,23,2,9)
    elif key == "reverse_flash":
        b.poly([(28,19),(52,19),(52,11),(71,29),(52,47),(52,38),(29,38)],"#f8dfa0","#d2a65c")
        b.pen("#c19b63",1.2); b.line(35,24,51,24)
        b.dumpling(24,53,1.0,.45); b.dumpling(53,55,.76,1)
        b.pen("#d9b373",2)
        b.line(13,45,6,45); b.line(10,54,3,54); b.line(16,63,9,63)
        b.star(43,44,4,"#ffe8a5")
    else:
        return False
    return True


def paint_collection_icon(b, key):
    """Draw in the existing atlas's 80-unit coordinate system; no cached art is changed."""
    p = b.p
    if _paint_part2_icon(b, key):
        return True
    if key == "form_dice":
        b.poly([(17,25),(43,12),(65,26),(40,40)], "#fffbee")
        b.poly([(17,25),(40,40),(40,68),(17,53)], "#e8d6b6")
        b.poly([(40,40),(65,26),(65,53),(40,68)], "#f4e7cb")
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        p.drawText(QRectF(18,33,22,23), Qt.AlignmentFlag.AlignCenter, "3")
        p.drawText(QRectF(41,34,23,24), Qt.AlignmentFlag.AlignCenter, "9")
        b.ellipse(37,23,6,4,"#9b7656"); b.shine(22,28,3,9)
    elif key == "kiting_rope":
        p.setBrush(Qt.BrushStyle.NoBrush)
        for color,dy in (("#c27175",0),("#87a9bf",7)):
            b.pen(color,4); path=QPainterPath(QPointF(17,39+dy))
            path.cubicTo(31,17+dy,49,62+dy,63,39+dy); p.drawPath(path)
        b.pen(); b.ellipse(7,30,16,23,"#e9bc88"); b.ellipse(57,30,16,23,"#e9bc88")
        b.ellipse(12,35,6,13,"#fff1d7"); b.ellipse(62,35,6,13,"#fff1d7")
    elif key == "summit_pickaxe":
        p.save(); p.translate(40,42); p.rotate(28)
        b.rect(-4,-24,8,51,"#cc9b65",3)
        path=QPainterPath(QPointF(-30,-18)); path.quadTo(0,-40,30,-18)
        path.quadTo(0,-25,-30,-18); b.fill("#d6e5e4","#94a8b0"); p.drawPath(path)
        b.rect(-7,-26,14,10,"#b99162",3); p.restore()
        p.setBrush(Qt.BrushStyle.NoBrush); b.pen("#d88d58",3)
        p.drawEllipse(QRectF(48,49,23,17)); p.drawEllipse(QRectF(52,53,15,9))
    elif key == "drama_clapper":
        b.rect(12,27,57,39,"#727985",5,"#465263")
        p.save(); p.translate(12,27); p.rotate(-13)
        b.rect(0,-12,57,12,"#eaddc6",2)
        for x in (4,23,42): b.poly([(x,-12),(x+9,-12),(x+2,0),(x-4,0)],"#666878")
        p.restore(); b.pen("#ead8b3",1.5); b.line(22,43,58,43); b.line(22,53,48,53)
        b.star(58,57,5)
    elif key == "iced_cola":
        b.poly([(21,20),(60,20),(55,66),(26,66)],"#bbdeea","#97b4c2")
        b.poly([(25,32),(56,32),(52,62),(29,62)],"#9a634e","#634a45")
        for x,y in ((30,29),(43,31),(35,42)): b.rect(x,y,10,10,"#d8edf0",2)
        b.pen("#c9877b",3); b.line(45,43,49,12,60,9)
        b.pen(); b.ellipse(17,43,4,7,"#d8f0f4"); b.ellipse(61,53,4,7,"#d8f0f4"); b.shine(27,26)
    elif key == "early_champagne":
        b.rect(26,26,28,42,"#aecda0",10,"#64846b"); b.rect(33,14,14,24,"#d7bd7d",3)
        b.rect(28,43,24,17,"#fff0ce",3); b.star(40,51,6)
        p.save(); p.translate(53,12); p.rotate(25); b.rect(-5,-4,10,10,"#b78b62",2); p.restore()
        for x,y,r in ((23,17,3),(61,29,3),(19,31,2),(57,5,2)): b.ellipse(x,y,r*2,r*2,"#fae6a8")
    elif key == "summit_lunch":
        b.rect(8,28,64,39,"#c78969",7,"#aa6e54"); b.rect(12,32,56,29,"#f5e0bb",4)
        for x,y in ((24,49),(42,44),(56,50)):
            b.poly([(x-11,y+8),(x,y-14),(x+11,y+8)],"#fff8dd")
            b.poly([(x-5,y+8),(x-5,y),(x+4,y),(x+4,y+8)],"#6f8a67")
        b.pen("#8c7457",2); b.line(42,28,42,9); b.poly([(42,9),(57,13),(42,17)],"#de947a")
    elif key == "watchparty_popcorn":
        b.poly([(16,30),(65,30),(58,68),(23,68)],"#fff0d0")
        for x in (24,40,56): b.poly([(x-4,32),(x+3,32),(x+1,65),(x-4,65)],"#cf8279")
        for i in range(9):
            x=21+i%4*12; y=22+i//4*7
            b.ellipse(x-6,y-6,13,12,"#fff2bd","#e4c37d")
        b.shine(28,18,3,4)
    elif key == "cooling_cap":
        b.ellipse(13,45,57,14,"#ae7371"); b.rect(19,26,42,27,"#e6bba0",16,"#c5917a")
        b.ellipse(30,22,22,22,"#faf0d5"); p.save(); p.translate(41,33)
        for i in range(3): p.rotate(120); b.ellipse(-3,-12,7,13,"#9abdc4")
        p.restore(); b.ellipse(38,30,6,6,"#e7c67e"); b.shine(25,32,3,7)
    elif key == "demon_hood":
        b.poly([(16,33),(13,14),(29,24),(40,18),(52,24),(67,14),(64,40)],"#6e5360")
        b.ellipse(15,23,50,45,"#68535c","#433c4b"); b.ellipse(23,36,34,29,"#cf817b")
        b.dumpling(40,51,.8); b.pen("#cd8d79",2); b.line(21,39,28,30); b.line(58,39,53,31)
    elif key == "summit_backpack":
        b.rect(19,19,43,48,"#e0a065",11,"#bb7652"); b.rect(25,42,31,20,"#edb876",5)
        b.rect(30,13,21,10,"#dfb578",4); b.pen("#805b42",2); b.line(25,32,55,32)
        b.pen("#edcd91",3); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(QRectF(24,23,31,15))
        b.pen(); b.line(60,41,64,15); b.poly([(64,15),(74,20),(63,26)],"#e18b77"); b.shine(24,47,3,7)
    elif key == "mini_gnar_hat":
        for side in (-1,1):
            b.ellipse(40+side*22-13,15,26,33,"#d4ac7c"); b.ellipse(40+side*22-7,20,14,23,"#efc2ae")
        b.ellipse(17,30,46,33,"#d7b07e","#b08a60")
        b.rect(28,35,24,8,"#fff4d5",4); b.ellipse(25,33,7,12,"#fff4d5"); b.ellipse(49,33,7,12,"#fff4d5")
        b.shine(24,46,4,7)
    elif key == "esports_chair":
        b.rect(23,10,35,42,"#fff5e1",12,"#bbc9ce"); b.rect(30,18,21,18,"#c5807f",6)
        b.rect(17,48,46,12,"#d4a282",5); b.pen("#665749",3); b.line(40,60,40,69); b.line(40,67,22,73); b.line(40,67,59,73)
        b.line(16,41,16,53); b.line(64,41,64,53); b.shine(27,17,3,9)
    elif key == "training_dummy":
        b.ellipse(18,63,44,10,"#a7805d"); b.rect(36,43,8,24,"#c9996a",3)
        b.ellipse(19,12,42,43,"#f5deb2","#d2aa7b"); b.ellipse(27,20,26,27,"#c58072"); b.ellipse(35,28,10,11,"#f7e8c2")
        b.pen("#85674e",1); b.line(16,36,21,37); b.line(59,36,64,34)
    elif key == "tactics_screen":
        b.rect(7,14,66,44,"#6f5e52",5); b.rect(11,18,58,36,"#344e55",3)
        for x in (15,34,53): b.rect(x,25,12,21,"#9db8aa",2); b.line(x+2,40,x+6,33,x+9,37)
        b.pen("#7a6049",3); b.line(40,58,40,68); b.line(26,68,54,68); b.shine(15,20,15,2)
    elif key == "postmatch_studio":
        b.rect(7,10,66,59,"#b6a6ad",6)
        for x in (13,25,55): b.rect(x,17,8,37,"#756c7d",2)
        b.rect(35,18,16,23,"#8fa9b3",2); b.poly([(10,57),(70,57),(70,66),(10,66)],"#cfac86")
        b.rect(35,44,15,14,"#d2a27d",3); b.line(42,57,42,64)
    elif key == "red_steam":
        b.dumpling(40,52,1)
        for x in (22,40,58):
            b.pen("#ce7e72",3); path=QPainterPath(QPointF(x,30)); path.cubicTo(x-8,23,x+7,19,x,10); p.drawPath(path)
    elif key == "cleanse_orange":
        b.ellipse(21,23,38,38,"#f5b463","#df9447")
        for side in (-1,1): b.poly([(40+side*12,35),(40+side*31,40),(40+side*23,57),(40+side*8,52)],"#f8ca7f")
        b.leaf(43,25,70,size=.45); b.shine(30,29)
    elif key == "champion_spotlight":
        for side in (-1,1):
            b.poly([(40+side*25,14),(40+side*9,58),(40-side*9,58)],"#f2dca2")
            b.rect(40+side*25-7,9,14,10,"#a58d67",3)
        b.dumpling(40,49,.9); b.ellipse(17,65,46,5,"#e2c38a")
    else:
        return False
    return True


def gift_pose(item, age, duration, faces=(3,6,9)):
    """Endpoint-neutral poses, applied only through RoomPetView."""
    u = max(0., min(1., age / duration))
    if u == 0 or u == 1: return 1., 1., 0., 0.
    envelope = math.sin(math.pi * u) ** 2
    if item == "gnar_workbook":
        phase = (u * 3) % 1
        wave = math.sin(phase * math.pi) * envelope
        return 1. + .035 * wave, 1. - .035 * wave, math.sin(u * math.pi * 6) * 7 * envelope, -6 * wave
    if item == "practice_hourglass":
        # Three isolated jumps settle more quickly with every practice round.
        hop = 0.
        for start, height in ((.18, 20), (.37, 15), (.56, 10)):
            phase = (u - start) / .16
            if 0 < phase < 1:
                hop -= height * math.sin(phase * math.pi)
        tilt = math.sin(u * math.pi * 6) * 4 * max(0., 1-u/.75) * envelope
        return 1., 1., tilt, hop
    if item == "fist_bump_glove":
        anticipate = math.sin(min(1., u / .62) * math.pi) * envelope
        return 1. + .025 * anticipate, 1. - .025 * anticipate, -4 * anticipate, -3 * anticipate
    if item == "form_dice":
        size = {3:.74,6:1.,9:1.22}[faces[min(2, int(u * 3))]]
        scale = 1 + (size - 1) * envelope
        return scale, scale, 0., -5 * envelope
    if item == "kiting_rope":
        return 1., 1., math.sin(age * 5) * 8 * envelope, -abs(math.sin(age * 5)) * 7 * envelope
    if item == "summit_pickaxe":
        climb=min(1.,u/.55)
        descent=max(0.,min(1.,(1-u)/.25))
        descent=descent*descent*(3-2*descent)
        height=(54*climb+abs(math.sin(climb*math.pi*3))*10)*descent
        return 1., 1., math.sin(age * 4) * 4 * envelope, -height
    if item == "drama_clapper":
        return 1., 1., math.sin(age * 7) * 10 * envelope, -abs(math.sin(age * 3)) * 6 * envelope
    return 1., 1., 0., 0.


def paint_gift_props(p, atlas, perf, foot, width, height):
    """Temporary props: no retained floor marker, no data settlement."""
    item, t = perf.item_id, perf.age
    if item in PART2_GIFTS:
        _paint_practice_props(p, atlas, perf, foot)
        return
    opacity = min(1., t / .35, max(0., (perf.duration - t) / .7))
    p.save(); p.setOpacity(p.opacity() * opacity)
    x, y = foot.x(), foot.y()
    p.setPen(QPen(QColor("#79523b"), 2))
    if item == "form_dice":
        p.save(); p.translate(x+95,y-45); p.rotate(math.sin(t*8)*28 if t<1.5 else 0)
        p.drawPixmap(QRectF(-31,-31,62,62),atlas.pixmap(item),QRectF(0,0,80,80)); p.restore()
        p.setFont(QFont("Segoe UI",11,QFont.Weight.Bold)); p.setPen(QColor("#976b48"))
        p.drawText(QRectF(x-45,y-185,90,25),Qt.AlignmentFlag.AlignCenter,str(perf.dice_faces[min(2,int(t/perf.duration*3))])*3)
    elif item == "kiting_rope":
        path=QPainterPath(QPointF(x-90,y-20)); path.cubicTo(x-35,y-55,x+30,y+12,x+88,y-20)
        for color,dy in (("#c77778",0),("#8eafc1",5)):
            p.save(); p.translate(0,dy); p.setPen(QPen(QColor(color),3)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path); p.restore()
        p.setBrush(QColor("#e2bd86")); p.drawEllipse(QPointF(x-90,y-20),7,10); p.drawEllipse(QPointF(x+88,y-20),7,10)
    elif item == "summit_pickaxe":
        for i in range(3):
            p.setBrush(QColor("#e2bd90")); p.drawRoundedRect(QRectF(x-63+i*18,y-7-i*18,65,12),4,4)
        p.drawPixmap(QRectF(x+72,y-90,64,64),atlas.pixmap(item),QRectF(0,0,80,80))
        if t>perf.duration*.55:
            p.setPen(QPen(QColor("#876046"),2)); p.drawLine(QPointF(x+18,y-54),QPointF(x+18,y-94))
            p.setBrush(QColor("#dc9277")); p.drawPolygon(QPolygonF([QPointF(x+18,y-94),QPointF(x+43,y-84),QPointF(x+18,y-76)]))
    elif item == "drama_clapper":
        p.setBrush(QColor("#d5a0a0"))
        for side in (-1,1):
            p.drawRoundedRect(QRectF(x+side*173-17,y-163,34,153),8,8)
        p.drawPixmap(QRectF(x+112,y-62,57,57),atlas.pixmap(item),QRectF(0,0,80,80))
        p.setFont(QFont("Microsoft YaHei UI",9,QFont.Weight.Bold)); p.setPen(QColor("#875c4b"))
        p.drawText(QRectF(x-125,y-196,250,24),Qt.AlignmentFlag.AlignCenter,("第一幕 · 来了","第二幕 · 看操作","第三幕 · 什么都没发生")[min(2,int(t/perf.duration*3))])
    p.restore()


def _practice_progress(perf):
    return max(0., min(1., perf.age / max(.1, perf.duration)))


def gift_hit_rect(perf, foot):
    """Local room coordinates for the *visible* invitation, never a data action."""
    if (perf.item_id != "fist_bump_glove" or perf.age < .3
            or perf.age >= min(4.8, perf.duration-.7) or getattr(perf, "fist_bumped", False)):
        return QRectF()
    return QRectF(foot.x()+67, foot.y()-99, 70, 76)


def _draw_boomerang(p, at, angle, tint="#c9906e"):
    p.save(); p.translate(at); p.rotate(angle)
    p.setPen(QPen(QColor("#79523b"), 1.6, Qt.PenStyle.SolidLine,
                  Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    shape=QPainterPath(QPointF(-14,-7)); shape.quadTo(-5,-2,0,-1)
    shape.quadTo(7,-5,14,-8); shape.lineTo(10,3); shape.lineTo(0,6)
    shape.lineTo(-10,2); shape.closeSubpath(); p.setBrush(QColor(tint)); p.drawPath(shape)
    p.setPen(QPen(QColor("#f6dab6"),1)); p.drawLine(QPointF(-8,-2),QPointF(-2,1)); p.restore()


def _draw_stamp(p, center, filled, number):
    p.save(); p.setPen(QPen(QColor("#a3a486" if not filled else "#789176"),1.5))
    p.setBrush(QColor("#e8dfbd" if not filled else "#d4dfb4")); p.drawEllipse(center,10,10)
    if filled:
        p.setPen(QPen(QColor("#668063"),2.0,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
        path=QPainterPath(center+QPointF(-4,0)); path.lineTo(center+QPointF(-1,4)); path.lineTo(center+QPointF(5,-4)); p.drawPath(path)
    else:
        p.setFont(QFont("Segoe UI",8)); p.drawText(QRectF(center.x()-10,center.y()-10,20,20),Qt.AlignmentFlag.AlignCenter,str(number))
    p.restore()


def _paint_practice_props(p, atlas, perf, foot):
    """Practice stories are disposable graphics tied only to the current token."""
    t, duration = perf.age, max(.1, perf.duration)
    if not 0 <= t < duration:
        return
    opacity=max(0.,min(1.,t/.25,(duration-t)/.6))
    p.save(); p.setOpacity(p.opacity()*opacity)
    p.setPen(QPen(QColor("#79523b"),1.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap,Qt.PenJoinStyle.RoundJoin))
    x,y=foot.x(),foot.y(); u=_practice_progress(perf)
    if perf.item_id == "gnar_workbook":
        # Page remains near the floor; three short arcs belong to this gift only.
        p.drawPixmap(QRectF(x+58,y-37,83,66),atlas.pixmap("gnar_workbook"),QRectF(0,0,80,80))
        cycle=min(2,int(u*3)); phase=min(1.,max(0.,(u*3-cycle-.08)/.78))
        if 0 < phase < 1:
            reach=(53,70,58)[cycle]; arc=math.sin(phase*math.pi)
            bx=x+15+reach*arc; by=y-73-(34,27,44)[cycle]*arc
            # The last throw returns to precisely the same launch point.
            if cycle < 2: by+=(cycle*2-1)*10*math.sin(phase*math.tau)
            _draw_boomerang(p,QPointF(bx,by),phase*540)
            p.setPen(QPen(QColor(176,158,111,70),1)); p.setBrush(Qt.BrushStyle.NoBrush)
            arc_path=QPainterPath(QPointF(x+15,y-73)); arc_path.quadTo(x+reach+15,y-150,x+15,y-73); p.drawPath(arc_path)
        for i in range(3): _draw_stamp(p,QPointF(x-25+i*25,y-170),u >= (i+1)/3-.035,i+1)
        if getattr(perf,"practice_combo",False):
            p.setPen(QColor("#7b8c65")); p.setFont(QFont("Microsoft YaHei UI",9,QFont.Weight.Bold))
            p.drawText(QRectF(x-80,y-206,160,23),Qt.AlignmentFlag.AlignCenter,"三连练习")
    elif perf.item_id == "practice_hourglass":
        p.save(); p.translate(x+94,y-35)
        angle=180*min(1.,max(0.,t/.9))
        p.rotate(angle); p.drawPixmap(QRectF(-27,-37,54,74),atlas.pixmap("practice_hourglass"),QRectF(0,0,80,80)); p.restore()
        p.setPen(Qt.PenStyle.NoPen)
        if .14<u<.77:
            for i in range(7):
                phase=(t*1.2+i/7)%1; p.setBrush(QColor(215,180,111,int(160*(1-phase))))
                p.drawEllipse(QPointF(x+94,y-51+phase*32),1.4,2.1)
        for i in range(3): _draw_stamp(p,QPointF(x-25+i*25,y-166),u > .34+i*.19,i+1)
        if u>.78:
            p.setPen(QPen(QColor("#82976b"),1.4)); p.setBrush(QColor("#edf0d3"))
            p.drawRoundedRect(QRectF(x+56,y-104,76,27),7,7)
            p.setFont(QFont("Microsoft YaHei UI",10,QFont.Weight.Bold)); p.drawText(QRectF(x+56,y-104,76,27),Qt.AlignmentFlag.AlignCenter,"已练")
    else:
        # An unclicked invitation meets a second glove without rewarding input.
        clicked=bool(getattr(perf,"fist_bumped",False))
        hit_age=(max(.3,min(duration-.7,float(getattr(perf,"fist_bump_age",t))))
                 if clicked else min(4.8,duration-.7))
        after=t-hit_age
        invitation=QRectF(x+67+math.sin(t*2)*2,y-99,70,76)
        if not clicked or after < .8:
            p.save(); p.translate(invitation.center()); p.rotate(-12+math.sin(t*2)*3)
            p.drawPixmap(QRectF(-35,-38,70,76),atlas.pixmap("fist_bump_glove"),QRectF(0,0,80,80)); p.restore()
        if after>=0:
            response_x=x+15+69*min(1.,after/.25)
            p.save(); p.translate(response_x,y-66); p.scale(-1,1)
            p.drawPixmap(QRectF(-22,-25,44,49),atlas.pixmap("fist_bump_glove"),QRectF(0,0,80,80)); p.restore()
            burst=max(0.,1-after/.8)
            p.setPen(QPen(QColor("#d2ac63"),2))
            for i in range(6):
                angle=i*math.tau/6; start=QPointF(x+87+math.cos(angle)*17,y-70+math.sin(angle)*17)
                end=start+QPointF(math.cos(angle)*13*burst,math.sin(angle)*13*burst)
                if burst>0:p.drawLine(start,end)
        elif t>.6:
            p.setPen(QColor("#957450")); p.setFont(QFont("Microsoft YaHei UI",9))
            p.drawText(QRectF(x+48,y-125,110,24),Qt.AlignmentFlag.AlignCenter,"碰一下")
    p.restore()


def food_pose(item, age):
    """Small arrival story layered over the room's shared chew pose."""
    if not 0 < age < 3:
        return 1.,1.,0.,0.
    if item == "late_practice_snack" and age < .55:
        nod=math.sin(age/.55*math.pi)
        return 1.,1.,6*nod,-2*nod
    if item == "postmatch_noodles":
        for start in (.15,1.):
            phase=(age-start)/.8
            if 0<phase<1:
                tug=math.sin(phase*math.pi)
                return 1.+.025*tug,1.-.025*tug,-2*tug,0.
    return 1.,1.,0.,0.


def paint_headwear(p, head, time, active=False, hot=False, flash=False):
    """Small local-space ornaments: top-centre is (0, 0)."""
    p.save(); p.setPen(QPen(QColor("#79523b"), 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    if head == "cooling_cap":
        p.setBrush(QColor("#d4a18a")); p.drawRoundedRect(QRectF(-29,-24,58,27),13,13)
        p.setBrush(QColor("#af7770")); p.drawEllipse(QRectF(-35,-4,70,10))
        p.setBrush(QColor("#f4e7c5")); p.drawEllipse(QPointF(0,-22),13,13)
        p.save(); p.translate(0,-22); p.rotate(time*(620 if hot else 130)); p.setBrush(QColor("#96bdc4"))
        for _ in range(3): p.rotate(120); p.drawEllipse(QRectF(-3,-11,7,13))
        p.restore(); p.setBrush(QColor("#d3b36c")); p.drawEllipse(QPointF(0,-22),3,3)
    elif head == "demon_hood":
        p.setBrush(QColor("#4b414f")); p.drawRoundedRect(QRectF(-33,-18,66,30),16,16)
        for side in (-1,1):
            p.drawPolygon(QPolygonF([QPointF(side*15,-11),QPointF(side*29,-33),QPointF(side*33,-4)]))
        p.setPen(QPen(QColor("#e9b274" if flash else "#b96f72"),3 if flash else 2))
        p.drawArc(QRectF(-26,-12,52,26),0,180*16)
    elif head == "mini_gnar_hat":
        for side in (-1,1):
            p.save(); p.translate(side*23,-6); p.rotate(side*(20 if active else 5)+math.sin(time*2)*3)
            p.setBrush(QColor("#caa074")); p.drawEllipse(QRectF(-12,-30,24,33))
            p.setBrush(QColor("#edc1ac")); p.drawEllipse(QRectF(-6,-25,12,23)); p.restore()
        p.setBrush(QColor("#c9a071")); p.drawRoundedRect(QRectF(-30,-16,60,20),10,10)
        p.setBrush(QColor("#fff0cc")); p.drawRoundedRect(QRectF(-12,-15,24,7),3,3)
        p.drawEllipse(QRectF(-16,-18,8,12)); p.drawEllipse(QRectF(8,-18,8,12))
    p.restore()


def paint_food_extra(p, atlas, item, age, bounds):
    """Three-second food gag after arrival, in widget coordinates."""
    if item not in ALL_FOODS or not 0 <= age < 3: return
    fade = min(1., age/.2, (3-age)/.5)
    p.save(); p.setOpacity(fade); p.setPen(QPen(QColor("#79523b"),1.6))
    mouth=QPointF(bounds.center().x(),bounds.top()+bounds.height()*.55)
    if item == "iced_cola":
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(6):
            phase=(age*.4+i/6)%1
            p.setBrush(QColor(179,221,230,int(90*(1-phase))))
            p.drawEllipse(QPointF(mouth.x()+(i-2.5)*14,mouth.y()+35-phase*35),15,6)
    elif item == "early_champagne":
        for i in range(7):
            phase=(age*.6+i/7)%1; p.setBrush(QColor("#efcf84"))
            p.drawEllipse(QPointF(mouth.x()+math.sin(i*7)*34,bounds.top()-phase*50),3,3)
        u=min(1.,age/2); y=bounds.top()-12-65*math.sin(u*math.pi)
        p.save(); p.translate(mouth.x()+math.sin(u*math.pi)*20,y); p.rotate(age*180)
        p.setBrush(QColor("#b58e63")); p.drawRoundedRect(QRectF(-5,-8,10,16),2,2); p.restore()
    elif item == "summit_lunch":
        count=max(0,3-int(age/.8))
        for i in range(count):
            x=mouth.x()+58+i*16; y=mouth.y()+30-i*12
            p.setBrush(QColor("#fff1cb")); p.drawPolygon(QPolygonF([QPointF(x-11,y),QPointF(x,y-21),QPointF(x+11,y)]))
        if age>2.2:
            p.setPen(QPen(QColor("#c18a5d"),2)); p.drawLine(mouth+QPointF(0,-40),mouth+QPointF(0,-66))
            p.setBrush(QColor("#dc9d7e")); p.drawPolygon(QPolygonF([mouth+QPointF(0,-66),mouth+QPointF(20,-59),mouth+QPointF(0,-52)]))
    elif item == "watchparty_popcorn":
        for i in range(5):
            u=max(0.,min(1.,(age-i*.36)/.8))
            if u==0 or u==1: continue
            point=mouth+QPointF((1-u)*(90+i*3),-math.sin(u*math.pi)*(45+i*5)+(1-u)*30)
            if i==4: point+=QPointF(math.sin(u*math.tau)*12,math.sin(u*math.tau)*9)
            p.setBrush(QColor("#f8e2a2")); p.drawEllipse(point,5,4); p.drawEllipse(point+QPointF(-3,-3),3,3)
    elif item == "postmatch_noodles":
        # Two slurps and one last elastic noodle, all tied to this food's age.
        cup=mouth+QPointF(74,37)
        p.drawPixmap(QRectF(cup.x()-25,cup.y()-34,50,55),atlas.pixmap(item),QRectF(0,0,80,80))
        for index,start in enumerate((.15,1.0)):
            u=max(0.,min(1.,(age-start)/.8))
            if 0<u<1:
                end=cup+(mouth-cup)*u
                strand=QPainterPath(cup+QPointF(0,-18))
                strand.cubicTo(cup.x()-30,cup.y()-75,end.x()+20,end.y()-28,end.x(),end.y())
                p.setPen(QPen(QColor("#e9bd73"),2.8,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(strand)
        if 1.95<age<2.8:
            u=(age-1.95)/.85; tip=cup+QPointF(-28*math.sin(u*math.pi),-38*math.sin(u*math.pi))
            strand=QPainterPath(cup+QPointF(2,-17)); strand.quadTo(tip+QPointF(-15,-20),tip)
            p.setPen(QPen(QColor("#e9bd73"),2.6,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(strand)
    elif item == "late_practice_snack":
        p.drawPixmap(QRectF(mouth.x()+49,mouth.y()+7,76,66),atlas.pixmap(item),QRectF(0,0,80,80))
        p.drawPixmap(QRectF(mouth.x()+106,mouth.y()-15,46,42),atlas.pixmap("gnar_workbook"),QRectF(0,0,80,80))
        for index,start in enumerate((.55,1.1,1.65)):
            u=max(0.,min(1.,(age-start)/.55))
            if 0<u<1:
                at=mouth+QPointF(70*(1-u),25*(1-u)-25*math.sin(u*math.pi))
                p.setPen(QPen(QColor("#b7aa7d"),1)); p.setBrush(QColor("#fff3d1"))
                p.drawEllipse(at,4,3)
    p.restore()
