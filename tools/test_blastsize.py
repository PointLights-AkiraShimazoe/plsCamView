# -*- coding: utf-8 -*-
"""Playblast(MP4 / Multi)の寸法・出力保護・復帰の回帰確認。Maya 不要。

- 純粋部分(blastsize)
- 実 ffmpeg / ffprobe で短い合成 PNG 連番を実エンコードし、寸法と「切り落としなし」を確認
  (※ Maya の Playblast の証明ではない。Maya が書く画像を合成画像で代用している)
- mp4blast.run / run_maya を偽の cmds で動かし、失敗時の既存出力保護と表示・時刻の復帰を確認
- multiblast.run を実 ffmpeg で動かし、奇数サイズの Combine / Keep each を確認

使い方: PKG_DIR=<scripts/パッケージ> python3 test_blastsize.py   (未指定なら tools/ の親の scripts/<名前>)
"""
import importlib
import math
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from PIL import Image
except Exception:                                    # pragma: no cover
    Image = None

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = Path(os.environ.get("PKG_DIR") or (ROOT / "scripts" / ROOT.name))
PACKAGE = PKG_DIR.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(PKG_DIR)]
sys.modules[PACKAGE] = pkg
bs = importlib.import_module(PACKAGE + ".blastsize")
mb = importlib.import_module(PACKAGE + ".mp4blast")
mu = importlib.import_module(PACKAGE + ".multiblast")
hook = importlib.import_module(PACKAGE + ".playblast_hook")
importlib.import_module(PACKAGE + ".i18n").set_language("ja")      # 文言の検査は日本語表示で固定

FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")
REAL = bool(FFMPEG and FFPROBE and Image)


def write_png(path, w, h):
    """内側は中間グレー、最外周 1px は白(切り落としの検出用)。"""
    img = Image.new("RGB", (w, h), (90, 90, 90))
    px = img.load()
    for x in range(w):
        px[x, 0] = px[x, h - 1] = (255, 255, 255)
    for y in range(h):
        px[0, y] = px[w - 1, y] = (255, 255, 255)
    img.save(str(path))


def probe(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=width,height,nb_frames,codec_name,pix_fmt", "-of", "csv=p=0", str(path)],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout.decode().strip()
    codec, w, h, pix, frames = out.split(",")[:5]
    return int(w), int(h), codec, pix, frames


def gray_frame(path, w, h):
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         check=True).stdout
    assert len(raw) == w * h, (len(raw), w, h)
    return raw


