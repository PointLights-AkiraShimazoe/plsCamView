# -*- coding: utf-8 -*-
u"""Language 行の移動(0.9.1): レイアウト切替アイコンと同じ行の右端に Language コンボを置き、
旧下部 Language 行を除去した配置の offscreen Qt 検証。縦ドック(最小幅 300 / 360 / 520)と
上下ドック(コンパクト 2x2)で、収まり・右端・同一行・非重なり・適用案内(2 行目)・保存と
復元(System/日本語/English)を確認する。実 Maya での見た目はチェックリスト側(これで合格扱いしない)。"""
import importlib
import os
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(os.environ.get('PLS_TEST_SOURCE', str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _qt_font_env   # noqa: E402  実フォント読込(Windows offscreen はフォント DB が空になるため)
_qt_font_env.prepare()
PACKAGE = 'plsCamView'
i18n = importlib.import_module(PACKAGE + '.i18n')


class LanguageRow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt = importlib.import_module(PACKAGE + '.qt')
        cls.QW = qt.QtWidgets
        cls.QC = qt.QtCore
        cls.app = cls.QW.QApplication.instance() or cls.QW.QApplication([])
        # 文字幅に依存する試験なので、フォントが解決できない環境は失敗扱い(skip にしない)
        cls.font_env = _qt_font_env.load_and_verify(qt.QtGui, cls.QW)
        cls.ui = importlib.import_module(PACKAGE + '.ui')

    def tearDown(self):
        i18n.set_language("system")
        self.app.processEvents()

    def _toolbox(self, language="system"):
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

    def _rects(self, tb):
        u"""スクロール中身(body)座標で測る。body は全カード最小幅まで広がるため、
        ビューポートより広いことがある(1.8.x からの既存挙動。狭幅では全カードが同様に切れる)。"""
        body = tb._scroll.widget()
        combo = tb.languageCombo
        dock = tb.dockPicker
        cl = combo.mapTo(body, combo.rect().topLeft())
        cr = combo.mapTo(body, combo.rect().bottomRight())
        dl = dock.mapTo(body, dock.rect().topLeft())
        dr = dock.mapTo(body, dock.rect().bottomRight())
        return (body, cl, cr, dl, dr)

    def _vp_rect(self, tb, w):
        u"""ウィジェットの矩形をスクロールのビューポート座標で返す(実際に見える位置)。"""
        vp = tb._scroll.viewport()
        tl = w.mapTo(vp, w.rect().topLeft())
        return self.QC.QRect(tl, w.size())

    def test_vertical_widths(self):
        u"""縦ドック 300 / 333 / 360 / 520 px(既定 UI 倍率・日英・System)の実測:
        - 横スクロール無しで、レイアウトアイコン 4 つ・⚙・Language がビューポート内に完全に見える
        - それぞれが重ならず同じ行にある
        - Language は行の右端に寄っている(右余白はカードの外枠ぶんだけ)
        - Language の文字は最長項目でも欠けず、矢印の領域と重ならない / ⚙ の文字とアイコンも枠内
        (旧版の「最上段の最小幅 ≤ 他カードの最大」という相対基準は、他カードを詰めると無関係に落ちるため廃止)"""
        style = importlib.import_module(PACKAGE + '.style')
        for language in ("ja", "en", "system"):
            for width in (300, 333, 360, 520):
                owner, tb = self._toolbox(language)
                tb.resize(width, 700)
                tb.show()
                self.app.processEvents()
                tag = u"{} width={}".format(language, width)
                vp = tb._scroll.viewport()
                self.assertEqual(tb._scroll.horizontalScrollBar().maximum(), 0, u"横スクロールが出る " + tag)
                items = [(u"dock{}".format(k), b) for k, b in enumerate(tb.dockPicker._order)]
                items += [(u"gear", tb.scaleBtn), (u"language", tb.languageCombo)]
                rects = {}
                for name, w in items:
                    self.assertTrue(w.isVisible(), name + u" " + tag)
                    r = self._vp_rect(tb, w)
                    rects[name] = r
                    self.assertGreaterEqual(r.left(), 0, name + u" 左が欠ける " + tag)
                    self.assertLessEqual(r.right(), vp.width() - 1, name + u" 右が欠ける " + tag)
                    self.assertGreaterEqual(r.top(), 0, name + u" 上が欠ける " + tag)
                names = [n for n, _ in items]
                for a in range(len(names)):
                    for b in range(a + 1, len(names)):
                        self.assertFalse(rects[names[a]].intersects(rects[names[b]]),
                                         u"{} と {} が重なる {}".format(names[a], names[b], tag))
                lang, gear, dock_last = rects["language"], rects["gear"], rects["dock3"]
                # 左から [アイコン 4 つ] … [⚙][Language] の順で同じ行
                self.assertLess(dock_last.right(), gear.left(), tag)
                self.assertLess(gear.right(), lang.left(), tag)
                for r in (gear, dock_last):
                    self.assertTrue(r.top() <= lang.center().y() <= r.bottom(), u"同じ行に無い " + tag)
                # 右寄せ: ビューポート右端との余白は本文の外枠(px(8))+ 誤差の範囲
                gap = vp.width() - 1 - lang.right()
                self.assertGreaterEqual(gap, 0, tag)
                self.assertLessEqual(gap, style.px(8) + 3, u"右端に寄っていない gap={} {}".format(gap, tag))
                # 文字: 最長項目 + 矢印(ComboBox は右端 px(18) 前後に矢印を描く)が収まる
                combo = tb.languageCombo
                fm = combo.fontMetrics()
                widest = max(fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count()))
                self.assertGreaterEqual(combo.width() - widest, style.px(24),
                                        u"最長項目と矢印が重なる/欠ける {}".format(tag))
                self.assertEqual(fm.elidedText(combo.currentText(), self.QC.Qt.ElideRight,
                                               combo.width() - style.px(24)), combo.currentText(), tag)
                # ⚙ の文字・アイコンが枠内
                gfm = tb.scaleBtn.fontMetrics()
                self.assertLessEqual(gfm.horizontalAdvance(tb.scaleBtn.text()), tb.scaleBtn.width() - 4, tag)
                for _, bt in items[:4]:
                    self.assertLessEqual(bt.iconSize().width(), bt.width(), tag)
                    self.assertLessEqual(bt.iconSize().height(), bt.height(), tag)
                # 旧下部行は無い: コンボは最上部カード(_topRow)の中
                w = combo.parentWidget()
                while w is not None and w is not tb._topRow:
                    w = w.parentWidget()
                self.assertIs(w, tb._topRow, tag)
                tb.deleteLater(); self.app.processEvents()

    def test_horizontal_compact(self):
        u"""上下ドック(2x2 アイコン): 行内に収まり、アイコンと重ならない。"""
        owner, tb = self._toolbox()
        tb.resize(900, 260)
        tb.show()
        tb.set_orientation(True)
        self.app.processEvents()
        body, cl, cr, dl, dr = self._rects(tb)
        self.assertTrue(tb.languageCombo.isVisible())
        self.assertGreater(cl.x(), dr.x(), u"2x2 アイコンと重なる")
        row = tb._topRow
        rl = row.mapTo(body, row.rect().topLeft())
        rr = row.mapTo(body, row.rect().bottomRight())
        self.assertGreaterEqual(cl.y() + 1, rl.y())
        self.assertLessEqual(cr.y() - 1, rr.y())
        self.assertLessEqual(cr.x(), rr.x() + 1)

    def test_note_second_line_and_save(self):
        u"""適用案内は選択後に 2 行目へ出る。保存(owner.data)と翻訳適用は従来仕様のまま。"""
        owner, tb = self._toolbox()
        tb.resize(300, 700)
        tb.show()
        self.app.processEvents()
        self.assertTrue(tb._languageNote.isHidden())
        idx = tb.languageCombo.findData("en")
        self.assertGreaterEqual(idx, 0)
        tb.languageCombo.setCurrentIndex(idx)
        self.app.processEvents()
        self.assertFalse(tb._languageNote.isHidden())
        self.assertEqual(owner.data.get("language"), "en")
        self.assertGreaterEqual(owner.saves, 1)
        self.assertEqual(i18n.current(), "en")
        body, cl, cr, dl, dr = self._rects(tb)
        nl = tb._languageNote.mapTo(body, tb._languageNote.rect().topLeft())
        nr = tb._languageNote.mapTo(body, tb._languageNote.rect().bottomRight())
        self.assertGreaterEqual(nl.y(), cr.y() - 2, u"案内が行の下に無い")
        self.assertLessEqual(nr.x(), body.width(), u"案内が行からはみ出す")

    def test_restore_saved_language(self):
        u"""保存済み language がコンボへ復元される。"""
        owner, tb = self._toolbox("en")
        tb.resize(360, 700)
        tb.show()
        self.app.processEvents()
        self.assertEqual(tb.languageCombo.currentData(), "en")


if __name__ == '__main__':
    unittest.main(verbosity=1)
