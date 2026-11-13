# -*- coding: utf-8 -*-
u"""gate_overlay の実親ウィンドウ**連続**移動・連続 resize・reparent(ポップアウト相当)・
複数ビュー(OverlayManager 相当の 2 オーバーレイ)の追従検証(0.9.1)。実 Qt(offscreen 可)・Maya なし。

対照条件: _retarget_top と _poll の位置検証(どちらも v1.8.1 の修正点。v1.8.0 には無い)を
無効化した「旧実装相当」では reparent 後の移動に追従できないことを確認し、この検査自体の
判別力を保証する(旧 v1.8.0 がユーザー環境でゲートずれを起こした経路の再現)。

注意: これは Qt の限定検査で、**実 Maya での解消を断定しない**(受入は実機チェックリスト側)。"""
import importlib
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(os.environ.get('PLS_TEST_SOURCE', str(Path(__file__).resolve().parents[1])))
PACKAGE = ROOT.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT / 'scripts' / PACKAGE)]
sys.modules.setdefault(PACKAGE, pkg)
qt = importlib.import_module(PACKAGE + '.qt')
gate_overlay = importlib.import_module(PACKAGE + '.gate_overlay')
QC, QW = qt.QtCore, qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])

CFG = {"gateEnabled": True}


def view_rect(view):
    return QC.QRect(view.mapToGlobal(QC.QPoint(0, 0)), view.size())


class Base(unittest.TestCase):
    def setUp(self):
        self.tops = []
        self.overlays = []

    def tearDown(self):
        for ov in self.overlays:
            try:
                ov.detach()
            except Exception:
                pass
        for w in self.tops:
            try:
                w.close(); w.deleteLater()
            except Exception:
                pass
        app.sendPostedEvents(None, QC.QEvent.DeferredDelete)
        app.processEvents()

    def make_view(self, x=100, y=100):
        top = QW.QWidget()
        top.setGeometry(x, y, 600, 400)
        view = QW.QWidget(top)
        view.setGeometry(10, 20, 400, 200)
        top.show(); view.show(); app.processEvents()
        self.tops.append(top)
        return top, view

    def attach(self, panel, view):
        ov = gate_overlay.GateOverlay(panel, view)
        ov.set_config(CFG)
        app.processEvents()
        self.overlays.append(ov)
        return ov


