"""CamView/FxViewの解除順と第三者フック保全。Mayaを起動しない。"""
import importlib
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT=Path(os.environ.get('PLS_HOOK_ROOT', str(Path(__file__).resolve().parents[2])))

# 併存試験: 兄弟リポジトリ plsFxView の playblast_hook を同条件で読み込んで解除順・第三者フック
# 保全を照合する(他製品コードはこのリポジトリに同梱しない)。単独の plsCamView リポジトリでは
# 対象が存在しないため、依存理由を明示して skip する。plsCamView と plsFxView が並ぶ作業ツリー
# では従来どおり全検証を行う(親フォルダは PLS_HOOK_ROOT で指定可)。
FXVIEW_HOOK = ROOT / 'plsFxView' / 'scripts' / 'plsFxView' / 'playblast_hook.py'

@unittest.skipUnless(
    FXVIEW_HOOK.is_file(),
    'plsFxView 併存試験: 兄弟リポジトリ plsFxView が見つからないため skip'
    '(plsCamView と plsFxView が並ぶ親フォルダを PLS_HOOK_ROOT に指定すると実行)')
class Hooks(unittest.TestCase):
    def setUp(self):
        self.base=lambda *a,**kw:kw
        self.focus=lambda *a,**kw:'originalPanel'
        self.cmds=types.ModuleType('maya.cmds')
        self.cmds.playblast=self.base
        self.cmds.getPanel=self.focus
        self.cmds.modelPanel=lambda p,**kw: True if kw.get('exists') else p+'Editor'
        self.cmds.modelEditor=lambda *a,**kw:True
        self.cmds.warning=Mock()
        self.mel=types.ModuleType('maya.mel'); self.mel.eval=Mock(return_value='')
        maya=types.ModuleType('maya'); maya.cmds=self.cmds; maya.mel=self.mel
        pm=types.ModuleType('pymel.core'); pm.playblast=self.base; pm.getPanel=self.focus
        pymel=types.ModuleType('pymel'); pymel.core=pm
        self.modules=patch.dict(sys.modules,{'maya':maya,'maya.cmds':self.cmds,'maya.mel':self.mel,
                                             'pymel':pymel,'pymel.core':pm})
        self.modules.start()
        self.hooks=[]
        for name in ('plsCamView','plsFxView'):
            sys.modules.pop(name+'.playblast_hook',None)
            pkg=types.ModuleType(name); pkg.__path__=[str(ROOT/name/'scripts'/name)]
            sys.modules[name]=pkg
            hook=importlib.import_module(name+'.playblast_hook')
            self.hooks.append(hook)
        self.a,self.b=self.hooks

    def tearDown(self):
        for h in self.hooks:h.uninstall()
        self.modules.stop()

    def python_hooks(self):
        for h,label in ((self.a,'A'),(self.b,'B')):
            h._panel_getter=lambda label=label:label
            h._install_python_patch()

    def test_close_older_then_newer(self):
        self.python_hooks()
        self.assertEqual(self.cmds.playblast()['editorPanelName'],'B')
        self.a.uninstall()
        self.assertEqual(self.cmds.playblast()['editorPanelName'],'B')
        self.assertEqual(self.cmds.getPanel(withFocus=True),'B')
        self.b.uninstall()
        self.assertIs(self.cmds.playblast,self.base)
        self.assertIs(self.cmds.getPanel,self.focus)

    def test_close_newer_restores_older(self):
        self.python_hooks(); self.b.uninstall()
        self.assertEqual(self.cmds.playblast()['editorPanelName'],'A')
        self.assertEqual(self.cmds.getPanel(withFocus=True),'A')
        self.a.uninstall(); self.assertIs(self.cmds.playblast,self.base)

    def test_explicit_target_and_query_are_preserved(self):
        self.python_hooks()
        self.assertEqual(self.cmds.playblast(editorPanelName='explicit'),{'editorPanelName':'explicit'})
        self.assertEqual(self.cmds.playblast(query=True,format=True),{'query':True,'format':True})

    def test_foreign_hook_is_not_overwritten(self):
        self.python_hooks()
        previous=self.cmds.playblast
        foreign=lambda **kw:previous(**kw)
        self.cmds.playblast=foreign
        self.a.uninstall(); self.b.uninstall()
        self.assertIs(self.cmds.playblast,foreign)
        self.assertEqual(foreign(),{})

    def install_mel(self,hook,label):
        sig={'ret':'','params':'int $option','names':['$option']}
        with patch.object(hook,'_find_orig_mel',return_value='original.mel'), \
             patch.object(hook,'_make_backup_proc',return_value=sig):
            self.assertTrue(hook.install(lambda:label))

    def test_mel_older_close_leaves_active_wrapper(self):
        self.install_mel(self.a,'A'); self.install_mel(self.b,'B')
        self.mel.eval.reset_mock(); self.a.uninstall()
        self.mel.eval.assert_not_called()
        self.b.uninstall()
        self.assertIn('source ',self.mel.eval.call_args.args[0])

    def test_mel_newer_close_restores_previous(self):
        self.install_mel(self.a,'A'); self.install_mel(self.b,'B')
        self.mel.eval.reset_mock(); self.b.uninstall()
        self.assertIn('plsCamView.playblast_hook',self.mel.eval.call_args.args[0])

    def test_failed_install_restores_previous_mel(self):
        self.install_mel(self.a,'A')
        with patch.object(self.b,'_find_orig_mel',return_value='original.mel'), \
             patch.object(self.b,'_make_backup_proc',return_value=None):
            self.assertFalse(self.b.install(lambda:'B'))
        self.assertIn('plsCamView.playblast_hook',self.mel.eval.call_args.args[0])
        self.b.uninstall()
        self.assertEqual(self.cmds.playblast()['editorPanelName'],'A')

    def test_failed_verification_restores_previous_mel(self):
        self.install_mel(self.a,'A')
        self.mel.eval.side_effect=lambda text: (_ for _ in ()).throw(RuntimeError('確認失敗')) if text.startswith('whatIs') else ''
        sig={'ret':'','params':'int $option','names':['$option']}
        with patch.object(self.b,'_find_orig_mel',return_value='original.mel'), \
             patch.object(self.b,'_make_backup_proc',return_value=sig):
            self.assertFalse(self.b.install(lambda:'B'))
        self.assertIn('plsCamView.playblast_hook',self.mel.eval.call_args.args[0])
        self.b.uninstall()
        self.assertEqual(self.cmds.playblast()['editorPanelName'],'A')

    def test_failed_verification_without_previous_restores_maya(self):
        self.mel.eval.side_effect=lambda text: (_ for _ in ()).throw(RuntimeError('確認失敗')) if text.startswith('whatIs') else ''
        sig={'ret':'','params':'int $option','names':['$option']}
        with patch.object(self.a,'_find_orig_mel',return_value='original.mel'), \
             patch.object(self.a,'_make_backup_proc',return_value=sig):
            self.assertFalse(self.a.install(lambda:'A'))
        self.assertEqual(self.mel.eval.call_args.args[0],'source "original.mel";')
        self.a.uninstall()
        self.assertIs(self.cmds.playblast,self.base)

if __name__=='__main__':unittest.main(verbosity=2)
