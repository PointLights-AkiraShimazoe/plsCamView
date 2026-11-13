# -*- coding: utf-8 -*-
u"""FX-INPUT-FIT-20261031-01: 数値入力欄が「最悪値の表示」を欠けずに表示でき、編集後の値も正しいことの offscreen Qt 検証。
(plsCamView / plsFxView 共通のファイル。パッケージ名はフォルダから判定する)

判定は見かけの余白ではなく、実際の文字領域で行う:
  ・SE_LineEditContents(QSS の border / padding を引いた入力部の文字領域)≥ 最悪値の文字幅 + 2px
  ・Qt に依らない厳密値 = 欄の幅 - 2×(border + padding) - 最悪値の文字幅 ≥ 2px
  ・実描画(欄を grab した画像)で、文字のインク範囲が枠の内側に完全に収まり、文字幅分だけ描かれている
最悪値 = 最小値 / 最大値の表示(接頭辞・接尾辞つき)の数字を、そのフォントで最も幅の広い数字に置き換えたもの(負号は最小値が負のときだけ)。
Qt 6.8 / 6.12 の両方で実行すること(6.12 は NoButtons + QSS で入力部が 1px に潰れる既知問題の再発検知を含む)。
実 Maya / 実 Windows フォント(Segoe UI)の表示確認は含まない。"""
import importlib
import os
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(os.environ.get('PLS_TEST_SOURCE', str(Path(__file__).resolve().parents[1])))
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _qt_font_env   # noqa: E402
_qt_font_env.prepare()
PACKAGE = 'plsCamView' if (ROOT / 'scripts' / 'plsCamView').is_dir() else 'plsFxView'
SCALES = (75, 85, 100, 115, 125)
WIDTHS = (333, 300, 280, 270)