class ContinuousFollow(Base):
    def test_continuous_window_move(self):
        u"""親ウィンドウを 30 ステップ連続移動。各ステップ直後(poll を待たず)に一致する。"""
        top, view = self.make_view()
        ov = self.attach("p1", view)
        for i in range(30):
            top.move(100 + 7 * (i + 1), 100 + 3 * (i + 1))
            app.processEvents()
            self.assertEqual(ov.geometry(), view_rect(view), u"step {} でゲートが遅れた".format(i + 1))

    def test_continuous_resize(self):
        u"""親ウィンドウとビューの連続 resize(20 ステップ)に即追従する。"""
        top, view = self.make_view()
        ov = self.attach("p1", view)
        for i in range(20):
            top.resize(600 + 6 * (i + 1), 400 + 4 * (i + 1))
            view.resize(400 + 6 * (i + 1), 200 + 4 * (i + 1))
            app.processEvents()
            self.assertEqual(ov.geometry(), view_rect(view), u"resize step {} で不一致".format(i + 1))

    def test_reparent_then_continuous_move(self):
        u"""別ウィンドウへ再親付け(ポップアウト相当)後の連続移動にも各ステップで追従する。"""
        top, view = self.make_view()
        ov = self.attach("p1", view)
        b = QW.QWidget()
        b.setGeometry(420, 260, 600, 400)
        self.tops.append(b)
        view.setParent(b)
        view.setGeometry(16, 24, 380, 180)
        b.show(); view.show(); app.processEvents()
        ov._sync_geometry()          # 再親付け直後の 1 回(実運用では poll ≤200ms が拾う)
        app.processEvents()
        for i in range(20):
            b.move(420 + 9 * (i + 1), 260 + 5 * (i + 1))
            app.processEvents()
            self.assertEqual(ov.geometry(), view_rect(view),
                             u"reparent 後 step {} でゲートが置き去り".format(i + 1))

    def test_two_views_follow_independently(self):
        u"""複数ビュー相当: 2 つの別ウィンドウのオーバーレイが独立に連続追従する。"""
        top1, view1 = self.make_view(80, 80)
        top2, view2 = self.make_view(760, 90)
        ov1 = self.attach("p1", view1)
        ov2 = self.attach("p2", view2)
        for i in range(15):
            top1.move(80 + 8 * (i + 1), 80 + 2 * (i + 1))
            top2.move(760 - 6 * (i + 1), 90 + 5 * (i + 1))
            app.processEvents()
            self.assertEqual(ov1.geometry(), view_rect(view1), u"view1 step {}".format(i + 1))
            self.assertEqual(ov2.geometry(), view_rect(view2), u"view2 step {}".format(i + 1))
        view2.hide(); app.processEvents()
        ov2._sync_geometry(); app.processEvents()
        self.assertFalse(ov2.isVisible(), u"隠したビューのゲートが残る")
        self.assertTrue(ov1.isVisible())

    def test_retarget_delivers_new_top_moves(self):
        u"""対照条件(機構レベル): v1.8.0 の経路では、再親付け後の新トップ B の Move が
        eventFilter に届かない(filter が旧トップ A にしか無い)。v1.8.1 の _retarget_top が
        あると B の Move が届き、ドラッグ中の即時追従経路が成立する。
        offscreen では無関係なイベント経由の遅延 sync が偶然効くことがあるため、
        「ゲート位置の一致」ではなく「Move イベントが届くこと」で判別する。"""
        received = []
        orig_filter = gate_overlay.GateOverlay.eventFilter

        def spy(self, obj, ev):
            if ev.type() == QC.QEvent.Move:
                received.append(obj)
            return orig_filter(self, obj, ev)

        def legacy_watch(self):
            # v1.8.0 相当: 生成時のビューと最上位だけを監視し、以後は付け替えない
            if getattr(self, "_watched", None):
                return self._watched
            chain = [self._view] + ([self._view.window()] if self._view.window() is not self._view else [])
            for w in chain:
                w.installEventFilter(self)
            self._watched = chain
            return chain

        # --- v1.8.0 相当(_retarget_top 無し・祖先監視の付け替え無し): B の Move は届かない
        with patch.object(gate_overlay.GateOverlay, 'eventFilter', spy), \
                patch.object(gate_overlay.GateOverlay, '_retarget_top', lambda self: False), \
                patch.object(gate_overlay.GateOverlay, '_rewatch', legacy_watch):
            top, view = self.make_view()
            ov = self.attach("p1", view)
            b = QW.QWidget()
            b.setGeometry(420, 260, 600, 400)
            self.tops.append(b)
            view.setParent(b)
            view.setGeometry(16, 24, 380, 180)
            b.show(); view.show(); app.processEvents()
            received.clear()
            b.move(520, 330); app.processEvents()
            self.assertNotIn(b, received,
                             u"旧実装相当で B の Move が届いている(検査が判別できていない)")
            ov.detach(); app.processEvents()

        # --- 現行(0.9.x): retarget 後は B の Move が届く(即時追従の主経路)
        with patch.object(gate_overlay.GateOverlay, 'eventFilter', spy):
            top2, view2 = self.make_view(140, 140)
            ov2 = self.attach("p2", view2)
            b2 = QW.QWidget()
            b2.setGeometry(460, 300, 600, 400)
            self.tops.append(b2)
            view2.setParent(b2)
            view2.setGeometry(16, 24, 380, 180)
            b2.show(); view2.show(); app.processEvents()
            ov2._sync_geometry(); app.processEvents()   # retarget を確定(実運用は poll ≤200ms)
            received.clear()
            b2.move(560, 370); app.processEvents()
            self.assertIn(b2, received, u"retarget 後も B の Move が届かない")
            self.assertEqual(ov2.geometry(), view_rect(view2))

    def test_poll_fixes_forced_drift(self):
        u"""v1.8.1 のもう一つの修正(poll の位置検証): 位置を強制的にずらしても
        _poll が実位置へ戻す(v1.8.0 の poll は位置を直さない=diff で確認済み・docstring 記録)。"""
        top, view = self.make_view()
        ov = self.attach("p1", view)
        wrong = QC.QRect(5, 5, 50, 50)
        ov.setGeometry(wrong)
        self.assertNotEqual(ov.geometry(), view_rect(view))
        ov._poll()
        app.processEvents()
        self.assertEqual(ov.geometry(), view_rect(view), u"poll が位置を直さない")


