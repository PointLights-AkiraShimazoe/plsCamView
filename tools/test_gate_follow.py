# -*- coding: utf-8 -*-
u"""gate_overlay のウィンドウ移動追従(v1.8.1 修正)の再現検証。実Qt(offscreen 可)・Maya なし。

対象の修正: _retarget_top(eventFilter と Qt 親を現在のトップレベルへ移す)と、
_poll の位置検証フォールバック。再現する不具合は 2 つ:
(a) 生成時のトップレベル(A)にしか filter が無いため、ビューが別ウィンドウ(B)へ再親付けされた後
    (ポップアウト/attach 直後の再親付けに相当)は B の移動が届かず、ゲートが置き去りになる。
(b) Qt 親が A のままだと、A が破棄された時にオーバーレイが Qt の親子関係で一緒に破棄され、
    生きているビューのゲートが消える(寿命問題。test_survives_old_top_delete が弁別する)。

注意: これは Qt の限定検査で、**実 Maya での遅れの解消を断定しない**(実機確認はチェックリスト側)。
実 Maya のユーザー報告(ドラッグ中の遅れ)がどの経路かも、この検査だけでは断定しない。
通常ドラッグの遅延(1)と、再親付け後の不追従(3)・旧トップ破棄の寿命(7)は別の条件として分けてある。
"""
import importlib
import os
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(os.environ.get('PLS_TEST_SOURCE', str(Path(__file__).resolve().parents[1])))
PACKAGE = ROOT.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT/'scripts'/PACKAGE)]
sys.modules[PACKAGE] = pkg
qt = importlib.import_module(PACKAGE+'.qt')
gate_overlay = importlib.import_module(PACKAGE+'.gate_overlay')
QC, QW = qt.QtCore, qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])

CFG = {"gateEnabled": True}      # any_drawing が真になる最小設定


def view_rect(view):
    return QC.QRect(view.mapToGlobal(QC.QPoint(0, 0)), view.size())


