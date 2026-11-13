# -*- coding: utf-8 -*-
"""FX-WHEEL-GUARD(候補 g1): 数値欄・スライダ・プルダウンは、フォーカスがあるときだけホイールで値が変わる。
フォーカスが無いときのホイールはパネル(QScrollArea)のスクロールになる。offscreen Qt(実 Maya ではない)。
使い方: PKG_DIR=<scripts/plsCamView|plsFxView> python3 test_wheel_guard.py   旧では値が変わる試験が落ちる。
"""
import importlib
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
QtCore, QtGui, QW = qt.QtCore, qt.QtGui, qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])


def wheel(w, dy=-120):
    pos = QtCore.QPointF(w.width() / 2.0, w.height() / 2.0)
    gpos = QtCore.QPointF(w.mapToGlobal(pos.toPoint()))
    e = QtGui.QWheelEvent(pos, gpos, QtCore.QPoint(0, 0), QtCore.QPoint(0, dy), QtCore.Qt.NoButton,
                          QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
    QW.QApplication.sendEvent(w, e)
    app.processEvents()
    return e


class WheelGuard(unittest.TestCase):
    def toolbox(self):
        o = types.SimpleNamespace(data={"language": "system", "camera": "persp"}, save_settings=lambda: None, views=None,
                                  refresh_cameras=lambda *a, **k: None, apply_effects=lambda *a, **k: None,
                                  fit_toolbox_height=lambda: None)
        tb = ui.ToolBox(o)
        o.tb = tb
        self.addCleanup(tb.deleteLater)
        tb.pull(dict(settings.DEFAULTS, **o.data))
        tb.resize(333, 300)                                   # 中身より低くしてスクロールが出るようにする
        tb.show()
        app.processEvents()
        return tb

    def test_focus_policy_is_strong_not_wheel(self):
        for cls in (style.FitSpinBox, style.FitDoubleSpinBox, style.ComboBox, style.Slider):
            w = cls()
            self.assertEqual(w.focusPolicy(), QtCore.Qt.StrongFocus, cls.__name__)
            w.deleteLater()

    def test_unfocused_widgets_do_not_change_on_wheel(self):
        tb = self.toolbox()
        rows = tb.findChildren(ui.SliderRow)
        self.assertTrue(rows, "SliderRow がある")
        for r in rows[:6]:
            self.assertIsInstance(r.slider, style.Slider)
            r.setValue((r._min + r._max) / 2.0)
            before = r.value()
            e1 = wheel(r.slider)
            e2 = wheel(r.field)
            self.assertEqual(r.value(), before, r.label.text())
            self.assertFalse(e1.isAccepted() and r.slider.hasFocus())
        for c in tb.findChildren(style.ComboBox):
            if type(c).__name__ == "CameraCombo" or c.count() < 2:
                continue                                       # カメラ切替は従来どおりホイールで実カメラを送る(n2)
            c.setCurrentIndex(0)
            wheel(c)
            self.assertEqual(c.currentIndex(), 0, c.objectName())

    def test_focused_widget_still_changes_on_wheel(self):
        w = style.Slider(QtCore.Qt.Horizontal)
        self.addCleanup(w.deleteLater)
        w.setRange(0, 100)
        w.setValue(50)
        w.hasFocus = lambda: True                              # offscreen ではフォーカスの付与が不安定なので代用
        QW.QApplication.sendEvent(w, QtGui.QFocusEvent(QtCore.QEvent.FocusIn, QtCore.Qt.MouseFocusReason))
        wheel(w)
        self.assertNotEqual(w.value(), 50)

    def test_auto_focus_on_window_activation_does_not_arm_wheel(self):
        for reason, armed in ((QtCore.Qt.ActiveWindowFocusReason, False), (QtCore.Qt.OtherFocusReason, False),
                              (QtCore.Qt.TabFocusReason, True), (QtCore.Qt.MouseFocusReason, True)):
            w = style.Slider(QtCore.Qt.Horizontal)
            self.addCleanup(w.deleteLater)
            w.setRange(0, 100)
            w.setValue(50)
            w.hasFocus = lambda: True
            QW.QApplication.sendEvent(w, QtGui.QFocusEvent(QtCore.QEvent.FocusIn, reason))
            wheel(w)
            self.assertEqual(w.value() != 50, armed, reason)
            QW.QApplication.sendEvent(w, QtGui.QFocusEvent(QtCore.QEvent.FocusOut, QtCore.Qt.MouseFocusReason))
            v = w.value()
            wheel(w)
            self.assertEqual(w.value(), v, "フォーカスが外れたら無効")

    def test_wheel_over_a_slider_scrolls_the_panel(self):
        tb = self.toolbox()
        areas = tb.findChildren(QW.QScrollArea)
        area = next((a for a in areas if a.verticalScrollBar().maximum() > 0), None)
        if area is None:
            self.skipTest("スクロールが出ない")
        bar = area.verticalScrollBar()
        bar.setValue(0)
        target = next(r.slider for r in tb.findChildren(ui.SliderRow) if area.isAncestorOf(r.slider) and r.slider.isVisible() and r.slider.isEnabled())   # 無効の部品は Qt がそもそも配らない
        # 実機のホイール(spontaneous)は、無視されると Qt が親へ順に渡す。offscreen の合成イベントは Qt が親へ渡さないので、
        # その連鎖をここで再現する: 受け手が無視したら 1 つ上の親へ送り直し、受け取られた所で止める。
        w = target
        while w is not None:
            e = wheel(w)
            if e.isAccepted():
                break
            w = w.parentWidget()
        self.assertIsNot(w, target, "スライダが受け取ってしまった(値が変わる)")
        self.assertGreater(bar.value(), 0)


def tearDownModule():
    app.processEvents()


if __name__ == "__main__":
    unittest.main(verbosity=2)
