# -*- coding: utf-8 -*-
u"""i18n(plsFxView 0.2.21 / plsCamView 1.8.1 共通構造)の限定検証: system 判定の期待分岐 /
ja・en 表示 / キー欠落 / 実 UI への適用 / 折り畳み要約・設定ラベルの翻訳(継続65) /
language の保存・復元と既存設定の保全。パッケージはこのファイルの位置(ROOT.name)から独立 import
する(FxView は DLL を生成/load しない。ToolBox は offscreen Qt で生成し、Maya へは接続しない。
設定ファイルは一時領域のみ)。実 Maya での表示・保存復元の確認はチェックリスト側(これで合格扱いしない)。"""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(os.environ.get('PLS_TEST_SOURCE', str(Path(__file__).resolve().parents[1])))
PACKAGE = ROOT.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT/'scripts'/PACKAGE)]
sys.modules[PACKAGE] = pkg
i18n = importlib.import_module(PACKAGE+'.i18n')


class I18n(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("system")

    def test_explicit_ja_en(self):
        self.assertEqual(i18n.set_language("ja"), "ja")
        self.assertEqual(i18n.tr(u"Mask color"), u"マスク色")           # EN→JA 辞書
        self.assertEqual(i18n.tr(u"三分割"), u"三分割")                 # ja 表示では日本語原文のまま
        self.assertEqual(i18n.set_language("en"), "en")
        self.assertEqual(i18n.tr(u"三分割"), u"Thirds")                 # JA→EN 辞書
        self.assertEqual(i18n.tr(u"Mask color"), u"Mask color")         # en 表示では英語原文のまま

    def test_missing_key_falls_back_to_source(self):
        i18n.set_language("en")
        self.assertEqual(i18n.tr(u"辞書に無い文字列"), u"辞書に無い文字列")
        i18n.set_language("ja")
        self.assertEqual(i18n.tr(u"Unknown label"), u"Unknown label")
        self.assertIsNone(i18n.tr(None))
        self.assertEqual(i18n.tr(u""), u"")

    def test_identifiers_not_translated(self):
        u"""識別子は辞書に入れない契約の確認(入っていたらこの検査で気付く)。"""
        for word in (u"plsCamView", u"persp", u"camera1", u"C:/path/to/scene.ma"):
            for lang in ("ja", "en"):
                i18n.set_language(lang)
                self.assertEqual(i18n.tr(word), word)

    def test_system_resolution_is_ja_or_en(self):
        i18n.set_language("system")
        self.assertIn(i18n.resolved(), ("ja", "en"))
        self.assertEqual(i18n.current(), "system")

    def test_invalid_code_treated_as_system(self):
        i18n.set_language("fr")
        self.assertEqual(i18n.current(), "system")
        self.assertIn(i18n.resolved(), ("ja", "en"))


class SystemResolution(unittest.TestCase):
    u"""system 判定の期待分岐(継続63): Maya の uiLanguage が ja_* → ja、他 → en、
    未対応ロケールは en、取得失敗は QLocale fallback(ja/en のどちらか)。"""

    def setUp(self):
        self._cmds = i18n.cmds

    def tearDown(self):
        i18n.cmds = self._cmds
        i18n.set_language("system")

    def _resolved_with(self, tag):
        i18n.cmds = types.SimpleNamespace(about=lambda **kw: tag)
        i18n.set_language("system")
        return i18n.resolved()

    def test_ja_locale(self):
        self.assertEqual(self._resolved_with(u"ja_JP"), "ja")

    def test_en_locale(self):
        self.assertEqual(self._resolved_with(u"en_US"), "en")

    def test_unsupported_locale_falls_back_to_en(self):
        self.assertEqual(self._resolved_with(u"fr_FR"), "en")

    def test_query_failure_falls_back_to_qlocale(self):
        def boom(**kw):
            raise RuntimeError(u"query failed")
        i18n.cmds = types.SimpleNamespace(about=boom)
        i18n.set_language("system")
        self.assertIn(i18n.resolved(), ("ja", "en"))

    def test_explicit_choice_ignores_system_locale(self):
        i18n.cmds = types.SimpleNamespace(about=lambda **kw: u"ja_JP")
        i18n.set_language("en")
        self.assertEqual(i18n.resolved(), "en")


@unittest.skipUnless(PACKAGE == "plsFxView", u"FxView の attach 工程(Loading / 事前コンパイル)")
class AttachPhase(unittest.TestCase):
    u"""継続66: ToolBox を通らない起動時表示(__init__ / loading_overlay / fxprecompile)の限定検証。
    実パッケージの __init__.py を実行して import し(Maya なし・DLL 生成/load なし・接続なし)、
    言語復元のタイミング(_restore_language)と、tr を通すフォーマット文字列の引数整合を確認する。
    中止/失敗時の保全(中止→_precompile_abort→Loading 終了、失敗→接続しない)は tr が文字列生成のみで
    分岐を変えないことをコードで確認済み(ここでは表示文言だけを検査する)。"""

    #  attach 工程で tr(key).format(*args) される全フォーマット(原文キー, 引数例)
    FORMATS = (
        (u"準備が {:.0f} 秒で終わりませんでした。Script Editor のログを確認してください", (90.0,)),
        (u"シェーダーを準備しています {}/{}  {}", (1, 3, u"x.fx")),
        (u"mll {} で対応を確認できないフラグを除外しました: {}", (u"0.2.20", u"dof, taa")),
        (u"ロード済み mll {} / scripts {}: DLL を保持して起動します。"
         u"未対応の新機能は利用できません。配備版を確認してください。", (u"0.2.20", u"0.2.21")),
        (u"シェーダーキャッシュの確認に失敗したため接続しませんでした: {}", (u"err",)),
        (u".fx のコンパイルに失敗したため接続しませんでした: {}(詳細は Script Editor)", (u"a.fx",)),
        (u".fx のコンパイルに失敗したため接続していません: {}", (u"a.fx",)),
        (u"ビュー {} のライティングが '{}' のため、シーンに置いたライトは"
         u"反映されません。Lighting > Use All Lights にしてください。", (u"modelPanel4", u"default")),
        (u"取得した{}件の診断は Script Editor（件数・長さには上限あり）", (3,)),
        (u"既存のキャッシュファイルが空(または使えない形)のため、公開できません。削除・上書きはしていません: {}\n"
         u"このファイルを手で削除すると次回の起動で作り直します", (u"c.fxo",)),
    )

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            PACKAGE, str(ROOT / 'scripts' / PACKAGE / '__init__.py'),
            submodule_search_locations=[str(ROOT / 'scripts' / PACKAGE)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = mod        # stub を実パッケージへ置き換え(既ロードのサブモジュールは共有)
        spec.loader.exec_module(mod)      # __init__.py のトップレベル実行(Maya なしで落ちないことの検証)
        cls.pkg = mod
        cls.lo = importlib.import_module(PACKAGE + '.loading_overlay')
        cls.fxp = importlib.import_module(PACKAGE + '.fxprecompile')

    def tearDown(self):
        i18n.set_language("system")

    def test_init_module_loaded_without_maya(self):
        self.assertTrue(callable(self.pkg.attach))
        self.assertTrue(callable(self.pkg.show))
        self.assertTrue(callable(self.pkg._restore_language))
        self.assertTrue(callable(self.lo.begin) and callable(self.lo.end))
        self.assertTrue(hasattr(self.fxp.Job, "progress_text"))

    def test_restore_language_reads_saved_setting(self):
        u"""attach/show 入口の言語復元(継続66 修正): ToolBox 生成前でも保存済み言語で表示できる。"""
        st = importlib.import_module(PACKAGE + '.settings')
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "settings.json")
            with mock.patch.object(st, "config_path", return_value=path):
                data = st.load()
                data["language"] = "en"
                self.assertTrue(st.save(data))
                i18n.set_language("system")
                self.pkg._restore_language()
                self.assertEqual(i18n.current(), "en")
                self.assertEqual(i18n.tr(u"プラグインを読み込んでいます"), u"Loading the plug-in")

    def test_restore_language_failure_keeps_current(self):
        u"""settings が読めなくても attach を止めず、言語は現状維持。"""
        st = importlib.import_module(PACKAGE + '.settings')
        i18n.set_language("ja")
        with mock.patch.object(st, "load", side_effect=OSError(u"読めない")):
            self.pkg._restore_language()      # 例外を外へ出さない
        self.assertEqual(i18n.current(), "ja")

    def test_attach_message_formats_match_args(self):
        u"""辞書訳のプレースホルダが原文と同数・同型で、.format が両言語で例外なく埋まる。"""
        for key, args in self.FORMATS:
            i18n.set_language("ja")
            out_ja = i18n.tr(key).format(*args)
            i18n.set_language("en")
            out_en = i18n.tr(key).format(*args)
            self.assertNotEqual(out_ja, out_en, u"訳が効いていない: " + key[:40])
            for a in args:
                probe = u"{:.0f}".format(a) if isinstance(a, float) else u"{}".format(a)
                self.assertIn(probe, out_ja)
                self.assertIn(probe, out_en)


@unittest.skipUnless(PACKAGE == "plsCamView", u"CamView の show / ウィンドウ生成入口(v1.8.2)")
class ShowEntryLanguage(unittest.TestCase):
    u"""v1.8.2: 初回 show のプレースホルダ(「すべてのビューがポップアウト中です」等)に保存言語が
    反映されない 1.8.1 の問題の限定回帰。保存済み言語がウィンドウ生成(プレースホルダを作る
    ViewManager は ToolBox より前)より先に復元されることを、Maya なしで到達できる地点
    (「Maya 上でのみ動作します」の RuntimeError 直前)まで実行して確認する。
    実パッケージの __init__.py を spec から実行する(Maya/DLL/接続なし・一時 settings のみ)。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            PACKAGE, str(ROOT / 'scripts' / PACKAGE / '__init__.py'),
            submodule_search_locations=[str(ROOT / 'scripts' / PACKAGE)])
        mod = importlib.util.module_from_spec(spec)
        sys.modules[PACKAGE] = mod        # stub を実パッケージへ置き換え(サブモジュールは共有)
        spec.loader.exec_module(mod)
        cls.pkg = mod
        cls.ui = importlib.import_module(PACKAGE + '.ui')
        cls.st = importlib.import_module(PACKAGE + '.settings')

    def tearDown(self):
        i18n.set_language("system")

    def _with_saved_language(self, code):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        path = os.path.join(td.name, "settings.json")
        patcher = mock.patch.object(self.st, "config_path", return_value=path)
        patcher.start()
        self.addCleanup(patcher.stop)
        data = self.st.load()
        data["language"] = code
        self.assertTrue(self.st.save(data))

    def test_restore_language_reads_saved_setting(self):
        self._with_saved_language("en")
        i18n.set_language("system")
        self.pkg._restore_language()
        self.assertEqual(i18n.current(), "en")
        self.assertEqual(i18n.tr(u"すべてのビューがポップアウト中です"),
                         u"All views are popped out")

    def test_show_restores_language_before_window(self):
        u"""show() 入口: プレースホルダ生成より前(Maya なしでは RuntimeError より前)に復元される。
        例外文言自体が保存言語(英語)になることで、復元が表示に効いていることも確認する。"""
        self._with_saved_language("en")
        i18n.set_language("system")
        with self.assertRaises(RuntimeError) as cm:
            self.pkg.show()
        self.assertEqual(i18n.current(), "en")
        self.assertEqual(u"{}".format(cm.exception), u"plsCamView only runs inside Maya.")

    def test_window_init_restores_language(self):
        u"""restart() / 直接生成の経路: PlsCamViewWindow.__init__ が ViewManager より前に復元する。"""
        self._with_saved_language("ja")
        i18n.set_language("en")
        with self.assertRaises(RuntimeError):
            self.ui.PlsCamViewWindow()
        self.assertEqual(i18n.current(), "ja")

    def test_restore_failure_keeps_current(self):
        u"""settings が読めなくても show を止めず、言語は現状維持。"""
        i18n.set_language("ja")
        with mock.patch.object(self.st, "load", side_effect=OSError(u"読めない")):
            self.pkg._restore_language()
        self.assertEqual(i18n.current(), "ja")


class ToolBoxLanguage(unittest.TestCase):
    u"""実 UI(ToolBox を offscreen Qt で生成)への適用と、language 保存・既存設定の保全。
    Maya なし(cmds=None)。実 Maya での見た目はチェックリスト側。"""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt = importlib.import_module(PACKAGE+'.qt')
        cls.QW = qt.QtWidgets
        cls.app = cls.QW.QApplication.instance() or cls.QW.QApplication([])
        cls.ui = importlib.import_module(PACKAGE+'.ui')

    def tearDown(self):
        i18n.set_language("system")
        self.app.processEvents()

    def _toolbox(self, language):
        owner = types.SimpleNamespace()
        owner.data = {"language": language, "camera": "persp", "mp4Crf": 18,
                      "guideWidth": 1.0, "showPreset": "all"}
        owner.saves = 0

        def _save():
            owner.saves += 1
        owner.save_settings = _save
        owner.views = None
        owner.refresh_cameras = lambda *a, **k: None
        tb = self.ui.ToolBox(owner)
        self.addCleanup(tb.deleteLater)
        return owner, tb

    def test_ja_applied_to_widgets(self):
        _, tb = self._toolbox("ja")
        self.assertEqual(tb.shadowChk.text(), u"シャドウ")            # EN ソース → JA
        self.assertEqual(tb.pbBtn.text(), u"Playblast 実行")          # JA ソースはそのまま
        self.assertEqual(tb.mp4Output.placeholderText(), u"自動")

    def test_en_applied_to_widgets(self):
        _, tb = self._toolbox("en")
        self.assertEqual(tb.shadowChk.text(), u"Shadows")
        self.assertEqual(tb.startupCamChk.text(), u"Startup cameras")  # JA ソース → EN
        self.assertEqual(tb.pbBtn.text(), u"Run Playblast")
        self.assertEqual(tb.mp4Output.placeholderText(), u"Auto")
        self.assertEqual(tb.mp4OpenAfter.text(), u"Open when done")

    def test_summary_and_setting_labels_ja(self):
        u"""継続65 監督指摘: 折り畳み要約と設定ラベル(Force/From Render)も翻訳される。
        数値・px は原表記、Maya 標準項目との対応(原名)は tooltip に保持。"""
        _, tb = self._toolbox("ja")
        self.assertEqual(tb.forceChk.text(), u"Playblast 対象を固定")
        self.assertIn(u"Force Playblast Target", tb.forceChk.toolTip())
        self.assertEqual(tb.mp4FromRender.text(), u"レンダー設定の解像度")
        self.assertIn(u"From Render Settings", tb.mp4FromRender.toolTip())
        tb._update_gate_summaries()
        self.assertTrue(tb.gateMaskSec._summary.text().startswith(u"マスク "),
                        u"ゲート要約が和訳されていない: " + tb.gateMaskSec._summary.text())
        self.assertIn(u"px", tb.gateMaskSec._summary.text())      # 単位は原表記
        self.assertEqual(tb.innerGatesSec._summary.text(), u"オフ")
        self.assertEqual(tb.guidesSec._summary.text(), u"オフ")

    def test_summary_and_setting_labels_en(self):
        _, tb = self._toolbox("en")
        self.assertEqual(tb.forceChk.text(), u"Force Playblast Target")
        self.assertEqual(tb.mp4FromRender.text(), u"From Render Settings")
        tb._update_gate_summaries()
        self.assertTrue(tb.gateMaskSec._summary.text().startswith(u"mask "))
        self.assertEqual(tb.innerGatesSec._summary.text(), u"off")
        self.assertEqual(tb.guidesSec._summary.text(), u"off")

    def test_language_change_saves_and_keeps_other_settings(self):
        owner, tb = self._toolbox("ja")
        before = {k: v for k, v in owner.data.items() if k != "language"}
        idx = tb.languageCombo.findData("en")
        self.assertGreaterEqual(idx, 0)
        tb.languageCombo.setCurrentIndex(idx)          # _on_language を発火
        self.assertEqual(owner.data["language"], "en")
        self.assertGreaterEqual(owner.saves, 1)
        self.assertEqual(i18n.current(), "en")
        self.assertFalse(tb._languageNote.isHidden(),
                         u"「次に開いたときに適用」の案内が出ていない")
        after = {k: v for k, v in owner.data.items() if k != "language"}
        self.assertEqual(before, after, u"language 以外の設定が変わった")

    def test_language_roundtrip_via_settings_file(self):
        u"""settings.save/load 経由の保存・復元(一時領域のみ)。他キーも保全される。"""
        st = importlib.import_module(PACKAGE+'.settings')
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "settings.json")
            with mock.patch.object(st, "config_path", return_value=path):
                data = st.load()
                self.assertEqual(data.get("language"), "system")   # 既定値
                data["language"] = "en"
                data["camera"] = u"|ns:camA"
                self.assertTrue(st.save(data))
                loaded = st.load()
                self.assertEqual(loaded.get("language"), "en")
                self.assertEqual(loaded.get("camera"), u"|ns:camA")
                raw = json.loads(Path(path).read_text(encoding="utf-8"))
                self.assertEqual(raw.get("language"), "en")


if __name__ == "__main__":
    unittest.main(verbosity=2)
