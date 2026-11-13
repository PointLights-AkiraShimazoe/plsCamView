# -*- coding: utf-8 -*-
u"""
plsCamView.mp4blast
===================
このビューを対象に Playblast を実行し、ffmpeg で MP4(H.264) に変換する。

    from plsCamView import mp4blast
    ok, msg, path = mp4blast.run("modelPanel4", output_path=None, width=1920, ...)

Playblaster(playblast_to_mp4.py)と同じ流れ:
    1. ffmpeg と出力先を事前確認(無駄な PNG 生成を防ぐ)
    2. 必要なら「ビューポート最適化」(画角をレンダー枠に固定 / Polygon のみ /
       Use All Lights / SSAO・lineAA・MSAA = ON)を適用
    3. PNG 連番を一時フォルダへ playblast
    4. ffmpeg で MP4 化
    5. 実行前の状態へ復帰、一時ファイル削除

ffmpeg は **パッケージ同梱の bin/ffmpeg.exe (bin/ffmpeg) のみ**を使う
(環境ごとの PATH や版の違いに依存させないため)。引数 ffmpeg_path は
テスト用の明示指定としてだけ残している。

mode:
    "mp4"  … PNG 連番 → ffmpeg で MP4
    "maya" … Maya 標準の Playblast 設定(形式 / 圧縮 / 保存先の既定)で撮る。
             幅・高さ・品質・装飾・オフスクリーン・出力先・ビューポート最適化は
             ツールボックスの値で上書きする。

対象パネルは常に引数で明示する(アクティブビューには依存しない)。
"""
from __future__ import absolute_import

import glob
import os
import shutil
import subprocess
import sys
import tempfile
import uuid

try:
    from maya import cmds
except Exception:                                   # Maya 外
    cmds = None

from . import blastsize
from .i18n import tr

_TAG = u"[plsCamView]"

PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
           "medium", "slow", "slower", "veryslow"]

# ビューポート最適化で操作する modelEditor の表示フラグ
_VIEWPORT_SHOW_FLAGS = [
    "nurbsCurves", "nurbsSurfaces", "controlVertices", "hulls",
    "polymeshes", "subdivSurfaces", "planes", "lights", "cameras",
    "imagePlane", "joints", "ikHandles", "deformers", "dynamics",
    "fluids", "hairSystems", "follicles", "nCloths", "nParticles",
    "nRigids", "dynamicConstraints", "locators", "dimensions",
    "pivots", "handles", "textures", "strokes", "motionTrails",
    "pluginShapes", "clipGhosts", "greasePencils", "particleInstancers",
    "grid", "manipulators",
]

# hardwareRenderingGlobals で playblast 中に 1 へ変更する属性
_HWR_ATTRS = ["ssaoEnable", "lineAAEnable", "multiSampleEnable"]

# 画角をレンダー枠(解像度ゲート)に固定するためのカメラ属性
_CAM_GATE_APPLY = [
    ("displayResolution", 1),
    ("overscan", 1.0),
    ("displayGateMask", 0),
    ("displayGateMaskOpacity", 0),
    ("displayFilmGate", 0),
    ("displaySafeAction", 0),
    ("displaySafeTitle", 0),
    ("displayFieldChart", 0),
]

_FPS_MAP = {
    "game": 15, "film": 24, "pal": 25, "ntsc": 30,
    "show": 48, "palf": 50, "ntscf": 60,
    "23.976fps": 23.976, "29.97fps": 29.97, "59.94fps": 59.94,
    "24fps": 24, "25fps": 25, "30fps": 30, "48fps": 48,
    "50fps": 50, "60fps": 60,
}


# ==========================================================================
#  ffmpeg
# ==========================================================================
def package_dir():
    return os.path.dirname(os.path.abspath(__file__))


def bundled_ffmpeg_path():
    u"""同梱 ffmpeg の「置くべき場所」(存在しなくても返す)。"""
    name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    return os.path.join(package_dir(), "bin", name)