class InputFit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.qt = importlib.import_module(PACKAGE + '.qt')
        cls.QW, cls.QC, cls.QG = cls.qt.QtWidgets, cls.qt.QtCore, cls.qt.QtGui
        cls.app = cls.QW.QApplication.instance() or cls.QW.QApplication([])
        cls.font_env = _qt_font_env.load_and_verify(cls.qt.QtGui, cls.QW)
        cls.style = importlib.import_module(PACKAGE + '.style')
        cls.ui = importlib.import_module(PACKAGE + '.ui')
        cls.i18n = importlib.import_module(PACKAGE + '.i18n')

    def tearDown(self):
        self.style.set_ui_scale(self.style.UI_SCALE_DEFAULT)
        self.i18n.set_language("system")
        self.app.processEvents()

    def toolbox(self, scale=85, lang="en", width=333):
        self.style.set_ui_scale(scale)
        self.i18n.set_language(lang)
        owner = types.SimpleNamespace(data={"language": lang, "camera": "persp", "uiScale": scale}, saves=0)
        owner.save_settings = lambda: None
        owner.views = None
        owner.refresh_cameras = lambda *a, **k: None
        owner.apply_gate = lambda *a, **k: None
        tb = self.ui.ToolBox(owner)
        self.addCleanup(tb.deleteLater)
        tb.resize(width, 1500)
        tb.show()
        # Gate 系の欄は gate / inner gate が OFF だと親ごと無効(灰色)。実際に編集できる状態(ON)で検証する
        # (OFF のまま setEnabled(True) すると 1 打鍵ごとの _update_gate_enabled が無効化し直して打鍵が途切れる=試験側の問題)
        tb.gateChk.setChecked(True)
        for chk in tb.innerGateEnabled:
            chk.setChecked(True)
        for s in tb.findChildren(self.style.CollapsibleSection):
            s.setCollapsed(False)
        for c in tb.findChildren(self.style.CollapsibleCard):
            c.setCollapsed(False)
        for _ in range(4):
            self.app.processEvents()
        return owner, tb

    @staticmethod
    def enable_chain(sb, top):
        u"""欄とその祖先を有効にする(親の行ごと灰色の欄は、描画の文字色が変わって比較にならないため)。"""
        w = sb
        while w is not None and w is not top:
            w.setEnabled(True)
            w = w.parentWidget()

    def spins(self, tb):
        return [sb for sb in tb.findChildren(self.QW.QAbstractSpinBox) if sb.isVisibleTo(tb)]

    @staticmethod
    def put_worst(sb):
        u"""最大桁数の表示になる端の値を入れる(シグナルは出さない)。"""
        best = max((sb.minimum(), sb.maximum()), key=lambda v: len(sb.textFromValue(v)))
        sb.blockSignals(True)
        sb.setValue(best)
        sb.blockSignals(False)
        return sb.text()

    def widest_text_width(self, sb):
        u"""最悪値の文字幅(全ての数字を最も幅の広い数字に置換。負号は最小値が負のときだけ)。"""
        fm = sb.lineEdit().fontMetrics()
        wid = max(u"0123456789", key=lambda d: fm.horizontalAdvance(d))
        best = 0
        for v in (sb.minimum(), sb.maximum()):
            t = u"".join(wid if c in u"0123456789" else c for c in sb.textFromValue(v))
            best = max(best, fm.horizontalAdvance(sb.prefix() + t + sb.suffix()))
        return best

    def real_text_area(self, sb):
        le = sb.lineEdit()
        opt = self.QW.QStyleOptionFrame()
        le.initStyleOption(opt)
        cr = le.style().subElementRect(self.QW.QStyle.SE_LineEditContents, opt, le)
        tm = le.textMargins()
        return cr.width() - tm.left() - tm.right()

    # ------------------------------------------------------------------ 構成
    def test_every_number_field_is_a_fit_field_without_buttons(self):
        u"""全ての数値欄が FitSpinBox / FitDoubleSpinBox で NoButtons(QSS が上下ボタンの幅を 0 にするため)。"""
        _, tb = self.toolbox()
        sbs = tb.findChildren(self.QW.QAbstractSpinBox)
        self.assertGreater(len(sbs), 10)
        for sb in sbs:
            self.assertIsInstance(sb, (self.style.FitSpinBox, self.style.FitDoubleSpinBox), sb.objectName())
            self.assertEqual(sb.buttonSymbols(), self.QW.QAbstractSpinBox.NoButtons)
        self.assertIn("::up-button", self.style.stylesheet())

    def test_worst_text_uses_widest_digit_and_sign_only_when_negative(self):
        sb = self.style.FitDoubleSpinBox()
        sb.setDecimals(1); sb.setRange(1.0, 100.0); sb.setSuffix(u" %")
        t = sb.worstText()
        self.assertEqual(len(t), len(u"100.0 %"))
        self.assertTrue(t.endswith(u" %"))
        self.assertNotIn(u"-", t)
        neg = self.style.FitDoubleSpinBox()
        neg.setDecimals(2); neg.setRange(-5.0, 5.0)
        self.assertTrue(neg.worstText().startswith(u"-"))
        self.assertEqual(len(neg.worstText()), len(u"-5.00"))
        pos = self.style.FitSpinBox()
        pos.setRange(-99999, 99999)
        self.assertEqual(len(pos.worstText()), len(u"-99999"))

    # ------------------------------------------------------------------ 実際の文字領域
    def _check_matrix(self, scales, langs, widths):
        for sc in scales:
            for lang in langs:
                for wd in widths:
                    _, tb = self.toolbox(sc, lang, wd)
                    for sb in self.spins(tb):
                        need = self.widest_text_width(sb)
                        le = sb.lineEdit()
                        label = (sc, lang, wd, type(sb).__name__, sb.suffix(), (sb.minimum(), sb.maximum()), sb.width())
                        # (1) 入力部が潰れていない(Qt 6.12 の 1px 問題の再発検知)
                        self.assertGreaterEqual(le.width(), need, label + ("入力部が最悪値より狭い le", le.width(), "need", need))
                        # (2) 実際の文字領域(QSS の border / padding を引いた領域)が最悪値 + 2px 以上
                        self.assertGreaterEqual(self.real_text_area(sb), need + 2, label + ("文字領域", self.real_text_area(sb), "need", need))
                        # (3) Qt の版に依らない厳密値(幅 - 左右の border/padding)
                        hp = getattr(sb, "_fit_hpad", 8)
                        strict = sb.width() - 2 * (self.style.px(1) + self.style.px(hp)) - need
                        self.assertGreaterEqual(strict, 2, label + ("厳密余裕", strict))
                    self.addCleanup(lambda: None)
                    tb.deleteLater()
                    self.app.processEvents()

    def test_worst_value_fits_real_text_area_default(self):
        u"""既定 85% × 日英 × 標準 333px / 狭い 280px。"""
        self._check_matrix((85,), ("ja", "en"), (333, 280))

    def test_worst_value_fits_real_text_area_all_scales_and_narrow(self):
        u"""全倍率(75〜125%)× 日英 × 333 / 300 / 270px。"""
        self._check_matrix(SCALES, ("ja", "en"), (333, 270))

    # ------------------------------------------------------------------ 実描画
    def _ink_span(self, sb, tb):
        sb.lineEdit().deselect()                      # 選択ハイライトの背景は文字との差を潰すので外す
        sb.clearFocus()
        # 欄の背景は半透明(親カードの色に重なる)ので、欄単体ではなく親(スクロール本体)から欄の矩形を実描画する
        body = tb._scroll.widget()
        rect = self.QC.QRect(sb.mapTo(body, self.QC.QPoint(0, 0)), sb.size())
        img = body.grab(rect).toImage().convertToFormat(self.QG.QImage.Format_RGB32)
        w, h = img.width(), img.height()
        bt = self.style.px(1) + 1                      # border の内側から数える
        bg = img.pixelColor(bt + 1, bt + 2)
        cols = []
        for x in range(bt, w - bt):
            for y in range(bt + 2, h - bt - 2):
                c = img.pixelColor(x, y)
                if abs(c.red() - bg.red()) + abs(c.green() - bg.green()) + abs(c.blue() - bg.blue()) > 60:
                    cols.append(x)
                    break
        return (min(cols), max(cols)) if cols else None, w, bt

    def test_rendered_worst_text_is_fully_drawn_inside_the_frame(self):
        u"""実描画: 最悪値の表示を入れた欄を grab し、文字のインクが枠の内側に収まり、文字幅分が描かれている(欠けていない)。"""
        for sc, lang, wd in ((85, "en", 333), (85, "ja", 280), (75, "en", 333), (125, "en", 333)):
            _, tb = self.toolbox(sc, lang, wd)
            for sb in self.spins(tb):
                self.enable_chain(sb, tb)
                text = self.put_worst(sb)
                self.app.processEvents()
                span, w, bt = self._ink_span(sb, tb)
                label = (sc, lang, wd, type(sb).__name__, text, sb.width())
                self.assertIsNotNone(span, label + ("何も描かれていない",))
                fm = sb.lineEdit().fontMetrics()
                tight = fm.tightBoundingRect(text).width()
                ink = span[1] - span[0] + 1
                self.assertGreaterEqual(ink, tight - 2, label + ("文字が欠けている ink", ink, "tight", tight))
                self.assertGreater(span[0], bt, label + ("左の枠に接している",))
                self.assertLess(span[1], w - bt, label + ("右の枠に接している",))

    # ------------------------------------------------------------------ 編集後の値
    @staticmethod
    def _qtest():
        try:
            from PySide6 import QtTest
        except ImportError:                         # pragma: no cover
            from PySide2 import QtTest
        return QtTest.QTest

    def _type(self, sb, text):
        u"""実際のキー入力で編集する(全選択 → 打鍵 → Enter で確定)。"""
        QTest = self._qtest()
        le = sb.lineEdit()
        sb.setFocus()
        le.selectAll()
        QTest.keyClicks(le, text)
        QTest.keyClick(le, self.QC.Qt.Key_Return)
        self.app.processEvents()

    def test_inner_gate_percent_editing_roundtrip(self):
        u"""Inner gates の割合: 入力 → 値 → 表示(末尾の %% を含む)→ 取り込み先(owner.data)まで。最大桁・小数・範囲外。"""
        for sc, lang, wd in ((85, "en", 333), (85, "ja", 280), (125, "en", 333)):
            owner, tb = self.toolbox(sc, lang, wd)
            for k, row in enumerate(tb.innerGatePercent):
                sb = row.field
                self.assertTrue(sb.isEnabled(), "Gate ON なら割合欄は編集可能")
                for typed, want, shown in (("100", 100.0, u"100.0 %"), ("33.3", 33.3, u"33.3 %"), ("1", 1.0, u"1.0 %"),
                                           ("66.67", 66.6, u"66.6 %")):
                    self._type(sb, typed)
                    label = (sc, lang, wd, k, typed)
                    self.assertAlmostEqual(sb.value(), want, places=3, msg=label)
                    self.assertEqual(sb.text(), shown, label)
                    self.assertAlmostEqual(row.value(), want, places=3, msg=label)
                    self.assertAlmostEqual(row.slider.value() / float(row._steps), (want - 1.0) / 99.0, places=2, msg=label)
                    self.assertAlmostEqual(owner.data["innerGatePercent"][k], want, places=3, msg=label)
                    # 表示そのものが文字領域に収まっている(末尾の % まで)
                    fm = sb.lineEdit().fontMetrics()
                    self.assertLessEqual(fm.horizontalAdvance(sb.text()), self.real_text_area(sb) - 2, label)
                # 範囲外は受け付けない(値は範囲内のまま)
                self._type(sb, "150")
                self.assertTrue(1.0 <= sb.value() <= 100.0, (sc, lang, wd, k, sb.value()))
                self._type(sb, "0")
                self.assertTrue(1.0 <= sb.value() <= 100.0, (sc, lang, wd, k, sb.value()))

    def test_negative_and_decimal_fields_edit_and_show_fully(self):
        u"""負号・小数・最大桁の欄(範囲に負を含む欄があれば全て)を実キー入力で編集し、確定後の表示が文字領域に収まる。"""
        for sc, lang, wd in ((85, "en", 333), (85, "ja", 280)):
            _, tb = self.toolbox(sc, lang, wd)
            n_neg = 0
            for sb in self.spins(tb):
                self.enable_chain(sb, tb)
                # 確定(Enter)まで valueChanged を出さない: 打鍵の途中でハンドラが欄を無効化し直す機能(SSAO など)の影響を受けないため
                sb.setKeyboardTracking(False)
                dec = getattr(sb, "decimals", lambda: 0)()
                hi, lo = sb.maximum(), sb.minimum()
                cases = [hi, lo]
                if lo < 0 < hi:
                    cases.append(lo / 3.0 if dec else int(lo / 3))
                for v in cases:
                    self.enable_chain(sb, tb)               # 直前の確定で SSAO などのハンドラが欄を無効化し直すことがある
                    txt = (u"{:.%df}" % dec).format(v) if dec else u"%d" % int(v)
                    self._type(sb, txt)
                    label = (sc, lang, wd, type(sb).__name__, sb.suffix(), (lo, hi), txt)
                    self.assertAlmostEqual(sb.value(), float(round(v, dec)), places=max(dec, 1), msg=label)
                    fm = sb.lineEdit().fontMetrics()
                    self.assertLessEqual(fm.horizontalAdvance(sb.text()), self.real_text_area(sb) - 2, label)
                    if v < 0:
                        n_neg += 1
                        self.assertTrue(sb.text().lstrip().startswith(u"-"), label)
            if PACKAGE == 'plsFxView':
                self.assertGreater(n_neg, 0, "Fx には負の範囲の欄がある(試験が負号を実際に通っている)")

    # ------------------------------------------------------------------ 現行幅の保全 / 隣を潰さない
    def test_fields_that_already_fit_keep_their_current_width(self):
        u"""根拠なしの一律拡大をしない: 足りている欄は現行(floor)の幅のまま。足りない欄だけ広がる。"""
        _, tb = self.toolbox(85, "en", 333)
        px = self.style.px
        grown, kept = [], []
        for sb in self.spins(tb):
            if not sb._fit_floor:
                continue
            fit = sb.fitWidth()
            if sb.sizePolicy().horizontalPolicy() == self.QW.QSizePolicy.Fixed:
                self.assertEqual(sb.width(), max(sb._fit_floor, fit), (sb.suffix(), sb.minimum(), sb.maximum()))
            (grown if fit > sb._fit_floor else kept).append((sb.suffix(), sb.minimum(), sb.maximum(), sb._fit_floor, fit))
        self.assertTrue(any(s == u" %" for s, *_ in grown), u"割合欄(末尾の単位)は現行幅では足りず広がる: {!r}".format(grown))
        self.assertGreater(len(kept), 3, u"足りている欄は広げない: {!r}".format(kept))
        # 代表: Mask opacity(0.00)は現行の幅 px(64) のまま
        self.assertEqual(tb.gateMaskOpacity.field.width(), px(64))

    def test_neighbors_are_not_crushed_at_narrow_docks(self):
        u"""狭いドックでも、どの部品も最小サイズより潰されない(足りなければ横スクロールへ逃げる)。数値欄の余裕も保たれる。"""
        for sc, lang in ((85, "en"), (85, "ja"), (125, "en"), (75, "en")):
            for wd in WIDTHS:
                _, tb = self.toolbox(sc, lang, wd)
                body = tb._scroll.widget()
                need = body.minimumSizeHint().width()
                self.assertGreaterEqual(body.width(), need, (sc, lang, wd, "本体が最小幅を割っている"))
                if need > tb._scroll.viewport().width():
                    self.assertGreater(tb._scroll.horizontalScrollBar().maximum(), 0, (sc, lang, wd, "届かない"))
                # 数値欄と同じ行にいる操作部品(ラベル以外)が、自身の最小サイズより潰されていない
                seen = set()
                for sb in self.spins(tb):
                    par = sb.parentWidget()
                    if par is None or id(par) in seen:
                        continue
                    seen.add(id(par))
                    for w in par.findChildren(self.QW.QWidget, options=self.QC.Qt.FindDirectChildrenOnly):
                        if not w.isVisibleTo(tb) or isinstance(w, (self.QW.QLabel, self.QW.QLineEdit)):
                            continue
                        mh = w.minimumSizeHint()
                        # 明示の最小幅があればそれ、無ければ minimumSizeHint(IconToggle は現行 p3 から 20px 指定 / hint 21)
                        mn = w.minimumWidth() or (mh.width() if mh.isValid() else 0)
                        self.assertGreaterEqual(w.width(), mn, (sc, lang, wd, type(w).__name__, w.objectName(), w.width(), mn))
                for sb in self.spins(tb):
                    self.assertGreaterEqual(self.real_text_area(sb), self.widest_text_width(sb) + 2, (sc, lang, wd, "狭幅で数値欄が潰れた", sb.width()))

    def test_content_min_width_stays_within_headroom_and_is_reported(self):
        u"""対応最小幅(横スクロール無しで収まる幅)= body.minimumSizeHint。既存の余裕 308px(85%)を超えない。"""
        for lang in ("ja", "en"):
            _, tb = self.toolbox(85, lang, 333)
            need = tb._scroll.widget().minimumSizeHint().width()
            self.assertLessEqual(need, 308, (lang, need))
            self.assertEqual(tb._scroll.horizontalScrollBar().maximum(), 0)


if __name__ == '__main__':
    unittest.main()
