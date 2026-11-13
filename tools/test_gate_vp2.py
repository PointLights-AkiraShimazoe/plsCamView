# -*- coding: utf-8 -*-
u"""FX-HUD-FRONT-20261031-01(h2): ゲート/ガイドを HUD の背後(VP2 内、HUD より先)に描く経路の試験。実 Qt(offscreen)・Maya なし。

【この試験が確かめること】
 (1) gate_overlay の描画を「命令リスト」に分けても、Qt オーバーレイの描画は p3 とピクセル単位で同一(退行なし)。
 (2) その命令リストを VP2 用の基本図形(塗り矩形 4 枚 / 線)へ展開しても、描画内容が変わらない(Qt の CPU 描画で比較)。
 (3) レンダラオーバーライドの操作順(SceneRender → HUDRender → PresentTarget)・切替・復帰・失敗時の巻き戻し・
     パネルごとの独立・既定 OFF(自動では何も起きない)。API は**模擬**(maya.api.OpenMayaRender の契約を写したスタブ)。
【確かめていないこと】 実 Maya の VP2 で HUD より前に描かれること、標準 VP2 と同じ見た目になること、座標原点・rect2d の寸法規約・
 アルファ合成・HiDPI 倍率・setup() 内の cmds 呼び出し可否・ポップアウト/再ドック挙動(docs の残務記録)。
"""
import importlib
import importlib.util
import os
from pathlib import Path
import re
import sys
import types
import unittest

ROOT = Path(os.environ.get('PLS_TEST_SOURCE', str(Path(__file__).resolve().parents[1])))
PACKAGE = ROOT.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT/'scripts'/PACKAGE)]
sys.modules[PACKAGE] = pkg
qt = importlib.import_module(PACKAGE+'.qt')
go = importlib.import_module(PACKAGE+'.gate_overlay')
gv = importlib.import_module(PACKAGE+'.gate_vp2')
QC, QG, QW = qt.QtCore, qt.QtGui, qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])

_spec = importlib.util.spec_from_file_location(PACKAGE+'.ref_p3_gate_overlay', str(Path(__file__).resolve().parent/'ref_p3_gate_overlay.py'))
p3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(p3)             # p3 の gate_overlay.py そのもの(退行比較の基準)


class Probe(QW.QWidget):
    u"""paintEvent だけを借りる検査用ウィジェット(overlay と同じ属性 _cfg / _gate / _suppressed だけを使う)。"""
    def __init__(self, paint, cfg, gate, w, h, suppressed=False):
        super(Probe, self).__init__()
        self.resize(w, h)
        self._cfg, self._gate, self._suppressed = cfg, gate, suppressed
        self._paint = paint

    def paintEvent(self, ev):
        self._paint(self, ev)


def render(paint, cfg, gate, w, h):
    wd = Probe(paint, cfg, gate, w, h)
    img = QG.QImage(w, h, QG.QImage.Format_ARGB32_Premultiplied)
    img.fill(0)
    wd.render(img, QC.QPoint(), QG.QRegion(), QW.QWidget.RenderFlag.DrawChildren)   # 窓の背景は描かない(透明のまま比べる)
    wd.deleteLater()
    return img


def raw(img):
    return bytes(img.constBits())[:img.sizeInBytes()]


def cfgs():
    base = dict(go.DEFAULTS)
    out = [dict(base)]
    mk = lambda **k: dict(base, **k)
    out += [
        mk(gateEnabled=True),
        mk(gateEnabled=True, gateMaskOpacity=0.0, gateLineWidth=0.0),
        mk(gateEnabled=True, gateMaskColor=[0.2, 0.1, 0.3], gateMaskOpacity=0.85, gateLineWidth=3.0, gateLineColor=[1, 0, 0]),
        mk(gateEnabled=True, innerGateEnabled=[True, True, True], innerGateFill=[True, False, True], innerGateStroke=[True, True, False]),
        mk(gateEnabled=True, innerGateEnabled=[True, False, True], innerGateDashed=False, innerGateFill=[True, True, True]),
        mk(gateEnabled=True, innerGateEnabled=True, innerGatePercent=[85, 85, 85]),
        mk(guideThirds=True), mk(guideGrid=True), mk(guideArmature=True), mk(guideCenter=True),
        mk(guideThirds=True, guideGrid=True, guideArmature=True, guideCenter=True, guideRatio=1, guideOpacity=0.5, guideWidth=2.0),
        mk(guideGrid=True, guideFit=1, innerGatePercent=[70, 80, 90]), mk(guideGrid=True, guideFit=3), mk(guideArmature=True, guideFit=4),
        mk(gateEnabled=True, innerGateEnabled=[True, True, True], innerGateFill=[True, True, True], guideThirds=True, guideGrid=True,
           guideArmature=True, guideCenter=True, guideFit=2, guideRatio=1),
    ]
    return out


GATES = [None, (0.0, 60.0, 400.0, 180.0), (50.5, 30.25, 300.0, 200.5), (-40.0, -20.0, 500.0, 360.0), (120.0, 90.0, 100.0, 60.0)]
SIZES = [(400, 300), (1, 1), (33, 517), (640, 360)]


