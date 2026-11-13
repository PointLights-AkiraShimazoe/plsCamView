# -*- coding: utf-8 -*-
"""FX-CAPTURE-FOLD-20261101-01 (s3): PLAYBLAST の「撮影オプション」を独立して畳める入れ物にした確認。

offscreen Qt のみ(実 Maya / 実 Windows の見た目は含まない)。
使い方: PKG_DIR=<scripts/パッケージ> python3 test_capture_fold.py
旧(EF)の ui.py に当てると、入れ物が畳めない・保存されない・要約が無い、の各試験が落ちる。新で全部通る。
"""
import importlib
import os
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = Path(os.environ.get("PKG_DIR") or (ROOT / "scripts" / ROOT.name))
PACKAGE = PKG_DIR.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(PKG_DIR)]
sys.modules[PACKAGE] = pkg
try:
    import ast
    _src = (PKG_DIR / "__init__.py").read_text(encoding="utf-8")
    for _node in ast.parse(_src).body:
        if isinstance(_node, ast.Assign) and getattr(_node.targets[0], "id", "") == "GRADE_DEFAULTS":
            pkg.GRADE_DEFAULTS = ast.literal_eval(_node.value)
except Exception:
    pass
qt = importlib.import_module(PACKAGE + ".qt")
style = importlib.import_module(PACKAGE + ".style")
ui = importlib.import_module(PACKAGE + ".ui")
i18n = importlib.import_module(PACKAGE + ".i18n")
settings = importlib.import_module(PACKAGE + ".settings")
QW = qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])
TOGGLES = ("mp4Ornaments", "mp4OffScreen", "mp4Optimize")
KEY = "playblastCaptureCollapsed"