def find_ffmpeg(ffmpeg_path=""):
    u"""
    同梱 ffmpeg の絶対パスを返す。無ければ None。
    ffmpeg_path はテスト用の明示指定(フルパスで実在するときだけ使う)。
    """
    p = (ffmpeg_path or "").strip()
    if p and os.path.isfile(p):
        return os.path.abspath(p)
    base = package_dir()
    for c in (
        os.path.join(base, "bin", "ffmpeg.exe"),
        os.path.join(base, "bin", "ffmpeg"),
    ):
        if os.path.isfile(c):
            return os.path.abspath(c)
    return None


def ffmpeg_status_text(ffmpeg_path=""):
    u"""ログ用: 解決結果を短い文にする。"""
    found = find_ffmpeg(ffmpeg_path)
    if not found:
        return u"ffmpeg が見つかりません → {} に置いてください".format(bundled_ffmpeg_path())
    return u"ffmpeg: {}".format(found)


# ==========================================================================
#  シーン情報
# ==========================================================================
def scene_fps():
    if cmds is None:
        return 30.0
    try:
        unit = cmds.currentUnit(q=True, time=True)
    except Exception:
        return 30.0
    if unit in _FPS_MAP:
        return float(_FPS_MAP[unit])
    if unit.endswith("fps"):
        try:
            return float(unit[:-3])
        except ValueError:
            pass
    return 30.0


def frame_range():
    if cmds is None:
        return 1, 24
    try:
        return (int(cmds.playbackOptions(q=True, min=True)),
                int(cmds.playbackOptions(q=True, max=True)))
    except Exception:
        return 1, 24


def _scene_base_name():
    name = ""
    if cmds is not None:
        try:
            name = cmds.file(q=True, sceneName=True, shortName=True) or ""
        except Exception:
            name = ""
    name = os.path.splitext(os.path.basename(name))[0]
    return name or "untitled"


def default_output_dir():
    u"""プロジェクトの movies ディレクトリ(無ければプロジェクトルート)。"""
    root = ""
    if cmds is not None:
        try:
            root = cmds.workspace(q=True, rootDirectory=True) or ""
        except Exception:
            root = ""
        rule = ""
        try:
            rule = cmds.workspace(fileRuleEntry="movie") or ""
        except Exception:
            rule = ""
        if root:
            d = os.path.join(root, rule) if rule else root
            return os.path.normpath(d)
    return os.path.normpath(os.path.expanduser("~"))


def default_output_path(camera=None):
    u"""出力先が空のときに使う既定パス: <movies>/<scene>_<camera>.mp4"""
    cam = (camera or "camera").replace("|", "_").replace(":", "_")
    fname = u"{}_{}.mp4".format(_scene_base_name(), cam)
    return os.path.join(default_output_dir(), fname).replace("\\", "/")


# ==========================================================================
#  出力先の確認
# ==========================================================================
def check_output_writable(output_path, overwrite_readonly=False):
    import stat as _stat
    out = output_path.replace("\\", "/")
    out_dir = os.path.dirname(out)
    try:
        if out_dir and not os.path.isdir(out_dir):
            os.makedirs(out_dir)
    except Exception as e:
        return False, tr(u"出力フォルダを作成できません: {} ({})").format(out_dir, e)

    if os.path.exists(out):
        if not os.access(out, os.W_OK):
            if overwrite_readonly:
                try:
                    os.chmod(out, _stat.S_IWRITE | _stat.S_IREAD)
                except Exception as e:
                    return False, tr(u"読み取り専用を解除できません: {} ({})").format(out, e)
            else:
                return False, (tr(u"出力ファイルが読み取り専用です(チェックアウト漏れ?): {}")
                               .format(out))
        try:
            f = open(out, "a")
            f.close()
        except Exception as e:
            return False, tr(u"出力ファイルを開けません(他アプリで使用中?): {} ({})").format(out, e)
    else:
        try:
            # 書込み確認は一意な一時ファイルで行う(固定名だと、同名の既存ファイルを壊しかねない)
            fd, test = tempfile.mkstemp(prefix=".plswtest-", suffix=".tmp", dir=out_dir or ".")
            os.close(fd)
            os.remove(test)
        except Exception as e:
            return False, tr(u"出力フォルダに書き込めません: {} ({})").format(out_dir, e)
    return True, u""