class PixelIdenticalToP3(unittest.TestCase):
    def test_matrix(self):
        n = 0
        multi = 0
        for cfg in cfgs():
            # g1(FX-INNER-GATE-COLOR, 2026-11-08): 内側ゲートが 2 つ以上有効だと p3 は帯の色を重ね塗りしていた(本人 NG)。
            # その組だけは p3 と一致させない(新しい規則は test_inner_gate_bands.py で画素確認)。1 つ以下は従来どおり完全一致。
            if sum(1 for e in go._per_gate(cfg.get("innerGateEnabled"), go.DEFAULTS["innerGateEnabled"]) if e) >= 2:
                multi += 1
                continue
            for (w, h) in SIZES:
                for g in GATES:
                    a = render(p3.GateOverlay.paintEvent, cfg, g, w, h)
                    b = render(go.GateOverlay.paintEvent, cfg, g, w, h)
                    self.assertEqual(raw(a), raw(b), "p3 と描画が違う cfg=%r size=%r gate=%r" % ({k: v for k, v in cfg.items() if cfg[k] != go.DEFAULTS[k]}, (w, h), g))
                    n += 1
        self.assertGreater(n, 100, (n, multi))

    def test_something_is_actually_drawn(self):
        # 比較が「両方空」で通っていないことの確認
        cfg = dict(go.DEFAULTS, gateEnabled=True, guideGrid=True, innerGateEnabled=[True, True, True], innerGateFill=[True, True, True])
        img = render(go.GateOverlay.paintEvent, cfg, (0.0, 60.0, 400.0, 180.0), 400, 300)
        self.assertGreater(sum(1 for i in raw(img) if i), 5000)

    def test_defaults_unchanged_and_no_hud_option(self):
        self.assertEqual(go.DEFAULTS, p3.DEFAULTS)
        src = Path(go.__file__).read_text(encoding="utf-8")
        for bad in ("hudFront", "_hud_clip", "hud_rects", "headsUpDisplay"):
            self.assertNotIn(bad, src)


class Ops(unittest.TestCase):
    def test_empty_when_nothing_enabled(self):
        self.assertEqual(go.build_ops(dict(go.DEFAULTS), 400.0, 300.0, None), [])

    def test_order_mask_inner_frame_guides(self):
        cfg = dict(go.DEFAULTS, gateEnabled=True, innerGateEnabled=[True, False, False], innerGateFill=[True, False, False], guideThirds=True)
        kinds = [(o[0]) for o in go.build_ops(cfg, 400.0, 300.0, (0, 60, 400, 180))]
        self.assertEqual(kinds, ["ring", "ring", "rect", "rect", "lines"])     # マスク, 内側塗り, 内側枠, 外枠, ガイド

    def test_gate_none_means_full_view(self):
        cfg = dict(go.DEFAULTS, guideThirds=True)
        ops = go.build_ops(cfg, 400.0, 300.0, None)
        self.assertAlmostEqual(ops[0][1][0][0], 400.0 / 3.0)

    def test_dashed_flag_only_on_inner_stroke(self):
        cfg = dict(go.DEFAULTS, gateEnabled=True, innerGateEnabled=[True, True, True])
        rects = [o for o in go.build_ops(cfg, 400.0, 300.0, (10, 10, 300, 200)) if o[0] == "rect"]
        self.assertEqual([r[5] for r in rects], [True, True, True, False])


