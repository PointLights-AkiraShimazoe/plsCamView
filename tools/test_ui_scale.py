# -*- coding: utf-8 -*-
u"""UI 倍率(0.9.x)の offscreen Qt 検証。
中央トークン style.px() が スタイルシート・固定寸法・カスタム描画(トグル/シェブロン/アイコン)・
クリック範囲へ一括適用されること、既定 85% で標準右ドック幅(約333px)に横スクロール無しで
収まること、狭幅では横スクロールが最終フォールバックとして働くこと、保存/復元、
日英・全ドック方向、QT_SCALE_FACTOR(OS 倍率相当) 1.0/1.25/1.5/2.0 で DIP 寸法が変わらない
(二重 DPI 適用なし)ことを確認する。実 Windows / 実 Maya の表示確認は含まない(チェックリスト側)。"""
import importlib
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys
import types
import unittest

ROOT = Path(os.environ.get('PLS_TEST_SOURCE', str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _qt_font_env   # noqa: E402  実フォント読込(Windows offscreen はフォント DB が空になるため)
_qt_font_env.prepare()
PACKAGE = 'plsCamView'


class UiScale(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt = importlib.import_module(PACKAGE + '.qt')
        cls.qt = qt
        cls.QW = qt.QtWidgets
        cls.app = cls.QW.QApplication.instance() or cls.QW.QApplication([])
        # フォントが解決できない(偽メトリクス)環境では幅の試験を合格にしない(setUpClass で失敗させる)
        cls.font_env = _qt_font_env.load_and_verify(qt.QtGui, cls.QW)
        cls.style = importlib.import_module(PACKAGE + '.style')
        cls.ui = importlib.import_module(PACKAGE + '.ui')
        cls.i18n = importlib.import_module(PACKAGE + '.i18n')

    def tearDown(self):
        self.style.set_ui_scale(self.style.UI_SCALE_DEFAULT)
        self.i18n.set_language("system")
        self.app.processEvents()

    def _toolbox(self, data=None):
        owner = types.SimpleNamespace()
        owner.data = dict({"language": "system", "camera": "persp"}, **(data or {}))
        owner.saves = 0

        def _save():
            owner.saves += 1
        owner.save_settings = _save
        owner.views = None
        owner.refresh_cameras = lambda *a, **k: None
        tb = self.ui.ToolBox(owner)
        self.addCleanup(tb.deleteLater)
        return owner, tb

    def test_px_token_applies_everywhere(self):
        u"""倍率がスタイルシート・固定寸法・カスタム描画(クリック範囲込み)に一括適用される。"""
        for pct in (75, 85, 100, 115, 125):
            owner, tb = self._toolbox({"uiScale": pct})
            self.assertEqual(self.style.ui_scale_percent(), pct)
            px = self.style.px
            # スタイルシートの本文フォント
            m = re.search(r'font-size:\s*(\d+)px', tb.styleSheet())
            self.assertEqual(int(m.group(1)), px(16), pct)
            # 固定寸法(レイアウトアイコン)
            b = tb.dockPicker._order[0]
            self.assertEqual((b.width(), b.height()), (px(40), px(36)), pct)
            self.assertEqual(b.iconSize().width(), px(30), pct)
            # カスタム描画のクリック範囲(トグル)
            sw = tb.shadowChk
            self.assertEqual(sw.TRACK_W, px(40), pct)
            self.assertEqual(sw.TRACK_H, px(22), pct)
            self.assertGreaterEqual(sw.minimumSizeHint().height(), px(22), pct)
            tb.deleteLater(); self.app.processEvents()

    def test_font_environment_is_real(self):
        u"""試験環境のフォントが実際に解決できている(Windows は Segoe UI と日本語 UI フォント)。"""
        info = self.font_env
        print(u"[font env] " + _qt_font_env.font_env_summary(info))
        for pr in info["probe"]:
            self.assertTrue(pr["resolved"], pr)
            self.assertGreater(pr["px"], 0, pr)
            self.assertGreater(pr["w_ja"], 0, pr)
        owner, tb = self._toolbox({"uiScale": 85, "language": "ja"})
        fi = self.qt.QtGui.QFontInfo(tb.languageCombo.font())
        self.assertTrue(fi.family(), u"ツールボックスのフォントが解決されていない")
        self.assertGreater(fi.pixelSize(), 0)

    def test_default_is_compact_85(self):
        owner, tb = self._toolbox()        # uiScale 未保存の既存設定
        self.assertEqual(self.style.ui_scale_percent(), 85)
        self.assertEqual(self.style.UI_SCALE_DEFAULT, 85)

    def test_gear_menu_saves_and_reset(self):
        owner, tb = self._toolbox({"uiScale": 85})
        tb._on_ui_scale(100)
        self.assertEqual(owner.data["uiScale"], 100)
        self.assertEqual(owner.saves, 1)
        self.assertFalse(tb._languageNote.isHidden())
        tb._on_ui_scale(100)               # 同値は保存しない
        self.assertEqual(owner.saves, 1)
        tb._on_ui_scale(self.style.UI_SCALE_DEFAULT)   # 標準へ戻す
        self.assertEqual(owner.data["uiScale"], 85)
        # 適用は自動で行わない(開き直しはユーザー明示操作)
        self.assertTrue(hasattr(tb, "_restart_tool"))

    # 標準右ドック相当の幅(既定ウィンドウ 1280 x 26%)
    DOCK_W = 333
    # 実フォント(_qt_font_env で読込・解決を確認)で測った本文最小幅に、OS / フォント差の余裕を
    # 見込んで標準ドック幅より狭い上限を要求する(フォントが解決できない環境は setUpClass で失敗)。
    HEADROOM_W = 308

    def _check_default_dock(self, lang, limit):
        owner, tb = self._toolbox({"uiScale": 85, "language": lang})
        tb.resize(self.DOCK_W, 800)
        tb.show(); self.app.processEvents()
        body = tb._scroll.widget()
        need = body.minimumSizeHint().width()
        self.assertLessEqual(need, limit,
                             u"[{}] 既定幅で中身が収まらない: {} > {}".format(lang, need, limit))
        self.assertEqual(tb._scroll.horizontalScrollBar().maximum(), 0,
                         u"[{}] 既定幅で横スクロールが必要になっている".format(lang))
        for name, w in ((u"歯車", tb.scaleBtn), (u"Language", tb.languageCombo),
                        (u"Playblast 実行", tb.pbBtn)):
            self.assertTrue(w.isVisible(), u"[{}] {} が表示されていない".format(lang, name))
            right = w.mapTo(tb._scroll.viewport(), w.rect().topRight()).x()
            self.assertLessEqual(right, tb._scroll.viewport().width(),
                                 u"[{}] {} の右端が見切れる".format(lang, name))
        tb.deleteLater(); self.app.processEvents()
        return need

    def test_default_dock_width_fits_without_hscroll(self):
        u"""既定 85%・標準右ドック相当(333px)で、横スクロール無しに主要項目(歯車/Language/
        Playblast 実行)が欠けず表示される。日英とも、Windows フォント差の余裕込みで判定する。"""
        for lang in ("ja", "en"):
            self._check_default_dock(lang, self.HEADROOM_W)

    def test_default_dock_width_wide_font_stress(self):
        u"""フォント差の吸収: 幅の広い代替フォント(DejaVu Sans + IPAGothic)と Windows 系 QStyle でも
        標準右ドック幅に収まる(Windows 実フォントの代替。実 Windows 表示はチェックリスト側)。"""
        fams = set(self.qt.QtGui.QFontDatabase.families()) if hasattr(self.qt.QtGui.QFontDatabase, "families") \
            else set(self.qt.QtGui.QFontDatabase().families())
        if "DejaVu Sans" not in fams:
            self.skipTest(u"DejaVu Sans が無い環境")
        orig_font = self.style.FONT_FAMILY
        orig_style = self.app.style().objectName()
        try:
            self.style.FONT_FAMILY = u'"DejaVu Sans", "IPAGothic", "Yu Gothic UI", sans-serif'
            if "Windows" in self.QW.QStyleFactory.keys():
                self.app.setStyle("Windows")
            for lang in ("ja", "en"):
                self.style._STYLESHEET_CACHE = None
                self._check_default_dock(lang, self.DOCK_W - 16)
        finally:
            self.style.FONT_FAMILY = orig_font
            self.style._STYLESHEET_CACHE = None
            if orig_style:
                self.app.setStyle(orig_style)

    def test_combo_text_not_clipped(self):
        u"""Language / 比率 / 合わせる枠のコンボは、実フォントの最長項目が欠けない幅になる
        (固定幅だと英語や Windows フォントで欠ける)。日英・幅広代替フォントの両方で確認。"""
        orig_font = self.style.FONT_FAMILY
        try:
            for fam in (None, u'"DejaVu Sans", "IPAGothic", sans-serif'):
                if fam:
                    self.style.FONT_FAMILY = fam
                for lang in ("ja", "en"):
                    self.style._STYLESHEET_CACHE = None
                    owner, tb = self._toolbox({"uiScale": 85, "language": lang})
                    tb.resize(self.DOCK_W, 800); tb.show(); self.app.processEvents()
                    for combo in (tb.languageCombo, tb.guideRatio, tb.guideFit):
                        fm = combo.fontMetrics()
                        widest = max(fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
                        self.assertGreaterEqual(combo.width(), widest + self.style.px(24),
                                                (fam, lang, combo.currentText()))
                    tb.deleteLater(); self.app.processEvents()
        finally:
            self.style.FONT_FAMILY = orig_font
            self.style._STYLESHEET_CACHE = None

    def test_narrow_width_scrollbar_fallback(self):
        u"""中身の最小幅より狭いときは横スクロールで全項目へ届く(最終フォールバック)。"""
        owner, tb = self._toolbox({"uiScale": 125})
        tb.resize(260, 800)
        tb.show(); self.app.processEvents()
        QC = self.qt.QtCore
        self.assertEqual(tb._scroll.horizontalScrollBarPolicy(), QC.Qt.ScrollBarAsNeeded)
        self.assertGreater(tb._scroll.horizontalScrollBar().maximum(), 0,
                           u"狭幅で横スクロールが出ない(項目に届かない)")

    def test_orientations_and_languages(self):
        for lang in ("ja", "en"):
            for pct in (75, 125):
                owner, tb = self._toolbox({"uiScale": pct, "language": lang})
                tb.resize(900, 300)
                tb.show()
                tb.set_orientation(True)
                self.app.processEvents()
                for horizontal in (True, False):
                    tb.set_orientation(horizontal)
                    self.app.processEvents()
                    # 上下ドック(True)・左右ドック(False)とも Language が表示され、右端が欠けない
                    self.assertTrue(tb.languageCombo.isVisible(), (lang, pct, horizontal))
                    self.assertTrue(tb.scaleBtn.isVisible(), (lang, pct, horizontal))
                    vp = tb._scroll.viewport()
                    right = tb.languageCombo.mapTo(vp, tb.languageCombo.rect().topRight()).x()
                    self.assertLessEqual(right, vp.width(), (lang, pct, horizontal))
                fm = tb.languageCombo.fontMetrics()
                widest = max(fm.horizontalAdvance(tb.languageCombo.itemText(i))
                             for i in range(tb.languageCombo.count()))
                self.assertEqual(tb.languageCombo.width(), widest + self.style.px(36))
                tb.deleteLater(); self.app.processEvents()

    def test_scale_menu_builds(self):
        u"""歯車メニューが構築できる(PySide2/6 両対応の QActionGroup)。exec はしない。"""
        owner, tb = self._toolbox({"uiScale": 85})
        menu = tb._build_scale_menu()
        # ポップアップも製品の見た目・倍率(Maya のパレット任せにしない)
        self.assertIn(u"QMenu {", menu.styleSheet())
        self.assertIn(u"padding: {}px".format(self.style.px(4)), menu.styleSheet())
        texts = [a.text() for a in menu.actions() if a.text()]
        for pct in self.style.UI_SCALE_CHOICES:
            self.assertTrue(any(t.startswith(u"{}%".format(pct)) for t in texts), texts)
        tr = self.i18n.tr
        self.assertTrue(any(t.endswith(tr(u"(標準)")) for t in texts), texts)
        self.assertIn(tr(u"標準({}%)へ戻す").format(self.style.UI_SCALE_DEFAULT), texts)
        self.assertIn(tr(u"開き直して適用"), texts)
        checked = [a.text() for a in menu.actions() if a.isChecked()]
        self.assertEqual(len(checked), 1)
        self.assertTrue(checked[0].startswith(u"85%"))
        # メニューのアクション経由で倍率選択 → 設定保存(歯車クリック後の実経路)
        act100 = next(a for a in menu.actions() if a.text().startswith(u"100%"))
        act100.trigger()
        self.app.processEvents()
        self.assertEqual(owner.data["uiScale"], 100)
        self.assertGreaterEqual(owner.saves, 1)
        self.assertFalse(tb._languageNote.isHidden())
        reset = next(a for a in menu.actions()
                     if a.text() == tr(u"標準({}%)へ戻す").format(self.style.UI_SCALE_DEFAULT))
        reset.trigger()
        self.app.processEvents()
        self.assertEqual(owner.data["uiScale"], self.style.UI_SCALE_DEFAULT)
        menu.deleteLater()

    def test_scale_strings_translated(self):
        u"""歯車メニュー・案内・ツールチップの新規文言が英語表示で日本語のまま残らない(日英とも訳あり)。"""
        import re
        jp = re.compile(u"[\u3040-\u30ff\u4e00-\u9fff]")
        for lang in ("ja", "en"):
            self.i18n.set_language(lang)
            owner, tb = self._toolbox({"uiScale": 85, "language": lang})
            menu = tb._build_scale_menu()
            texts = [a.text() for a in menu.actions() if a.text()] + \
                [a.toolTip() for a in menu.actions() if a.text()] + \
                [tb.scaleBtn.toolTip(), tb.languageCombo.toolTip()]
            tb._on_ui_scale(115)
            texts.append(tb._languageNote.text())
            if lang == "en":
                left = [t for t in texts if jp.search(t)]
                self.assertEqual(left, [], u"英語表示に日本語が残る")
            menu.deleteLater(); tb.deleteLater(); self.app.processEvents()

    def test_gate_overlay_not_scaled(self):
        u"""Gate の座標計算・オーバーレイ描画には UI 倍率を掛けない(ソース保証)。"""
        import io
        go = importlib.import_module(PACKAGE + '.gate_overlay')
        with io.open(go.__file__.replace('.pyc', '.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertNotIn('from .style', src)
        self.assertNotIn('ui_scale', src)
        self.assertNotIn('px(', src.replace('pix', ''))

    def test_qt_scale_factor_no_double_scaling(self):
        u"""QT_SCALE_FACTOR 1.0/1.25/1.5/2.0(OS 倍率相当)で DIP 寸法が同一=二重適用なし。
        (本物のマルチモニタ DPI 切替は offscreen では再現できない。実機はチェックリスト側)"""
        script = (
            "import os,sys,types;"
            "sys.path.insert(0, r'%s');"
            "os.environ['QT_QPA_PLATFORM']='offscreen';"
            "sys.path.insert(0, r'%s');import _qt_font_env;_qt_font_env.prepare();"
            "import plsCamView.qt as qt;"
            "from plsCamView import ui, style;"
            "app=qt.QtWidgets.QApplication.instance() or qt.QtWidgets.QApplication([]);"
            "_qt_font_env.load_and_verify(qt.QtGui, qt.QtWidgets);"
            "o=types.SimpleNamespace(data={'language':'system','uiScale':85},save_settings=lambda:None,views=None,refresh_cameras=lambda *a,**k:None);"
            "tb=ui.ToolBox(o);tb.show();app.processEvents();"
            "b=tb.dockPicker._order[0];"
            "print(b.width(),b.height(),tb._scroll.widget().minimumSizeHint().width())"
        ) % (str(ROOT / 'scripts'), str(Path(__file__).resolve().parent))
        results = []
        for factor in ("1", "1.25", "1.5", "2"):
            env = dict(os.environ)
            env["QT_SCALE_FACTOR"] = factor
            env.pop("QT_AUTO_SCREEN_SCALE_FACTOR", None)
            out = subprocess.run([sys.executable, "-c", script], env=env,
                                 capture_output=True, text=True, timeout=120)
            self.assertEqual(out.returncode, 0, out.stderr[-400:])
            results.append(out.stdout.strip().splitlines()[-1])
        self.assertEqual(len(set(results)), 1,
                         u"QT_SCALE_FACTOR で DIP 寸法が変わる(二重適用の疑い): {}".format(results))


class _WindowDouble(types.SimpleNamespace):
    u"""PlsCamViewWindow の代役(試験用ダブル)。

    types.SimpleNamespace 自体は weakref を作れない。PySide6 6.8 の QTimer.singleShot(ms, bound_method) は
    bound method の __self__ への weakref を作るため、素の SimpleNamespace だと
    `TypeError: cannot create weak reference to 'types.SimpleNamespace' object` で save_settings が失敗する。
    実物の PlsCamViewWindow は通常のクラス(__weakref__ あり)なので製品側の欠陥ではない。サブクラスにして weakref できるようにする。"""


class UiScalePersistence(unittest.TestCase):
    u"""uiScale の永続保存/復元を、隔離した一時 settings.json の実ファイル I/O で確認する。
    保存は本体ウィンドウの実コード(PlsCamViewWindow._flush_save -> _collect -> settings.save)を通し、
    復元は settings.load と show 入口の _restore_language(実 __init__.py を spec 実行)を通す。
    Maya・実ウィンドウ・ユーザーの実設定ファイルには触れない(config_path を一時パスへ差し替え)。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt = importlib.import_module(PACKAGE + '.qt')
        cls.QW = qt.QtWidgets
        cls.app = cls.QW.QApplication.instance() or cls.QW.QApplication([])
        spec = importlib.util.spec_from_file_location(
            PACKAGE, str(ROOT / 'scripts' / PACKAGE / '__init__.py'),
            submodule_search_locations=[str(ROOT / 'scripts' / PACKAGE)])
        if PACKAGE not in sys.modules or not hasattr(sys.modules[PACKAGE], '_restore_language'):
            mod = importlib.util.module_from_spec(spec)
            sys.modules[PACKAGE] = mod
            spec.loader.exec_module(mod)
        cls.pkg = sys.modules[PACKAGE]
        cls.style = importlib.import_module(PACKAGE + '.style')
        cls.st = importlib.import_module(PACKAGE + '.settings')
        cls.ui = importlib.import_module(PACKAGE + '.ui')
        cls.i18n = importlib.import_module(PACKAGE + '.i18n')

    def setUp(self):
        import tempfile
        from unittest import mock
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.path = os.path.join(td.name, "settings.json")
        p = mock.patch.object(self.st, "config_path", return_value=self.path)
        p.start()
        self.addCleanup(p.stop)

    def tearDown(self):
        self.style.set_ui_scale(self.style.UI_SCALE_DEFAULT)
        self.i18n.set_language("system")

    def _window_like(self, data):
        u"""PlsCamViewWindow の保存経路だけを実コードで動かすための最小オブジェクト。"""
        W = self.ui.PlsCamViewWindow
        o = _WindowDouble(data=data, views=None, _win="plsCamViewTestWin",
                                  _closing=False, _savePending=False, _saveTimerArmed=False)
        o._percent_key = lambda: "toolboxPercent"
        o._query_toolbox_percent = lambda: data.get("toolboxPercent", 26)
        o.target_camera = types.MethodType(W.target_camera, o)
        o._collect = types.MethodType(W._collect, o)
        o._flush_save = types.MethodType(W._flush_save, o)
        o.save_settings = types.MethodType(W.save_settings, o)
        o.refresh_cameras = lambda *a, **k: None
        return o

    def _wait_flush(self, o):
        import time
        t0 = time.time()
        while (o._saveTimerArmed or o._savePending) and time.time() - t0 < 3.0:
            self.app.processEvents()
            time.sleep(0.02)
        self.assertFalse(o._savePending, u"保存が実行されなかった")

    def test_ui_scale_written_and_restored_via_settings_file(self):
        import json
        data = self.st.load()
        self.assertEqual(data.get("uiScale"), self.style.UI_SCALE_DEFAULT)   # 既定(未保存)
        data["language"] = "en"
        data["camera"] = u"|ns:camA"
        o = self._window_like(data)
        tb = self.ui.ToolBox(o)
        self.addCleanup(tb.deleteLater)
        # 歯車メニューの実アクションで 115% を選ぶ -> 本体の save_settings(300ms まとめ書き)
        menu = tb._build_scale_menu()
        next(a for a in menu.actions() if a.text().startswith(u"115%")).trigger()
        self._wait_flush(o)
        menu.deleteLater()
        raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
        self.assertEqual(raw.get("uiScale"), 115, u"settings.json に uiScale が書かれていない")
        self.assertEqual(raw.get("language"), "en", u"他の設定が失われた")
        self.assertEqual(raw.get("camera"), u"|ns:camA", u"他の設定が失われた")
        # 適用はユーザー操作まで行わない(現在の UI 倍率は変えない)
        self.assertEqual(self.style.ui_scale_percent(), self.style.UI_SCALE_DEFAULT)
        # 復元 1: show 入口(実 __init__.py の _restore_language)
        self.style.set_ui_scale(self.style.UI_SCALE_DEFAULT)
        self.pkg._restore_language()
        self.assertEqual(self.style.ui_scale_percent(), 115)
        # 復元 2: 読み込んだ設定でツールボックスを開き直すと 115% で構築される
        self.style.set_ui_scale(self.style.UI_SCALE_DEFAULT)
        o2 = self._window_like(self.st.load())
        tb2 = self.ui.ToolBox(o2)
        self.addCleanup(tb2.deleteLater)
        self.assertEqual(self.style.ui_scale_percent(), 115)
        b = tb2.dockPicker._order[0]
        self.assertEqual((b.width(), b.height()), (self.style.px(40), self.style.px(36)))
        # 標準へ戻す -> ファイルも 85 に戻る
        tb2._on_ui_scale(self.style.UI_SCALE_DEFAULT)
        self._wait_flush(o2)
        raw = json.loads(Path(self.path).read_text(encoding="utf-8"))
        self.assertEqual(raw.get("uiScale"), self.style.UI_SCALE_DEFAULT)

    def test_broken_value_falls_back(self):
        u"""手編集等で壊れた uiScale でも起動は止めず、既定 / 範囲内に丸める。"""
        import json
        for bad, expect in (("abc", self.style.UI_SCALE_DEFAULT), (None, self.style.UI_SCALE_DEFAULT),
                            (999, 200), (10, 50)):
            Path(self.path).write_text(json.dumps({"uiScale": bad}), encoding="utf-8")
            self.pkg._restore_language()
            self.assertEqual(self.style.ui_scale_percent(), expect, bad)
            # 壊れた値のまま歯車メニューを開いても落ちない(保存値は既定扱い)
            o = self._window_like(self.st.load())
            tb = self.ui.ToolBox(o)
            menu = tb._build_scale_menu()
            self.assertTrue(menu.actions())
            menu.deleteLater(); tb.deleteLater(); self.app.processEvents()


if __name__ == '__main__':
    unittest.main(verbosity=1)