# ==========================================================================
#  ビューポート最適化(保存 / 適用 / 復帰)
# ==========================================================================
def _panel_camera_shape(panel):
    try:
        cam = cmds.modelEditor(panel, q=True, camera=True)
    except Exception:
        return None
    if not cam:
        return None
    try:
        if cmds.objectType(cam) == "camera":
            return cam
        shapes = cmds.listRelatives(cam, shapes=True, type="camera", fullPath=True) or []
        return shapes[0] if shapes else None
    except Exception:
        return None


# --------------------------------------------------------------------------
#  From Render Settings(レンダー解像度・ゲート一致の書き出し)  0.2.16
#  Maya 標準 Playblast の「Display size: From Render Settings」と同じ意味。
#  サイズを defaultResolution に合わせ、オーバースキャン 1.0・解像度ゲート表示・
#  パン/ズーム無効にして、書き出し範囲 = レゾリューションゲートにする。
# --------------------------------------------------------------------------
_FINAL_FRAME_ATTRS = [("overscan", 1.0), ("displayResolution", 1), ("panZoomEnabled", 0)]


def render_settings_size():
    u"""レンダー設定の解像度 (width, height)。"""
    try:
        return int(cmds.getAttr("defaultResolution.width")), int(cmds.getAttr("defaultResolution.height"))
    except Exception:
        return 1920, 1080


def apply_final_frame(panel):
    u"""パネルのカメラをレンダー枠に固定し、復帰用の (camShape, originals) を返す。"""
    cam_shape = _panel_camera_shape(panel)
    if not cam_shape:
        return None
    originals = {}
    for attr, value in _FINAL_FRAME_ATTRS:
        try:
            if not cmds.attributeQuery(attr, node=cam_shape, exists=True):
                continue
            originals[attr] = cmds.getAttr(cam_shape + "." + attr)
            cmds.setAttr(cam_shape + "." + attr, value)
        except Exception:
            continue
    return (cam_shape, originals) if originals else None


def restore_final_frame(state):
    u"""最終フレーム用に変えたカメラ属性を元へ戻す。

    1 件の失敗で残りを止めない。戻せなかったものは黙って捨てず、まとめて警告する
    （黙殺すると撮影用の設定がユーザーのカメラに残ったままになる）。
    """
    if not state:
        return []
    cam_shape, originals = state
    failed = []
    for attr, value in originals.items():
        plug = cam_shape + "." + attr
        try:
            cmds.setAttr(plug, value)
        except Exception as e:
            failed.append(u"{}: {}".format(plug, e))
    if failed:
        _warn(u"[plsCamView] カメラ設定を元に戻せませんでした（手で確認してください）: "
              + u", ".join(failed))
    return failed


def save_viewport_state(panel):
    state = {"panel": panel, "cam_gate": None, "show_flags": {},
             "display_lights": None, "hwr": {}}
    cam_shape = _panel_camera_shape(panel)
    if cam_shape:
        originals = {}
        for attr, _ in _CAM_GATE_APPLY:
            try:
                if not cmds.attributeQuery(attr, node=cam_shape, exists=True):
                    continue
                originals[attr] = cmds.getAttr(cam_shape + "." + attr)
            except Exception:
                continue
        if originals:
            state["cam_gate"] = (cam_shape, originals)
    for flag in _VIEWPORT_SHOW_FLAGS:
        try:
            state["show_flags"][flag] = cmds.modelEditor(panel, q=True, **{flag: True})
        except Exception:
            pass
    try:
        state["display_lights"] = cmds.modelEditor(panel, q=True, displayLights=True)
    except Exception:
        pass
    for attr in _HWR_ATTRS:
        try:
            state["hwr"][attr] = cmds.getAttr("hardwareRenderingGlobals." + attr)
        except Exception:
            pass
    return state


