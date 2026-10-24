# -*- coding: utf-8 -*-
"""Mayaを操作しない複数カメラ検査。--media は同梱ffmpegで小さな合成を実検証。"""
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(ROOT / 'scripts' / PACKAGE)]
sys.modules[PACKAGE] = pkg
m = importlib.import_module(PACKAGE + '.multiblast')
mb = m.mp4blast
hook = importlib.import_module(PACKAGE + '.playblast_hook')


class Cmds:
    def __init__(self):
        self.time = 42
        self.focus = '元のパネル'
    def currentTime(self, value=None, **kw):
        if kw.get('q'):
            return self.time
        self.time = value
    def modelPanel(self, panel, **kw):
        return panel != 'missing'
    def setFocus(self, panel):
        self.focus = panel


class NamingLayout(unittest.TestCase):
    def test_names(self):
        self.assertEqual(m.camera_suffixes(['|g|A:front', '|g|B:side']), ['front', 'side'])
        self.assertEqual(m.camera_suffixes(['|A:cam', '|B:cam', '|C:other']), ['A', 'B', 'other'])
        self.assertEqual(m.camera_suffixes(['A:sub:cam', 'B:sub:cam']), ['A_sub', 'B_sub'])
    def test_collisions(self):
        for names in (['A:cam', 'A:cam'], ['cam', 'A:cam'], ['A:cam', 'a:cam'], ['A:sub:cam', 'A_sub:cam']):
            with self.subTest(names=names), self.assertRaises(ValueError):
                m.camera_suffixes(names)
    def test_layouts_and_ratios(self):
        for rects, expected in [
            ([(0, 0, 100, 100), (100, 0, 100, 100)], [(0, 0, 160, 180), (160, 0, 160, 180)]),
            ([(0, 0, 100, 100), (0, 100, 100, 100)], [(0, 0, 320, 90), (0, 90, 320, 90)]),
            ([(0, 0, 300, 100), (0, 100, 100, 100), (100, 100, 200, 100)], [(0, 0, 320, 90), (0, 90, 106, 90), (106, 90, 214, 90)]),
            ([(-300, -100, 100, 100), (-100, -100, 100, 100)], [(0, 0, 106, 180), (214, 0, 106, 180)])]:
            with self.subTest(rects=rects):
                self.assertEqual(m.layout_cells(rects, 320, 180), expected)
    def test_invalid_layout(self):
        for rects, wh in [([(0, 0, 100, 100), (50, 50, 100, 100)], (320, 180)),
                          ([(0, 0, 0, 100)], (320, 180)), ([(0, 0, 100, 100)], (321, 180))]:
            with self.subTest(rects=rects), self.assertRaises(ValueError):
                m.layout_cells(rects, *wh)
    def test_native_sequence(self):
        self.assertIn('shot.%04d.png', m._media_input(['shot.0001.png', 'shot.0002.png'], 24, 1, 2))
        with self.assertRaises(ValueError):
            m._media_input(['shot.0001.png', 'shot.0003.png'], 24, 1, 3)


