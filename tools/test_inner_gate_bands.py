# -*- coding: utf-8 -*-
"""FX-INNER-GATE-COLOR(候補 g1): 内側ゲートの各帯に、そのゲートの色が 1 回だけ乗り、線が後続の塗りで濁らないこと。

CamView の gate_overlay.build_ops を offscreen の QImage に描いて画素で確かめる(実 Maya の見た目ではない)。
FxView の PSGate(HLSL)は、同じ規則(帯の持ち主 = 画素を含まない有効なゲートで最大のもの)を Python に写した関数と
CamView の帯の対応を照合する(GPU 実行ではない)。
使い方: PKG_DIR=<scripts/plsCamView> python3 test_inner_gate_bands.py   旧(h4 版)では帯・線の試験が落ちる。
"""
import importlib
import os
import random
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PKG_DIR = Path(os.environ["PKG_DIR"])
pkg = types.ModuleType(PKG_DIR.name)
pkg.__path__ = [str(PKG_DIR)]
sys.modules[PKG_DIR.name] = pkg
qt = importlib.import_module(PKG_DIR.name + ".qt")
go = importlib.import_module(PKG_DIR.name + ".gate_overlay")
QtGui, QtCore, QW = qt.QtGui, qt.QtCore, qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])

W, H = 400, 300
GATE = (20.0, 20.0, 360.0, 260.0)
BASE = (50, 50, 50)
COLS = [[1.0, 1.0, 0.0], [0.0, 1.0, 0.0], [0.0, 1.0, 1.0]]


def cfg(pcts=(90, 80, 70), ens=(True, True, True), fills=(True, True, True), strokes=(True, True, True), op=0.3):
    return {"gateEnabled": True, "gateMaskOpacity": 0.0, "gateLineWidth": 0.0,
            "innerGateEnabled": list(ens), "innerGatePercent": list(pcts), "innerGateColor": COLS,
            "innerGateOpacity": [op] * 3, "innerGateStroke": list(strokes), "innerGateFill": list(fills),
            "innerGateDashed": False}


def render(c):
    img = QtGui.QImage(W, H, QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor(*BASE))
    p = QtGui.QPainter(img)
    go.paint_ops(p, go.build_ops(c, W, H, GATE))
    p.end()
    return img


def px(img, x, y):
    q = QtGui.QColor(img.pixel(int(x), int(y)))
    return (q.red(), q.green(), q.blue())


def blend(rgb, a):
    return tuple(round(b * (1 - a) + 255 * c * a) for b, c in zip(BASE, rgb))


def rect_of(pct):
    gx, gy, gw, gh = GATE
    sw, sh = gw * pct / 100.0, gh * pct / 100.0
    return (gx + (gw - sw) / 2, gy + (gh - sh) / 2, sw, sh)


def band_point(outer_pct, inner_pct):
    u"""外側(outer_pct、None は解像度ゲート)と内側の矩形の間で、左辺の中央の画素。"""
    ox = GATE[0] if outer_pct is None else rect_of(outer_pct)[0]
    ix = rect_of(inner_pct)[0]
    return ((ox + ix) / 2.0, GATE[1] + GATE[3] / 2.0)


def hlsl_owner(x, y, pcts, ens):
    u"""PSGate と同じ規則: 画素を含まない有効なゲートのうち最大のもの(同じ大きさは番号の小さい方)。"""
    owner, best = -1, -1.0
    for k in range(3):
        if not ens[k]:
            continue
        rx, ry, rw, rh = rect_of(pcts[k])
        inside = rx <= x <= rx + rw and ry <= y <= ry + rh
        if not inside and pcts[k] / 100.0 > best:
            owner, best = k, pcts[k] / 100.0
    return owner