def apply_optimized_state(state):
    panel = state.get("panel")
    if state.get("cam_gate"):
        cam_shape, originals = state["cam_gate"]
        apply_map = dict(_CAM_GATE_APPLY)
        for attr in originals:
            try:
                cmds.setAttr(cam_shape + "." + attr, apply_map[attr])
            except Exception:
                pass
    for flag in state.get("show_flags", {}):
        try:
            cmds.modelEditor(panel, e=True, **{flag: (flag == "polymeshes")})
        except Exception:
            pass
    if state.get("display_lights") is not None:
        try:
            cmds.modelEditor(panel, e=True, displayLights="all")
        except Exception:
            pass
    for attr in _HWR_ATTRS:
        try:
            cmds.setAttr("hardwareRenderingGlobals." + attr, 1)
        except Exception:
            pass
    try:
        cmds.refresh(force=True)
    except Exception:
        pass


def restore_viewport_state(state):
    u"""save_viewport_state() で退避した表示設定を元へ戻す。

    項目ごとに独立して戻し、1 件の失敗で残りを止めない。戻せなかったものは
    黙って捨てずにまとめて警告する（撮影用の設定がユーザーのビューポートや
    hardwareRenderingGlobals に残ったままになるため）。
    """
    if not state:
        return []
    panel = state.get("panel")
    failed = []
    if state.get("cam_gate"):
        cam_shape, originals = state["cam_gate"]
        for attr, value in originals.items():
            plug = cam_shape + "." + attr
            try:
                cmds.setAttr(plug, value)
            except Exception as e:
                failed.append(u"{}: {}".format(plug, e))
    for flag, value in state.get("show_flags", {}).items():
        try:
            cmds.modelEditor(panel, e=True, **{flag: value})
        except Exception as e:
            failed.append(u"{} {}: {}".format(panel, flag, e))
    if state.get("display_lights") is not None:
        try:
            cmds.modelEditor(panel, e=True, displayLights=state["display_lights"])
        except Exception as e:
            failed.append(u"{} displayLights: {}".format(panel, e))
    for attr, value in state.get("hwr", {}).items():
        plug = "hardwareRenderingGlobals." + attr
        try:
            cmds.setAttr(plug, value)
        except Exception as e:
            failed.append(u"{}: {}".format(plug, e))
    if failed:
        _warn(u"[plsCamView] ビューポート設定を元に戻せませんでした"
              u"（手で確認してください）: " + u", ".join(failed))
    return failed


# ==========================================================================
#  実行
# ==========================================================================
def _raw_playblast(**kw):
    u"""playblast_hook の差し替えを経由せず、元の playblast を呼ぶ。"""
    try:
        from . import playblast_hook as _pbh
    except ImportError:
        return cmds.playblast(**kw)
    return _pbh._raw_playblast(**kw)


def _hidden_window_kwargs():
    kwargs = {}
    if sys.platform.startswith("win"):
        try:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = si
        except Exception:
            pass
    return kwargs


def _make_logger(log):
    def _log(msg):
        text = u"{} {}".format(_TAG, msg)
        if log is not None:
            try:
                log(text)
                return
            except Exception:
                pass
        print(text)
    return _log


def _warn(text):
    try:
        cmds.warning(text)
    except Exception:
        print(text)


def _restore_current_time(saved_time):
    u"""撮影前の現在時刻へ戻す。戻せなければ黙って捨てずに警告し、失敗の一覧を返す。"""
    if saved_time is None:
        return []
    try:
        cmds.currentTime(saved_time, edit=True)
        return []
    except Exception as e:
        failed = [u"currentTime={}: {}".format(saved_time, e)]
        _warn(u"{} 現在時刻を元に戻せませんでした(手で確認してください): ".format(_TAG) + failed[0])
        return failed


def _restore_all(saved_time, ff_state, vp_state):
    u"""撮影のために変えた時刻・カメラ・ビューポートを、互いに独立に元へ戻す(1 件の失敗で止めない)。"""
    for fn, arg in ((_restore_current_time, saved_time),
                    (restore_final_frame, ff_state),
                    (restore_viewport_state, vp_state)):
        try:
            fn(arg)
        except Exception as e:
            _warn(u"{} 復帰処理で例外: {}".format(_TAG, e))
    try:
        cmds.refresh(force=True)
    except Exception:
        pass


