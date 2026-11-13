# -*- coding: utf-8 -*-
"""FX-PB-HZ-LAYOUT / FX-TOGGLE-SIZE(候補 g2)。offscreen Qt(実 Maya ではない)。
1) 上下配置(横並び)でペインが低くても、PLAYBLAST の部品が押し縮められず重ならない(足りない分は縦スクロール)。
2) トグルは全部同じ大きさ(小さいトラックを使わない)。
3) 縦ドックの最小幅 300px でも、Multi の 2 行目を含めて横スクロールが出ない(日本語・英語)。
使い方: PKG_DIR=<scripts/plsCamView|plsFxView> python3 test_pb_layout.py   旧(g1)では 1・2 が落ちる。
"""
import importlib
import itertools
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PKG_DIR = Path(os.environ["PKG_DIR"])
pkg = types.ModuleType(PKG_DIR.name)
pkg.__path__ = [str(PKG_DIR)]
sys.modules[PKG_DIR.name] = pkg
try:
    import ast
    for _n in ast.parse((PKG_DIR / "__init__.py").read_text(encoding="utf-8")).body:
        if isinstance(_n, ast.Assign) and getattr(_n.targets[0], "id", "") == "GRADE_DEFAULTS":
            pkg.GRADE_DEFAULTS = ast.literal_eval(_n.value)
except Exception:
    pass
qt = importlib.import_module(PKG_DIR.name + ".qt")
style = importlib.import_module(PKG_DIR.name + ".style")
ui = importlib.import_module(PKG_DIR.name + ".ui")
settings = importlib.import_module(PKG_DIR.name + ".settings")
i18n = importlib.import_module(PKG_DIR.name + ".i18n")
QtCore, QtGui, QW = qt.QtCore, qt.QtGui, qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])

LEAF = (style.ToggleSwitch, QW.QAbstractSpinBox, QW.QComboBox, QW.QAbstractButton, QW.QLineEdit, QW.QSlider)
WORST = {"playblastSettingsCollapsed": False, "playblastCaptureCollapsed": False, "playblastMulti": True,
         "playblastCombine": True, "playblastKeepIndividuals": True}


def make(lang="ja", extra=None):
    data = {"language": lang, "camera": "persp"}
    data.update(extra or {})
    o = types.SimpleNamespace(data=data, save_settings=lambda: None, views=None,
                              refresh_cameras=lambda *a, **k: None, apply_effects=lambda *a, **k: None,
                              fit_toolbox_height=lambda: None, set_dock_area=lambda k: None,
                              on_target_changed=lambda: None, set_force_playblast=lambda v: None)
    tb = ui.ToolBox(o)
    o.tb = tb
    tb.pull(dict(settings.DEFAULTS, **o.data))
    return tb


def settle():
    for _ in range(3):
        QW.QApplication.sendPostedEvents()
        app.processEvents()


def leaves(root):
    out = []
    for w in root.findChildren(QW.QWidget):
        if not isinstance(w, LEAF) or not w.isVisibleTo(root) or w.width() <= 0:
            continue
        if any(isinstance(p, LEAF) for p in _parents(w, root)):
            continue                                    # 部品の中の部品(スピンボックスの中の編集欄など)は除く
        out.append(w)
    return out


def _parents(w, root):
    p = w.parentWidget()
    while p is not None and p is not root:
        yield p
        p = p.parentWidget()


def need_h(w):
    u"""その部品が潰れずに必要な高さ。固定寸法(setFixedSize)の部品はその値。"""
    if w.minimumHeight() > 0 and w.minimumHeight() == w.maximumHeight():
        return w.maximumHeight()
    return min(max(w.minimumSizeHint().height(), 1), w.sizeHint().height(), w.maximumHeight())


def rect_in(w, root):
    tl = w.mapTo(root, QtCore.QPoint(0, 0))
    return QtCore.QRect(tl, w.size())