class Pure(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(bs.normalize_size(1913, 1074), (1913, 1074))
        self.assertEqual(bs.normalize_size(1913.4, 1073.6), (1913, 1074))      # 端数は四捨五入
        self.assertEqual(bs.normalize_size("640", 360.0), (640, 360))
        for bad in (0, -1, 0.4, float("nan"), float("inf"), "x", None, 16385):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                bs.normalize_dimension(bad, "幅")

    def test_even_and_pad(self):
        self.assertEqual([bs.even_up(n) for n in (0, 1, 2, 3, 1913, 1914)], [2, 2, 2, 4, 1914, 1914])
        self.assertEqual(bs.pad_filter(1913, 1074), "pad=1914:1074:0:0:color=black")
        self.assertEqual(bs.pad_filter(1, 1), "pad=2:2:0:0:color=black")
        self.assertEqual(bs.pad_filter(1920, 1080), "")           # 偶数は従来の ffmpeg コマンドと同一

    def test_ranges(self):
        self.assertEqual(bs.normalize_range(1.4, 10.6), (1, 11))
        for bad in ((5, 1), (float("nan"), 1), ("a", 2)):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                bs.normalize_range(*bad)
        for bad in (0, -24, float("inf")):
            with self.assertRaises(ValueError):
                bs.normalize_fps(bad)
        for bad in (-1, 52):
            with self.assertRaises(ValueError):
                bs.normalize_crf(bad)

    def test_parse_video_size(self):
        text = ("  Stream #0:0: Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, progressive), "
                "1914x1074 [SAR 1:1 DAR 319:179], 24 fps, 24 tbr")
        self.assertEqual(bs.parse_video_size(text), (1914, 1074))
        self.assertIsNone(bs.parse_video_size("no video"))

    def test_command_filter_position(self):
        a = mb.build_ffmpeg_command("ff", "in.%04d.png", "o.mp4", 24, 1)
        b = mb.build_ffmpeg_command("ff", "in.%04d.png", "o.mp4", 24, 1, video_filter="pad=2:2:0:0:color=black")
        self.assertNotIn("-vf", a)
        self.assertEqual(b[b.index("-vf") + 1], "pad=2:2:0:0:color=black")
        self.assertEqual([x for x in b if x not in ("-vf", "pad=2:2:0:0:color=black")], a)

    def test_png_size_and_sequence(self):
        if not Image:
            self.skipTest("PIL なし")
        with tempfile.TemporaryDirectory() as t:
            a, b = Path(t) / "a.png", Path(t) / "b.png"
            write_png(a, 7, 5)
            write_png(b, 8, 5)
            self.assertEqual(bs.png_size(a), (7, 5))
            self.assertIsNone(bs.png_size(Path(t) / "none.png"))
            self.assertEqual(bs.sequence_size([str(a), str(a)]), (7, 5))
            with self.assertRaises(ValueError):
                bs.sequence_size([str(a), str(b)])                  # 寸法が混在
            with self.assertRaises(ValueError):
                bs.sequence_size([])


@unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
class RealEncode(unittest.TestCase):
    SIZES = [(1913, 1074), (1914, 1073), (1919, 1079), (1, 1), (3, 5), (2, 2), (1920, 1080), (641, 359)]

    def make_seq(self, folder, w, h, n=3):
        files = []
        for i in range(1, n + 1):
            p = Path(folder) / ("frame.%04d.png" % i)
            write_png(p, w, h)
            files.append(str(p))
        return files, str(Path(folder) / "frame.%04d.png")

    def test_old_command_fails_for_odd(self):
        """従来(フィルタ無し)の ffmpeg コマンドが 1913x1074 で失敗することの再現(原因の確認)。"""
        with tempfile.TemporaryDirectory() as t:
            files, pat = self.make_seq(t, 1913, 1074)
            cmd = mb.build_ffmpeg_command(FFMPEG, pat, str(Path(t) / "o.mp4"), 24, 1, preset="ultrafast")
            r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("not divisible by 2", r.stderr.decode())

    def test_encode_sizes_and_no_crop(self):
        for w, h in self.SIZES:
            with self.subTest(size="%dx%d" % (w, h)), tempfile.TemporaryDirectory() as t:
                files, pat = self.make_seq(t, w, h)
                out = str(Path(t) / "o.mp4")
                ok, msg, size = mb.encode_png_sequence(FFMPEG, pat, files, out, 24, 1,
                                                       crf=18, preset="ultrafast")
                self.assertTrue(ok, msg)
                ew, eh = bs.even_size(w, h)
                self.assertEqual(size, (ew, eh))
                pw, ph, codec, pix, frames = probe(out)
                self.assertEqual((pw, ph, codec, pix, frames), (ew, eh, "h264", "yuv420p", "3"))
                self.assertEqual([p.name for p in Path(t).glob(".*")], [])     # 一時ファイルが残らない
                if min(w, h) >= 3:
                    g = gray_frame(out, ew, eh)
                    # 最外周の白がそのまま残る(切り落とされていない)
                    self.assertGreater(g[(h // 2) * ew + (w - 1)], 200)       # 右端の列
                    self.assertGreater(g[(h - 1) * ew + (w // 2)], 200)       # 最下行
                    self.assertGreater(g[(h // 2) * ew + 0], 200)             # 左端
                    self.assertGreater(g[0 * ew + (w // 2)], 200)             # 最上行
                    if ew > w:
                        self.assertLess(g[(h // 2) * ew + w], 40)             # 足した列は黒
                    if eh > h:
                        self.assertLess(g[h * ew + (w // 2)], 40)             # 足した行は黒

    def test_failed_encode_keeps_existing_output(self):
        with tempfile.TemporaryDirectory() as t:
            files, pat = self.make_seq(t, 64, 48)
            out = Path(t) / "o.mp4"
            out.write_bytes(b"existing")
            bad = Path(t) / "fakeffmpeg"
            bad.write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
            bad.chmod(0o755)
            ok, msg, _ = mb.encode_png_sequence(str(bad), pat, files, str(out), 24, 1)
            self.assertFalse(ok)
            self.assertEqual(out.read_bytes(), b"existing")
            self.assertEqual([p.name for p in Path(t).glob(".*")], [])

    def test_mixed_sequence_is_rejected_before_ffmpeg(self):
        with tempfile.TemporaryDirectory() as t:
            files, pat = self.make_seq(t, 64, 48, 2)
            write_png(files[1], 66, 48)
            out = Path(t) / "o.mp4"
            ok, msg, _ = mb.encode_png_sequence(FFMPEG, pat, files, str(out), 24, 1, preset="ultrafast")
            self.assertFalse(ok)
            self.assertFalse(out.exists())


class FakeCmds:
    """Maya の cmds の最小の代用。表示設定と時刻の「変更 → 復帰」を記録する。"""

    def __init__(self):
        self.time = 42
        self.attrs = {}
        self.editor = {}
        self.warnings = []
        self.set_log = []
        self.fail_set = set()
        self.fail_time = False

    def modelPanel(self, panel, **kw):
        return True

    def currentTime(self, value=None, **kw):
        if kw.get("q"):
            return self.time
        if self.fail_time:
            raise RuntimeError("time locked")
        self.time = value

    def warning(self, text):
        self.warnings.append(text)

    def refresh(self, **kw):
        pass

    def objectType(self, node):
        return "camera"

    def listRelatives(self, *a, **kw):
        return []

    def attributeQuery(self, attr, node=None, exists=False):
        return True

    DEFAULT = 0.5          # 撮影用の適用値(0 / 1)とは違う「元の値」

    def getAttr(self, plug):
        return self.attrs.get(plug, self.DEFAULT)

    def setAttr(self, plug, value):
        self.set_log.append((plug, value))
        if plug in self.fail_set:
            raise RuntimeError("locked " + plug)
        self.attrs[plug] = value

    def modelEditor(self, panel, **kw):
        if kw.get("q"):
            key = [k for k in kw if k != "q"][0]
            if key == "camera":
                return "persp"
            return self.editor.get((panel, key), "default" if key == "displayLights" else True)
        for k, v in kw.items():
            if k != "e":
                self.editor[(panel, k)] = v

    def snapshot(self):
        """元の値(既定)と同じものは「変更なし」として省く。残っていれば撮影用の値が戻っていない。"""
        attrs = {k: v for k, v in self.attrs.items() if v != self.DEFAULT}
        editor = {k: v for k, v in self.editor.items() if v not in (True, "default")}
        return (self.time, attrs, editor)


class SingleRun(unittest.TestCase):
    """mp4blast.run(単独 MP4)を偽の cmds と合成画像で。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cmds = FakeCmds()
        self.image_size = (1913, 1074)
        self.fail_playblast = None
        self.calls = []

        def raw(**kw):
            self.calls.append(kw)
            self.cmds.time = 9999                           # 撮影で時刻が動く
            if self.fail_playblast:
                raise RuntimeError(self.fail_playblast)
            if "filename" not in kw or "startTime" not in kw:
                return None                                 # run_maya(画像を書かない経路)
            for f in range(int(kw["startTime"]), int(kw["endTime"]) + 1):
                if self.image_size:
                    write_png(Path("%s.%04d.png" % (kw["filename"], f)), *self.image_size)
        self.raw = raw
        self.ps = [patch.object(mb, "cmds", self.cmds), patch.object(mb, "_raw_playblast", side_effect=raw)]
        for p in self.ps:
            p.start()

    def tearDown(self):
        for p in reversed(self.ps):
            p.stop()
        self.tmp.cleanup()

    def opts(self, **kw):
        base = dict(output_path=str(self.dir / "shot.mp4"), width=1913, height=1074, fps=24, crf=18,
                    preset="ultrafast", start_frame=1, end_frame=3, open_after=False,
                    optimize_viewport=True, ffmpeg_path=FFMPEG or "")
        base.update(kw)
        return base

    @unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
    def test_odd_request_succeeds_and_restores(self):
        before = self.cmds.snapshot()
        ok, msg, out = mb.run("modelPanel4", **self.opts())
        self.assertTrue(ok, msg)
        self.assertEqual(probe(out)[:2], (1914, 1074))
        self.assertEqual(self.calls[0]["width"], 1913)               # Maya へは要求どおりの整数
        self.assertEqual(self.cmds.snapshot(), before)               # 時刻・属性・表示設定が元どおり
        self.assertEqual(self.cmds.warnings, [])
        self.assertEqual([p.name for p in self.dir.iterdir()], ["shot.mp4"])

    @unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
    def test_actual_image_size_decides_encode_size(self):
        """要求 1920x1080 でも Maya が 1919x1079 を書いたら、その寸法から偶数化する。"""
        self.image_size = (1919, 1079)
        ok, msg, out = mb.run("modelPanel4", **self.opts(width=1920, height=1080))
        self.assertTrue(ok, msg)
        self.assertEqual(probe(out)[:2], (1920, 1080))

    @unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
    def test_fractional_request_is_rounded(self):
        self.image_size = (641, 359)
        ok, msg, out = mb.run("modelPanel4", **self.opts(width=640.6, height=358.7))
        self.assertTrue(ok, msg)
        self.assertEqual((self.calls[0]["width"], self.calls[0]["height"]), (641, 359))
        self.assertEqual(probe(out)[:2], (642, 360))

    def test_invalid_values_fail_before_touching_maya(self):
        before = self.cmds.snapshot()
        for kw in (dict(width=0), dict(height=-5), dict(width=float("nan")), dict(width=0.3),
                   dict(start_frame=5, end_frame=1), dict(fps=0), dict(fps=2000), dict(fps=float("nan")),
                   dict(crf=99), dict(preset="bogus"), dict(start_frame=float("inf"))):
            with self.subTest(kw=kw):
                ok, msg, out = mb.run("modelPanel4", **self.opts(**kw))
                self.assertFalse(ok)
                self.assertEqual(self.cmds.set_log, [])              # 表示・属性に一切触れていない
                self.assertEqual(self.cmds.snapshot(), before)
                self.assertEqual(self.calls, [])
                self.assertEqual(list(self.dir.iterdir()), [])
        # 0 / 負 は Maya の playblast へ渡さない
        self.assertEqual(self.calls, [])

    @unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
    def test_failure_keeps_existing_output_and_restores(self):
        existing = self.dir / "shot.mp4"
        existing.write_bytes(b"precious")
        before = self.cmds.snapshot()
        bad = self.dir / "fakeffmpeg"
        bad.write_text("#!/bin/sh\necho boom >&2\nexit 1\n")
        bad.chmod(0o755)
        ok, msg, out = mb.run("modelPanel4", **self.opts(ffmpeg_path=str(bad)))
        self.assertFalse(ok)
        self.assertEqual(existing.read_bytes(), b"precious")
        self.assertEqual(self.cmds.snapshot(), before)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["fakeffmpeg", "shot.mp4"])

    @unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
    def test_playblast_exception_and_missing_frames_restore(self):
        existing = self.dir / "shot.mp4"
        existing.write_bytes(b"precious")
        before = self.cmds.snapshot()
        self.fail_playblast = "撮影中に例外"
        ok, msg, _ = mb.run("modelPanel4", **self.opts())
        self.assertFalse(ok)
        self.assertEqual(self.cmds.snapshot(), before)
        self.fail_playblast = None
        self.image_size = None                                       # 1 枚も書かれない(取消し等)
        ok, msg, _ = mb.run("modelPanel4", **self.opts())
        self.assertFalse(ok)
        self.assertIn("足りません", msg)
        self.assertEqual(self.cmds.snapshot(), before)
        self.assertEqual(existing.read_bytes(), b"precious")

    @unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
    def test_restore_failures_are_isolated_and_warned(self):
        self.cmds.fail_time = True                                   # 時刻が戻せなくても…
        ok, msg, out = mb.run("modelPanel4", **self.opts())
        self.assertTrue(ok, msg)                                     # 動画は書けている
        self.assertTrue(any("currentTime" in w for w in self.cmds.warnings))   # 黙って捨てない
        self.assertEqual(self.cmds.snapshot()[1:], ({}, {}))          # 属性・表示の復帰は別に実行された

    def test_run_maya_validates_and_restores(self):
        before = self.cmds.snapshot()
        with patch.object(mb, "_maya_playblast_options", return_value={}):
            ok, msg, _ = mb.run_maya("modelPanel4", width=0, height=1080, optimize_viewport=True)
            self.assertFalse(ok)
            self.assertEqual(self.cmds.snapshot(), before)
            self.assertEqual(self.calls, [])
            ok, msg, _ = mb.run_maya("modelPanel4", width=1913.4, height=1074, optimize_viewport=True,
                                     start_frame=1, end_frame=2)
            self.assertTrue(ok, msg)
            self.assertEqual(self.calls[0]["widthHeight"], (1913, 1074))   # Maya 標準形式は奇数のまま
            self.assertEqual(self.cmds.snapshot(), before)

    # ---- 追指示1-1: 寸法を確認できない動画は公開しない ----------------------------------
    @unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
    def test_probe_none_is_failure_keeps_existing_and_cleans_part(self):
        existing = self.dir / "shot.mp4"
        existing.write_bytes(b"precious")
        before = self.cmds.snapshot()
        with patch.object(mb, "probe_video_size", return_value=None):
            ok, msg, out = mb.run("modelPanel4", **self.opts())
        self.assertFalse(ok)
        self.assertIn("確認できません", msg)
        self.assertEqual(existing.read_bytes(), b"precious")                # 既存は置換されない
        self.assertEqual([p.name for p in self.dir.iterdir()], ["shot.mp4"])   # .part も残らない
        self.assertEqual(self.cmds.snapshot(), before)

    @unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
    def test_probe_wrong_size_is_failure_and_new_output_not_created(self):
        with patch.object(mb, "probe_video_size", return_value=(100, 100)):
            ok, msg, out = mb.run("modelPanel4", **self.opts())
        self.assertFalse(ok)
        self.assertIn("想定", msg)
        self.assertEqual(list(self.dir.iterdir()), [])                       # 新規も公開されない

    def test_probe_video_size_unreadable_returns_none(self):
        bad = self.dir / "fakeffmpeg"
        bad.write_text("#!/bin/sh\nsleep 5\n")
        bad.chmod(0o755)
        self.assertIsNone(mb.probe_video_size(str(bad), str(self.dir / "x.mp4"), timeout=0.3))   # タイムアウト
        self.assertIsNone(mb.probe_video_size(str(self.dir / "nonexistent"), "x.mp4"))          # 実行できない

    def test_check_output_writable_never_touches_user_files(self):
        out = self.dir / "shot.mp4"
        user = self.dir / "shot.mp4.__wtest__"          # 旧実装の固定名と同名の利用者ファイル
        user.write_bytes(b"user data")
        ok, msg = mb.check_output_writable(str(out))
        self.assertTrue(ok, msg)
        self.assertEqual(user.read_bytes(), b"user data")                    # 壊さない・消さない
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["shot.mp4.__wtest__"])   # 一時ファイルも残さない
        out.write_bytes(b"precious")                                         # 既存の出力は追記モードで開くだけ
        ok, msg = mb.check_output_writable(str(out))
        self.assertTrue(ok, msg)
        self.assertEqual(out.read_bytes(), b"precious")
        ro = self.dir / "nonexistent" / "deeper" / "x.mp4"                   # 無いフォルダは作る
        self.assertTrue(mb.check_output_writable(str(ro))[0])

    # ---- 追指示1-3: 共通 normalize ---------------------------------------------------
    def test_normalize_settings_spec(self):
        with patch.object(mb, "scene_fps", return_value=30.0), patch.object(mb, "frame_range", return_value=(10, 20)):
            n = mb.normalize_settings(641.4, 359.6, None, 18, "slow", None, None)
            self.assertEqual((n["width"], n["height"], n["fps"]), (641, 360, 30.0))      # None = シーン fps
            self.assertEqual((n["start_frame"], n["end_frame"]), (10, 20))               # 範囲は補う
            n = mb.normalize_settings(640, 360, 24, 18, "slow", 1.5, 2.4)
            self.assertEqual((n["start_frame"], n["end_frame"]), (2, 2))                 # 四捨五入(.5 は切り上げ)
            n = mb.normalize_settings(640, 360, None, 99, "bogus", None, None, need_encode=False, fill_range=False)
            self.assertEqual((n["start_frame"], n["end_frame"]), (None, None))           # Maya 標準: 検査しない・範囲は既定のまま
            for kw in (dict(fps=0), dict(fps=-1), dict(fps=1001), dict(crf=52), dict(crf=-1), dict(preset="x"),
                       dict(start_frame=5, end_frame=1), dict(width=0), dict(width=16385)):
                with self.subTest(kw=kw), self.assertRaises(ValueError):
                    mb.normalize_settings(**dict(dict(width=640, height=360, fps=24), **kw))

    def test_fractional_range_single_is_rounded_like_multi(self):
        self.image_size = (640, 360)
        ok, msg, out = mb.run("modelPanel4", **self.opts(width=640, height=360, start_frame=1.4, end_frame=2.6))
        if REAL:
            self.assertTrue(ok, msg)
        self.assertEqual((self.calls[0]["startTime"], self.calls[0]["endTime"]), (1, 3))


@unittest.skipUnless(REAL, "ffmpeg / ffprobe / PIL が必要")
class MultiReal(unittest.TestCase):
    """multiblast.run を実 ffmpeg で(撮影だけ合成画像)。奇数サイズ・Combine / Keep each。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.cmds = FakeCmds()
        self.focus = "元のパネル"

        self.calls = []

        def raw(**kw):
            self.calls.append(kw)
            self.cmds.time = 7
            for f in range(int(kw["startTime"]), int(kw["endTime"]) + 1):
                write_png(Path("%s.%04d.png" % (kw["filename"], f)), kw["width"], kw["height"])
        self.ps = [patch.object(mb, "cmds", self.cmds), patch.object(mb, "_raw_playblast", side_effect=raw),
                   patch.object(mb, "find_ffmpeg", return_value=FFMPEG),
                   patch.object(hook, "_raw_get_panel", return_value=self.focus)]
        self.cmds.setFocus = lambda p: setattr(self, "focus", p)
        for p in self.ps:
            p.start()
        self.targets = [dict(camera="|a:front", panel="p1", rect=(0, 0, 100, 100)),
                        dict(camera="|b:side", panel="p2", rect=(100, 0, 100, 100))]

    def tearDown(self):
        for p in reversed(self.ps):
            p.stop()
        self.tmp.cleanup()

    def opts(self, **kw):
        base = dict(output_path=str(self.dir / "shot.mp4"), mode="mp4", fps=24, width=1913, height=1074,
                    crf=30, preset="ultrafast", start_frame=1, end_frame=2, open_after=False)
        base.update(kw)
        return base

    def test_combine_and_keep_each_odd(self):
        ok, msg, out = mu.run(self.targets, combine=True, keep_individuals=True, **self.opts())
        self.assertTrue(ok, msg)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["shot_Multi.mp4", "shot_front.mp4", "shot_side.mp4"])
        self.assertEqual(probe(self.dir / "shot_Multi.mp4")[:2], (1914, 1074))      # 合成は偶数キャンバス
        for n in ("shot_front.mp4", "shot_side.mp4"):
            self.assertEqual(probe(self.dir / n)[:2], (1914, 1074))                  # 個別も 1px 足して偶数

    def test_combine_only_odd_and_restore(self):
        self.cmds.time = 42
        ok, msg, out = mu.run(self.targets, combine=True, keep_individuals=False, **self.opts(width=641, height=359))
        self.assertTrue(ok, msg)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["shot_Multi.mp4"])
        self.assertEqual(probe(out)[:2], (642, 360))
        self.assertEqual((self.cmds.time, self.focus), (42, "元のパネル"))

    def test_keep_each_only_odd(self):
        ok, msg, out = mu.run(self.targets, combine=False, keep_individuals=True, **self.opts(width=3, height=5))
        self.assertTrue(ok, msg)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["shot_front.mp4", "shot_side.mp4"])
        for n in ("shot_front.mp4", "shot_side.mp4"):
            self.assertEqual(probe(self.dir / n)[:2], (4, 6))

    def test_even_request_unchanged(self):
        ok, msg, out = mu.run(self.targets, **self.opts(width=640, height=360))
        self.assertTrue(ok, msg)
        self.assertEqual(probe(self.dir / "shot_Multi.mp4")[:2], (640, 360))
        self.assertEqual(probe(self.dir / "shot_front.mp4")[:2], (640, 360))

    def test_invalid_size_stops_before_capture(self):
        for bad in (0, -3, float("nan")):
            ok, msg, rec = mu.run(self.targets, **self.opts(width=bad))
            self.assertFalse(ok)
            self.assertEqual(list(self.dir.iterdir()), [])
            self.assertEqual(self.cmds.set_log, [])

    def test_existing_output_is_protected(self):
        old = self.dir / "shot_Multi.mp4"
        old.write_bytes(b"precious")
        ok, msg, _ = mu.run(self.targets, **self.opts())
        self.assertFalse(ok)
        self.assertEqual(old.read_bytes(), b"precious")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["shot_Multi.mp4"])

    # ---- 追指示1-1: Multi の合成動画も寸法を確認できなければ公開しない -------------------
    def test_combined_probe_none_is_failure_and_keeps_recovery(self):
        real = mb.probe_video_size
        # 個別動画の確認は通し、合成の確認だけ「読めない」にする
        with patch.object(mb, "probe_video_size", side_effect=lambda ff, path, **k: None if "_Multi" in path else real(ff, path, **k)):
            ok, msg, recovery = mu.run(self.targets, combine=True, keep_individuals=True, **self.opts())
        self.assertFalse(ok)
        self.assertIn("確認できません", msg)
        names = sorted(p.name for p in self.dir.iterdir())
        self.assertEqual(len(names), 1)                                      # 公開物なし(recovery だけ)
        self.assertTrue(names[0].startswith(".plsMulti-"))
        self.assertTrue(any(f.name == "shot_Multi.mp4" for f in Path(recovery).rglob("*")))   # 保全されている
        self.assertEqual(self.focus, "元のパネル")                              # フォーカスは戻る

    def test_combined_probe_wrong_size_is_failure(self):
        real = mb.probe_video_size
        with patch.object(mb, "probe_video_size", side_effect=lambda ff, path, **k: (10, 10) if "_Multi" in path else real(ff, path, **k)):
            ok, msg, recovery = mu.run(self.targets, combine=True, keep_individuals=True, **self.opts())
        self.assertFalse(ok)
        self.assertIn("想定", msg)
        self.assertEqual([p.name for p in self.dir.iterdir() if not p.name.startswith(".plsMulti-")], [])

    # ---- 追指示1-3: 撮影・時刻変更・フォルダ作成の前に弾く ------------------------------
    def test_invalid_encode_values_stop_before_capture(self):
        for kw in (dict(fps=0), dict(fps=2000), dict(fps=-24), dict(crf=99), dict(preset="bogus"),
                   dict(start_frame=5, end_frame=1)):
            with self.subTest(kw=kw):
                ok, msg, rec = mu.run(self.targets, combine=True, **self.opts(**kw))
                self.assertFalse(ok)
                self.assertIn("設定値が不正", msg)
                self.assertEqual(self.calls, [])                              # 撮影していない
                self.assertEqual(self.cmds.set_log, [])
                self.assertEqual(list(self.dir.iterdir()), [])                # フォルダ内に何も作っていない

    def test_maya_mode_combine_checks_encode_values_but_not_without_combine(self):
        with patch.object(mb, "_maya_playblast_options", return_value={}):
            ok, msg, _ = mu.run(self.targets, combine=True, **self.opts(mode="maya", crf=99))
            self.assertFalse(ok)                                              # 標準 + Combine は ffmpeg を使う
            self.assertEqual(self.calls, [])
            self.assertEqual(list(self.dir.iterdir()), [])
        # Combine なしの Maya 標準は ffmpeg を使わないので crf / preset / fps は検査しない
        with patch.object(mb, "scene_fps", return_value=24.0):
            n = mb.normalize_settings(640, 360, 0, 99, "bogus", 1, 2, need_encode=False)
            self.assertEqual((n["start_frame"], n["end_frame"]), (1, 2))

    def test_fps_none_is_scene_fps_and_zero_is_not_replaced(self):
        with patch.object(mb, "scene_fps", return_value=30.0):
            ok, msg, out = mu.run(self.targets, **self.opts(fps=None, width=640, height=360))
            self.assertTrue(ok, msg)
            self.assertIn("30", subprocess.run([FFMPEG, "-hide_banner", "-i", str(self.dir / "shot_Multi.mp4")],
                                               stderr=subprocess.PIPE).stderr.decode())
        n_before = len(self.calls)
        ok, msg, _ = mu.run(self.targets, **self.opts(fps=0, output_path=str(self.dir / "zero.mp4")))
        self.assertFalse(ok)                                                  # 0 を黙ってシーン値にしない
        self.assertEqual(len(self.calls), n_before)

    def test_fractional_range_multi_is_rounded(self):
        ok, msg, out = mu.run(self.targets, combine=False, keep_individuals=True,
                              **self.opts(width=640, height=360, start_frame=1.4, end_frame=2.6))
        self.assertTrue(ok, msg)                                              # 単独と同じく四捨五入(1..3)
        self.assertEqual({(c["startTime"], c["endTime"]) for c in self.calls}, {(1, 3)})

    def test_layout_cells_stays_strict(self):
        for wh in ((321, 180), (320, 181), (0, 180)):
            with self.assertRaises(ValueError):
                mu.layout_cells([(0, 0, 100, 100), (100, 0, 100, 100)], *wh)


if __name__ == "__main__":
    unittest.main(argv=[sys.argv[0]], verbosity=2)