def normalize_settings(width=1920, height=1080, fps=None, crf=18, preset="slow",
                       start_frame=None, end_frame=None, from_render_settings=False,
                       need_encode=True, fill_range=True):
    u"""書き出しに使う値を、撮影・時刻変更の前にすべて検査して確定する(単独 / Multi / Maya 標準+Combine 共通)。

    仕様(短く):
      - 幅・高さ: 1〜16384 の整数へ四捨五入(0 / 負 / 非数 / 無限大は失敗)。From Render Settings 時はレンダー設定の値
      - fps: None(未指定)はシーンの fps。0 や負・非数・1000 超は失敗(黙ってシーン値に置き換えない)
      - crf 0〜51 / preset は PRESETS のみ。ffmpeg を使う書き出し(need_encode)のときだけ検査する
      - フレーム範囲: 端数は四捨五入(.5 は切り上げ。単独も Multi も同じ)、終了 < 開始は失敗。
        片方だけ None ならシーン範囲で補う(fill_range=False で両方 None のときは None のまま = Maya 標準の既定範囲)
    不正なら ValueError(撮影・時刻変更・ビューポート変更・フォルダ作成の前に呼ぶこと)。
    Returns: dict(width, height, fps, crf, preset, start_frame, end_frame)
    """
    if from_render_settings:
        width, height = render_settings_size()
    width, height = blastsize.normalize_size(width, height)
    if need_encode:
        fps = blastsize.normalize_fps(scene_fps() if fps is None else fps)
        crf = blastsize.normalize_crf(crf)
        if str(preset) not in PRESETS:
            raise ValueError(u"プリセットが不正です: {!r}".format(preset))
    if start_frame is None and end_frame is None and not fill_range:
        pass
    else:
        if start_frame is None or end_frame is None:
            s, e = frame_range()
            start_frame = s if start_frame is None else start_frame
            end_frame = e if end_frame is None else end_frame
        start_frame, end_frame = blastsize.normalize_range(start_frame, end_frame)
    return dict(width=width, height=height, fps=fps, crf=crf, preset=preset,
                start_frame=start_frame, end_frame=end_frame)


def build_ffmpeg_command(ffmpeg_exe, image_pattern, output_path, fps,
                         start_frame, crf=18, preset="slow", video_filter=""):
    cmd = [
        ffmpeg_exe, "-y",
        "-framerate", str(fps),
        "-start_number", str(int(start_frame)),
        "-i", image_pattern,
    ]
    if video_filter:
        cmd += ["-vf", video_filter]
    cmd += [
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level:v", "4.1",
        "-pix_fmt", "yuv420p",
        "-colorspace", "bt709",
        "-color_primaries", "bt709",
        "-color_trc", "bt709",
        "-preset", str(preset),
        "-crf", str(int(crf)),
        "-x264-params", "keyint=60:min-keyint=60:bframes=3",
        "-movflags", "+faststart",
        output_path.replace("\\", "/"),
    ]
    return cmd


def probe_video_size(ffmpeg_exe, path, timeout=30):
    u"""書き終えた動画の (幅, 高さ)。ffmpeg の出力から読む。読めなければ None。"""
    try:
        proc = subprocess.run([ffmpeg_exe, "-hide_banner", "-nostdin", "-i", path],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=timeout, **_hidden_window_kwargs())
        text = proc.stderr.decode("utf-8", "replace")
    except Exception:
        return None
    return blastsize.parse_video_size(text)


def _part_path(output_path):
    u"""出力と同じフォルダの一時ファイル名(.mp4 で終わる。完成してから置換する)。"""
    folder, name = os.path.split(output_path)
    root = os.path.splitext(name)[0]
    return os.path.join(folder, u".{}.part-{}-{}.mp4".format(root, os.getpid(), uuid.uuid4().hex[:6]))