class Suppress(unittest.TestCase):
    def test_overlay_suppressed_paints_nothing_and_returns(self):
        view = QW.QWidget()
        view.setGeometry(0, 0, 200, 100)
        view.show(); app.processEvents()
        ov = go.GateOverlay("dummyPanel", view)
        ov.set_config(dict(go.DEFAULTS, guideThirds=True))
        app.processEvents()

        def drawn():
            img = QG.QImage(ov.width(), ov.height(), QG.QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            ov.render(img)
            return any(raw(img))
        self.assertTrue(drawn())
        ov.set_suppressed(True)
        self.assertFalse(drawn())
        ov.set_suppressed(False)
        self.assertTrue(drawn())
        ov.detach(); view.deleteLater()

    def test_manager_config_is_a_copy(self):
        m = go.OverlayManager()
        m.set_config({"guideGrid": True})
        c = m.config()
        self.assertTrue(c["guideGrid"])
        c["guideGrid"] = False
        self.assertTrue(m.config()["guideGrid"], "config() はコピーを返す")

    def test_manager_suppress_is_remembered_for_overlays_created_later(self):
        view = QW.QWidget(); view.setGeometry(0, 0, 200, 100); view.show(); app.processEvents()
        saved = (go.cmds, go._view_widget)
        go.cmds = types.SimpleNamespace(warning=lambda *a: None, modelPanel=lambda *a, **k: True)
        go._view_widget = lambda panel: view
        try:
            m = go.OverlayManager()
            self.assertTrue(m.set_suppressed("pX", True), "オーバーレイが無くても印は付く(True)")
            self.assertTrue(m.is_suppressed("pX"))
            ov = m.ensure("pX")
            self.assertTrue(ov._suppressed, "後から作られたオーバーレイも抑止される(二重描画しない)")
            m.set_suppressed("pX", False)
            self.assertFalse(ov._suppressed)
            self.assertFalse(m.is_suppressed("pX"))
            # 破棄の確認でのみ印を外す: 照会が例外なら残す / False なら外す
            m.set_suppressed("pX", True)
            go.cmds = types.SimpleNamespace(warning=lambda *a: None, modelPanel=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
            m.refresh()
            self.assertTrue(m.is_suppressed("pX"), "照会失敗では抑止の印を外さない")
            m._overlays["pX"] = go.GateOverlay("pX", view) if "pX" not in m._overlays else m._overlays["pX"]
            go.cmds = types.SimpleNamespace(warning=lambda *a: None, modelPanel=lambda *a, **k: False)
            m.refresh()
            self.assertFalse(m.is_suppressed("pX"), "破棄を確認できたら外す")
        finally:
            go.cmds, go._view_widget = saved
            m.remove_all(); view.deleteLater()


class Geometry(unittest.TestCase):
    def test_ring_strips_cover_exactly_outer_minus_hole(self):
        outer = (0.0, 0.0, 100.0, 80.0)
        for hole in [(20, 10, 50, 40), (-30, -30, 80, 60), (60, 50, 100, 100), (200, 200, 10, 10), (0, 0, 100, 80), (-10, 20, 300, 20), (30, -5, 10, 200)]:
            strips = gv.ring_strips(outer, hole)
            for (x, y, w, h) in strips:
                self.assertGreater(w, 0); self.assertGreater(h, 0)
            for iy in range(-80, 240):                               # outer の外側も含めて走査(はみ出す帯を検出する)
                for ix in range(-80, 280):
                    px, py = ix * 0.5 + 0.25, iy * 0.5 + 0.25
                    inside_outer = 0 <= px < 100 and 0 <= py < 80
                    inside_hole = hole[0] <= px < hole[0] + hole[2] and hole[1] <= py < hole[1] + hole[3]
                    cnt = sum(1 for (x, y, w, h) in strips if x <= px < x + w and y <= py < y + h)
                    self.assertEqual(cnt, 1 if (inside_outer and not inside_hole) else 0, "hole=%r p=%r cnt=%d" % (hole, (px, py), cnt))

    def test_dash_segments(self):
        rect = (10.0, 20.0, 100.0, 50.0)
        segs = gv.dash_segments(rect)
        import math
        total = sum(math.hypot(s[2] - s[0], s[3] - s[1]) for s in segs)
        per = 2 * (100 + 50)
        self.assertAlmostEqual(total, per / 2.0, delta=gv.DASH)
        for s in segs:
            self.assertLessEqual(math.hypot(s[2] - s[0], s[3] - s[1]), gv.DASH + 1e-6)
            for (x, y) in ((s[0], s[1]), (s[2], s[3])):
                on_edge = (abs(y - 20) < 1e-6 or abs(y - 70) < 1e-6 or abs(x - 10) < 1e-6 or abs(x - 110) < 1e-6)
                self.assertTrue(on_edge and 10 - 1e-6 <= x <= 110 + 1e-6 and 20 - 1e-6 <= y <= 70 + 1e-6)

    def test_dash_pattern_matches_qt_custom_dash_6_6(self):
        self.assertEqual(gv.DASH, 6.0)                       # Qt 側 setDashPattern([6.0, 6.0])(線幅 1)と同じ周期
        segs = gv.dash_segments((10.0, 20.0, 100.0, 50.0))
        self.assertEqual(segs[0], (10.0, 20.0, 16.0, 20.0))
        self.assertEqual(segs[1][:2], (22.0, 20.0))          # 6 on / 6 off

    def test_dashed_rect_flattens_to_many_short_lines_solid_to_four(self):
        r = (10.0, 20.0, 100.0, 50.0)
        dashed = gv.flatten([("rect", r, [1, 1, 1], 1.0, 1.0, True)], 100)
        solid = gv.flatten([("rect", r, [1, 1, 1], 1.0, 3.0, False)], 100)
        self.assertGreater(len(dashed), 20)
        self.assertEqual(len(solid), 4)
        self.assertTrue(all(p[3] == 3.0 for p in solid))

    def test_flatten_flips_y_to_bottom_origin(self):
        prims = gv.flatten([("lines", [(10.0, 0.0, 10.0, 300.0)], [1, 0, 0], 0.5, 2.0)], 300)
        self.assertEqual(prims, [("line", (10.0, 300.0, 10.0, 0.0), (1.0, 0.0, 0.0, 0.5), 2.0)])
        f = gv.flatten([("ring", (0.0, 0.0, 400.0, 300.0), (0.0, 60.0, 400.0, 180.0), [0, 0, 0], 0.6)], 300)
        self.assertEqual(len(f), 2)                                 # 上 60px と下 60px
        centers = sorted(p[1][1] for p in f)
        self.assertEqual(centers, [30.0, 270.0])                    # 下原点: 下帯の中心 30、上帯の中心 270
        self.assertTrue(all(p[1][2] == 200.0 for p in f))

    def test_rgba_clamps(self):
        self.assertEqual(gv._rgba([2, -1, 0.5], 3), (1.0, 0.0, 0.5, 1.0))


class Rasterize(unittest.TestCase):
    u"""VP2 用の基本図形へ展開した結果を Qt の CPU 描画で再現し、命令リストを直接描いた結果と比べる(Maya の描画ではない)。"""
    def raster(self, ops, w, h, aa=False):
        img = QG.QImage(w, h, QG.QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QG.QPainter(img)
        p.setRenderHint(QG.QPainter.Antialiasing, aa)
        for prim in gv.flatten(ops, h):
            if prim[0] == "fill":
                (cx, cy, hw, hh), col = prim[1], prim[2]
                c = QG.QColor.fromRgbF(*col)
                p.fillRect(QC.QRectF(cx - hw, (h - cy) - hh, hw * 2, hh * 2), c)
            else:
                (x0, y0, x1, y1), col, wd = prim[1], prim[2], prim[3]
                p.setPen(QG.QPen(QG.QColor.fromRgbF(*col), wd))
                p.drawLine(QC.QLineF(x0, h - y0, x1, h - y1))
        p.end()
        return img

    def direct(self, ops, w, h):
        img = QG.QImage(w, h, QG.QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QG.QPainter(img)
        p.setRenderHint(QG.QPainter.Antialiasing, False)
        go.paint_ops(p, ops)
        p.end()
        return img

    def test_mask_fills_and_guides_are_identical(self):
        w, h = 400, 300
        gate = (30.0, 60.0, 340.0, 180.0)
        cfg = dict(go.DEFAULTS, gateEnabled=True, gateLineWidth=0.0, innerGateEnabled=[True, True, False], innerGateFill=[True, True, False],
                   innerGateStroke=[False, False, False], guideThirds=True, guideGrid=True, guideArmature=True, guideCenter=True, guideFit=2)
        ops = go.build_ops(cfg, float(w), float(h), gate)
        a, b = self.direct(ops, w, h), self.raster(ops, w, h)
        diff = sum(1 for x, y in zip(raw(a), raw(b)) if abs(x - y) > 1)
        self.assertEqual(diff, 0, "展開後の図形が命令リストの描画と違う(%d バイト)" % diff)
        self.assertGreater(sum(1 for i in raw(a) if i), 10000)

    def test_rect_outline_differs_only_at_corners(self):
        w, h = 300, 200
        gate = (40.0, 30.0, 220.0, 140.0)
        cfg = dict(go.DEFAULTS, gateEnabled=True, gateMaskOpacity=0.0, gateLineWidth=3.0, innerGateDashed=False)
        ops = go.build_ops(cfg, float(w), float(h), gate)
        a, b = self.direct(ops, w, h), self.raster(ops, w, h)
        corners = [(40, 30), (260, 30), (40, 170), (260, 170)]
        bad = 0
        for y in range(h):
            for x in range(w):
                if a.pixel(x, y) != b.pixel(x, y):
                    if not any(abs(x - cx) <= 3 and abs(y - cy) <= 3 for cx, cy in corners):
                        bad += 1
        self.assertEqual(bad, 0, "角以外で枠線の描画が違う")


# ---------------------------------------------------------------------------------------------
#  Maya API の模擬(maya.api.OpenMayaRender / cmds の契約を写したスタブ。実 Maya の挙動ではない)
# ---------------------------------------------------------------------------------------------
class FOp(object):
    def __init__(self, *a):
        self.args = a


class FSceneRender(FOp):
    kRenderAllItems = -1


class FHUD(FOp):
    pass


class FPresent(FOp):
    pass


class FRenderOverride(object):
    def __init__(self, name):
        self._name = name


class FRenderer(object):
    kAllDevices = 255
    registered = []
    fail = False

    @staticmethod
    def registerOverride(o):
        if FRenderer.fail:
            raise RuntimeError("register failed")
        FRenderer.registered.append(o)


class FOmr(object):
    MSceneRender = FSceneRender
    MHUDRender = FHUD
    MPresentTarget = FPresent
    MRenderOverride = FRenderOverride
    MRenderer = FRenderer


class FDM(object):
    def __init__(self):
        self.log = []

    def beginDrawable(self): self.log.append(("begin",))
    def endDrawable(self): self.log.append(("end",))
    def setColor(self, c): self.log.append(("color", c))
    def setLineWidth(self, w): self.log.append(("width", w))
    def line2d(self, a, b): self.log.append(("line", a, b))
    def rect2d(self, c, up, sx, sy, filled): self.log.append(("rect", c, up, sx, sy, filled))


class FCmds(object):
    u"""cmds のスタブ。query_raises: 次の N 回の query を例外にする(-1=常に)。fail_set(name)=True なら代入が例外。
    after_set(ed, name): 代入のあとに呼ぶ(本人/別ツールが途中で変更する状況の再現)。exists_raises: 存在照会が例外のパネル。"""
    def __init__(self, panels=("modelPanel1", "modelPanel2"), takes=True):
        self.override = {"ed_" + p: "" for p in panels}
        self.alive = set(panels)
        self.takes = takes
        self.edits = []
        self.query_raises = 0
        self.fail_set = None
        self.ignore_set = None         # ignore_set(name)=True なら代入は例外にならず、値も変わらない(黙って効かない)
        self.after_set = None
        self.exists_raises = set()
        self.warnings = []

    def warning(self, msg):
        self.warnings.append(msg)

    def modelPanel(self, p, q=False, modelEditor=False, exists=False):
        if exists:
            if p in self.exists_raises:
                raise RuntimeError("exists query failed")
            return p in self.alive
        if p not in self.alive:
            raise RuntimeError("no panel")
        return "ed_" + p

    def modelEditor(self, ed, q=False, e=False, rendererOverrideName=None):
        if q:
            if self.query_raises != 0:
                if self.query_raises > 0:
                    self.query_raises -= 1
                raise RuntimeError("query failed")
            return self.override[ed]
        self.edits.append((ed, rendererOverrideName))
        if self.fail_set and self.fail_set(rendererOverrideName):
            raise RuntimeError("set failed")
        if self.ignore_set and self.ignore_set(rendererOverrideName):
            return
        if self.takes or rendererOverrideName != gv.OVERRIDE_NAME:
            self.override[ed] = rendererOverrideName
        if self.after_set:
            self.after_set(ed, rendererOverrideName)


class Mgr(object):
    u"""OverlayManager のスタブ。fail(panel, flag) が "raise" なら例外、"false" なら False を返す。sup は実際に適用できた状態。"""
    def __init__(self, cfg=None, fail=None):
        self.cfg = cfg or {}
        self.sup = {}
        self.fail = fail
        self.calls = []

    def config(self):
        c = dict(go.DEFAULTS)
        c.update(self.cfg)
        return c

    def set_suppressed(self, p, f):
        self.calls.append((p, f))
        mode = self.fail(p, f) if self.fail else None
        if mode == "raise":
            raise RuntimeError("suppress failed")
        if mode == "false":
            return False
        self.sup[p] = f
        return True


class NoSuppress(object):
    def config(self):
        return dict(go.DEFAULTS)


class OverrideTests(unittest.TestCase):
    def setUp(self):
        self._saved = (gv.cmds, gv.omr, gv.om2, gv.omui2, gv._override, dict(gv._state), go.compute_gate, gv._view_size)
        gv.cmds, gv.omr = FCmds(), FOmr
        gv.om2 = types.SimpleNamespace(MPoint=lambda x, y: (x, y), MVector=lambda x, y: (x, y), MColor=lambda c: c)
        gv._override = None
        gv._state.clear()
        FRenderer.registered = []
        FRenderer.fail = False
        self.mgr = Mgr({"gateEnabled": True, "guideThirds": True})

    def tearDown(self):
        (gv.cmds, gv.omr, gv.om2, gv.omui2, gv._override) = self._saved[:5]
        gv._state.clear(); gv._state.update(self._saved[5])
        go.compute_gate, gv._view_size = self._saved[6], self._saved[7]

    def ov(self):
        return gv._make_override()

    def draws(self, panel, size=(400, 300), gate=(0.0, 60.0, 400.0, 180.0)):
        u"""enable 済みの override にそのパネルで 1 フレーム描かせ、MUIDrawManager へ出た begin の数を返す。"""
        gv._view_size = lambda p: size
        go.compute_gate = lambda p, w, h: gate
        o = gv._override
        o.setup(panel)
        dm = FDM()
        o._ops[0].addPostUIDrawables(dm, None)
        return len([x for x in dm.log if x[0] == "begin"])

    # ---------------- 操作列・描画(従来) ----------------
    def test_operation_order_scene_then_hud_then_present(self):
        o = self.ov()
        self.assertTrue(o.startOperationIterator())
        seq = [o.renderOperation()]
        while o.nextRenderOperation():
            seq.append(o.renderOperation())
        self.assertEqual([type(x).__name__ for x in seq], ["_GateScene", "FHUD", "FPresent"])
        self.assertTrue(o.startOperationIterator())
        self.assertEqual(type(o.renderOperation()).__name__, "_GateScene")

    def test_scene_declares_post_ui_drawables(self):
        s = self.ov()._ops[0]
        self.assertTrue(s.hasUIDrawables())
        self.assertEqual(s.renderFilterOverride(), FSceneRender.kRenderAllItems)

    def test_post_ui_drawables_replays_same_ops_as_qt(self):
        self.assertTrue(gv.enable("modelPanel1", self.mgr))
        n = self.draws("modelPanel1")
        want = gv.flatten(go.build_ops(self.mgr.config(), 400.0, 300.0, (0.0, 60.0, 400.0, 180.0)), 300)
        self.assertEqual(n, len(want))
        o = gv._override
        dm = FDM()
        o._ops[0].addPostUIDrawables(dm, None)
        self.assertTrue(any(x[0] == "rect" and x[5] is True and x[2] == (0.0, 1.0) for x in dm.log))
        self.assertEqual(dm.log[0], ("begin",)); self.assertEqual(dm.log[-1], ("end",))

    def test_nothing_drawn_without_size_or_config_or_manager(self):
        o = self.ov()
        dm = FDM()
        o._ops[0].addPostUIDrawables(dm, None)
        self.assertEqual(dm.log, [])
        o.size, o.manager = (400, 300), self.mgr
        self.mgr.cfg = {}
        o._ops[0].addPostUIDrawables(dm, None)
        self.assertEqual(dm.log, [])
        o.manager = None
        self.mgr.cfg = {"guideThirds": True}
        o._ops[0].addPostUIDrawables(dm, None)
        self.assertEqual(dm.log, [], "manager が分からないパネルでは描かない")

    def test_setup_reads_panel_size_gate_and_that_panels_manager(self):
        o = self.ov()
        gv._view_size = lambda panel: (640, 360) if panel == "modelPanel1" else None
        got = []
        go.compute_gate = lambda panel, w, h: got.append((panel, w, h)) or (1.0, 2.0, 3.0, 4.0)
        gv._state["modelPanel1"] = {"manager": self.mgr}
        o.setup("modelPanel1")
        self.assertEqual((o.size, o.gate, got, o.manager), ((640, 360), (1.0, 2.0, 3.0, 4.0), [("modelPanel1", 640, 360)], self.mgr))
        o.setup("gone")
        self.assertEqual((o.size, o.gate, o.manager), (None, None, None))

    # ---------------- enable / disable の基本 ----------------
    def test_enable_disable_roundtrip_and_suppress(self):
        gv.cmds.override["ed_modelPanel1"] = "someOtherOverride"
        self.assertTrue(gv.enable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], gv.OVERRIDE_NAME)
        self.assertEqual(self.mgr.sup, {"modelPanel1": True})
        self.assertEqual(len(FRenderer.registered), 1)
        self.assertEqual(gv.status(), {"modelPanel1": {"prev": "someOtherOverride", "pending": None, "checked": True}})
        self.assertTrue(gv.disable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "someOtherOverride", "以前のオーバーライドへ戻す")
        self.assertEqual(self.mgr.sup, {"modelPanel1": False})
        self.assertEqual(gv.status(), {})

    def test_enable_twice_is_idempotent_and_keeps_original(self):
        gv.cmds.override["ed_modelPanel1"] = "someOtherOverride"
        self.assertTrue(gv.enable("modelPanel1", self.mgr))
        edits = list(gv.cmds.edits)
        self.assertTrue(gv.enable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.edits, edits, "2 回目は何も書き換えない")
        self.assertEqual(gv.status()["modelPanel1"]["prev"], "someOtherOverride", "prev を自分の名前で上書きしない")
        self.assertEqual(len(FRenderer.registered), 1)
        self.assertTrue(gv.disable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "someOtherOverride", "disable 後に実験 override が残らない")
        self.assertEqual(self.mgr.sup, {"modelPanel1": False})

    def test_enable_twice_with_empty_original_restores_empty(self):
        gv.enable("modelPanel1", self.mgr); gv.enable("modelPanel1", self.mgr)
        gv.disable("modelPanel1", self.mgr)
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "")

    def test_reenable_with_another_manager_is_refused_untouched(self):
        gv.enable("modelPanel1", self.mgr)
        other = Mgr({"guideGrid": True})
        self.assertFalse(gv.enable("modelPanel1", other))
        self.assertEqual(other.calls, [])
        self.assertIs(gv._state["modelPanel1"]["manager"], self.mgr)

    def test_reenable_when_someone_else_changed_override_does_not_overwrite(self):
        gv.enable("modelPanel1", self.mgr)
        gv.cmds.override["ed_modelPanel1"] = "userChoice"
        edits = list(gv.cmds.edits)
        self.assertFalse(gv.enable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "userChoice")
        self.assertEqual(gv.cmds.edits, edits, "上書きも復元もしない")
        self.assertEqual(self.mgr.sup, {"modelPanel1": False}, "Qt の抑止だけ外す(描画が消えない)")
        self.assertEqual(gv.status(), {})

    def test_untracked_but_already_ours_is_refused_without_any_change(self):
        u"""記録が無いのに自分の名前が設定済み(モジュール再読込など)= 元の設定が不明。元を空に捏造して採用してはいけない。
        登録・切替・抑止のどれも行わず False、短い警告を出す。後続の disable / disable_all でも標準へ書き換えない。"""
        gv.cmds.override["ed_modelPanel1"] = gv.OVERRIDE_NAME
        self.assertFalse(gv.enable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.edits, [], "設定変更なし")
        self.assertEqual(FRenderer.registered, [], "登録もしない")
        self.assertIsNone(gv._override)
        self.assertEqual(self.mgr.calls, [], "抑止もしない(Qt を止めない)")
        self.assertEqual(gv._state, {}, "記録を作らない(元を捏造しない)")
        self.assertEqual(gv.status(), {})
        self.assertEqual(len(gv.cmds.warnings), 1, "元設定が不明であることを短く報告")
        self.assertIn(gv.OVERRIDE_NAME, gv.cmds.warnings[0])
        self.assertFalse(gv.disable("modelPanel1", self.mgr))
        self.assertEqual(gv.disable_all(self.mgr), [])
        self.assertEqual(gv.cmds.edits, [], "disable でも標準へ書き換えない")
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], gv.OVERRIDE_NAME, "そのまま保持")
        self.assertTrue(all(f is False for _, f in self.mgr.calls), "disable の保険は抑止の解除だけ")
        self.assertEqual(self.mgr.sup.get("modelPanel1", False), False)

    def test_untracked_but_already_ours_refusal_is_per_panel_and_does_not_block_others(self):
        gv.cmds.override["ed_modelPanel1"] = gv.OVERRIDE_NAME
        self.assertFalse(gv.enable("modelPanel1", self.mgr))
        self.assertTrue(gv.enable("modelPanel2", self.mgr), "別パネルは通常どおり")
        self.assertEqual(gv.cmds.override["ed_modelPanel2"], gv.OVERRIDE_NAME)
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], gv.OVERRIDE_NAME)
        self.assertEqual(list(gv._state), ["modelPanel2"])
        self.assertTrue(gv.disable("modelPanel2", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel2"], "")
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], gv.OVERRIDE_NAME, "拒否したパネルは最後まで触らない")

    def test_untracked_ours_then_user_resets_then_enable_works_with_that_original(self):
        gv.cmds.override["ed_modelPanel1"] = gv.OVERRIDE_NAME
        self.assertFalse(gv.enable("modelPanel1", self.mgr))
        gv.cmds.override["ed_modelPanel1"] = "userRenderer"              # 本人が手で戻した
        self.assertTrue(gv.enable("modelPanel1", self.mgr))
        self.assertEqual(gv._state["modelPanel1"]["prev"], "userRenderer")
        self.assertTrue(gv.disable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "userRenderer")

    def test_no_prev_unknown_adoption_path_remains_in_source(self):
        src = open(gv.__file__.replace(".pyc", ".py"), encoding="utf-8").read()
        self.assertNotIn("prev_unknown", src)

    # ---------------- enable の失敗経路 ----------------
    def test_register_failure_leaves_no_override_and_retry_registers(self):
        FRenderer.fail = True
        self.assertFalse(gv.enable("modelPanel1", self.mgr))
        self.assertIsNone(gv._override, "登録に失敗したら保持しない")
        self.assertEqual((self.mgr.sup, gv.cmds.edits, gv._state), ({}, [], {}))
        FRenderer.fail = False
        self.assertTrue(gv.enable("modelPanel1", self.mgr), "再試行で登録される")
        self.assertEqual(len(FRenderer.registered), 1)
        self.assertIs(gv._override, FRenderer.registered[0])

    def test_switch_that_does_not_take_changes_nothing(self):
        gv.cmds = FCmds(takes=False)
        gv.cmds.override["ed_modelPanel1"] = "prev"
        self.assertFalse(gv.enable("modelPanel1", self.mgr))
        self.assertEqual(self.mgr.sup, {}, "Qt オーバーレイを止めてはいけない")
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "prev")
        self.assertEqual(gv.status(), {})

    def test_someone_changes_override_right_after_our_switch_is_not_overwritten(self):
        gv.cmds.after_set = lambda ed, name: gv.cmds.override.__setitem__(ed, "userChoice") if name == gv.OVERRIDE_NAME else None
        self.assertFalse(gv.enable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "userChoice")
        self.assertEqual([e for e in gv.cmds.edits if e[1] != gv.OVERRIDE_NAME], [], "元への書き戻しをしない")
        self.assertEqual((self.mgr.sup, gv._state), ({}, {}))

    def test_verify_query_fails_once_then_rolls_back_when_confirmable(self):
        gv.cmds.override["ed_modelPanel1"] = "prev"
        real = gv.cmds.modelEditor
        n = [0]

        def flaky(ed, q=False, e=False, rendererOverrideName=None):
            if q:
                n[0] += 1
                if n[0] == 2:                      # 1 回目: 切替前の取得 / 2 回目: 切替後の確認(失敗)
                    raise RuntimeError("query failed")
            return real(ed, q=q, e=e, rendererOverrideName=rendererOverrideName)
        gv.cmds.modelEditor = flaky
        self.assertFalse(gv.enable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "prev", "確認できたので元へ戻した")
        self.assertEqual((gv._state, self.mgr.sup.get("modelPanel1", False)), ({}, False))

    def test_verify_query_keeps_failing_no_blind_write_and_pending_retry_info(self):
        gv.cmds.override["ed_modelPanel1"] = "prev"
        real = gv.cmds.modelEditor
        state = {"fail": False}

        def flaky(ed, q=False, e=False, rendererOverrideName=None):
            if q and state["fail"]:
                raise RuntimeError("query failed")
            r = real(ed, q=q, e=e, rendererOverrideName=rendererOverrideName)
            if e and rendererOverrideName == gv.OVERRIDE_NAME:
                state["fail"] = True               # 切替の直後から照会が失敗し続ける
            return r
        gv.cmds.modelEditor = flaky
        self.assertFalse(gv.enable("modelPanel1", self.mgr))
        self.assertEqual([e for e in gv.cmds.edits if e[1] == "prev"], [], "確認できないまま書き戻さない")
        st = gv.status()["modelPanel1"]
        self.assertEqual((st["pending"], st["prev"]), ("override", "prev"), "再試行できる情報が残る")
        self.assertEqual(self.mgr.sup.get("modelPanel1", False), False)
        state["fail"] = False                      # 照会が回復
        self.assertTrue(gv.disable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "prev")
        self.assertEqual(gv.status(), {})

    def test_set_suppressed_false_or_raise_rolls_back_the_switch(self):
        for mode in ("false", "raise"):
            gv._state.clear(); gv._override = None; FRenderer.registered = []
            gv.cmds = FCmds(); gv.cmds.override["ed_modelPanel1"] = "prev"
            m = Mgr({"guideThirds": True}, fail=lambda p, f, mode=mode: mode if f else None)
            self.assertFalse(gv.enable("modelPanel1", m), mode)
            self.assertEqual(gv.cmds.override["ed_modelPanel1"], "prev", mode)
            self.assertEqual(gv._state, {}, mode)

    def test_suppress_fails_and_override_restore_also_fails_leaves_retry_info(self):
        gv.cmds.override["ed_modelPanel1"] = "prev"
        gv.cmds.fail_set = lambda name: name == "prev"                      # 戻す書込みが失敗
        m = Mgr({"guideThirds": True}, fail=lambda p, f: "false" if f else None)
        self.assertFalse(gv.enable("modelPanel1", m))
        self.assertEqual(gv.status()["modelPanel1"]["pending"], "override")
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], gv.OVERRIDE_NAME, "戻せなかったことが状態に残っている")
        gv.cmds.fail_set = None
        m.fail = None
        self.assertTrue(gv.disable("modelPanel1", m))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "prev")

    def test_manager_missing_or_unable_to_suppress_never_succeeds(self):
        edits = lambda: list(gv.cmds.edits)
        self.assertFalse(gv.enable("modelPanel1", NoSuppress()))
        gv.cmds.edits.clear()
        saved_manager = gv._manager
        gv._manager = lambda m: None                                         # manager を解決できない
        try:
            self.assertFalse(gv.enable("modelPanel1", None))
        finally:
            gv._manager = saved_manager
        self.assertEqual((edits(), gv._state, FRenderer.registered), ([], {}, []), "何も変えない・登録もしない")

    def test_missing_panel_and_no_maya(self):
        self.assertFalse(gv.enable("nope", self.mgr))
        self.assertEqual(self.mgr.sup, {})
        gv.omr = None
        self.assertFalse(gv.enable("modelPanel1", self.mgr))

    # ---------------- disable の失敗経路 ----------------
    def test_disable_override_restore_fails_keeps_qt_suppressed_and_retries(self):
        gv.cmds.override["ed_modelPanel1"] = "prev"
        gv.enable("modelPanel1", self.mgr)
        gv.cmds.fail_set = lambda name: name == "prev"
        self.assertFalse(gv.disable("modelPanel1", self.mgr))
        self.assertEqual(self.mgr.sup["modelPanel1"], True, "オーバーライドが残っている間は Qt を戻さない(二重描画しない)")
        self.assertEqual(gv.status()["modelPanel1"]["pending"], "override")
        gv.cmds.fail_set = None
        self.assertTrue(gv.disable("modelPanel1", self.mgr))
        self.assertEqual((gv.cmds.override["ed_modelPanel1"], self.mgr.sup["modelPanel1"], gv.status()), ("prev", False, {}))

    def test_disable_restore_silently_ignored_is_detected_and_kept_for_retry(self):
        gv.cmds.override["ed_modelPanel1"] = "prev"
        gv.enable("modelPanel1", self.mgr)
        gv.cmds.ignore_set = lambda name: name == "prev"                    # 例外なしで効かない
        self.assertFalse(gv.disable("modelPanel1", self.mgr), "書込み後の確認で気づく")
        self.assertEqual((gv.status()["modelPanel1"]["pending"], self.mgr.sup["modelPanel1"]), ("override", True))
        gv.cmds.ignore_set = None
        self.assertTrue(gv.disable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.override["ed_modelPanel1"], "prev")

    def test_retry_after_override_restored_never_touches_override_again(self):
        gv.cmds.override["ed_modelPanel1"] = "prev"
        gv.enable("modelPanel1", self.mgr)
        self.mgr.fail = lambda p, f: "false" if not f else None
        self.assertFalse(gv.disable("modelPanel1", self.mgr))                # override は戻り、Qt 解除だけ未完
        gv.cmds.override["ed_modelPanel1"] = gv.OVERRIDE_NAME               # 別ツールが自分のものを選び直した
        edits = list(gv.cmds.edits)
        self.mgr.fail = None
        self.assertTrue(gv.disable("modelPanel1", self.mgr))
        self.assertEqual((gv.cmds.edits, gv.cmds.override["ed_modelPanel1"]), (edits, gv.OVERRIDE_NAME), "再試行は Qt の解除だけ")

    def test_disable_query_fails_keeps_everything_for_retry(self):
        gv.enable("modelPanel1", self.mgr)
        gv.cmds.query_raises = -1
        edits = list(gv.cmds.edits)
        self.assertFalse(gv.disable("modelPanel1", self.mgr))
        self.assertEqual((gv.cmds.edits, self.mgr.sup["modelPanel1"]), (edits, True))
        self.assertIn("modelPanel1", gv._state)
        gv.cmds.query_raises = 0
        self.assertTrue(gv.disable("modelPanel1", self.mgr))

    def test_disable_when_override_changed_by_someone_only_releases_qt(self):
        gv.enable("modelPanel1", self.mgr)
        gv.cmds.override["ed_modelPanel1"] = "userChoice"
        edits = list(gv.cmds.edits)
        self.assertTrue(gv.disable("modelPanel1", self.mgr))
        self.assertEqual((gv.cmds.override["ed_modelPanel1"], gv.cmds.edits), ("userChoice", edits), "別のものを上書きしない")
        self.assertEqual((self.mgr.sup["modelPanel1"], gv._state), (False, {}))

    def test_disable_qt_release_fails_keeps_info_and_retry_only_releases_qt(self):
        gv.cmds.override["ed_modelPanel1"] = "prev"
        gv.enable("modelPanel1", self.mgr)
        for mode in ("false", "raise"):
            self.mgr.fail = lambda p, f, mode=mode: mode if not f else None
            self.assertFalse(gv.disable("modelPanel1", self.mgr), mode)
            self.assertEqual(gv.cmds.override["ed_modelPanel1"], "prev", "オーバーライドは戻っている")
            self.assertEqual(gv.status()["modelPanel1"]["pending"], "qt", mode)
            self.assertEqual(self.mgr.sup["modelPanel1"], True, "Qt は抑止のまま(情報を失わない)")
        edits = list(gv.cmds.edits)
        self.mgr.fail = None
        self.assertTrue(gv.disable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.edits, edits, "再試行は Qt の解除だけ")
        self.assertEqual((self.mgr.sup["modelPanel1"], gv._state), (False, {}))

    def test_disable_without_state_is_false_and_harmless(self):
        self.assertFalse(gv.disable("modelPanel1", self.mgr))
        self.assertEqual(gv.cmds.edits, [])

    def test_disable_uses_the_state_manager_not_the_argument(self):
        gv.enable("modelPanel1", self.mgr)
        other = Mgr()
        self.assertTrue(gv.disable("modelPanel1", other))
        self.assertEqual(other.calls, [])
        self.assertEqual(self.mgr.sup["modelPanel1"], False)

    # ---------------- パネル別 manager ----------------
    def test_two_panels_two_managers_are_independent(self):
        m1 = Mgr({"guideThirds": True})
        m2 = Mgr({"guideGrid": True, "guideCenter": True})
        self.assertTrue(gv.enable("modelPanel1", m1))
        self.assertTrue(gv.enable("modelPanel2", m2))
        self.assertEqual(len(FRenderer.registered), 1)
        n1, n2 = self.draws("modelPanel1"), self.draws("modelPanel2")
        w1 = len(gv.flatten(go.build_ops(m1.config(), 400.0, 300.0, (0.0, 60.0, 400.0, 180.0)), 300))
        w2 = len(gv.flatten(go.build_ops(m2.config(), 400.0, 300.0, (0.0, 60.0, 400.0, 180.0)), 300))
        self.assertEqual((n1, n2), (w1, w2))
        self.assertNotEqual(n1, n2)
        self.assertEqual(self.draws("modelPanel1"), w1, "panel2 を enable した後も panel1 は自分の manager の設定")
        self.assertTrue(gv.disable("modelPanel1"))
        self.assertEqual((m1.sup, m2.sup), ({"modelPanel1": False}, {"modelPanel2": True}))
        self.assertEqual(self.draws("modelPanel2"), w2)
        self.assertEqual(self.draws("modelPanel1"), 0, "disable したパネルは描かない")
        self.assertEqual(gv.cmds.override["ed_modelPanel2"], gv.OVERRIDE_NAME)
        self.assertEqual(m2.calls, [("modelPanel2", True)], "別パネルの disable が m2 に触れない")
        self.assertEqual(gv.disable_all(), ["modelPanel2"])

    def test_disable_all_reports_only_successes_and_keeps_failures(self):
        gv.enable("modelPanel1", self.mgr); gv.enable("modelPanel2", self.mgr)
        self.mgr.fail = lambda p, f: "false" if (p == "modelPanel1" and not f) else None
        self.assertEqual(gv.disable_all(), ["modelPanel2"])
        self.assertEqual(list(gv.status()), ["modelPanel1"])
        self.assertEqual(gv.status()["modelPanel1"]["pending"], "qt")

    # ---------------- status ----------------
    def test_status_exists_query_failure_is_not_destruction(self):
        gv.enable("modelPanel1", self.mgr)
        gv.cmds.exists_raises = {"modelPanel1"}
        st = gv.status()
        self.assertEqual(st["modelPanel1"]["checked"], False)
        self.assertIn("modelPanel1", gv._state, "照会失敗では状態を捨てない")
        self.assertEqual(self.mgr.sup["modelPanel1"], True)

    def test_status_drops_only_confirmed_destroyed_panels_and_releases_qt(self):
        gv.enable("modelPanel1", self.mgr); gv.enable("modelPanel2", self.mgr)
        gv.cmds.alive.discard("modelPanel2")
        st = gv.status()
        self.assertEqual(list(st), ["modelPanel1"])
        self.assertEqual((self.mgr.sup["modelPanel2"], self.mgr.sup["modelPanel1"]), (False, True))

    def test_disable_after_panel_destroyed_still_releases_qt(self):
        gv.enable("modelPanel1", self.mgr)
        gv.cmds.alive.discard("modelPanel1")
        gv.cmds.query_raises = -1                                           # 破棄済みで照会不能
        self.assertFalse(gv.disable("modelPanel1", self.mgr))
        gv.cmds.query_raises = 0
        st = gv.status()                                                    # 破棄を確認できた → 状態を外し Qt を解放
        self.assertEqual((st, self.mgr.sup["modelPanel1"]), ({}, False))


class DefaultOff(unittest.TestCase):
    def test_nothing_imports_or_calls_gate_vp2_automatically(self):
        d = ROOT / 'scripts' / PACKAGE
        for f in d.glob('*.py'):
            if f.name == 'gate_vp2.py':
                continue
            import ast
            tree = ast.parse(f.read_text(encoding='utf-8'))
            for node in ast.walk(tree):               # コメント・docstring ではなく、実際の import / 参照だけを見る
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn('gate_vp2', [a.name for a in node.names] + [node.module or ''], f.name)
                elif isinstance(node, ast.Import):
                    self.assertNotIn('gate_vp2', [a.name for a in node.names], f.name)
                elif isinstance(node, ast.Name):
                    self.assertNotEqual(node.id, 'gate_vp2', f.name)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertIsNone(re.match(r'^[\w.]*gate_vp2$', node.value), f.name)   # import_module("...gate_vp2") 等の名前だけの文字列

    def test_import_has_no_side_effects(self):
        self.assertEqual(gv._state, {})
        self.assertIsNone(gv._override)

    def test_no_new_settings_keys(self):
        self.assertEqual(sorted(go.DEFAULTS), sorted(p3.DEFAULTS))


if __name__ == "__main__":
    unittest.main(verbosity=2)
