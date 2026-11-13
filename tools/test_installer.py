# -*- coding: utf-8 -*-
"""実Mayaを使わず、一時ディレクトリで独立導入と旧版保全を検証。"""
import importlib
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

try:
    import PySide6.QtWidgets  # noqa: F401
    _HAS_QT = True
except Exception:
    try:
        import PySide2.QtWidgets  # noqa: F401
        _HAS_QT = True
    except Exception:
        _HAS_QT = False


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix='camview-installer-test-', dir=str(Path(__file__).resolve().parent))
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.src = self.root / 'source'
        pkg = self.src / 'scripts' / 'plsCamView'
        pkg.mkdir(parents=True)
        (pkg / '__init__.py').write_text('__version__ = "1.8.0"\n', encoding='utf8')
        (self.src / 'LICENSE').write_text('ライセンス', encoding='utf8')
        self.dest = self.root / 'modules' / 'plsCamView'
        self.dest.mkdir(parents=True)
        (self.dest / 'old.txt').write_bytes(b'previous package')
        self.mod = self.dest.parent / 'plsCamView.mod'
        self.mod.write_bytes(b'previous module')
        cmds = types.ModuleType('maya.cmds')
        cmds.error = lambda msg: (_ for _ in ()).throw(RuntimeError(msg))
        maya = types.ModuleType('maya')
        maya.cmds = cmds
        spec = importlib.util.spec_from_file_location(
            'installer_under_test', Path(__file__).resolve().parents[1] / 'plsCamView_install.py')
        self.inst = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'maya': maya, 'maya.cmds': cmds}):
            spec.loader.exec_module(self.inst)
        self.inst._source_dir = lambda: str(self.src)
        self.inst._install_paths = lambda: (str(self.dest), str(self.mod))
        saved_path = sys.path[:]
        self.addCleanup(lambda: sys.path.__setitem__(slice(None), saved_path))

    def assert_old(self):
        self.assertEqual((self.dest / 'old.txt').read_bytes(), b'previous package')
        self.assertEqual(self.mod.read_bytes(), b'previous module')
        self.assertFalse(list(self.dest.parent.glob('.plsCamView-install-*')))

    def test_independent_update(self):
        self.assertEqual(self.inst.install(False), str(self.dest))
        self.assertTrue((self.dest / 'scripts/plsCamView/__init__.py').is_file())
        self.assertEqual((self.dest / 'LICENSE').read_text(encoding='utf8'), 'ライセンス')
        self.assertIn(str(self.dest), self.mod.read_text(encoding='utf8'))
        self.assertFalse((self.dest / 'old.txt').exists())
        self.assertFalse(list(self.dest.parent.glob('.plsCamView-install-*')))

    def test_copy_failure_preserves_old(self):
        with patch.object(self.inst.shutil, 'copytree', side_effect=OSError('コピー失敗')):
            with self.assertRaises(RuntimeError):
                self.inst.install(False)
        self.assert_old()

    def test_payload_publish_failure_restores_old(self):
        real = self.inst.os.rename
        def fail_new(src, dst):
            if Path(src).name == 'new':
                raise OSError('本体公開失敗')
            return real(src, dst)
        with patch.object(self.inst.os, 'rename', side_effect=fail_new):
            with self.assertRaises(RuntimeError):
                self.inst.install(False)
        self.assert_old()

    def test_module_publish_failure_restores_old(self):
        with patch.object(self.inst.os, 'replace', side_effect=OSError('mod公開失敗')):
            with self.assertRaises(RuntimeError):
                self.inst.install(False)
        self.assert_old()

    def test_fresh_install_failure_removes_partial_payload(self):
        (self.dest / 'old.txt').unlink()
        self.dest.rmdir()
        self.mod.unlink()
        with patch.object(self.inst.os, 'replace', side_effect=OSError('mod公開失敗')):
            with self.assertRaises(RuntimeError):
                self.inst.install(False)
        self.assertFalse(self.dest.exists())
        self.assertFalse(self.mod.exists())

    def test_restore_failure_keeps_recovery_files(self):
        real = self.inst.os.rename
        def fail_restore(src, dst):
            if Path(src).name == 'previous':
                raise OSError('復元失敗')
            return real(src, dst)
        with patch.object(self.inst.os, 'replace', side_effect=OSError('mod公開失敗')), \
                patch.object(self.inst.os, 'rename', side_effect=fail_restore):
            with self.assertRaisesRegex(RuntimeError, '退避先を保持'):
                self.inst.install(False)
        backups = list(self.dest.parent.glob('.plsCamView-install-*/previous/old.txt'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b'previous package')
        self.assertEqual(self.mod.read_bytes(), b'previous module')

    # ---- 更新時の利用者配置 ffmpeg の保全(0.9.0: 公開 zip は ffmpeg 非同梱) ----
    def _put_dest_ffmpeg(self, data=b'user ffmpeg'):
        b = self.dest / 'scripts' / 'plsCamView' / 'bin'
        b.mkdir(parents=True, exist_ok=True)
        (b / 'ffmpeg.exe').write_bytes(data)

    def test_update_without_bundled_ffmpeg_preserves_user_copy(self):
        self._put_dest_ffmpeg()
        self.assertEqual(self.inst.install(False), str(self.dest))
        kept = self.dest / 'scripts' / 'plsCamView' / 'bin' / 'ffmpeg.exe'
        self.assertEqual(kept.read_bytes(), b'user ffmpeg')
        self.assertFalse(list(self.dest.parent.glob('.plsCamView-install-*')))

    def test_update_with_bundled_ffmpeg_uses_distribution(self):
        self._put_dest_ffmpeg()
        sb = self.src / 'scripts' / 'plsCamView' / 'bin'
        sb.mkdir(parents=True)
        (sb / 'ffmpeg.exe').write_bytes(b'bundled ffmpeg')
        self.assertEqual(self.inst.install(False), str(self.dest))
        got = (self.dest / 'scripts' / 'plsCamView' / 'bin' / 'ffmpeg.exe').read_bytes()
        self.assertEqual(got, b'bundled ffmpeg')   # 既存 binary の保全より配布物を優先(強制保全はしない)

    def test_publish_failure_keeps_user_ffmpeg(self):
        self._put_dest_ffmpeg()
        with patch.object(self.inst.os, 'replace', side_effect=OSError('mod公開失敗')):
            with self.assertRaises(RuntimeError):
                self.inst.install(False)
        self.assert_old()
        kept = self.dest / 'scripts' / 'plsCamView' / 'bin' / 'ffmpeg.exe'
        self.assertEqual(kept.read_bytes(), b'user ffmpeg')   # 失敗時も旧版ごと保全

    # ---- 0.9.1 レビュー対応: スタイル由来と import 解決先の保証 ----
    def _purge_camview_modules(self):
        for m in [m for m in list(sys.modules)
                  if m == 'plsCamView' or m.startswith('plsCamView.')
                  or m == 'plsCamViewInstallerBundle' or m.startswith('plsCamViewInstallerBundle.')]:
            sys.modules.pop(m, None)

    @unittest.skipUnless(_HAS_QT, 'PySide なし(デバイス側)。cloud offscreen で実行')
    def test_qt_modules_use_bundled_even_if_old_loaded(self):
        u"""旧 plsCamView がロード済みでも、installer の UI スタイルは同梱版を読み、
        ロード済みモジュールと sys.path に触れない。"""
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        import shutil as sh
        real = Path(__file__).resolve().parents[1] / 'scripts' / 'plsCamView'
        pkg = self.src / 'scripts' / 'plsCamView'
        for name in ('qt.py', 'style.py'):
            sh.copy(str(real / name), str(pkg / name))
        stale = types.ModuleType('plsCamView'); stale.__path__ = ['/stale']
        stale_style = types.ModuleType('plsCamView.style'); stale_style.MARK = 'OLD'
        path_before = list(sys.path)
        self.addCleanup(self._purge_camview_modules)
        with patch.dict(sys.modules, {'plsCamView': stale, 'plsCamView.style': stale_style}):
            mods = self.inst._qt_modules()
            self.assertIsNotNone(mods, u"同梱 qt/style を読めない")
            qt, style = mods
            got = Path(style.__file__).resolve()
            self.assertTrue(str(got).startswith(str(self.src.resolve())),
                            u"スタイルの由来が同梱版でない: {}".format(got))
            self.assertIs(sys.modules['plsCamView'], stale)
            self.assertEqual(sys.modules['plsCamView.style'].MARK, 'OLD')
            self.assertEqual(sys.path, path_before, u"_qt_modules が sys.path を汚した")

    def test_post_install_import_resolves_to_dest(self):
        u"""展開元 scripts が sys.path の先頭にあっても、install 後の import plsCamView は
        導入先(dest)を解決する(__file__ が導入先になる)。"""
        src_scripts = str(self.src / 'scripts')
        sys.path.insert(0, src_scripts)
        self.addCleanup(lambda: sys.path.remove(src_scripts) if src_scripts in sys.path else None)
        self._purge_camview_modules()
        self.addCleanup(self._purge_camview_modules)
        self.assertEqual(self.inst.install(False), str(self.dest))
        mod = importlib.import_module('plsCamView')
        got = Path(mod.__file__).resolve()
        self.assertTrue(str(got).startswith(str(self.dest.resolve())),
                        u"import が導入先を解決しない: {}".format(got))


if __name__ == '__main__':
    unittest.main()