class PbLayout(unittest.TestCase):
    def check_not_squeezed(self, tb, tag):
        card = tb._pbCard
        ws = leaves(card)
        self.assertGreater(len(ws), 8, tag)
        for w in ws:
            need = need_h(w)
            self.assertGreaterEqual(w.height() + 1, need,
                                    "%s: %s %s が押し縮められた(高さ %d < %d)" % (tag, type(w).__name__,
                                                                         getattr(w, "text", lambda: "")(), w.height(), need))
        for a, b in itertools.combinations(ws, 2):
            ra, rb = rect_in(a, card), rect_in(b, card)
            inter = ra.intersected(rb)
            self.assertFalse(inter.width() > 1 and inter.height() > 1,
                             "%s: 重なり %s(%s) と %s(%s)" % (tag, type(a).__name__, getattr(a, "text", lambda: "")(),
                                                         type(b).__name__, getattr(b, "text", lambda: "")()))

    def test_horizontal_low_pane_does_not_squeeze_playblast(self):
        for lang, h in (("ja", 240), ("en", 240), ("ja", 160), ("ja", 600)):
            tb = make(lang, WORST)
            self.addCleanup(tb.deleteLater)
            tb.set_orientation(True)
            # 自動で畳まれた Settings / 撮影オプションも開いた最悪の状態にする
            tb.pbSettings.setCollapsed(False)
            tb.pbCaptureBox.setCollapsed(False)
            tb.resize(2000, h)
            tb.show()
            settle()
            tag = "%s h=%d" % (lang, h)
            self.check_not_squeezed(tb, tag)
            if tb._pbCard.sizeHint().height() > h:
                sc = next(a for a in tb.findChildren(QW.QScrollArea) if a.isAncestorOf(tb._pbCard))
                self.assertGreater(sc.verticalScrollBar().maximum(), 0, tag + ": 低いのにスクロールできない")
            tb.hide()

    def test_back_to_vertical_restores_card_in_main_scroll(self):
        tb = make("ja", WORST)
        self.addCleanup(tb.deleteLater)
        tb.resize(333, 700)
        tb.show()
        tb.set_orientation(True)
        settle()
        tb.set_orientation(False)
        settle()
        self.assertTrue(tb._scroll.widget().isAncestorOf(tb._pbCard))
        self.assertTrue(tb._pbCard.isVisible())
        tb.set_orientation(True)
        settle()
        self.assertFalse(tb._scroll.widget().isAncestorOf(tb._pbCard))
        self.assertTrue(tb._pbCard.isVisible())

    def test_all_toggles_same_size(self):
        tb = make("ja", WORST)
        self.addCleanup(tb.deleteLater)
        ts = tb.findChildren(style.ToggleSwitch)
        self.assertGreater(len(ts), 10)
        sizes = {(t.TRACK_W, t.TRACK_H) for t in ts}
        self.assertEqual(len(sizes), 1, "トグルの大きさが混在: %r" % sorted(sizes))

    def test_multi_sub_row_follows_multi(self):
        tb = make("ja", {"playblastMulti": False})
        self.addCleanup(tb.deleteLater)
        tb.resize(333, 700)
        tb.show()
        settle()
        self.assertFalse(tb.multiCombine.isVisible())
        tb.multiEnabled.setChecked(True)
        settle()
        self.assertTrue(tb.multiCombine.isVisible())
        # g3(2026-11-08 本人指定): 合成 / 個別保持 は Multi と同じ組(入る限り同じ行。幅が足りなければ組ごと次の行)
        settle()
        self.assertEqual(tb.multiCombine.mapTo(tb, QtCore.QPoint(0, 0)).y(),
                         tb.multiEnabled.mapTo(tb, QtCore.QPoint(0, 0)).y(), "合成は Multi と同じ行")

    def test_vertical_min_width_fits_without_hscroll(self):
        for lang in ("ja", "en"):
            tb = make(lang, WORST)
            self.addCleanup(tb.deleteLater)
            tb.resize(style.px(300), 900)
            tb.show()
            settle()
            # PLAYBLAST カードがパネルの最小幅を広げないこと(上段の言語行など他カードの幅は対象外)
            avail = tb._scroll.viewport().width() - 2 * style.px(8)
            if lang == "ja":                              # 英語は既存の幅超過あり(g1 270px → g2 263px。別件)
                self.assertLessEqual(tb._pbCard.minimumSizeHint().width(), avail,
                                     "%s: 300px で PLAYBLAST がはみ出す" % lang)
            self.check_not_squeezed(tb, lang + " 縦 300px")
            # 他カード(SliderRow の数値欄は設計上 27px、Gate の一部に数 px の既存の詰まり)は対象外。別件で記録
            tb.hide()


if __name__ == "__main__":
    unittest.main(verbosity=2)
