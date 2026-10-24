"""移動・サイズ変更・終了・保存保全を実Qtと代役Mayaで検証。"""
import importlib
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch, Mock

ROOT = Path(os.environ.get('PLS_TEST_SOURCE', str(Path(__file__).resolve().parents[1])))
PACKAGE = ROOT.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT/'scripts'/PACKAGE)]
sys.modules[PACKAGE] = pkg
qt = importlib.import_module(PACKAGE+'.qt')
views = importlib.import_module(PACKAGE+'.views')
settings = importlib.import_module(PACKAGE+'.settings')
QC, QW = qt.QtCore, qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])

def settle_timers():
    loop = QC.QEventLoop()
    timer = QC.QTimer(loop)
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(500)
    (getattr(loop, 'exec', None) or loop.exec_)()

class ReleaseUI(unittest.TestCase):
    def setUp(self):
        self.top = QW.QWidget()
        self.top.resize(600, 400)
        self.view = QW.QWidget(self.top)
        self.view.setGeometry(10, 20, 400, 200)
        self.top.show(); self.view.show(); app.processEvents()
        self.overlay = None

    def tearDown(self):
        if self.overlay is not None:
            fn = getattr(self.overlay, 'detach', None) or self.overlay.dispose
            fn()
        self.top.close(); self.top.deleteLater()
        app.sendPostedEvents(None, QC.QEvent.DeferredDelete)
        app.processEvents()

    def gate(self):
        go = importlib.import_module(PACKAGE+'.gate_overlay')
        self.overlay = go.GateOverlay('testPanel', self.view)
        self.overlay.set_config({'gateEnabled': True})
        return go, self.overlay

    @unittest.skipUnless(PACKAGE == 'plsCamView', 'CamViewのゲート')
    def test_resize_updates_gate_before_poll(self):
        go, overlay = self.gate()
        with patch.object(go, 'compute_gate', side_effect=lambda p,w,h:(w/4,h/4,w/2,h/2)) as calc:
            overlay._poll(force=True)
            self.view.resize(500, 300)
            self.assertEqual(overlay.size(), self.view.size())
            self.assertEqual(overlay._gate, (125,75,250,150))
            self.assertEqual(calc.call_count, 2)

    @unittest.skipUnless(PACKAGE == 'plsCamView', 'CamViewのゲート')
    def test_move_updates_immediately_without_camera_query(self):
        go, overlay = self.gate()
        with patch.object(go, 'compute_gate') as calc:
            self.top.move(self.top.x()+20, self.top.y()+30)
            expected = QC.QRect(self.view.mapToGlobal(QC.QPoint()),self.view.size())
            self.assertEqual(overlay.geometry(), expected)
            calc.assert_not_called()

    @unittest.skipUnless(PACKAGE == 'plsCamView', 'CamViewのゲート')
    def test_layout_burst_one_timer_and_detach(self):
        _, overlay = self.gate()
        for _ in range(100):
            app.sendEvent(self.view, QC.QEvent(QC.QEvent.LayoutRequest))
        self.assertTrue(overlay._sync_timer.isActive())
        self.assertEqual(len(overlay.findChildren(QC.QTimer)), 2)
        overlay.detach()
        self.assertFalse(overlay._sync_timer.isActive())
        self.assertFalse(overlay._timer.isActive())
        app.sendEvent(self.view, QC.QEvent(QC.QEvent.Resize))

    @unittest.skipUnless(PACKAGE == 'plsFxView', 'FxViewの起動表示')
    def test_loading_move_no_maya_lookup_and_one_timer(self):
        lo = importlib.import_module(PACKAGE+'.loading_overlay')
        self.overlay = lo.LoadingOverlay('testPanel')
        with patch.object(lo, '_view_widget', return_value=self.view) as lookup:
            self.overlay.set_text('Loading')
            lookup.reset_mock()
            self.top.move(self.top.x()+20, self.top.y()+30)
            expected=QC.QRect(self.view.mapToGlobal(QC.QPoint()),self.view.size())
            self.assertEqual(self.overlay.geometry(), expected)
            lookup.assert_not_called()
            for _ in range(100):
                app.sendEvent(self.view, QC.QEvent(QC.QEvent.LayoutRequest))
            self.assertTrue(self.overlay._sync_timer.isActive())
            self.overlay.dispose()
            self.assertFalse(self.overlay._sync_timer.isActive())

    def test_view_fit_burst_one_calibration_batch(self):
        owner = types.SimpleNamespace()
        with patch.object(views.ViewSlot, 'fit_bar') as fit:
            slot = views.ViewSlot(owner, 0, {})
            for _ in range(100): slot._schedule_fit()
            settle_timers()
            self.assertEqual(fit.call_count, 3)
            slot.bar.close(); slot.bar.deleteLater()

    def test_closed_view_cancels_calibration(self):
        owner = types.SimpleNamespace()
        with patch.object(views.ViewSlot, 'fit_bar') as fit, patch.object(views, 'cmds', Mock()):
            slot = views.ViewSlot(owner, 0, {})
            slot._schedule_fit()
            slot.destroy()
            settle_timers()
            fit.assert_not_called()

    def test_settings_failure_keeps_previous_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'settings.json'
            original = b'{"camera":"|testCam"}'
            path.write_bytes(original)
            with patch.object(settings, 'config_path', return_value=str(path)), \
                 patch.object(settings.os, 'replace', side_effect=OSError('検証用の保存失敗')), \
                 patch.object(settings.os, 'rename', side_effect=OSError('検証用の保存失敗')):
                self.assertFalse(settings.save({'camera':'|newCam'}))
                self.assertEqual(path.read_bytes(), original)

    def test_settings_success_keeps_unrelated_options(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'settings.json'
            data={'camera':'|ns:camera', 'custom':{'保持':True}}
            with patch.object(settings,'config_path',return_value=str(path)):
                self.assertTrue(settings.save(data))
                self.assertEqual(json.loads(path.read_text(encoding='utf-8')),data)

if __name__=='__main__': unittest.main(verbosity=2)
