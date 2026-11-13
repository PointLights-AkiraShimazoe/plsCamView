# -*- coding: utf-8 -*-
"""FX-EFFECTS-FOLD-20261101-01: Effects カードの「自動の畳み(上 / 下ドックへ入るとき)」が、利用者の開閉の保存値を上書きしない確認。

offscreen Qt のみ(実 Maya / 実 Windows の見た目は含まない)。
使い方: PKG_DIR=<scripts/パッケージ> python3 test_effects_fold.py
旧(s2)の ui.py に当てると、保存値の上書き・縦へ戻したとき開かない・再起動で畳んだまま、の各試験が落ちる。新で全部通る。
"""
import importlib
import json
import os
import re
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

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
UI_SRC = (PKG_DIR / "ui.py").read_text(encoding="utf-8")


class EffectsFold(unittest.TestCase):
    DOCK_W = 333

    def tearDown(self):
        style.set_ui_scale(style.UI_SCALE_DEFAULT)
        i18n.set_language("system")
        app.processEvents()

    def toolbox(self, data=None):
        owner = types.SimpleNamespace()
        owner.data = dict({"language": "system", "camera": "persp"}, **(data or {}))
        owner.saves = []

        def _save():
            owner.saves.append(owner.data.get("effectsCollapsed"))
        owner.save_settings = _save
        owner.views = None
        owner.refresh_cameras = lambda *a, **k: None
        owner.apply_effects = lambda *a, **k: None          # Effects のヘッダーのスイッチが呼ぶ(実機では Window.apply_effects)
        owner.fits = 0

        def _fit():
            owner.fits += 1
        owner.fit_toolbox_height = _fit
        # 実機では PlsFxViewWindow.set_dock_area が toolbox.set_orientation を呼ぶ(その代用)
        owner.set_dock_area = lambda key, save=True: (owner.data.__setitem__("dockArea", key),
                                                      owner.tb.set_orientation(key in ("top", "bottom")))
        tb = ui.ToolBox(owner)
        owner.tb = tb
        self.addCleanup(tb.deleteLater)
        tb.pull(dict(settings.DEFAULTS, **owner.data))      # 実機では Window が pull する
        return owner, tb

    def shown(self, data=None, width=None, height=900):
        owner, tb = self.toolbox(data)
        tb.resize(width or self.DOCK_W, height)
        tb.show()
        app.processEvents()
        return owner, tb

    def to_horizontal(self, tb):
        tb.resize(1100, 320)
        tb.set_orientation(True)
        app.processEvents()

    def to_vertical(self, tb):
        tb.resize(self.DOCK_W, 900)
        tb.set_orientation(False)
        app.processEvents()

    # ---- 中心: 自動の畳みは保存値を書き換えない -------------------------------------------------
    def test_horizontal_dock_does_not_overwrite_saved_effects_fold(self):
        owner, tb = self.shown({"effectsCollapsed": False})
        self.assertFalse(tb._effectsCard.isCollapsed())
        self.to_horizontal(tb)
        self.assertTrue(tb._effectsCard.isCollapsed())                  # 高さを抑えるため畳んで見せるのは従来どおり
        self.assertFalse(owner.data["effectsCollapsed"])                # ただし保存値(利用者の選択)は書き換えない
        self.assertNotIn(True, owner.saves)                             # 自動の畳みで「畳んだ」を保存しない
        self.to_vertical(tb)
        self.assertFalse(tb._effectsCard.isCollapsed())                 # 利用者が開いていた状態に戻る
        self.assertFalse(owner.data["effectsCollapsed"])

    def test_horizontal_dock_keeps_a_folded_effects_folded(self):
        owner, tb = self.shown({"effectsCollapsed": True})
        self.to_horizontal(tb)
        self.to_vertical(tb)
        self.assertTrue(tb._effectsCard.isCollapsed())
        self.assertTrue(owner.data["effectsCollapsed"])

    def test_user_choice_in_horizontal_dock_wins_over_restore(self):
        owner, tb = self.shown({"effectsCollapsed": False})
        self.to_horizontal(tb)
        tb._effectsCard.setCollapsed(False)                              # 横で利用者が開いた(保存される)
        self.assertFalse(owner.data["effectsCollapsed"])
        tb._effectsCard.setCollapsed(True)                               # 横で利用者が畳んだ(保存される)
        self.assertTrue(owner.data["effectsCollapsed"])
        self.to_vertical(tb)
        self.assertTrue(tb._effectsCard.isCollapsed())                   # 利用者の最後の選択を優先(自動では開けない)
        # 横で開いたまま縦へ戻る場合は開いたまま
        owner2, tb2 = self.shown({"effectsCollapsed": False})
        self.to_horizontal(tb2)
        tb2._effectsCard.setCollapsed(False)
        self.to_vertical(tb2)
        self.assertFalse(tb2._effectsCard.isCollapsed())
        self.assertFalse(owner2.data["effectsCollapsed"])

    def test_user_open_then_close_in_horizontal_is_saved_as_user_value(self):
        owner, tb = self.shown({"effectsCollapsed": False})
        self.to_horizontal(tb)
        tb._effectsCard.toggleCollapsed()                                # 畳み表示 -> 開く(利用者)
        tb._effectsCard.toggleCollapsed()                                # 開く -> 畳む(利用者)
        self.assertEqual(owner.saves[-2:], [False, True])
        self.assertTrue(owner.data["effectsCollapsed"])

    def test_horizontal_to_horizontal_move_keeps_the_restore_target(self):
        # 上 -> 下(どちらも横配置)の移動では set_orientation は何もしない。戻し先を失わない
        owner, tb = self.shown({"effectsCollapsed": False})
        self.to_horizontal(tb)
        owner.set_dock_area("bottom")
        app.processEvents()
        self.assertTrue(tb._effectsCard.isCollapsed())
        self.assertFalse(owner.data["effectsCollapsed"])
        owner.set_dock_area("right")
        app.processEvents()
        self.assertFalse(tb._effectsCard.isCollapsed())

    def test_right_to_top_to_right_through_the_dock_picker_path(self):
        # 実際の入口: dockPicker.changed -> _on_dock_changed -> owner.set_dock_area -> set_orientation
        owner, tb = self.shown({"effectsCollapsed": False})
        tb.dockPicker.changed.emit("top")
        app.processEvents()
        self.assertTrue(tb._effectsCard.isCollapsed())
        self.assertFalse(owner.data["effectsCollapsed"])
        tb.dockPicker.changed.emit("right")
        app.processEvents()
        self.assertFalse(tb._effectsCard.isCollapsed())
        self.assertFalse(owner.data["effectsCollapsed"])
        tb.dockPicker.changed.emit("bottom")
        tb.dockPicker.changed.emit("left")
        app.processEvents()
        self.assertFalse(tb._effectsCard.isCollapsed())

    def test_every_vertical_horizontal_cycle_is_stable(self):
        owner, tb = self.shown({"effectsCollapsed": False})
        for _ in range(4):
            self.to_horizontal(tb)
            self.assertTrue(tb._effectsCard.isCollapsed())
            self.to_vertical(tb)
            self.assertFalse(tb._effectsCard.isCollapsed())
        self.assertFalse(owner.data["effectsCollapsed"])
        self.assertNotIn(True, owner.saves)

    # ---- 再表示・再起動・設定の再読込 --------------------------------------------------------------
    def test_close_in_horizontal_then_reopen_keeps_user_value(self):
        # ウィンドウを閉じて開き直す代用: 横ドックで閉じる -> 保存値で作り直す -> 縦ドックで開く
        owner, tb = self.shown({"effectsCollapsed": False})
        self.to_horizontal(tb)
        saved = dict(owner.data)
        self.assertFalse(saved["effectsCollapsed"])
        owner2, tb2 = self.shown(saved)                                  # 次の起動 / 再表示は同じ保存値から
        self.assertFalse(tb2._effectsCard.isCollapsed())
        self.to_horizontal(tb2)                                          # Window._restore と同じ順(pull -> 横ドック)
        self.assertTrue(tb2._effectsCard.isCollapsed())
        self.assertFalse(owner2.data["effectsCollapsed"])
        self.to_vertical(tb2)
        self.assertFalse(tb2._effectsCard.isCollapsed())

    def test_saved_settings_file_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            with patch.object(settings, "config_dir", lambda: td):
                data = settings.load()
                data["effectsCollapsed"] = False
                owner, tb = self.shown(data)
                self.to_horizontal(tb)
                self.assertTrue(settings.save(owner.data))               # 横ドックのまま保存(終了時の保存の代用)
                again = settings.load()
                self.assertFalse(again["effectsCollapsed"])              # ファイルにも「畳んだ」は書かれない
                self.assertEqual(json.loads(Path(settings.config_path()).read_text("utf-8"))["effectsCollapsed"], False)
                # 利用者が横で畳んだ場合は、それが保存される
                tb._effectsCard.setCollapsed(False)                      # 畳んで見せている状態への操作は、開く -> 畳む
                tb._effectsCard.setCollapsed(True)
                settings.save(owner.data)
                self.assertTrue(settings.load()["effectsCollapsed"])

    def test_pull_is_the_source_of_truth_for_effects_fold(self):
        owner, tb = self.shown({"effectsCollapsed": False})
        self.to_horizontal(tb)                                           # 自動で畳んだ(戻す物あり)
        tb.pull(dict(settings.DEFAULTS, effectsCollapsed=True))          # 設定の読み直し: 正本は設定
        self.to_vertical(tb)
        self.assertTrue(tb._effectsCard.isCollapsed())
        # 読み直した値が「開いている」なら、横でも保存値どおり開く(Settings と同じ扱い)
        owner2, tb2 = self.shown({"effectsCollapsed": True})
        self.to_horizontal(tb2)
        tb2.pull(dict(settings.DEFAULTS, effectsCollapsed=False))
        self.assertFalse(tb2._effectsCard.isCollapsed())
        self.to_vertical(tb2)
        self.assertFalse(tb2._effectsCard.isCollapsed())

    def test_preset_and_reset_pull_do_not_touch_the_fold(self):
        # プリセットの切替 / Reset(pull_effects)は値と ON/OFF だけ。自動の畳みを解かず、戻し先も失わない
        owner, tb = self.shown({"effectsCollapsed": False})
        self.to_horizontal(tb)
        tb.pull_effects(dict(settings.DEFAULTS, effectsCollapsed=False, effectsMaster=False))
        app.processEvents()
        self.assertTrue(tb._effectsCard.isCollapsed())
        self.assertFalse(tb.effectsMaster.isChecked())                   # 値は反映される
        self.assertFalse(owner.data["effectsCollapsed"])
        self.to_vertical(tb)
        self.assertFalse(tb._effectsCard.isCollapsed())                  # 戻し先は保たれている
        # 縦のときの pull_effects でも開閉は変えない
        tb.pull_effects(dict(settings.DEFAULTS, effectsCollapsed=True))
        self.assertFalse(tb._effectsCard.isCollapsed())

    def test_fold_changes_never_touch_effect_values_or_other_cards(self):
        owner, tb = self.shown({"effectsCollapsed": False, "effectsMaster": True, "dofEnabled": False,
                                "taaEnabled": True})
        names = ("effectsMaster", "dofChk", "taaChk", "diffStrength", "bloomChk")
        names = [n for n in names if hasattr(tb, n)]

        def snap():
            out = {}
            for n in names:
                w = getattr(tb, n)
                out[n] = w.isChecked() if hasattr(w, "isChecked") else w.value()
            out["pbSettings"] = tb.pbSettings.isCollapsed()
            out["pbCard"] = tb._pbCardCollapsed
            return out
        before = snap()
        self.to_horizontal(tb)
        self.to_vertical(tb)
        self.assertEqual(snap(), before)

    def test_header_master_switch_does_not_reopen_the_auto_folded_card(self):
        owner, tb = self.shown({"effectsCollapsed": False})
        self.to_horizontal(tb)
        tb.effectsMaster.setChecked(not tb.effectsMaster.isChecked())    # ヘッダーのスイッチは開閉ではない
        app.processEvents()
        self.assertTrue(tb._effectsCard.isCollapsed())
        self.to_vertical(tb)
        self.assertFalse(tb._effectsCard.isCollapsed())

    # ---- 従来の挙動の保全 ------------------------------------------------------------------------
    def test_vertical_user_toggle_still_saves_every_time(self):
        owner, tb = self.shown({"effectsCollapsed": False})
        tb._effectsCard.setCollapsed(True)
        tb._effectsCard.setCollapsed(False)
        self.assertEqual(owner.saves, [True, False])
        self.assertFalse(owner.data["effectsCollapsed"])

    def test_auto_fold_still_fits_the_toolbox_height(self):
        owner, tb = self.shown({"effectsCollapsed": False})
        self.to_horizontal(tb)
        app.processEvents()
        n = owner.fits
        self.assertGreater(n, 0)                                         # 上下配置の畳み / 開くのたびに高さを合わせる(従来どおり)
        self.to_vertical(tb)
        app.processEvents()
        self.assertEqual(owner.fits, n)                                  # 縦配置では合わせない(従来どおり)

    def test_building_flag_still_blocks_the_handler(self):
        owner, tb = self.shown({"effectsCollapsed": False})
        tb._building = True
        try:
            tb._effectsCard.setCollapsed(True)
        finally:
            tb._building = False
        self.assertEqual(owner.saves, [])
        self.assertFalse(owner.data["effectsCollapsed"])

    def test_playblast_settings_fold_unchanged_alongside(self):
        # 同じ向きの切替で Settings(s1)と Effects が互いに邪魔をしない
        owner, tb = self.shown({"effectsCollapsed": False, "playblastSettingsCollapsed": False})
        self.to_horizontal(tb)
        self.assertTrue(tb._effectsCard.isCollapsed())
        self.assertTrue(tb.pbSettings.isCollapsed())
        self.assertFalse(owner.data["effectsCollapsed"])
        self.assertFalse(owner.data["playblastSettingsCollapsed"])
        tb.pbSettings.setCollapsed(False)                                # 利用者が Settings を開いて
        tb.pbSettings.setCollapsed(True)                                 # 畳む(畳んで見せている状態への操作は、開く -> 畳む)
        self.to_vertical(tb)
        self.assertFalse(tb._effectsCard.isCollapsed())                  # Effects は元へ
        self.assertTrue(tb.pbSettings.isCollapsed())                     # Settings は利用者の選択

    # ---- 実呼出元の静的確認 -----------------------------------------------------------------------
    def test_only_set_orientation_auto_folds_and_only_the_handler_saves(self):
        sites = [m.start() for m in re.finditer(r"_effectsCard\.setCollapsed\(", UI_SRC)]
        self.assertEqual(len(sites), 2, "Effects の setCollapsed の呼び出しは 2 か所(自動の畳み 1 + 設定の読み込み 1)")
        saves = re.findall(r'data\["effectsCollapsed"\]\s*=', UI_SRC)
        self.assertEqual(len(saves), 1, "effectsCollapsed を書き込むのは利用者の操作の受け口 1 か所だけ")
        m = re.search(r"def _on_effects_collapsed\(self, collapsed\):(.*?)\n    def ", UI_SRC, re.S)
        self.assertIn("if not self._effectsAutoFold:", m.group(1))
        self.assertLess(m.group(1).index("if not self._effectsAutoFold:"), m.group(1).index('data["effectsCollapsed"]'))

    def test_window_set_dock_area_is_the_only_caller_of_set_orientation(self):
        calls = re.findall(r"\.set_orientation\(", UI_SRC)
        self.assertEqual(len(calls), 1)
        self.assertRegex(UI_SRC, r"self\.toolbox\.set_orientation\(horizontal\)")


def tearDownModule():
    u"""プロセス終了前に widget を確実に片付ける(offscreen Qt 6.8 で、終了時の自動破棄がまれに異常終了するのを避ける。製品側の話ではない)。"""
    for w in list(app.topLevelWidgets()):
        try:
            w.close()
            w.deleteLater()
        except Exception:
            pass
    for _ in range(3):
        app.processEvents()
        app.sendPostedEvents(None, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
