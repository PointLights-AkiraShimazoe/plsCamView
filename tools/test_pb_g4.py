# -*- coding: utf-8 -*-
"""FX-PB-LAYOUT-G4(2026-11-10 本人指定)。offscreen Qt(実 Maya ではない)。
  1 行目 [Force] / 2 行目 [Multi](ON で右に [合成][個別保持]。位置も行数も変わらない)
  Time Range [シーン範囲](OFF で同じ行に 開始 → 終了) / 解像度・FPS の欄は隠さず、切替 ON の間は押せない+元の値
  品質 / CRF / プリセット 1 行 / [完了後に開く][PNG を残す]
使い方: PKG_DIR=<scripts/plsCamView|plsFxView> python3 test_pb_g4.py   g3 では落ちる。
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
QtCore, QW = qt.QtCore, qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])

RS = (1280, 720)
SCENE_FPS = 24.0
ui.mp4blast.render_settings_size = lambda *a, **k: RS      # レンダー設定 / シーン FPS(Maya の代わり)
ui.mp4blast.scene_fps = lambda *a, **k: SCENE_FPS


def settle(n=5):
    for _ in range(n):
        QW.QApplication.sendPostedEvents()
        app.processEvents()


def pos(w, root):
    p = w.mapTo(root, QtCore.QPoint(0, 0))
    return p.x(), p.y()


def cy(w, root):
    return pos(w, root)[1] + w.height() // 2


def same_row(*ws, root=None, tol=2):
    c = [cy(w, root) for w in ws]
    return max(c) - min(c) <= tol


class G4(unittest.TestCase):
    def tearDown(self):
        style.set_ui_scale(style.UI_SCALE_DEFAULT)
        i18n.set_language("system")
        app.processEvents()

    def make(self, extra=None, width=333, height=1600, horizontal=False):
        data = {"language": "ja", "camera": "persp"}
        data.update(extra or {})
        saved = {}

        def save():
            saved.update(o.data)
        o = types.SimpleNamespace(data=data, save_settings=save, views=None,
                                  refresh_cameras=lambda *a, **k: None, apply_effects=lambda *a, **k: None,
                                  fit_toolbox_height=lambda: None, set_dock_area=lambda k: None,
                                  on_target_changed=lambda: None, set_force_playblast=lambda v: None)
        tb = ui.ToolBox(o)
        o.tb = tb
        o.saved = saved
        self.addCleanup(tb.deleteLater)
        tb.pull(dict(settings.DEFAULTS, **data))
        if horizontal:
            tb.set_orientation(True)
            tb.pbSettings.setCollapsed(False)
        tb.resize(width, height)
        tb.show()
        settle()
        return o, tb

    # ---- 1) Force / Multi --------------------------------------------------------------
    def test_force_alone_then_multi_row(self):
        o, tb = self.make(width=520)
        fy, my = pos(tb.forceChk, tb)[1], pos(tb.multiEnabled, tb)[1]
        self.assertLess(fy, my, "Multi は Force の下の行")
        self.assertEqual(pos(tb.forceChk, tb)[0], pos(tb.multiEnabled, tb)[0], "どちらも行の先頭")

    def test_multi_toggle_moves_nothing(self):
        for lang, width in itertools.product(("ja", "en"), (520, 333, 300, 280)):
            o, tb = self.make({"language": lang, "playblastMulti": False}, width=width)
            before = (pos(tb.multiEnabled, tb), tb._pbTopRow.height(), pos(tb.pbRangeScene, tb), pos(tb.pbBtn, tb))
            self.assertFalse(tb.multiCombine.isVisible() or tb.multiKeep.isVisible())
            tb.multiEnabled.setChecked(True)
            settle()
            after = (pos(tb.multiEnabled, tb), tb._pbTopRow.height(), pos(tb.pbRangeScene, tb), pos(tb.pbBtn, tb))
            self.assertEqual(before, after, (lang, width))
            self.assertTrue(tb.multiCombine.isVisible() and tb.multiKeep.isVisible(), (lang, width))
            if width >= 520:
                self.assertTrue(same_row(tb.multiEnabled, tb.multiCombine, tb.multiKeep, root=tb), (lang, width))
                self.assertLess(pos(tb.multiEnabled, tb)[0], pos(tb.multiCombine, tb)[0])

    def test_default_width_has_no_reserved_blank_rows(self):
        u"""既定幅(333)では、隠している部品のために空いた行ができない(Multi / PNG を残す の組が 1 行に収まる)。"""
        for lang in ("ja", "en"):
            o, tb = self.make({"language": lang, "playblastMulti": True, "playblastCombine": True, "outputMode": "mp4"})
            self.assertTrue(same_row(tb.multiEnabled, tb.multiCombine, tb.multiKeep, root=tb), lang)
            self.assertTrue(same_row(tb.mp4OpenAfter, tb.mp4KeepFrames, root=tb), lang)

    def test_keep_each_needs_combine(self):
        o, tb = self.make({"playblastMulti": True, "playblastCombine": False})
        self.assertTrue(tb.multiKeep.isVisible())
        self.assertFalse(tb.multiKeep.isEnabled())
        tb.multiCombine.setChecked(True)
        settle()
        self.assertTrue(tb.multiKeep.isEnabled())

    # ---- 2) Time Range -----------------------------------------------------------------
    def test_range_fields_on_the_scene_row(self):
        for lang, width in itertools.product(("ja", "en"), (520, 333, 280)):
            o, tb = self.make({"language": lang, "playblastRangeScene": True}, width=width)
            before = (pos(tb.pbRangeScene, tb), tb._pbRangeHead.height(), pos(tb.pbOutputBox, tb))
            self.assertTrue(tb.pbStart.isVisible() and tb.pbEnd.isVisible(), "シーン範囲 ON でも欄は見える")
            self.assertFalse(tb.pbStart.isEnabled() or tb.pbEnd.isEnabled(), "シーン範囲 ON の間は押せない")
            self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), tuple(tb._scene_range()), "シーンの範囲を表示")
            tb.pbRangeScene.setChecked(False)
            settle()
            after = (pos(tb.pbRangeScene, tb), tb._pbRangeHead.height(), pos(tb.pbOutputBox, tb))
            self.assertEqual(before, after, (lang, width, "切替で行も位置も変わらない"))
            self.assertTrue(tb.pbStart.isEnabled() and tb.pbEnd.isEnabled())
            self.assertTrue(same_row(tb.pbStart, tb.pbEnd, root=tb))
            if width >= 520:
                self.assertTrue(same_row(tb.pbRangeScene, tb.pbStart, root=tb), (lang, "同じ行"))
                self.assertLess(pos(tb.pbRangeScene, tb)[0], pos(tb.pbStart, tb)[0])
            tb.pbStart.setValue(1001)
            tb.pbEnd.setValue(1100)
            settle()
            self.assertIn(u"100", tb.pbStart.toolTip())

    # ---- 3) 解像度 / FPS ---------------------------------------------------------------
    def test_render_settings_shows_values_disabled_and_keeps_custom(self):
        o, tb = self.make({"playblastSettingsCollapsed": False, "mp4FromRenderSettings": False,
                           "mp4Width": 1920, "mp4Height": 1080})
        before = (pos(tb.mp4Width, tb), tb.mp4Box.height())
        tb.mp4FromRender.setChecked(True)
        settle()
        self.assertEqual((pos(tb.mp4Width, tb), tb.mp4Box.height()), before, "欄は隠れない・動かない")
        self.assertTrue(tb.mp4Width.isVisible() and not tb.mp4Width.isEnabled())
        self.assertEqual((tb.mp4Width.value(), tb.mp4Height.value()), RS, "レンダー設定の値を表示")
        self.assertEqual((o.data["mp4Width"], o.data["mp4Height"]), (1920, 1080), "保存は指定値のまま")
        self.assertEqual(tb.mp4_options()["width"], 1920)
        tb.mp4FromRender.setChecked(False)
        settle()
        self.assertTrue(tb.mp4Width.isEnabled())
        self.assertEqual((tb.mp4Width.value(), tb.mp4Height.value()), (1920, 1080), "OFF で指定値に戻る")

    def test_render_settings_on_at_startup(self):
        o, tb = self.make({"playblastSettingsCollapsed": False, "mp4FromRenderSettings": True,
                           "mp4Width": 2048, "mp4Height": 858})
        self.assertEqual((tb.mp4Width.value(), tb.mp4Height.value()), RS)
        self.assertFalse(tb.mp4Width.isEnabled())
        tb.mp4FromRender.setChecked(False)
        settle()
        self.assertEqual((tb.mp4Width.value(), tb.mp4Height.value()), (2048, 858))
        tb.pull(dict(settings.DEFAULTS, **dict(o.data, mp4FromRenderSettings=True)))
        settle()
        self.assertEqual((tb.mp4Width.value(), tb.mp4Height.value()), RS, "pull し直しても預かり値が壊れない")
        tb.mp4FromRender.setChecked(False)
        settle()
        self.assertEqual((tb.mp4Width.value(), tb.mp4Height.value()), (2048, 858))

    def test_scene_fps_shows_value_disabled_on_the_same_row(self):
        o, tb = self.make({"playblastSettingsCollapsed": False, "mp4UseSceneFps": False, "mp4Fps": 30.0}, width=520)
        self.assertTrue(same_row(tb.mp4UseSceneFps, tb.mp4Fps, root=tb), "FPS 欄は同じ行")
        tb.mp4UseSceneFps.setChecked(True)
        settle()
        self.assertTrue(tb.mp4Fps.isVisible() and not tb.mp4Fps.isEnabled())
        self.assertEqual(tb.mp4Fps.value(), SCENE_FPS)
        self.assertEqual(o.data["mp4Fps"], 30.0)
        self.assertIsNone(tb.mp4_options()["fps"])
        tb.mp4UseSceneFps.setChecked(False)
        settle()
        self.assertEqual(tb.mp4Fps.value(), 30.0)

    def test_summary_uses_custom_values(self):
        o, tb = self.make({"outputMode": "mp4", "mp4FromRenderSettings": False, "mp4UseSceneFps": False,
                           "mp4Width": 1920, "mp4Height": 1080, "mp4Fps": 24.0, "mp4Crf": 18})
        tb._update_pb_summary()
        self.assertEqual(tb.pbSettings._summary.text(), u"MP4 · 1920×1080 · 24fps · CRF 18")
        tb.mp4FromRender.setChecked(True)
        settle()
        self.assertIn(u"1280×720(RS)", tb.pbSettings._summary.text())

    # ---- 4) 品質 / CRF / プリセット -------------------------------------------------------
    def test_quality_crf_preset_one_row(self):
        for lang in ("ja", "en"):
            o, tb = self.make({"language": lang, "playblastSettingsCollapsed": False, "outputMode": "mp4"}, width=560)
            self.assertTrue(same_row(tb.mp4Quality, tb.mp4Crf, tb.mp4Preset, root=tb), lang)
            tb.outputSeg.setCurrent("maya", emit=True)
            settle()
            self.assertFalse(tb.mp4Crf.isVisible() or tb.mp4Preset.isVisible())
            self.assertTrue(tb.mp4Quality.isVisible())

    def test_labels_align(self):
        for lang in ("ja", "en"):
            o, tb = self.make({"language": lang, "playblastSettingsCollapsed": False, "outputMode": "mp4"}, width=420)
            widths = {lab.width() for lab in tb._pbAlignLabels if lab.isVisible()}
            self.assertEqual(len(widths), 1, (lang, widths))
            xs = {pos(w, tb.mp4Box)[0] for w in (tb.outputSeg, tb.mp4FromRender, tb.mp4UseSceneFps, tb.mp4Quality)}
            self.assertEqual(len(xs), 1, (lang, sorted(xs)))

    # ---- 5) PNG を残す --------------------------------------------------------------------
    def test_keep_png_next_to_open_after(self):
        o, tb = self.make({"outputMode": "mp4"}, width=420)
        self.assertTrue(tb.mp4KeepFrames.isVisible())
        self.assertTrue(same_row(tb.mp4OpenAfter, tb.mp4KeepFrames, root=tb))
        self.assertLess(pos(tb.mp4OpenAfter, tb)[0], pos(tb.mp4KeepFrames, tb)[0])
        self.assertLess(pos(tb.mp4KeepFrames, tb)[1], pos(tb.pbBtn, tb)[1])
        tb.outputSeg.setCurrent("maya", emit=True)
        settle()
        self.assertFalse(tb.mp4KeepFrames.isVisible(), "MP4 以外では隠す(押せないではない)")

    def test_run_button_text_does_not_follow_format(self):
        o, tb = self.make({"outputMode": "mp4"})
        t = tb.pbBtn.text()
        self.assertEqual(t, i18n.tr(u"Playblast 実行"))
        tb.outputSeg.setCurrent("maya", emit=True)
        settle()
        self.assertEqual(tb.pbBtn.text(), t)

    def test_format_switch_keeps_height(self):
        for lang, width, folded in itertools.product(("ja", "en"), (520, 333, 300, 280), (False, True)):
            o, tb = self.make({"language": lang, "outputMode": "mp4", "playblastSettingsCollapsed": folded},
                              width=width)
            before = (tb._pbCard.height(), pos(tb.pbBtn, tb), pos(tb.mp4OpenAfter, tb))
            tb.outputSeg.setCurrent("maya", emit=True)
            settle()
            mid = (tb._pbCard.height(), pos(tb.pbBtn, tb), pos(tb.mp4OpenAfter, tb))
            tb.outputSeg.setCurrent("mp4", emit=True)
            settle()
            after = (tb._pbCard.height(), pos(tb.pbBtn, tb), pos(tb.mp4OpenAfter, tb))
            self.assertEqual(before, mid, (lang, width, folded))
            self.assertEqual(before, after, (lang, width, folded))

    # ---- はみ出し・重なり ------------------------------------------------------------------
    def test_no_clipping_or_overlap_in_any_state(self):
        for lang, width, mode, rs, sf, scene, multi in itertools.product(
                ("ja", "en"), (333, 300, 280), ("maya", "mp4"), (True, False), (True, False), (True, False), (True, False)):
            if width == 300 and (rs, sf) == (False, True):
                continue
            o, tb = self.make({"language": lang, "playblastSettingsCollapsed": False, "outputMode": mode,
                               "mp4FromRenderSettings": rs, "mp4UseSceneFps": sf, "playblastRangeScene": scene,
                               "playblastMulti": multi, "playblastCombine": True}, width=width)
            card = tb._pbCard
            tag = (lang, width, mode, rs, sf, scene, multi)
            self.assertLessEqual(card.minimumSizeHint().width(), tb._scroll.viewport().width(), tag)
            leaves = [w for w in card.findChildren(QW.QWidget)
                      if isinstance(w, (style.ToggleSwitch, QW.QAbstractSpinBox, QW.QComboBox, QW.QLineEdit,
                                        QW.QPushButton, QW.QLabel)) and w.isVisibleTo(card) and w.width() > 0
                      and not isinstance(w.parentWidget(), (QW.QAbstractSpinBox, QW.QComboBox))
                      and type(w.parentWidget()).__name__ != "SegmentedControl"]
            for a, b in itertools.combinations(leaves, 2):
                if a.isAncestorOf(b) or b.isAncestorOf(a):
                    continue
                ra = QtCore.QRect(a.mapTo(card, QtCore.QPoint(0, 0)), a.size())
                rb = QtCore.QRect(b.mapTo(card, QtCore.QPoint(0, 0)), b.size())
                inter = ra.intersected(rb)
                self.assertFalse(inter.width() > 1 and inter.height() > 1,
                                 (tag, getattr(a, "text", lambda: "")(), getattr(b, "text", lambda: "")()))
            for w in leaves:
                p = w.parentWidget()
                r = QtCore.QRect(w.mapTo(p, QtCore.QPoint(0, 0)), w.size())
                self.assertTrue(p.rect().adjusted(-1, -1, 1, 1).contains(r),
                                (tag, type(w).__name__, getattr(w, "text", lambda: "")(), r, p.size()))

    def test_horizontal_dock_toggles_move_nothing(self):
        for lang in ("ja", "en"):
            o, tb = self.make({"language": lang, "playblastMulti": False, "playblastRangeScene": True,
                               "outputMode": "mp4"}, width=1800, height=420, horizontal=True)
            before = (pos(tb.multiEnabled, tb), pos(tb.pbRangeScene, tb), pos(tb.pbBtn, tb), tb._pbMain.height())
            tb.multiEnabled.setChecked(True)
            tb.pbRangeScene.setChecked(False)
            settle()
            after = (pos(tb.multiEnabled, tb), pos(tb.pbRangeScene, tb), pos(tb.pbBtn, tb), tb._pbMain.height())
            self.assertEqual(before, after, lang)
            self.assertTrue(same_row(tb.mp4Quality, tb.mp4Crf, tb.mp4Preset, root=tb))
            self.assertTrue(same_row(tb.multiCombine, tb.multiKeep, root=tb))
            self.assertTrue(same_row(tb.pbStart, tb.pbEnd, root=tb))
            # 列の幅は出力先の行が決める(g3 と同じ幅。Time Range 等の行で広げない)
            self.assertLessEqual(tb._pbMain.width(), tb.pbOutputBox.sizeHint().width() + 2, lang)


if __name__ == "__main__":
    unittest.main(verbosity=2)