class AncestorFollow(Base):
    u"""0.9.1 r6: ビュー自身は動かず、途中の祖先(ドック/スプリッタ/ワークスペース内の配置)だけが動く場合。
    Maya のワークスペースで隣のパネル幅を変える・ツールボックスのドック幅を変えると、ビューは親の中の
    同じ位置(0,0)のまま画面位置だけが変わり、ビューにも最上位ウィンドウにも Move が届かない。
    旧実装(ビューと最上位だけを監視)は poll(≤200ms)まで置き去りになる=「UI を動かすとずれる」の候補経路。"""

    def make_nested(self):
        top = QW.QWidget()
        top.setGeometry(100, 100, 900, 500)
        lay = QW.QHBoxLayout(top)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        side = QW.QWidget(top)          # 隣のドック(幅が変わる)
        side.setFixedWidth(200)
        host = QW.QWidget(top)          # ワークスペースのパネル
        host.setFixedWidth(520)         # パネル幅は一定(ビューは resize されず位置だけ変わる)
        lay.addWidget(side)
        lay.addWidget(host)
        lay.addStretch(1)
        hl = QW.QVBoxLayout(host)
        hl.setContentsMargins(0, 0, 0, 0)
        slot = QW.QWidget(host)         # ビュー枠
        hl.addWidget(slot)
        sl = QW.QVBoxLayout(slot)
        sl.setContentsMargins(0, 0, 0, 0)
        view = QW.QWidget(slot)         # ビューは枠の (0,0) に固定
        sl.addWidget(view)
        top.show(); app.processEvents()
        self.tops.append(top)
        return top, side, host, slot, view

    def test_sibling_dock_width_change(self):
        u"""隣のドック幅を 20 段階で変える(ビューは親内 (0,0) のまま)。各段で poll を待たず一致する。"""
        top, side, host, slot, view = self.make_nested()
        ov = self.attach("p1", view)
        ov._timer.stop()                 # poll を止め、イベント経路だけで追従できるかを見る
        size0 = view.size()
        for i in range(20):
            side.setFixedWidth(200 + 9 * (i + 1))
            app.processEvents()
            self.assertEqual(view.pos(), QC.QPoint(0, 0))
            self.assertEqual(view.size(), size0, u"この試験はビューが resize されない条件")
            self.assertEqual(ov.geometry(), view_rect(view), u"ドック幅 step {} でゲートが置き去り".format(i + 1))

    def test_intermediate_ancestor_move(self):
        u"""途中の祖先(パネル)だけを動かす。"""
        top, side, host, slot, view = self.make_nested()
        ov = self.attach("p1", view)
        ov._timer.stop()
        top.layout().removeWidget(host)
        for i in range(15):
            host.setGeometry(220 + 11 * (i + 1), 10 + 4 * (i + 1), 500, 400)
            app.processEvents()
            self.assertEqual(ov.geometry(), view_rect(view), u"祖先移動 step {}".format(i + 1))

    def test_intermediate_reparent_within_window(self):
        u"""途中の祖先を同じウィンドウ内の別コンテナへ付け替えた後も、その新しい祖先の移動に追従する。"""
        top, side, host, slot, view = self.make_nested()
        ov = self.attach("p1", view)
        ov._timer.stop()
        other = QW.QWidget(top)
        other.setGeometry(300, 50, 500, 400)
        other.show()
        slot.setParent(other)
        slot.setGeometry(0, 0, 400, 300)
        slot.show(); app.processEvents()
        for i in range(10):
            other.move(300 + 13 * (i + 1), 50 + 6 * (i + 1))
            app.processEvents()
            self.assertEqual(ov.geometry(), view_rect(view), u"付け替え後 step {}".format(i + 1))

    def test_control_view_and_top_only_lags(self):
        u"""対照: 監視をビューと最上位だけに限定した旧方式では、隣のドック幅変更に poll なしでは追従しない
        (この試験群の判別力の保証)。"""
        top, side, host, slot, view = self.make_nested()
        ov = self.attach("p1", view)
        ov._timer.stop()
        for w in list(getattr(ov, "_watched", [])):
            if w is not view and w is not ov._top:
                w.removeEventFilter(ov)
        ov._watched = [view, ov._top]
        miss = 0
        with patch.object(ov, "_rewatch", lambda *a, **k: ov._watched):
            for i in range(6):
                side.setFixedWidth(200 + 25 * (i + 1))
                app.processEvents()
                miss += int(ov.geometry() != view_rect(view))
        self.assertGreater(miss, 0, u"対照条件でも全段追従した(試験の判別力が無い)")


if __name__ == '__main__':
    unittest.main(verbosity=1)