class Bands(unittest.TestCase):
    def assertClose(self, got, exp, msg=None, tol=3):
        self.assertTrue(all(abs(a - b) <= tol for a, b in zip(got, exp)), (got, exp, msg))

    def test_each_band_has_its_own_color_once(self):
        img = render(cfg())
        for k, (outer, inner) in enumerate(((None, 90), (90, 80), (80, 70))):
            self.assertClose(px(img, *band_point(outer, inner)), blend(COLS[k], 0.3), "band %d" % k)
        self.assertClose(px(img, W / 2, H / 2), BASE, "inside the smallest gate is untouched")

    def test_order_of_gates_does_not_matter(self):
        img = render(cfg(pcts=(70, 90, 80)))
        self.assertClose(px(img, *band_point(None, 90)), blend(COLS[1], 0.3))     # 90% は gate 2
        self.assertClose(px(img, *band_point(90, 80)), blend(COLS[2], 0.3))       # 80% は gate 3
        self.assertClose(px(img, *band_point(80, 70)), blend(COLS[0], 0.3))       # 70% は gate 1

    def test_disabled_gate_does_not_split_bands_and_fill_off_leaves_band_empty(self):
        img = render(cfg(ens=(True, False, True)))
        self.assertClose(px(img, *band_point(90, 70)), blend(COLS[2], 0.3), "gate 2 disabled: gate 3 band from 90 to 70")
        img = render(cfg(fills=(True, False, True)))
        self.assertClose(px(img, *band_point(90, 80)), BASE, "gate 2 fill off: its band is empty")
        self.assertClose(px(img, *band_point(80, 70)), blend(COLS[2], 0.3), "gate 3 band still starts at 80")

    def test_equal_sizes_paint_once(self):
        img = render(cfg(pcts=(80, 80, 70)))
        self.assertClose(px(img, *band_point(None, 80)), blend(COLS[0], 0.3), "same size: first gate only, no double paint")

    def test_lines_are_pure_and_drawn_after_all_fills(self):
        ops = go.build_ops(cfg(), W, H, GATE)
        kinds = [o[0] for o in ops]
        last_ring = max(i for i, k in enumerate(kinds) if k == "ring")
        first_rect = min(i for i, k in enumerate(kinds) if k == "rect")
        self.assertLess(last_ring, first_rect)
        img = render(cfg())
        for k, pct in enumerate((90, 80, 70)):
            rx, ry, rw, rh = rect_of(pct)
            pure = tuple(round(255 * c) for c in COLS[k])
            near = [px(img, x, ry + rh / 2) for x in (round(rx) - 1, round(rx), round(rx) + 1)]   # 小数の丸めで 1px ずれる
            self.assertTrue(any(all(abs(a - b) <= 40 for a, b in zip(g, pure)) for g in near), ("line %d" % k, near, pure))

    def test_fill_rings_are_disjoint(self):
        ops = [o for o in go.build_ops(cfg(pcts=(95, 60, 85)), W, H, GATE) if o[0] == "ring"]
        for i, (_, outer, hole, _c, _a) in enumerate(ops[1:], 1):
            self.assertEqual(outer, ops[i - 1][2], "ring %d starts where the previous one ends" % i)

    def test_hlsl_owner_rule_matches_cam_bands(self):
        rnd = random.Random(7)
        for _ in range(4):
            pcts = [rnd.choice((60, 70, 80, 85, 90, 95)) for _ in range(3)]
            ens = [rnd.random() > 0.2 for _ in range(3)]
            c = cfg(pcts=pcts, ens=ens, strokes=(False, False, False), op=1.0)
            img = render(c)
            for _ in range(300):
                x, y = rnd.uniform(GATE[0] + 2, GATE[0] + GATE[2] - 2), rnd.uniform(GATE[1] + 2, GATE[1] + GATE[3] - 2)
                o = hlsl_owner(x, y, pcts, ens)
                exp = BASE if o < 0 else tuple(round(255 * v) for v in COLS[o])
                # 境界の 1px はアンチエイリアスで混ざるので除く
                near_edge = any(abs(x - r[0]) < 1.5 or abs(x - r[0] - r[2]) < 1.5 or abs(y - r[1]) < 1.5 or abs(y - r[1] - r[3]) < 1.5
                                for r in (rect_of(p) for p in pcts))
                if not near_edge:
                    self.assertClose(px(img, x, y), exp, (pcts, ens, x, y), tol=3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