def encode_png_sequence(ffmpeg_exe, image_pattern, files, output_path, fps,
                        start_frame, crf=18, preset="slow", log=None):
    u"""PNG 連番 → MP4(H.264 / yuv420p)。

    エンコード寸法は「実際に書かれた画像」の寸法から決める(要求した幅・高さではない)。
    奇数なら右 / 下へ黒を足して偶数にする(切り落とし・拡縮なし)。
    一時ファイルへ書き、寸法を確かめてから出力へ置換する(失敗しても既存の出力は触らない)。
    Returns: (ok, message, (width, height))  ※ (width, height) は動画の寸法(失敗時は画像の寸法)
    """
    _log = log or (lambda m: None)
    try:
        actual = blastsize.sequence_size(files)
    except ValueError as e:
        return False, tr(u"画像連番を確認できません: {}").format(e), None
    ew, eh = blastsize.even_size(*actual)
    vf = blastsize.pad_filter(*actual)
    if vf:
        _log(u"画像 {}x{} は奇数のため、右/下に黒を足して {}x{} にします(切り落としなし)".format(
            actual[0], actual[1], ew, eh))
    part = _part_path(output_path)
    cmd = build_ffmpeg_command(ffmpeg_exe, image_pattern, part, fps, start_frame,
                               crf=crf, preset=preset, video_filter=vf)
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                **_hidden_window_kwargs())
        _, err = proc.communicate()
        if proc.returncode != 0:
            try:
                err = err.decode("utf-8", "replace")
            except Exception:
                pass
            _log(u"ffmpeg エラー:\n{}".format(err))
            return False, tr(u"ffmpeg が失敗しました(Script Editor を確認)。"), actual
        if not os.path.isfile(part) or os.path.getsize(part) <= 0:
            return False, tr(u"動画が作成されませんでした。"), actual
        got = probe_video_size(ffmpeg_exe, part)
        if got is None:
            # 寸法を確認できない動画は公開しない(タイムアウト / 読取エラー / 解析不可)。
            # part は finally で消え、既存の出力動画には触れない。
            return False, tr(u"動画の寸法を確認できませんでした(公開しません。既存の動画はそのままです)。"), actual
        if got != (ew, eh):
            return False, tr(u"動画の寸法が想定と違います: {}x{}(想定 {}x{})").format(
                got[0], got[1], ew, eh), actual
        os.replace(part, output_path)
        return True, u"", (ew, eh)
    except Exception as e:
        return False, tr(u"動画を書き出せませんでした: {}").format(e), actual
    finally:
        if os.path.exists(part):
            try:
                os.remove(part)
            except Exception:
                pass


