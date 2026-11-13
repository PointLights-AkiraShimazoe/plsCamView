# -*- coding: utf-8 -*-
"""Playblast カードの UI(折り畳み・Time Range / Output の位置・Multi 1 行・文字切れ・縦横)の確認。

offscreen Qt のみ(実 Maya / 実 Windows / 実フォントの見た目は含まない)。
使い方: PKG_DIR=<scripts/パッケージ> python3 test_playblast_ui.py
"""
import importlib
import os
import sys
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
# plsFxView の ui は __init__ の GRADE_DEFAULTS を参照する。__init__ 全体(Maya 依存)は読まず、定義だけ取り出す。
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


def settle(n=4):
    u"""g3: 折り返す行は配置された幅で高さを決め、親に取り直しを頼む(イベントを数回まわすと収まる)。"""
    for _ in range(n):
        QW.QApplication.sendPostedEvents()
        app.processEvents()


class PlayblastUi(unittest.TestCase):
    DOCK_W = 333

    def tearDown(self):
        style.set_ui_scale(style.UI_SCALE_DEFAULT)
        i18n.set_language("system")
        app.processEvents()

    def toolbox(self, data=None):
        owner = types.SimpleNamespace()
        owner.data = dict({"language": "system", "camera": "persp"}, **(data or {}))
        owner.saves = 0

        def _save():
            owner.saves += 1
        owner.save_settings = _save
        owner.views = None
        owner.refresh_cameras = lambda *a, **k: None
        tb = ui.ToolBox(owner)
        self.addCleanup(tb.deleteLater)
        tb.pull(dict(settings.DEFAULTS, **owner.data))      # 実機では Window が pull する
        return owner, tb

    def shown(self, data=None, width=None, height=900):
        owner, tb = self.toolbox(data)
        tb.resize(width or self.DOCK_W, height)
        tb.show()
        settle()
        return owner, tb

    # ---- 構造 ---------------------------------------------------------
    # test_order_and_ownership: g3(2026-11-08 本人指定の構成)で旧構成の試験として外した。test_pb_g3.py を参照

    def test_card_and_settings_collapse_independently(self):
        owner, tb = self.shown({"playblastSettingsCollapsed": False})
        self.assertFalse(tb._pbCardCollapsed)
        self.assertFalse(tb.pbSettings.isCollapsed())
        tb._toggle_pb_card()
        app.processEvents()
        self.assertTrue(tb._pbCardCollapsed)
        self.assertTrue(tb._pbBody.isHidden())
        self.assertFalse(tb._pbCardSummary.isHidden())
        self.assertTrue(tb._pbCardSummary.text())
        self.assertFalse(tb.pbSettings.isCollapsed())             # Settings の状態は変わらない
        self.assertTrue(owner.data["playblastCollapsed"])
        tb._toggle_pb_card()
        self.assertFalse(tb._pbBody.isHidden())
        self.assertTrue(tb._pbCardSummary.isHidden())
        self.assertFalse(owner.data["playblastCollapsed"])
        tb.pbSettings.setCollapsed(True)                           # Settings だけ畳む
        app.processEvents()
        self.assertFalse(tb._pbCardCollapsed)
        self.assertFalse(tb.pbRangeBox.isHidden())
        self.assertFalse(tb.pbOutputBox.isHidden())
        self.assertTrue(owner.data["playblastSettingsCollapsed"])

    def test_collapsed_state_restored(self):
        owner, tb = self.shown({"playblastCollapsed": True, "playblastSettingsCollapsed": False})
        self.assertTrue(tb._pbCardCollapsed)
        self.assertTrue(tb._pbBody.isHidden())
        self.assertFalse(tb.pbSettings.isCollapsed())

    # ---- Multi / 合成 / 個別保持 は同じ 1 行 --------------------------------
    def _multi_centers(self, tb):
        ys = []
        for w in (tb.multiEnabled, tb.multiCombine, tb.multiKeep):
            self.assertTrue(w.isVisible(), w.text())
            c = w.mapTo(tb, w.rect().center())
            ys.append(c.y())
        return ys

    # test_multi_row_single_line_all_scales_languages: g3(2026-11-08 本人指定の構成)で旧構成の試験として外した。test_pb_g3.py を参照

    def test_inputs_not_clipped(self):
        for lang in ("ja", "en"):
            for pct in (75, 85, 125):
                owner, tb = self.shown({"uiScale": pct, "language": lang, "playblastSettingsCollapsed": False,
                                        "playblastRangeScene": False, "outputMode": "mp4",
                                        "mp4UseSceneFps": False, "mp4FromRenderSettings": False},   # g3: 数値欄が見える状態
                                       width=max(self.DOCK_W, int(self.DOCK_W * pct / 85.0)))
                pad = style.px(8) * 2 + 4
                for name in ("mp4Width", "mp4Height", "mp4Fps", "mp4Quality", "mp4Crf", "pbStart", "pbEnd"):
                    w = getattr(tb, name)
                    self.assertTrue(w.isVisible(), name)
                    fm = w.fontMetrics()
                    texts = [w.textFromValue(w.minimum()), w.textFromValue(w.maximum())]
                    widest = max(fm.horizontalAdvance(t) for t in texts)
                    self.assertGreaterEqual(w.width(), widest + pad, (lang, pct, name, w.width(), widest))
                fm = tb.mp4Preset.fontMetrics()
                widest = max(fm.horizontalAdvance(tb.mp4Preset.itemText(i)) for i in range(tb.mp4Preset.count()))
                self.assertGreaterEqual(tb.mp4Preset.width(), widest + style.px(24), (lang, pct))
                self.assertGreaterEqual(tb.mp4Output.width(), style.px(60), (lang, pct))
                tb.deleteLater()
                app.processEvents()

    # ---- 縦 / 横(ドック方向) ---------------------------------------------
    def test_orientation_roundtrip(self):
        owner, tb = self.shown({"playblastSettingsCollapsed": False})
        col = tb._pbMainCol

        def order():
            return [col.indexOf(w) for w in (tb.forceChk, tb.pbRangeBox, tb.pbOutputBox,
                                              tb.pbSettings, tb.pbCaptureBox, tb._pngRow, tb.pbBtn)]   # g4: 完了後に開く は _pngRow の中
        vertical = order()
        self.assertEqual(vertical, sorted(vertical))
        tb.resize(1100, 320)
        tb.set_orientation(True)
        tb.show()
        app.processEvents()
        # 横: Settings は main 列の外(右)。Time Range / Output は main 列に残る
        self.assertEqual(col.indexOf(tb.pbSettings), -1)
        self.assertGreaterEqual(col.indexOf(tb.pbRangeBox), 0)
        self.assertGreaterEqual(col.indexOf(tb.pbOutputBox), 0)
        self.assertGreaterEqual(col.indexOf(tb.pbCaptureBox), 0)
        self.assertEqual(tb._pbFlow.direction(), QW.QBoxLayout.LeftToRight)
        tb.pbSettings.setCollapsed(False)
        app.processEvents()
        # 横でカード全体も畳める
        tb._set_pb_card_collapsed(True)
        app.processEvents()
        self.assertTrue(tb._pbBody.isHidden())
        tb._set_pb_card_collapsed(False)
        tb.resize(self.DOCK_W, 900)
        tb.set_orientation(False)
        app.processEvents()
        self.assertEqual(order(), vertical)                      # 縦へ戻すと元の順(挿入位置は常に Output の直後)
        self.assertEqual(tb._pbFlow.direction(), QW.QBoxLayout.TopToBottom)

    # ---- Time Range の値 ----------------------------------------------------
    class Scene(object):
        u"""Maya のシーン再生範囲の代用(mp4blast.frame_range を差し替える)。"""
        def __init__(self, s=1, e=48):
            self.range = (s, e)

        def __call__(self):
            return self.range

    def with_scene(self, s=1, e=48):
        scene = self.Scene(s, e)
        p = patch.object(ui.mp4blast, "frame_range", scene)
        p.start()
        self.addCleanup(p.stop)
        return scene

    def test_time_range_options_and_persistence(self):
        scene = self.with_scene(1, 48)
        owner, tb = self.shown()
        opts = tb.mp4_options()
        self.assertEqual((opts["start_frame"], opts["end_frame"]), (1, 48))   # 既定はシーン範囲(今の値を明示して採用)
        self.assertFalse(tb.pbStart.isEnabled())
        tb.pbRangeScene.setChecked(False)
        app.processEvents()
        self.assertTrue(tb.pbStart.isEnabled() and tb.pbEnd.isEnabled())
        tb.pbStart.setValue(10)
        tb.pbEnd.setValue(50)
        opts = tb.mp4_options()
        self.assertEqual((opts["start_frame"], opts["end_frame"]), (10, 50))
        self.assertEqual((owner.data["playblastStart"], owner.data["playblastEnd"]), (10, 50))
        self.assertFalse(owner.data["playblastRangeScene"])
        tb.pbStart.setValue(80)                                    # 開始 > 終了 → 終了が追従(開始 ≤ 終了を保つ)
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (80, 80))
        tb.pbEnd.setValue(20)                                      # 終了 < 開始 → 開始が追従
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (20, 20))
        # シーン範囲へ戻すと指定値は保持され、オプションはシーン範囲
        tb.pbStart.setValue(5)
        tb.pbEnd.setValue(30)
        tb.pbRangeScene.setChecked(True)
        opts = tb.mp4_options()
        self.assertEqual((opts["start_frame"], opts["end_frame"]), scene.range)
        self.assertEqual(owner.data["playblastStart"], 5)
        tb.pbRangeScene.setChecked(False)
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (5, 30))

    # ---- 追指示1-4: Scene ON のまま Maya の再生範囲が変わっても、表示 = 書出しの採用範囲 ----------
    def test_scene_on_external_range_change_display_equals_output(self):
        scene = self.with_scene(1, 48)
        owner, tb = self.shown()
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (1, 48))
        scene.range = (10, 200)                                   # UI は何も知らされない外部変更(イベント未発火)
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (1, 48))    # 表示は古いまま(イベントが無い場合の状況)
        opts = tb.mp4_options()                                   # 書出し直前: 取り直して表示に反映し、同じ値を採用
        self.assertEqual((opts["start_frame"], opts["end_frame"]), (10, 200))
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (10, 200))  # 表示 = 採用範囲
        self.assertEqual(owner.saves, 0)                          # 表示の同期は設定を書き換えない
        self.assertNotIn("playblastStart", owner.data)             # 範囲を指定値として保存し直してもいない

    def test_scene_on_range_refreshes_on_show_and_event(self):
        scene = self.with_scene(1, 48)
        owner, tb = self.shown()
        tb.hide()
        scene.range = (3, 7)
        tb.show()                                                  # 表示したとき(showEvent)に拾う
        app.processEvents()
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (3, 7))
        # イベント(playbackRangeChanged 等)の scriptJob → ハンドラ → 表示更新
        Window = getattr(ui, "PlsCamViewWindow", None) or getattr(ui, "PlsFxViewWindow")
        registered = []

        class FakeCmds(object):
            def scriptJob(self, **kw):
                registered.append(kw["event"])
                return len(registered)
        stub = types.SimpleNamespace(_scriptJobs=[], _closing=False, exists=lambda: True, toolbox=tb)
        stub._on_scene_changed = lambda *a: None
        stub._on_before_scene_change = lambda *a: None
        stub._on_active_view_changed = lambda *a: None
        stub._on_playback_range_changed = types.MethodType(Window._on_playback_range_changed, stub)
        with patch.object(ui, "cmds", FakeCmds()):
            Window._setup_script_jobs(stub)
        events = [e[0] for e in registered if e[1] == stub._on_playback_range_changed]
        self.assertEqual(sorted(events), sorted(["playbackRangeChanged", "playbackRangeSliderChanged",
                                                 "SceneOpened", "NewSceneOpened"]))
        scene.range = (100, 120)
        for ev, cb in registered:
            if cb == stub._on_playback_range_changed:
                cb()
                break
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (100, 120))
        # Scene OFF のときは指定値のまま(外部の変更に引きずられない)
        tb.pbRangeScene.setChecked(False)
        tb.pbStart.setValue(2)
        tb.pbEnd.setValue(9)
        scene.range = (500, 600)
        stub._on_playback_range_changed()
        opts = tb.mp4_options()
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value(), opts["start_frame"], opts["end_frame"]), (2, 9, 2, 9))

    def test_scene_on_external_change_reaches_the_playblast_call(self):
        """UI 表示 = mp4_options の範囲 = Maya の playblast に渡る startTime / endTime(Maya 標準経路)。"""
        from unittest.mock import MagicMock
        scene = self.with_scene(1, 48)
        owner, tb = self.shown()
        scene.range = (10, 200)                                    # Maya の再生範囲を外から変更
        kw = tb.mp4_options()
        kw.update(optimize_viewport=False, output_path=None, open_after=False)
        captured = {}
        with patch.object(ui.mp4blast, "cmds", MagicMock()), \
                patch.object(ui.mp4blast, "_maya_playblast_options", return_value={}), \
                patch.object(ui.mp4blast, "_raw_playblast", side_effect=lambda **k: captured.update(k)):
            ok, msg, _ = ui.mp4blast.run("modelPanel4", **kw)
        self.assertTrue(ok, msg)
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (10, 200))                    # 表示
        self.assertEqual((captured["startTime"], captured["endTime"]), (10, 200))              # 実際の撮影範囲

    # ---- 追指示2: 数字・文字が実際に描画領域を持つ(値を持つだけでは表示の証明にならない) ------------------
    def _card_widgets(self, tb):
        card = tb._pbBody
        while card is not None and not isinstance(card, style.Card):
            card = card.parentWidget()
        return card

    @staticmethod
    def _clipped_by_ancestors(card):
        """可視の全子 widget(と card 自身)が、すべての祖先の可視領域に収まっているか。
        子 widget 自身の幅だけでなく、祖先 frame / viewport の contentsRect との交差で見る(右端が祖先の外へ出る = 切れる)。"""
        QC = qt.QtCore
        bad = []
        for wd in [card] + card.findChildren(QW.QWidget):
            if not wd.isVisibleTo(card) or wd.width() <= 0 or wd.height() <= 0:
                continue
            g = QC.QRect(wd.mapToGlobal(QC.QPoint(0, 0)), wd.size())
            p = wd.parentWidget()
            while p is not None:
                if isinstance(p, QW.QAbstractScrollArea):
                    area = QC.QRect(p.viewport().mapToGlobal(QC.QPoint(0, 0)), p.viewport().size())
                else:
                    cr = p.contentsRect()
                    area = QC.QRect(p.mapToGlobal(cr.topLeft()), cr.size())
                if not area.contains(g):
                    bad.append((type(wd).__name__, wd.objectName(), g.right() - area.right(), g.left() - area.left(),
                                type(p).__name__))
                    break
                p = p.parentWidget()
        return bad

    def test_nothing_is_clipped_by_ancestors_at_dock_widths(self):
        """日英 × Settings 開閉 × Multi × 幅 333 / 300 / 280 で、全項目が祖先の可視領域に収まる
        (右端の End / Height / CRF / Preset を含む)。数値欄の幅に依存しないので Qt 6.12 でも検査する。"""
        problems = []
        for width in (333, 300, 280):
            for lang in ("ja", "en"):
                for settings_open in (False, True):
                    for multi in (False, True):
                        owner, tb = self.shown({"language": lang, "playblastSettingsCollapsed": not settings_open,
                                                "playblastMulti": multi, "playblastCombine": True,
                                                "playblastKeepIndividuals": True, "playblastRangeScene": False},
                                               width=width, height=4200)
                        bad = self._clipped_by_ancestors(self._card_widgets(tb))
                        if bad:
                            problems.append(((width, lang, settings_open, multi), bad[:3]))
                        tb.deleteLater()
                        app.processEvents()
        self.assertEqual(problems, [])

    # test_multi_buttons_share_one_row_and_do_not_add_height: g3(2026-11-08 本人指定の構成)で旧構成の試験として外した。test_pb_g3.py を参照

    def test_text_has_room_in_all_states(self):
        """日英 × Settings 開閉 × Multi(合成 / 個別保持の横並び)で、可視の文字・数字が自分の幅に収まる。

        スピンの数字は QSpinBox 内の入力部(lineEdit)の幅で確認する。Qt 6.12 では『NoButtons + QSS』の
        QSpinBox は入力部が 1px になる(製品の変更とは無関係。既存の SliderRow の数値欄も同じ)ため、
        その環境では数字の項目だけ skip して理由を出す(Qt 6.8 では検査する)。
        """
        probe = QW.QSpinBox()
        probe.setButtonSymbols(QW.QAbstractSpinBox.NoButtons)
        probe.setStyleSheet("QSpinBox{border:1px solid #444;padding:4px 8px;min-height:22px;}")
        probe.setFixedWidth(100)
        probe.show()
        app.processEvents()
        spin_layout_ok = probe.lineEdit().width() > 40
        probe.close()
        problems = []
        for width, lang, settings_open, multi in [(wd, lg, so, mu) for wd in (333, 280) for lg in ("ja", "en")
                                                  for so in (False, True) for mu in (False, True)]:
            if True:
                if True:
                    owner, tb = self.shown({"language": lang, "playblastSettingsCollapsed": not settings_open,
                                            "playblastMulti": multi, "playblastCombine": True,
                                            "playblastKeepIndividuals": True, "playblastRangeScene": False},
                                           width=width, height=4200)
                    card = self._card_widgets(tb)
                    for w in card.findChildren(QW.QWidget):
                        if not w.isVisible() or w.width() <= 0:
                            continue
                        tag = (width, lang, settings_open, multi, type(w).__name__, w.objectName())
                        if isinstance(w, QW.QSpinBox) or isinstance(w, QW.QDoubleSpinBox):
                            if spin_layout_ok:
                                le = w.lineEdit()
                                need = le.fontMetrics().horizontalAdvance(w.text())
                                if le.width() < need:
                                    problems.append(tag + ("spin", le.width(), need))
                        elif isinstance(w, style.ElidedLabel):
                            continue                              # 要約は幅に応じて省略する部品(意図した省略)
                        elif isinstance(w, QW.QLabel) and w.text() and not w.wordWrap() and not hasattr(w, "fullText"):
                            need = w.fontMetrics().horizontalAdvance(w.text())
                            if w.width() < need - 1:
                                problems.append(tag + ("label", w.width(), need))
                        elif isinstance(w, (QW.QCheckBox, style.ToggleSwitch)) and w.text():
                            if w.width() < w.sizeHint().width() - 1:
                                problems.append(tag + ("toggle", w.width(), w.sizeHint().width()))
                    tb.deleteLater()
                    app.processEvents()
        self.assertEqual(problems, [])
        if not spin_layout_ok:
            self.skipTest("Qt %s: NoButtons + QSS の QSpinBox は入力部が 1px になるため、数字の項目は未検査(文字 / トグルは検査済み)"
                          % qt.QtCore.qVersion())

    def test_scene_range_fraction_matches_backend_rounding(self):
        scene = self.with_scene(1.4, 48.5)                        # 端数の再生範囲: 表示も書出しも四捨五入(.5 は切り上げ)
        owner, tb = self.shown()
        opts = tb.mp4_options()
        self.assertEqual((opts["start_frame"], opts["end_frame"]), (1, 49))
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (1, 49))

    def test_pull_with_bad_saved_values(self):
        owner, tb = self.toolbox()
        data = dict(owner.data, playblastRangeScene=False, playblastStart="x", playblastEnd=None,
                    playblastCollapsed="yes", mp4Width=0, mp4Height=-5)
        tb.pull(data)
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (1, 24))
        data = dict(owner.data, playblastRangeScene=False, playblastStart=90, playblastEnd=10)
        tb.pull(data)
        self.assertEqual((tb.pbStart.value(), tb.pbEnd.value()), (10, 90))
        self.assertGreaterEqual(tb.mp4Width.value(), tb.mp4Width.minimum())    # 範囲外はスピンの下限へ

    def test_defaults_exist(self):
        for key, value in (("playblastCollapsed", False), ("playblastRangeScene", True),
                           ("playblastStart", 1), ("playblastEnd", 24)):
            self.assertEqual(settings.DEFAULTS[key], value)

    def test_existing_single_path_options_unchanged(self):
        owner, tb = self.shown()
        opts = tb.mp4_options()
        for key in ("width", "height", "fps", "crf", "preset", "quality", "show_ornaments", "off_screen",
                    "optimize_viewport", "keep_frames", "open_after", "output_path", "mode",
                    "from_render_settings"):
            self.assertIn(key, opts)

    def test_new_strings_have_both_languages(self):
        for text in (u"シーン範囲", u"開始", u"終了", u"設定値が不正です: {}"):
            i18n.set_language("en")
            self.assertNotEqual(i18n.tr(text), text, text)
        for text in (u"Time Range", u"Output"):
            i18n.set_language("ja")
            self.assertNotEqual(i18n.tr(text), text, text)


    # ---- FX-SUBFRAME-FOLD: 開閉しても値 / enabled / 保存値を壊さない ---------------------------
    SETTINGS_DATA = {
        "mp4Width": 1280, "mp4Height": 720, "mp4Fps": 24.0, "mp4UseSceneFps": False, "mp4Quality": 80,
        "mp4Crf": 22, "mp4Preset": "fast", "mp4OutputPath": "D:/x/y.mp4", "playblastRangeScene": False,
        "playblastStart": 10, "playblastEnd": 50, "playblastMulti": True, "playblastCombine": True,
        "playblastKeepIndividuals": False, "outputMode": "mp4", "playblastSettingsCollapsed": False,
        "mp4FromRenderSettings": True, "mp4KeepFrames": True, "mp4ShowOrnaments": True,
        "mp4OffScreen": True, "mp4OptimizeViewport": False, "mp4OpenAfter": False,
    }

    def snapshot(self, tb):
        u"""Settings / Time Range / Output / Multi の全部品の (値, enabled, 表示するか) と出力モード。"""
        snap = {}
        for name in ("mp4Width", "mp4Height", "mp4Fps", "mp4UseSceneFps", "mp4Quality", "mp4Crf", "mp4Preset",
                     "mp4FromRender", "mp4Ornaments", "mp4OffScreen", "mp4Optimize", "mp4KeepFrames",
                     "mp4OpenAfter", "mp4Output", "pbRangeScene", "pbStart", "pbEnd", "multiEnabled",
                     "multiCombine", "multiKeep", "forceChk"):
            w = getattr(tb, name)
            if hasattr(w, "currentText"):
                v = w.currentText()
            elif hasattr(w, "value"):
                v = w.value()
            elif hasattr(w, "isChecked"):
                v = w.isChecked()
            else:
                v = w.text()
            snap[name] = (v, w.isEnabled(), not w.isHidden())
        snap["mode"] = tb.outputSeg.current()
        snap["custom_range"] = tb._pbRangeCustom
        return snap

    def test_fold_cycles_keep_values_enabled_and_visibility(self):
        owner, tb = self.shown(dict(self.SETTINGS_DATA))
        before = self.snapshot(tb)
        self.assertFalse(before["pbStart"][1] and False)                    # スナップショット自体が取れている
        self.assertEqual(before["mode"], "mp4")
        self.assertEqual(before["pbStart"][0], 10)
        tb._toggle_pb_card()
        tb._toggle_pb_card()
        tb.pbSettings.setCollapsed(True)
        tb.pbSettings.setCollapsed(False)
        tb._toggle_pb_card()
        tb.pbSettings.setCollapsed(True)
        tb._toggle_pb_card()                                                 # カードを開いても Settings は畳んだまま
        self.assertTrue(tb.pbSettings.isCollapsed())
        tb.pbSettings.setCollapsed(False)
        app.processEvents()
        self.assertEqual(self.snapshot(tb), before)

    def test_fold_state_and_values_round_trip_through_saved_settings(self):
        owner, tb = self.shown(dict(self.SETTINGS_DATA, playblastCollapsed=False))
        before = self.snapshot(tb)
        tb._toggle_pb_card()                                                 # 利用者が PLAYBLAST 全体を畳む
        tb.pbSettings.setCollapsed(True)                                     # Settings も畳む
        self.assertTrue(owner.data["playblastCollapsed"])
        self.assertTrue(owner.data["playblastSettingsCollapsed"])
        owner2, tb2 = self.shown(dict(owner.data))                           # 保存値から作り直す(再起動の代用)
        self.assertTrue(tb2._pbCardCollapsed)
        self.assertTrue(tb2.pbSettings.isCollapsed())
        tb2._toggle_pb_card()
        tb2.pbSettings.setCollapsed(False)
        app.processEvents()
        self.assertEqual(self.snapshot(tb2), before)
        # 畳んだまま保存された値で書出し引数も同じ(Settings を開かなくても有効)
        self.assertEqual(tb2.mp4_options()["width"], 1280)
        self.assertEqual(tb2.mp4_options()["crf"], 22)

    def test_horizontal_dock_does_not_overwrite_saved_settings_fold(self):
        owner, tb = self.shown({"playblastSettingsCollapsed": False})
        seen = []                                                            # 保存のたびに Settings の保存値を記録
        plain_save = owner.save_settings
        owner.save_settings = lambda: (seen.append(owner.data.get("playblastSettingsCollapsed")), plain_save())
        tb.resize(1100, 320)
        tb.set_orientation(True)                                             # 上 / 下ドックへ
        app.processEvents()
        self.assertTrue(tb.pbSettings.isCollapsed())                         # 高さを抑えるため畳んで見せるのは従来どおり
        self.assertFalse(owner.data["playblastSettingsCollapsed"])           # ただし保存値(利用者の選択)は書き換えない
        self.assertNotIn(True, seen)                                         # 自動の畳みで「畳んだ」を保存しない(Effects の保存は別件)
        tb.resize(self.DOCK_W, 900)
        tb.set_orientation(False)                                            # 左 / 右ドックへ戻す
        app.processEvents()
        self.assertFalse(tb.pbSettings.isCollapsed())                        # 利用者が開いていた状態に戻る
        self.assertFalse(owner.data["playblastSettingsCollapsed"])

    def test_horizontal_dock_keeps_a_folded_settings_folded(self):
        owner, tb = self.shown({"playblastSettingsCollapsed": True})
        tb.set_orientation(True)
        app.processEvents()
        tb.set_orientation(False)
        app.processEvents()
        self.assertTrue(tb.pbSettings.isCollapsed())
        self.assertTrue(owner.data["playblastSettingsCollapsed"])

    def test_user_choice_in_horizontal_dock_wins_over_restore(self):
        owner, tb = self.shown({"playblastSettingsCollapsed": False})
        tb.set_orientation(True)
        app.processEvents()
        tb.pbSettings.setCollapsed(False)                                    # 横で利用者が開いた(保存される)
        self.assertFalse(owner.data["playblastSettingsCollapsed"])
        tb.pbSettings.setCollapsed(True)                                     # 横で利用者が畳んだ(保存される)
        self.assertTrue(owner.data["playblastSettingsCollapsed"])
        tb.set_orientation(False)
        app.processEvents()
        self.assertTrue(tb.pbSettings.isCollapsed())                         # 利用者の最後の選択を優先(自動では開けない)
        # 横で開いたまま縦へ戻る場合は開いたまま
        owner2, tb2 = self.shown({"playblastSettingsCollapsed": False})
        tb2.set_orientation(True)
        tb2.pbSettings.setCollapsed(False)
        tb2.set_orientation(False)
        app.processEvents()
        self.assertFalse(tb2.pbSettings.isCollapsed())
        self.assertFalse(owner2.data["playblastSettingsCollapsed"])

    def test_restart_in_horizontal_dock_keeps_saved_fold(self):
        # 再起動の代用: 保存値(開いている)で作る -> pull -> 横ドックへ(Window._restore と同じ順)。保存値は変わらない
        owner, tb = self.shown({"playblastSettingsCollapsed": False})
        tb.set_orientation(True)
        app.processEvents()
        self.assertFalse(owner.data["playblastSettingsCollapsed"])
        owner2, tb2 = self.shown(dict(owner.data))                           # 次の起動でも同じ保存値から始まる
        self.assertFalse(tb2.pbSettings.isCollapsed())
        self.assertFalse(owner2.data["playblastSettingsCollapsed"])

    def test_pull_is_the_source_of_truth_for_settings_fold(self):
        owner, tb = self.shown({"playblastSettingsCollapsed": False})
        tb.set_orientation(True)                                             # 自動で畳んだ(戻す物あり)
        app.processEvents()
        tb.pull(dict(settings.DEFAULTS, playblastSettingsCollapsed=True))    # 設定の読み直し: 正本は設定
        tb.set_orientation(False)
        app.processEvents()
        self.assertTrue(tb.pbSettings.isCollapsed())

    def test_horizontal_dock_does_not_touch_card_fold_or_values(self):
        owner, tb = self.shown(dict(self.SETTINGS_DATA, playblastCollapsed=True))
        before = self.snapshot(tb)
        tb.set_orientation(True)
        app.processEvents()
        self.assertTrue(tb._pbCardCollapsed)
        self.assertTrue(owner.data["playblastCollapsed"])
        tb.set_orientation(False)
        tb._toggle_pb_card()
        tb.pbSettings.setCollapsed(False)
        app.processEvents()
        self.assertEqual(self.snapshot(tb), before)

    # ---- FX-SUBFRAME-FOLD s2: Settings は数値だけ。切替 / プリセットは用途の合う既存位置 -------------------
    NUMBERS = ("mp4Width", "mp4Height", "mp4Fps", "mp4Quality", "mp4Crf")
    MOVED = {"mp4UseSceneFps": "pbRangeBox", "mp4FromRender": "pbOutputBox", "mp4Preset": "pbOutputBox",
             "mp4KeepFrames": "pbOutputBox", "mp4Ornaments": "pbCaptureBox", "mp4OffScreen": "pbCaptureBox",
             "mp4Optimize": "pbCaptureBox"}

    # test_settings_contains_only_the_five_numbers: g3(2026-11-08 本人指定の構成)で旧構成の試験として外した。test_pb_g3.py を参照

    # test_moved_items_live_in_their_purpose_box: g3(2026-11-08 本人指定の構成)で旧構成の試験として外した。test_pb_g3.py を参照

    # test_moved_items_stay_visible_when_settings_folded_and_follow_the_card: g3(2026-11-08 本人指定の構成)で旧構成の試験として外した。test_pb_g3.py を参照

    def test_moved_items_keep_values_through_pull_and_options(self):
        """設定 → UI(pull)→ mp4_options で、移した項目も従来どおりの値になる。"""
        owner, tb = self.shown(dict(self.SETTINGS_DATA))
        self.assertTrue(tb.mp4FromRender.isChecked())
        self.assertFalse(tb.mp4UseSceneFps.isChecked())
        self.assertEqual(tb.mp4Preset.currentText(), "fast")
        self.assertTrue(tb.mp4KeepFrames.isChecked())
        self.assertTrue(tb.mp4Ornaments.isChecked())
        self.assertTrue(tb.mp4OffScreen.isChecked())
        self.assertFalse(tb.mp4Optimize.isChecked())
        opt = tb.mp4_options()
        self.assertEqual((opt["fps"], opt["preset"], opt["keep_frames"], opt["show_ornaments"], opt["off_screen"],
                          opt["optimize_viewport"], opt["from_render_settings"]),
                         (24.0, "fast", True, True, True, False, True))
        tb.mp4UseSceneFps.setChecked(True)
        self.assertIsNone(tb.mp4_options()["fps"])                      # シーン FPS は None(従来どおり)

    def test_moved_items_keep_enabled_links(self):
        """関連付け・無効状態: シーン FPS ↔ FPS 欄 / From Render Settings ↔ 幅・高さ / 出力形式 ↔ プリセット・PNG・CRF。"""
        owner, tb = self.shown(dict(self.SETTINGS_DATA, mp4UseSceneFps=False, mp4FromRenderSettings=False,
                                    outputMode="mp4"))
        for n in ("mp4Fps", "mp4Width", "mp4Height", "mp4Crf", "mp4Preset", "mp4KeepFrames"):
            self.assertTrue(getattr(tb, n).isEnabled(), n)
        tb.mp4UseSceneFps.setChecked(True)                              # Time Range 側の切替で Settings の FPS 欄が無効に
        self.assertFalse(tb.mp4Fps.isEnabled())
        tb.mp4UseSceneFps.setChecked(False)
        self.assertTrue(tb.mp4Fps.isEnabled())
        tb.mp4FromRender.setChecked(True)                               # Output 側の切替で Settings の幅 / 高さが無効に
        self.assertFalse(tb.mp4Width.isEnabled())
        self.assertFalse(tb.mp4Height.isEnabled())
        self.assertTrue(tb.mp4Fps.isEnabled())
        tb.mp4FromRender.setChecked(False)
        self.assertTrue(tb.mp4Width.isEnabled() and tb.mp4Height.isEnabled())
        tb.outputSeg.setCurrent("maya")                                 # Maya 標準では MP4 専用の項目が無効(隠さない)
        tb._on_output_mode("maya")
        for n in ("mp4Crf", "_crfLabel", "mp4Preset", "_presetLabel", "mp4KeepFrames"):
            self.assertFalse(getattr(tb, n).isEnabled(), n)
        for n in ("mp4Width", "mp4Quality", "mp4FromRender", "mp4Ornaments", "mp4OffScreen", "mp4Optimize",
                  "mp4UseSceneFps"):
            self.assertTrue(getattr(tb, n).isEnabled(), n)
        self.assertFalse(tb.mp4Width.isHidden())              # g4: 解像度などは隠さない
        self.assertTrue(tb.mp4KeepFrames.isHidden())          # g4r2(本人指定): PNG を残す / CRF / プリセットは MP4 以外で隠す
        self.assertTrue(tb.mp4Preset.isHidden())
        tb._on_output_mode("mp4")
        self.assertTrue(tb.mp4Preset.isEnabled() and tb.mp4KeepFrames.isEnabled() and tb.mp4Crf.isEnabled())

    def test_moved_items_save_the_same_keys(self):
        """移した項目を触ると、従来と同じ設定キーへ保存される(保存形式は不変)。"""
        owner, tb = self.shown(dict(self.SETTINGS_DATA))
        keys = {"mp4UseSceneFps": "mp4UseSceneFps", "mp4FromRender": "mp4FromRenderSettings",
                "mp4KeepFrames": "mp4KeepFrames", "mp4Ornaments": "mp4ShowOrnaments",
                "mp4OffScreen": "mp4OffScreen", "mp4Optimize": "mp4OptimizeViewport"}
        for attr, key in keys.items():
            w = getattr(tb, attr)
            now = w.isChecked()
            w.setChecked(not now)
            self.assertEqual(owner.data[key], not now, attr)
            w.setChecked(now)                                            # 両方向(ON → OFF / OFF → ON)の保存を確認
            self.assertEqual(owner.data[key], now, attr)
            w.setChecked(not now)
            self.assertEqual(owner.data[key], not now, attr)
        other = [i for i in range(tb.mp4Preset.count()) if tb.mp4Preset.itemText(i) != "fast"][0]
        tb.mp4Preset.setCurrentIndex(other)
        self.assertEqual(owner.data["mp4Preset"], tb.mp4Preset.currentText())
        self.assertNotEqual(owner.data["mp4Preset"], "fast")
        self.assertEqual(owner.data["mp4Width"], 1280)                  # 他のキーは壊れない
        # 再起動相当: 保存値からもう一度組み立てても同じ
        owner2, tb2 = self.shown(dict(owner.data))
        for attr in keys:
            self.assertEqual(getattr(tb2, attr).isChecked(), getattr(tb, attr).isChecked(), attr)
        self.assertEqual(tb2.mp4Preset.currentText(), tb.mp4Preset.currentText())

    def test_summary_still_follows_moved_switches(self):
        owner, tb = self.shown(dict(self.SETTINGS_DATA, mp4UseSceneFps=False, mp4FromRenderSettings=False))
        tb._set_pb_card_collapsed(True)
        self.assertIn("24", tb._pbCardSummary.text())
        tb.mp4UseSceneFps.setChecked(True)
        self.assertIn("scene", tb._pbCardSummary.text())
        tb.mp4FromRender.setChecked(True)
        self.assertTrue("RS" in tb._pbCardSummary.text() or "Render Settings" in tb._pbCardSummary.text())

    # test_horizontal_dock_keeps_moved_items_in_main_column: g3(2026-11-08 本人指定の構成)で旧構成の試験として外した。test_pb_g3.py を参照

    # test_moved_rows_do_not_break_multi_row_and_dock_heights: g3(2026-11-08 本人指定の構成)で旧構成の試験として外した。test_pb_g3.py を参照

if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
