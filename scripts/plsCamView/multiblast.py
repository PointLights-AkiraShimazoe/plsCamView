# -*- coding: utf-8 -*-
"""選択ビューの連続撮影、配置合成、既存出力を保護した公開。"""
from __future__ import absolute_import

import glob
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections import Counter

from . import mp4blast
from .i18n import tr


def camera_suffixes(cameras):
    leaves = [str(c).split("|")[-1] for c in cameras]
    names = [c.rsplit(":", 1)[-1] for c in leaves]
    counts = Counter(n.casefold() for n in names)
    result = []
    for leaf, name in zip(leaves, names):
        value = leaf.rsplit(":", 1)[0] if counts[name.casefold()] > 1 and ":" in leaf else name
        if counts[name.casefold()] > 1 and ":" not in leaf:
            raise ValueError(tr(u"同名カメラにnamespaceがありません: {}").format(leaf))
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
        if not value:
            raise ValueError(tr(u"カメラの出力名を決められません: {}").format(leaf))
        result.append(value)
    folded = [x.casefold() for x in result]
    if len(set(folded)) != len(folded):
        raise ValueError(tr(u"namespaceを使っても出力名が重複します。対象またはnamespaceを変更してください。"))
    return result


def layout_cells(rects, width, height):
    """画面上の対象矩形の位置・比率を、偶数ピクセルの合成枠へ写す。"""
    width, height = int(width), int(height)
    if width < 2 or height < 2 or width % 2 or height % 2:
        raise ValueError(tr(u"合成サイズは2以上の偶数にしてください。"))
    if any(len(r) != 4 or not all(math.isfinite(v) for v in r) or r[2] <= 0 or r[3] <= 0 for r in rects):
        raise ValueError(tr(u"ビューの表示配置を取得できません。ウィンドウを表示してください。"))
    for i, (x, y, w, h) in enumerate(rects):
        for xx, yy, ww, hh in rects[i + 1:]:
            if min(x + w, xx + ww) > max(x, xx) and min(y + h, yy + hh) > max(y, yy):
                raise ValueError(tr(u"合成対象のビューが重なっています。重ならない位置へ移動してください。"))
    left = min(r[0] for r in rects)
    top = min(r[1] for r in rects)
    span_x = max(r[0] + r[2] for r in rects) - left
    span_y = max(r[1] + r[3] for r in rects) - top
    even = lambda v: int(round(v / 2.0)) * 2
    cells = []
    for x, y, w, h in rects:
        a, b = even((x - left) / span_x * width), even((y - top) / span_y * height)
        c, d = even((x + w - left) / span_x * width), even((y + h - top) / span_y * height)
        if c - a < 2 or d - b < 2:
            raise ValueError(tr(u"合成サイズに対して小さすぎるビューがあります。"))
        cells.append((a, b, c - a, d - b))
    return cells


def build_compose_command(ffmpeg, inputs, cells, output, fps, crf=18, preset="slow"):
    args = [ffmpeg, "-hide_banner", "-nostdin", "-y"]
    for source in inputs:
        args.extend(source)
    filters = []
    for i, (_, _, w, h) in enumerate(cells):
        filters.append("[{i}:v]setpts=PTS-STARTPTS,fps={fps},scale={w}:{h}:force_original_aspect_ratio=decrease,"
                       "pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1[v{i}]".format(i=i, fps=fps, w=w, h=h))
    labels = "".join("[v{}]".format(i) for i in range(len(cells)))
    positions = "|".join("{}_{}".format(x, y) for x, y, _, _ in cells)
    filters.append("{}xstack=inputs={}:layout={}:fill=black:shortest=1[out]".format(labels, len(cells), positions))
    args.extend(["-filter_complex", ";".join(filters), "-map", "[out]", "-map", "0:a?",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", str(preset), "-crf", str(int(crf)),
                 "-c:a", "aac", "-movflags", "+faststart", output])
    return args