class GateFollow(unittest.TestCase):
    def setUp(self):
        self.a = QW.QWidget()
        self.a.setGeometry(100, 100, 600, 400)
        self.view = QW.QWidget(self.a)
        self.view.setGeometry(10, 20, 400, 200)
        self.a.show(); self.view.show(); app.processEvents()
        self.b = None
        self.ov = gate_overlay.GateOverlay("dummyPanel", self.view)
        self.ov.set_config(CFG)
        app.processEvents()

    def tearDown(self):
        try:
            self.ov.detach()
        except Exception:
            pass
        for w in (self.b, self.a):
            if w is not None:
                w.close(); w.deleteLater()
        app.sendPostedEvents(None, QC.QEvent.DeferredDelete)
        app.processEvents()

    # (1) 同一ウィンドウの移動: Move イベントだけで即追従する(タイマー待ちなし)
    def test_move_follows_immediately(self):
        self.assertTrue(self.ov.isVisible())
        self.assertEqual(self.ov.geometry(), view_rect(self.view))
        self.a.move(self.a.x() + 150, self.a.y() + 60)
        app.processEvents()
        self.assertEqual(self.ov.geometry(), view_rect(self.view),
                         u"トップレベル移動にオーバーレイが即追従していない")

    # (2) リサイズ: ビューの実寸へ即追従
    def test_resize_follows(self):
        self.view.setGeometry(10, 20, 320, 160)
        app.processEvents()
        self.assertEqual(self.ov.geometry(), view_rect(self.view))

    # (3) 再親付け(ポップアウト相当)後、新ウィンドウ B の移動へ追従する
    #     v1.8.0 では filter が A のままなので B の移動が届かず不合格になる(修正の弁別点)。
    def test_follows_after_reparent(self):
        self.b = QW.QWidget()
        self.b.setGeometry(800, 150, 500, 320)
        self.view.setParent(self.b)
        self.view.setGeometry(5, 5, 300, 150)
        self.b.show(); self.view.show()
        app.processEvents()           # Show → _sync_timer(0) → _sync_geometry → _retarget_top
        app.processEvents()
        self.assertEqual(self.ov.geometry(), view_rect(self.view),
                         u"再親付け直後にオーバーレイ位置が揃っていない")
        self.b.move(self.b.x() + 120, self.b.y() + 40)
        app.processEvents()
        self.assertEqual(self.ov.geometry(), view_rect(self.view),
                         u"再親付け後、新しいウィンドウの移動に追従していない(filter 未付替え)")

    # (4) 再親付け後、旧ウィンドウ A の移動では動かない(古い filter が残っていない)
    def test_old_window_detached(self):
        self.test_follows_after_reparent()
        g = self.ov.geometry()
        self.a.move(self.a.x() + 200, self.a.y() + 90)
        app.processEvents()
        self.assertEqual(self.ov.geometry(), g,
                         u"旧ウィンドウの移動でオーバーレイが動いた(古い filter が残っている)")
        self.assertEqual(self.ov.geometry(), view_rect(self.view))

    # (5) _poll の位置検証フォールバック: イベント無しでずれても次の poll で復帰
    def test_poll_restores_position(self):
        wrong = QC.QRect(self.ov.geometry().translated(999, 999))
        self.ov.setGeometry(wrong)
        self.assertNotEqual(self.ov.geometry(), view_rect(self.view))
        self.ov._poll()
        app.processEvents()
        self.assertEqual(self.ov.geometry(), view_rect(self.view),
                         u"_poll の位置検証がずれを直していない")

    # (7) 旧トップレベルの破棄で現ビューのゲートが消えない(Qt 親の付け替え。寿命の弁別点)
    #     filter だけ移して Qt 親を旧ウィンドウ A に残す実装(継続62 版)では、A の破棄と一緒に
    #     オーバーレイの C++ 側が破棄されてゲートが消えるため、この検査で不合格になる。
    def test_survives_old_top_delete(self):
        self.test_follows_after_reparent()
        self.assertIs(self.ov.parent(), self.b,
                      u"Qt 親が現在のトップレベルへ移っていない(旧トップ破棄で道連れになる)")
        a, self.a = self.a, None
        a.close(); a.deleteLater()
        app.sendPostedEvents(None, QC.QEvent.DeferredDelete)
        app.processEvents()
        self.assertFalse(gate_overlay._dead(self.ov),
                         u"旧トップレベルの破棄でオーバーレイが道連れに破棄された(寿命問題)")
        self.assertFalse(self.ov._disposed)
        self.assertTrue(self.ov.isVisible(), u"旧トップレベル破棄後にゲートが消えた")
        self.b.move(self.b.x() + 60, self.b.y() + 25)
        app.processEvents()
        self.assertEqual(self.ov.geometry(), view_rect(self.view),
                         u"旧トップレベル破棄後にビューへの追従が失われた")

    # (8) 対照: Qt 親を移さない実装(継続62 相当)では同じ手順で道連れ破棄になる
    #     = (7) が修正の有無を実際に弁別できることの証明(製品コードは修正版のまま)。
    def test_old_top_delete_discriminates(self):
        self.ov.detach()
        app.processEvents()

        class NoReparent(gate_overlay.GateOverlay):
            def _retarget_top(self):      # filter だけ移す(継続62 の実装相当)
                try:
                    top = self._view.window()
                except RuntimeError:
                    return False
                if top is None or top is self._top:
                    return False
                old = self._top
                self._top = top
                if old is not None and old is not self._view and not gate_overlay._dead(old):
                    old.removeEventFilter(self)
                if top is not self._view:
                    top.installEventFilter(self)
                return True

        self.ov = NoReparent("dummyPanel", self.view)
        self.ov.set_config(CFG)
        app.processEvents()
        self.b = QW.QWidget()
        self.b.setGeometry(800, 150, 500, 320)
        self.view.setParent(self.b)
        self.view.setGeometry(5, 5, 300, 150)
        self.b.show(); self.view.show()
        app.processEvents(); app.processEvents()
        a, self.a = self.a, None
        a.close(); a.deleteLater()
        app.sendPostedEvents(None, QC.QEvent.DeferredDelete)
        app.processEvents()
        self.assertTrue(gate_overlay._dead(self.ov),
                        u"対照(親を移さない)が道連れ破棄にならなかった: (7) の弁別性が崩れている")

    # (6) detach: ビュー破棄で孤児ウィンドウを残さない
    def test_detach_no_orphan(self):
        self.view.deleteLater()
        app.sendPostedEvents(None, QC.QEvent.DeferredDelete)
        app.processEvents()
        self.assertTrue(self.ov._disposed, u"ビュー破棄後に detach されていない")
        app.sendPostedEvents(None, QC.QEvent.DeferredDelete)
        app.processEvents()
        alive = [w for w in QW.QApplication.topLevelWidgets()
                 if isinstance(w, gate_overlay.GateOverlay) and w.isVisible()]
        self.assertEqual(alive, [], u"可視のオーバーレイ孤児ウィンドウが残っている")


if __name__ == "__main__":
    unittest.main(verbosity=2)