def run(panel, output_path=None, width=1920, height=1080, fps=None,
        crf=18, preset="slow", quality=100, show_ornaments=False,
        off_screen=False, optimize_viewport=True, keep_frames=False,
        ffmpeg_path="", start_frame=None, end_frame=None,
        open_after=True, overwrite_readonly=False, camera=None, log=None,
        mode="mp4", from_render_settings=False):
    u"""
    指定 modelPanel を対象に Playblast を実行する。
    mode="mp4"  … PNG 連番 → ffmpeg(同梱) で MP4
    mode="maya" … Maya 標準の Playblast(形式・圧縮は Maya の Playblast 設定に従う)
    from_render_settings=True … 幅/高さをレンダー設定の解像度にし、オーバースキャン無し・
        パン/ズーム無しで書き出す(= レゾリューションゲートの範囲ぴったり)。width/height は無視。

    寸法: 要求した幅・高さは撮影の前に検査する(0 / 負 / 非数は Maya に触れる前に失敗)。MP4 は
    Maya が実際に書いた画像の寸法から決め、奇数なら右/下に黒を足して偶数にする(切り落とさない)。

    Returns:
        (ok: bool, message: unicode, output_path: str)
    """
    if mode == "maya":
        return run_maya(panel, output_path=output_path, width=width, height=height,
                        quality=quality, show_ornaments=show_ornaments,
                        off_screen=off_screen, optimize_viewport=optimize_viewport,
                        start_frame=start_frame, end_frame=end_frame,
                        open_after=open_after, camera=camera, log=log,
                        from_render_settings=from_render_settings)

    _log = _make_logger(log)

    if cmds is None:
        return False, tr(u"Maya 外では実行できません。"), ""
    if not panel or not cmds.modelPanel(panel, exists=True):
        return False, tr(u"対象パネルが見つかりません。"), ""

    # ---- 入力の検査(Maya の表示や時刻を変える前に済ませる。共通 normalize_settings) ----
    try:
        norm = normalize_settings(width, height, fps, crf, preset, start_frame, end_frame,
                                  from_render_settings=from_render_settings, need_encode=True)
    except ValueError as e:
        msg = tr(u"設定値が不正です: {}").format(e)
        _log(msg)
        return False, msg, output_path or ""
    width, height, fps = norm["width"], norm["height"], norm["fps"]
    crf, preset = norm["crf"], norm["preset"]
    start_frame, end_frame = norm["start_frame"], norm["end_frame"]

    if not output_path:
        if camera is None:
            try:
                camera = cmds.modelEditor(panel, q=True, camera=True)
            except Exception:
                camera = None
        output_path = default_output_path(camera)
    output_path = output_path.replace("\\", "/")
    if not output_path.lower().endswith(".mp4"):
        output_path += ".mp4"

    ffmpeg_exe = find_ffmpeg(ffmpeg_path)
    if not ffmpeg_exe:
        msg = tr(u"同梱の ffmpeg が見つかりません: {} に ffmpeg.exe を置いてください。").format(bundled_ffmpeg_path())
        _log(msg)
        return False, msg, output_path

    ok, msg = check_output_writable(output_path, overwrite_readonly)
    if not ok:
        _log(msg)
        return False, msg, output_path

    temp_dir = tempfile.mkdtemp(prefix="plsCamView_")
    frame_prefix = os.path.join(temp_dir, "frame").replace("\\", "/")
    image_pattern = os.path.join(temp_dir, "frame.%04d.png").replace("\\", "/")

    saved_time = None
    vp_state = None
    ff_state = None
    try:
        try:
            saved_time = cmds.currentTime(q=True)
        except Exception:
            saved_time = None
        if optimize_viewport:
            _log(u"ビューポート最適化を適用(完了後に復帰します)")
            vp_state = save_viewport_state(panel)
            apply_optimized_state(vp_state)
        if from_render_settings:
            ff_state = apply_final_frame(panel)
            _log(u"From Render Settings: {}x{} (オーバースキャン 1.0 / パン・ズーム無効)".format(width, height))

        _log(u"PNG 連番を生成中... ({}-{}, 要求 {}x{})".format(
            start_frame, end_frame, width, height))
        _raw_playblast(
            editorPanelName=panel,
            filename=frame_prefix,
            format="image",
            compression="png",
            width=int(width),
            height=int(height),
            quality=int(quality),
            percent=100,
            viewer=False,
            offScreen=bool(off_screen),
            framePadding=4,
            startTime=start_frame,
            endTime=end_frame,
            forceOverwrite=True,
            showOrnaments=bool(show_ornaments),
            clearCache=True,
        )

        files = sorted(glob.glob(glob.escape(os.path.join(temp_dir, "frame.")) + "*.png"))
        expected = int(end_frame) - int(start_frame) + 1
        if len(files) < expected:
            msg = tr(u"PNG 連番が足りません({}/{} 枚)。取り消された可能性があります。").format(
                len(files), expected)
            _log(msg)
            return False, msg, output_path

        _log(u"ffmpeg で MP4 化中... (crf={}, preset={})".format(crf, preset))
        ok, msg, size = encode_png_sequence(ffmpeg_exe, image_pattern, files, output_path,
                                            fps, start_frame, crf=crf, preset=preset, log=_log)
        if not ok:
            _log(msg)
            return False, msg, output_path

        _log(u"完了: {} ({}x{})".format(output_path, size[0], size[1]))
        if keep_frames:
            _log(u"PNG 連番: {}".format(temp_dir))
        if open_after:
            _open_file(output_path)
        return True, tr(u"完了: {}").format(output_path), output_path

    except Exception as e:
        _log(u"Playblast(MP4) に失敗: {}".format(e))
        return False, tr(u"失敗: {}").format(e), output_path

    finally:
        _restore_all(saved_time, ff_state, vp_state)
        if not keep_frames and os.path.isdir(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)


def _maya_playblast_options():
    u"""Maya の Playblast 設定(optionVar)を playblast の引数にする(playblast_hook と共通)。"""
    try:
        from . import playblast_hook as _pbh
        return dict(_pbh._collect_playblast_options())
    except Exception:
        return {}


