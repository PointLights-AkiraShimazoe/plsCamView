# -*- coding: utf-8 -*-
"""実QtとMaya API代役で選択・表示・単体経路を照合。実Mayaは起動しない。"""
import importlib
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT / 'scripts' / PACKAGE)]
sys.modules[PACKAGE] = pkg
ui = importlib.import_module(PACKAGE + '.ui')
views = ui.vw
QtWidgets = ui.QtWidgets
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
Window = getattr(ui, 'PlsCamViewWindow', None) or getattr(ui, 'PlsFxViewWindow')


class MultiUI(unittest.TestCase):
    def setUp(self):
        self.owner = Mock()
        self.owner.data = {"playblastMulti": True}
        self.manager = views.ViewManager.__new__(views.ViewManager)
        self.manager.owner = self.owner
        self.manager.target_index = 0
        self.manager.target_indices = [0]
        self.manager.views = [types.SimpleNamespace(bar=views.CameraBar(), panel='p'+str(i),
                              slot='slot'+str(i), camera=lambda i=i: 'cam'+str(i)) for i in range(3)]
    def tearDown(self):
        for v in self.manager.views:
            v.bar.close()
            v.bar.deleteLater()
        app.processEvents()
    def test_add_remove_and_keep_last(self):
        m = self.manager
        m.toggle_target(1); m.toggle_target(2)
        self.assertEqual(m.target_indices, [0, 1, 2])
        self.assertEqual(m.target_index, 2)
        m.toggle_target(2); m.toggle_target(1); m.toggle_target(0)
        self.assertEqual(m.target_indices, [0])
        self.assertEqual(m.target_index, 0)
        self.assertEqual(len(m.selected_views()), 1)
    def test_shrinking_invalid_saved_indices(self):
        m = self.manager
        m.target_indices = [9, -1, '1']; m.target_index = 9
        m._normalize_targets()
        self.assertEqual(m.target_indices, [2])
        self.assertEqual(m.target_index, 2)
        m.set_target(1)
        self.assertEqual(m.target_indices, [1])
    def test_single_mode_restore_switch_and_select(self):
        m = self.manager
        m.toggle_target(1); m.toggle_target(2)
        self.owner.data['playblastMulti'] = False
        m._normalize_targets()
        self.assertEqual(m.target_indices, [2])
        m.toggle_target(1)
        self.assertEqual(m.target_indices, [1])
        m.toggle_target(1)
        self.assertEqual(m.target_indices, [1])
        self.owner.data['playblastMulti'] = True
        m.toggle_target(0)
        self.assertEqual(m.target_indices, [0, 1])

    def test_defaults(self):
        self.assertFalse(ui.st.DEFAULTS['playblastMulti'])
        self.assertFalse(ui.st.DEFAULTS['playblastCombine'])
        self.assertTrue(ui.st.DEFAULTS['playblastKeepIndividuals'])

    def test_camera_identity_geometry_and_hidden_view(self):
        m = self.manager
        m.toggle_target(1)
        widget = QtWidgets.QWidget()
        widget.resize(320, 180); widget.show(); app.processEvents()
        fake = Mock()
        fake.ls.side_effect = lambda camera, **kw: ['|grp|ns:'+camera]
        fake.nodeType.return_value = 'transform'
        with patch.object(views, 'cmds', fake), patch.object(views, 'to_qwidget', return_value=widget):
            targets = m.playblast_targets(geometry=True)
            self.assertEqual([t['camera'] for t in targets], ['|grp|ns:cam0', '|grp|ns:cam1'])
            self.assertEqual(targets[0]['rect'][2:], (320, 180))
            widget.hide()
            with self.assertRaises(ValueError):
                m.playblast_targets(geometry=True)
            self.assertEqual(len(m.playblast_targets(geometry=False)), 2)
            fake.ls.return_value = []; fake.ls.side_effect = None
            with self.assertRaises(ValueError):
                m.playblast_targets()
        widget.close(); widget.deleteLater()
    def test_combine_keep_controls(self):
        box = ui.ToolBox.__new__(ui.ToolBox)
        QtWidgets.QWidget.__init__(box)
        box.owner = self.owner
        box._building = True
        box._horizontal = False
        with patch.object(ui, 'cmds', None):
            card = box._build_playblast()
        box.multiEnabled.setChecked(True)
        box.multiCombine.setChecked(True); box.multiKeep.setChecked(True)
        box._building = False
        box._on_multi_option()
        self.assertFalse(box.multiKeep.isHidden())
        self.assertTrue(self.owner.data['playblastKeepIndividuals'])
        box.multiCombine.setChecked(False)
        self.assertTrue(box.multiKeep.isHidden())
        self.assertFalse(self.owner.data['playblastCombine'])
        box.multiCombine.setChecked(True)
        self.assertFalse(box.multiKeep.isHidden())
        self.assertTrue(box.multiKeep.isChecked())
        box.multiKeep.setChecked(False)
        self.assertFalse(self.owner.data['playblastKeepIndividuals'])
        box.multiEnabled.setChecked(False)
        self.assertTrue(box.multiCombine.isHidden())
        self.assertTrue(box.multiKeep.isHidden())
        self.assertFalse(self.owner.data['playblastMulti'])
        card.close(); card.deleteLater(); box.close(); box.deleteLater()
    def test_single_dispatch_unchanged_and_multi_options(self):
        owner = types.SimpleNamespace(_panel_getter=lambda: 'p0', activate_window=lambda: None,
            toolbox=types.SimpleNamespace(mp4_options=lambda: {'output_path': 'x.mp4'}),
            target_camera=lambda: '|cam0', data={}, views=Mock(), _playblast_multiple=Mock(),
            suppress_gate=Mock())
        owner.views.selected_views.return_value = [1]
        with patch.object(ui.mp4blast, 'run', return_value=(True, 'ok', 'x.mp4')) as run, patch.object(ui, 'cmds', Mock()):
            self.assertTrue(Window.do_playblast_mp4(owner)[0])
            run.assert_called_once_with('p0', output_path='x.mp4', camera='|cam0')
            owner._playblast_multiple.assert_not_called()
            owner.data['playblastMulti'] = True
            owner.views.selected_views.return_value = [1, 2]
            Window.do_playblast_mp4(owner, combine=False, keep_individuals=False)
            owner._playblast_multiple.assert_called_once_with({'output_path':'x.mp4','camera':'|cam0'}, False, False)
            self.assertEqual(run.call_count, 1)
    def test_explicit_batch_panel_survives_force_hook(self):
        hook = ui.pbh
        kw = {'editorPanelName': 'batchPanel'}
        with patch.object(hook, '_panel_getter', return_value='otherToolPanel'):
            self.assertFalse(hook._inject_panel(kw))
        self.assertEqual(kw['editorPanelName'], 'batchPanel')


if __name__ == '__main__':
    unittest.main(verbosity=2)