class Batch(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cmds = Cmds()
        self.calls = []
        self.targets = [dict(camera='|one:front', panel='p1', rect=(0, 0, 100, 100)),
                        dict(camera='|two:side', panel='p2', rect=(100, 0, 100, 100))]
        self.options = dict(output_path=str(self.root / 'shot_suffix.mp4'), mode='mp4', fps=24,
                            width=320, height=180, start_frame=1, end_frame=3, open_after=False)
        def capture(panel, **kw):
            self.calls.append((panel, kw))
            self.cmds.time = 3
            self.cmds.focus = panel
            Path(kw['output_path']).write_bytes(b'video')
            return True, 'ok', kw['output_path']
        self.capture = capture
        def encode(command, cancelled, progress):
            Path(command[-1]).write_bytes(b'composite')
        self.patches = [patch.object(mb, 'cmds', self.cmds), patch.object(mb, 'run', side_effect=capture),
                        patch.object(mb, 'find_ffmpeg', return_value='ffmpeg'),
                        patch.object(mb, 'frame_range', return_value=(1, 3)),
                        patch.object(mb, 'scene_fps', return_value=24),
                        patch.object(hook, '_raw_get_panel', return_value='元のパネル'),
                        patch.object(m, '_encode', side_effect=encode)]
        for p in self.patches:
            p.start()
    def test_dotted_stem(self):
        options = dict(self.options, output_path=str(self.root / 'shot.v003'))
        self.assertTrue(m.run(self.targets, **options)[0])
        self.assertTrue((self.root / 'shot.v003_Multi.mp4').is_file())
    def test_directory_is_not_output_name(self):
        options = dict(self.options, output_path=str(self.root))
        self.assertFalse(m.run(self.targets, **options)[0])
        self.assertEqual(self.calls, [])

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()
    def test_default_on_on_and_restore(self):
        ok, msg, out = m.run(self.targets, **self.options)
        self.assertTrue(ok, msg)
        self.assertEqual(Path(out).name, 'shot_suffix_Multi.mp4')
        self.assertEqual(sorted(p.name for p in self.root.iterdir()),
                         ['shot_suffix_Multi.mp4', 'shot_suffix_front.mp4', 'shot_suffix_side.mp4'])
        self.assertEqual([p for p, _ in self.calls], ['p1', 'p2'])
        self.assertTrue(all(not kw['open_after'] and kw['start_frame'] == 1 and kw['end_frame'] == 3 for _, kw in self.calls))
        self.assertEqual((self.cmds.time, self.cmds.focus), (42, '元のパネル'))
    def test_combined_only(self):
        self.assertTrue(m.run(self.targets, keep_individuals=False, **self.options)[0])
        self.assertEqual([p.name for p in self.root.iterdir()], ['shot_suffix_Multi.mp4'])
    def test_combine_off_always_keeps_individuals(self):
        self.assertTrue(m.run(self.targets, combine=False, keep_individuals=False, **self.options)[0])
        self.assertEqual(len(list(self.root.glob('*.mp4'))), 2)
        m._encode.assert_not_called()
    def test_namespaces(self):
        self.targets[0]['camera'] = 'one:cam'
        self.targets[1]['camera'] = 'two:cam'
        self.assertTrue(m.run(self.targets, combine=False, **self.options)[0])
        self.assertTrue((self.root / 'shot_suffix_one.mp4').exists())
        self.assertTrue((self.root / 'shot_suffix_two.mp4').exists())
    def test_existing_file_stops_before_capture(self):
        old = self.root / 'shot_suffix_Multi.mp4'
        old.write_bytes(b'original')
        self.assertFalse(m.run(self.targets, **self.options)[0])
        self.assertEqual(old.read_bytes(), b'original')
        self.assertFalse(self.calls)
    def test_missing_ffmpeg_stops_before_capture(self):
        mb.find_ffmpeg.return_value = None
        self.assertFalse(m.run(self.targets, **self.options)[0])
        self.assertFalse(self.calls)
    def test_bad_panel_stops_before_capture(self):
        self.targets[1]['panel'] = 'missing'
        self.assertFalse(m.run(self.targets, **self.options)[0])
        self.assertFalse(self.calls)
    def test_multi_name_collision_stops(self):
        self.targets[0]['camera'] = 'Multi'
        self.assertFalse(m.run(self.targets, **self.options)[0])
        self.assertFalse(self.calls)
    def test_capture_failure_keeps_staged_media_and_restores(self):
        def fail(panel, **kw):
            return self.capture(panel, **kw) if panel == 'p1' else (False, '撮影失敗', '')
        mb.run.side_effect = fail
        ok, msg, recovery = m.run(self.targets, keep_individuals=False, **self.options)
        self.assertFalse(ok)
        self.assertTrue(list(Path(recovery).rglob('*.mp4')))
        self.assertFalse(list(self.root.glob('*.mp4')))
        self.assertEqual((self.cmds.time, self.cmds.focus), (42, '元のパネル'))
    def test_encode_failure_keeps_staged_media(self):
        m._encode.side_effect = RuntimeError('合成失敗')
        ok, msg, recovery = m.run(self.targets, keep_individuals=False, **self.options)
        self.assertFalse(ok)
        self.assertEqual(len(list(Path(recovery).rglob('*.mp4'))), 2)
    def test_cancel_between_cameras(self):
        ok, msg, recovery = m.run(self.targets, cancelled=lambda: bool(self.calls), **self.options)
        self.assertFalse(ok)
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(Path(recovery).exists())
    def test_publish_race_does_not_overwrite(self):
        real_publish = m._publish
        def race(src, dst):
            Path(dst).write_bytes(b'other job')
            real_publish(src, dst)
        with patch.object(m, '_publish', side_effect=race):
            ok, msg, recovery = m.run(self.targets, **self.options)
        self.assertFalse(ok)
        self.assertEqual((self.root / 'shot_suffix_front.mp4').read_bytes(), b'other job')
        self.assertTrue(Path(recovery).exists())
    def test_native_image_sequence_without_ffmpeg(self):
        mb.find_ffmpeg.side_effect = AssertionError('ffmpeg不要')
        def images(panel, **kw):
            for frame in range(1, 4):
                Path(os.path.splitext(kw['output_path'])[0] + '.%04d.png' % frame).write_bytes(b'image')
            return True, 'ok', ''
        mb.run.side_effect = images
        self.options['mode'] = 'maya'
        self.assertTrue(m.run(self.targets, combine=False, **self.options)[0])
        self.assertEqual(len(list(self.root.glob('*.png'))), 6)
    def test_raw_failure_is_not_repeated(self):
        with patch.object(hook, '_raw_playblast', side_effect=RuntimeError('fail')) as raw:
            self.cmds.playblast = unittest.mock.Mock()
            with self.assertRaises(RuntimeError):
                mb._raw_playblast(filename='x')
            self.assertEqual(raw.call_count, 1)
            self.cmds.playblast.assert_not_called()


class Media(unittest.TestCase):
    @unittest.skipUnless('--media' in sys.argv, '明示時のみ実ffmpeg')
    def test_real_four_colors(self):
        ffmpeg = mb.find_ffmpeg()
        self.assertTrue(ffmpeg)
        with tempfile.TemporaryDirectory() as tmp:
            inputs = []
            for i, color in enumerate(('red', 'lime', 'blue', 'white')):
                out = str(Path(tmp) / ('%s.mp4' % i))
                subprocess.run([ffmpeg, '-v', 'error', '-f', 'lavfi', '-i',
                                'color=c=%s:s=64x48:r=12:d=0.5' % color,
                                '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', out], check=True,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                inputs.append(['-i', out])
            out = str(Path(tmp) / 'Multi.mp4')
            cells = m.layout_cells([(0, 0, 100, 100), (100, 0, 100, 100),
                                    (0, 100, 100, 100), (100, 100, 100, 100)], 160, 120)
            m._encode(m.build_compose_command(ffmpeg, inputs, cells, out, 12, preset='ultrafast'), lambda: False, lambda _: None)
            decoded = subprocess.run([ffmpeg, '-v', 'error', '-i', out, '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
                                     creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0).stdout
            self.assertEqual(len(decoded), 160 * 120 * 3 * 6)
            for x, y, expected in [(40, 30, (255, 0, 0)), (120, 30, (0, 255, 0)),
                                    (40, 90, (0, 0, 255)), (120, 90, (255, 255, 255))]:
                pos = (y * 160 + x) * 3
                self.assertTrue(all(abs(a - b) <= 10 for a, b in zip(decoded[pos:pos + 3], expected)))


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