def run_maya(panel, output_path=None, width=1920, height=1080, quality=100,
             show_ornaments=False, off_screen=False, optimize_viewport=True,
             start_frame=None, end_frame=None, open_after=True, camera=None,
             log=None, from_render_settings=False):
    u"""
    Maya 標準の Playblast(形式・圧縮・既定の保存先は Maya の Playblast 設定に従う)を、
    ツールボックスの書き出し設定(幅 / 高さ / 品質 / 装飾 / オフスクリーン / 出力先 /
    ビューポート最適化 / 完了後に開く)で上書きして実行する。
    幅・高さは整数に検査して渡す(Maya 標準形式は奇数も書けるので偶数化はしない)。
    """
    _log = _make_logger(log)

    if cmds is None:
        return False, tr(u"Maya 外では実行できません。"), ""
    if not panel or not cmds.modelPanel(panel, exists=True):
        return False, tr(u"対象パネルが見つかりません。"), ""

    try:
        # ffmpeg は使わないので crf / preset / fps は検査しない(Combine 側は multiblast が検査する)
        norm = normalize_settings(width, height, start_frame=start_frame, end_frame=end_frame,
                                  from_render_settings=from_render_settings,
                                  need_encode=False, fill_range=False)
        width, height = norm["width"], norm["height"]
        start_frame, end_frame = norm["start_frame"], norm["end_frame"]
    except ValueError as e:
        msg = tr(u"設定値が不正です: {}").format(e)
        _log(msg)
        return False, msg, output_path or ""

    kw = _maya_playblast_options()
    kw["editorPanelName"] = panel
    kw["widthHeight"] = (int(width), int(height))
    kw["percent"] = 100
    kw["quality"] = int(quality)
    kw["showOrnaments"] = bool(show_ornaments)
    kw["offScreen"] = bool(off_screen)
    kw["viewer"] = bool(open_after)
    if start_frame is not None and end_frame is not None:
        kw["startTime"] = start_frame
        kw["endTime"] = end_frame
    if output_path:
        out = output_path.replace("\\", "/")
        # Maya が形式に応じた拡張子を付けるので、.mp4 / .mov / .avi は外す
        root, ext = os.path.splitext(out)
        if ext.lower() in (".mp4", ".mov", ".avi", ".png", ".jpg", ".tif"):
            out = root
        kw["filename"] = out
        kw["forceOverwrite"] = True
        ok, msg = check_output_writable(out + ".chk")   # フォルダの書き込み可否だけ確認
        if not ok:
            _log(msg)
            return False, msg, out

    saved_time = None
    vp_state = None
    ff_state = None
    try:
        try:
            saved_time = cmds.currentTime(q=True)
        except Exception:
            saved_time = None
        if optimize_viewport:
            _log(u"ビューポート最適化を適用(完了後に復帰します)")
            vp_state = save_viewport_state(panel)
            apply_optimized_state(vp_state)
        if from_render_settings:
            ff_state = apply_final_frame(panel)
            if ff_state:
                _log(u"From Render Settings: {}x{} (オーバースキャン 1.0 / パン・ズーム無効)".format(width, height))
        _log(u"Maya 標準 Playblast を実行: {}x{} format={} compression={}".format(
            width, height, kw.get("format", "(Maya)"), kw.get("compression", "(Maya)")))
        result = _raw_playblast(**kw)
        path = result if isinstance(result, str) else (output_path or u"")
        _log(u"完了: {}".format(path))
        return True, tr(u"完了: {}").format(path), path
    except Exception as e:
        _log(u"Playblast に失敗: {}".format(e))
        return False, tr(u"失敗: {}").format(e), output_path or ""
    finally:
        _restore_all(saved_time, ff_state, vp_state)


def _open_file(path):
    try:
        if sys.platform.startswith("win"):
            os.startfile(path)                          # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except Exception:
        pass


def reveal_folder(path):
    u"""出力先のフォルダをエクスプローラで開く(無ければ存在する親まで遡る)。"""
    p = os.path.normpath(path)
    if os.path.isfile(p):
        p = os.path.dirname(p)
    while p and not os.path.isdir(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    if p and os.path.isdir(p):
        _open_file(p)