class CaptureFold(unittest.TestCase):
    DOCK_W = 333

    def tearDown(self):
        style.set_ui_scale(style.UI_SCALE_DEFAULT)
        i18n.set_language("system")
        app.processEvents()

    def toolbox(self, data=None):
        owner = types.SimpleNamespace()
        owner.data = dict({"language": "system", "camera": "persp"}, **(data or {}))
        owner.saves = []
        owner.save_settings = lambda: owner.saves.append(dict(owner.data))
        owner.views = None
        owner.refresh_cameras = lambda *a, **k: None
        owner.apply_effects = lambda *a, **k: None
        owner.fits = 0

        def _fit():
            owner.fits += 1
        owner.fit_toolbox_height = _fit
        owner.set_dock_area = lambda key, save=True: (owner.data.__setitem__("dockArea", key),
                                                      owner.tb.set_orientation(key in ("top", "bottom")))
        tb = ui.ToolBox(owner)
        owner.tb = tb
        self.addCleanup(tb.deleteLater)
        tb.pull(dict(settings.DEFAULTS, **owner.data))
        return owner, tb

    def shown(self, data=None, width=None, height=900):
        owner, tb = self.toolbox(data)
        tb.resize(width or self.DOCK_W, height)
        tb.show()
        app.processEvents()
        return owner, tb

    def reopen(self, owner):
        u"""同じ保存値で開き直す(再起動・再表示の代用)。"""
        return self.shown(dict(owner.data))

    # ---- 構造 ---------------------------------------------------------------------------------
    def test_capture_box_is_an_independent_collapsible_section(self):
        owner, tb = self.shown()
        box = tb.pbCaptureBox
        self.assertIsInstance(box, style.CollapsibleSection)
        col = tb._pbMainCol
        order = [col.indexOf(w) for w in (tb.pbSettings, box, tb._pngRow, tb.pbBtn)]   # g4: 完了後に開く は _pngRow の中
        self.assertTrue(all(i >= 0 for i in order), order)
        self.assertEqual(order, sorted(order))                     # Settings → 撮影オプション → 完了後に開く → 実行
        for n in TOGGLES:
            w = getattr(tb, n)
            self.assertTrue(box.isAncestorOf(w), n)
            self.assertFalse(tb.pbSettings.isAncestorOf(w), n)      # Settings(数値)の中ではない
        self.assertFalse(box.isAncestorOf(tb.mp4OpenAfter))         # 完了後に開く・実行は常時表示のまま
        self.assertFalse(box.isAncestorOf(tb.pbBtn))
        self.assertEqual(box._title.text().lower(), i18n.tr(u"撮影オプション").lower())

    def test_default_is_folded_with_a_summary_of_what_is_on(self):
        owner, tb = self.shown()                                    # 保存値なし(既定)
        self.assertTrue(tb.pbCaptureBox.isCollapsed())
        on = [getattr(tb, n).text() for n in TOGGLES if getattr(tb, n).isChecked()]
        self.assertEqual(tb.pbCaptureBox._summary.text(), u" / ".join(on) if on else i18n.tr(u"すべて OFF"))
        self.assertEqual(owner.saves, [])                           # 開くだけで保存しない

    # ---- 開閉の保存 ---------------------------------------------------------------------------
    def test_user_toggle_is_saved_and_restored_on_reopen(self):
        owner, tb = self.shown()
        tb.pbCaptureBox.setCollapsed(False)                         # 利用者が開いた
        self.assertFalse(owner.data[KEY])
        self.assertTrue(owner.saves and owner.saves[-1][KEY] is False)
        owner2, tb2 = self.reopen(owner)
        self.assertFalse(tb2.pbCaptureBox.isCollapsed())            # 再起動 / 再表示で開いたまま
        tb2.pbCaptureBox.setCollapsed(True)                         # 畳む
        self.assertTrue(owner2.data[KEY])
        owner3, tb3 = self.reopen(owner2)
        self.assertTrue(tb3.pbCaptureBox.isCollapsed())

    def test_capture_and_settings_fold_independently(self):
        owner, tb = self.shown({"playblastSettingsCollapsed": True, KEY: True})
        tb.pbCaptureBox.setCollapsed(False)
        self.assertTrue(tb.pbSettings.isCollapsed())
        self.assertTrue(owner.data["playblastSettingsCollapsed"])
        tb.pbSettings.setCollapsed(False)
        self.assertFalse(tb.pbCaptureBox.isCollapsed())
        self.assertFalse(owner.data[KEY])
        tb.pbCaptureBox.setCollapsed(True)
        self.assertFalse(tb.pbSettings.isCollapsed())
        self.assertFalse(owner.data["playblastSettingsCollapsed"])
        self.assertTrue(owner.data[KEY])

    def test_dock_round_trip_keeps_user_choice_and_place(self):
        for start in (True, False):
            owner, tb = self.shown({KEY: start})
            n_saves = len(owner.saves)
            idx = tb._pbMainCol.indexOf(tb.pbCaptureBox)
            tb.resize(1100, 320)
            owner.set_dock_area("top")
            app.processEvents()
            self.assertEqual(tb.pbCaptureBox.isCollapsed(), start)  # ドック移動で自動に畳まない・開かない
            self.assertGreaterEqual(tb._pbMainCol.indexOf(tb.pbCaptureBox), 0)  # 横配置でも main 列
            tb.resize(self.DOCK_W, 900)
            owner.set_dock_area("right")
            app.processEvents()
            self.assertEqual(tb.pbCaptureBox.isCollapsed(), start)
            self.assertEqual(tb._pbMainCol.indexOf(tb.pbCaptureBox), idx)
            self.assertEqual(owner.data.get(KEY), start)
            self.assertTrue(all(s.get(KEY, start) == start for s in owner.saves[n_saves:]))

    def test_toggle_in_horizontal_dock_refits_height(self):
        owner, tb = self.shown({KEY: True})
        tb.resize(1100, 320)
        owner.set_dock_area("bottom")
        app.processEvents()
        fits = owner.fits
        tb.pbCaptureBox.setCollapsed(False)
        app.processEvents()
        self.assertGreater(owner.fits, fits)                        # 上下配置では高さを中身に合わせ直す(他の入れ物と同じ)
        self.assertFalse(owner.data[KEY])

    # ---- 中身は畳んでも生きている -----------------------------------------------------------------
    def test_folding_hides_but_keeps_values_and_saving(self):
        owner, tb = self.shown({KEY: False, "mp4ShowOrnaments": True, "mp4OffScreen": False,
                                "mp4OptimizeViewport": True})
        tb.pbCaptureBox.setCollapsed(True)
        app.processEvents()
        for n in TOGGLES:
            self.assertFalse(getattr(tb, n).isVisible(), n)
        self.assertTrue(tb.mp4Ornaments.isChecked())
        self.assertFalse(tb.mp4OffScreen.isChecked())
        self.assertTrue(tb.mp4Optimize.isChecked())
        tb.mp4OffScreen.setChecked(True)                            # 畳んだままでも値は保存・撮影に使われる
        self.assertTrue(owner.data["mp4OffScreen"])
        tb.pbCaptureBox.setCollapsed(False)
        app.processEvents()
        for n in TOGGLES:
            self.assertTrue(getattr(tb, n).isVisible(), n)

    def test_summary_follows_toggles(self):
        owner, tb = self.shown({KEY: True})
        for n in TOGGLES:
            getattr(tb, n).setChecked(False)
        self.assertEqual(tb.pbCaptureBox._summary.text(), i18n.tr(u"すべて OFF"))
        tb.mp4OffScreen.setChecked(True)
        self.assertEqual(tb.pbCaptureBox._summary.text(), tb.mp4OffScreen.text())
        tb.mp4Ornaments.setChecked(True)
        tb.mp4Optimize.setChecked(True)
        self.assertEqual(tb.pbCaptureBox._summary.text(),
                         u" / ".join(getattr(tb, n).text() for n in TOGGLES))

    def test_english_labels(self):
        i18n.set_language("en")
        owner, tb = self.shown({KEY: True, "language": "en", "mp4ShowOrnaments": False,
                                "mp4OffScreen": False, "mp4OptimizeViewport": False})
        self.assertEqual(tb.pbCaptureBox._title.text().lower(), u"capture options")
        self.assertEqual(tb.pbCaptureBox._summary.text(), u"All off")
        tb.mp4Ornaments.setChecked(True)
        self.assertEqual(tb.pbCaptureBox._summary.text(), u"Ornaments (HUD)")

    def test_pull_does_not_save(self):
        owner, tb = self.shown({KEY: False})
        before = len(owner.saves)
        tb.pull(dict(settings.DEFAULTS, **dict(owner.data, **{KEY: True})))
        self.assertTrue(tb.pbCaptureBox.isCollapsed())
        self.assertEqual(len(owner.saves), before)                  # 読み込みは保存しない(_building で守る)

    def test_folding_reduces_card_height(self):
        heights = {}
        for folded in (False, True):
            owner, tb = self.shown({KEY: folded, "playblastSettingsCollapsed": True})
            heights[folded] = tb._pbBody.sizeHint().height()
        print("PLAYBLAST 本体の高さ(333px 幅): 撮影オプション開={} / 畳み={}".format(heights[False], heights[True]))
        self.assertLess(heights[True], heights[False])

    def test_capture_fold_key_is_not_a_preset_key(self):
        keys = getattr(settings, "PRESET_KEYS", ())
        self.assertNotIn(KEY, keys)                                 # 開閉は見た目の状態。調整プリセットには入れない


def tearDownModule():
    app.processEvents()


if __name__ == "__main__":
    unittest.main(verbosity=2)