def _media_input(files, fps, start, end):
    if len(files) == 1 and os.path.splitext(files[0])[1].lower() in (".mp4", ".mov", ".avi", ".qt", ".webm"):
        return ["-i", files[0]]
    frames = []
    for path in files:
        match = re.match(r"^(.*)\.(-?\d+)\.([^.]+)$", path)
        if not match:
            raise ValueError(tr(u"画像連番として認識できません: {}").format(path))
        frames.append((int(match[2]), match[1], match[2], match[3]))
    if sorted(f[0] for f in frames) != list(range(int(start), int(end) + 1)):
        raise ValueError(tr(u"撮影した画像連番に欠落があります。"))
    first = frames[0]
    if any((f[1], f[3]) != (first[1], first[3]) for f in frames):
        raise ValueError(tr(u"画像連番の形式が混在しています。"))
    pattern = "{}.%0{}d.{}".format(first[1], len(first[2]), first[3])
    return ["-framerate", str(fps), "-start_number", str(int(start)), "-i", pattern]


def _encode(command, cancelled, progress):
    kwargs = dict(stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    proc = subprocess.Popen(command, **kwargs)
    try:
        while True:
            try:
                _, err = proc.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                progress(tr(u"合成中"))
                if cancelled():
                    raise RuntimeError(tr(u"合成を取り消しました。"))
        if proc.returncode:
            raise RuntimeError(tr(u"合成に失敗: {}").format(err.decode("utf-8", "replace")[-2000:]))
    finally:
        if proc.poll() is None:
            proc.terminate()
            proc.communicate()


def _publish(source, destination):
    # 事前照合後に別ジョブが作ったファイルも上書きしない。
    created = False
    try:
        with open(source, "rb") as src, open(destination, "xb") as dst:
            created = True
            shutil.copyfileobj(src, dst, 1024 * 1024)
    except Exception:
        if created:
            os.remove(destination)
        raise


def run(targets, combine=True, keep_individuals=True, cancelled=None, progress=None, **options):
    """対象リストは開始時点のpanel/camera/rect。戻り値は単体runと同じ3要素。"""
    cancelled = cancelled or (lambda: False)
    progress = progress or (lambda text: None)
    recovery = ""
    published = []
    saved_time = None
    saved_focus = None
    try:
        if len(targets) < 2:
            raise ValueError(tr(u"複数書き出しには2つ以上の対象が必要です。"))
        suffixes = camera_suffixes([t["camera"] for t in targets])
        if combine and "multi" in [s.casefold() for s in suffixes]:
            raise ValueError(tr(u"カメラ名Multiは合成名と重なります。対象名を変更してください。"))
        mode = options.get("mode", "mp4")
        output = options.get("output_path")
        if output:
            base = os.path.abspath(output)
            if os.path.isdir(base):
                raise ValueError(tr(u"出力先はフォルダーではなくファイル名まで指定してください。"))
            if os.path.splitext(base)[1].lower() in (".mp4", ".mov", ".avi", ".qt", ".webm"):
                base = os.path.splitext(base)[0]
        else:
            base = os.path.join(mp4blast.default_output_dir(), mp4blast._scene_base_name())
        directory = os.path.dirname(base)
        roots = [base + "_" + s for s in suffixes]
        multi = base + "_Multi.mp4"
        desired = list(roots) + ([os.path.splitext(multi)[0]] if combine else [])
        for root in desired:
            if os.path.exists(root) or glob.glob(glob.escape(root) + ".*"):
                raise ValueError(tr(u"出力が既に存在します。別の出力名を指定してください: {}").format(root))
        if not os.path.isdir(directory):
            os.makedirs(directory)
        fps = options.get("fps") or mp4blast.scene_fps()
        if not math.isfinite(float(fps)) or float(fps) <= 0:
            raise ValueError(tr(u"FPSは正の数にしてください。"))
        start, end = mp4blast.frame_range()
        start = options.get("start_frame") if options.get("start_frame") is not None else start
        end = options.get("end_frame") if options.get("end_frame") is not None else end
        if int(start) != start or int(end) != end or end < start:
            raise ValueError(tr(u"複数書き出しの範囲は整数フレームの開始≦終了にしてください。"))
        width, height = (mp4blast.render_settings_size() if options.get("from_render_settings") else
                         (options.get("width", 1920), options.get("height", 1080)))
        cells = layout_cells([t["rect"] for t in targets], width, height) if combine else []
        ffmpeg = mp4blast.find_ffmpeg(options.get("ffmpeg_path", "")) if combine or mode == "mp4" else None
        if (combine or mode == "mp4") and not ffmpeg:
            raise ValueError(tr(u"動画合成にはffmpegが必要です: {}").format(mp4blast.bundled_ffmpeg_path()))
        for t in targets:
            if not t["panel"] or not mp4blast.cmds.modelPanel(t["panel"], exists=True):
                raise ValueError(tr(u"対象ビューが見つかりません: {}").format(t["camera"]))
        saved_time = mp4blast.cmds.currentTime(q=True)
        from . import playblast_hook
        saved_focus = playblast_hook._raw_get_panel(withFocus=True)
        recovery = tempfile.mkdtemp(prefix=".plsMulti-", dir=directory)
        captures, inputs = [], []
        for i, (target, root) in enumerate(zip(targets, roots)):
            progress(tr(u"撮影 {}/{}: {}").format(i + 1, len(targets), target["camera"]))
            if cancelled():
                raise RuntimeError(tr(u"書き出しを取り消しました。"))
            folder = os.path.join(recovery, str(i + 1))
            os.mkdir(folder)
            stem = os.path.join(folder, os.path.basename(root))
            kw = dict(options, output_path=stem + ".mp4", camera=target["camera"],
                      start_frame=start, end_frame=end, open_after=False)
            ok, msg, _ = mp4blast.run(target["panel"], **kw)
            files = sorted(p for p in glob.glob(glob.escape(stem) + ".*") if os.path.isfile(p) and os.path.getsize(p))
            if not ok or not files:
                raise RuntimeError(u"{}: {}".format(target["camera"], msg if not ok else tr(u"出力がありません。")))
            captures.extend(files)
            if combine:
                inputs.append(_media_input(files, mp4blast.scene_fps() if mode == "maya" else fps, start, end))
        if cancelled():
            raise RuntimeError(tr(u"書き出しを取り消しました。"))
        if combine:
            combined = os.path.join(recovery, os.path.basename(multi))
            progress(tr(u"合成中"))
            _encode(build_compose_command(ffmpeg, inputs, cells, combined, fps,
                                         options.get("crf", 18), options.get("preset", "slow")), cancelled, progress)
            if not os.path.isfile(combined) or not os.path.getsize(combined):
                raise RuntimeError(tr(u"合成動画が作成されませんでした。"))
            if cancelled():
                raise RuntimeError(tr(u"書き出しを取り消しました。"))
        publish = (captures if not combine or keep_individuals else []) + ([combined] if combine else [])
        for source in publish:
            destination = os.path.join(directory, os.path.basename(source))
            _publish(source, destination)
            published.append(destination)
        shutil.rmtree(recovery)
        recovery = ""
        result = multi if combine else published[0]
        if options.get("open_after", True):
            mp4blast._open_file(result if combine else directory)
        return True, tr(u"完了 {}件: {}").format(len(published), directory), result
    except Exception as exc:
        detail = u"{}".format(exc)
        if recovery:
            detail += tr(u"\n途中の動画・画像を保全: {}").format(recovery)
        if published:
            detail += tr(u"\n出力済み: {}").format(u", ".join(published))
        return False, detail, recovery
    finally:
        if saved_time is not None:
            try:
                mp4blast.cmds.currentTime(saved_time, edit=True)
            except Exception:
                pass
        if saved_focus:
            try:
                mp4blast.cmds.setFocus(saved_focus)
            except Exception:
                pass
