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

import os
import shutil
import subprocess
import sys
import tempfile

try:
    from maya import cmds
except Exception:                                   # Maya 外
    cmds = None

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
            test = out + ".__wtest__"
            with open(test, "w") as f:
                f.write("")
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
    if not state:
        return
    cam_shape, originals = state
    for attr, value in originals.items():
        try:
            cmds.setAttr(cam_shape + "." + attr, value)
        except Exception:
            pass


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
    if not state:
        return
    panel = state.get("panel")
    if state.get("cam_gate"):
        cam_shape, originals = state["cam_gate"]
        for attr, value in originals.items():
            try:
                cmds.setAttr(cam_shape + "." + attr, value)
            except Exception:
                pass
    for flag, value in state.get("show_flags", {}).items():
        try:
            cmds.modelEditor(panel, e=True, **{flag: value})
        except Exception:
            pass
    if state.get("display_lights") is not None:
        try:
            cmds.modelEditor(panel, e=True, displayLights=state["display_lights"])
        except Exception:
            pass
    for attr, value in state.get("hwr", {}).items():
        try:
            cmds.setAttr("hardwareRenderingGlobals." + attr, value)
        except Exception:
            pass


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


def build_ffmpeg_command(ffmpeg_exe, image_pattern, output_path, fps,
                         start_frame, crf=18, preset="slow"):
    return [
        ffmpeg_exe, "-y",
        "-framerate", str(fps),
        "-start_number", str(int(start_frame)),
        "-i", image_pattern,
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

    def _log(msg):
        text = u"{} {}".format(_TAG, msg)
        if log is not None:
            try:
                log(text)
                return
            except Exception:
                pass
        print(text)

    if cmds is None:
        return False, tr(u"Maya 外では実行できません。"), ""
    if not panel or not cmds.modelPanel(panel, exists=True):
        return False, tr(u"対象パネルが見つかりません。"), ""

    if fps is None:
        fps = scene_fps()
    if start_frame is None or end_frame is None:
        s, e = frame_range()
        start_frame = s if start_frame is None else start_frame
        end_frame = e if end_frame is None else end_frame

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
        msg = tr(u"同梱の ffmpeg が見つかりません: {} に ffmpeg.exe を置いてください。").format(
            bundled_ffmpeg_path())
        _log(msg)
        return False, msg, output_path

    ok, msg = check_output_writable(output_path, overwrite_readonly)
    if not ok:
        _log(msg)
        return False, msg, output_path

    temp_dir = tempfile.mkdtemp(prefix="plsCamView_")
    frame_prefix = os.path.join(temp_dir, "frame").replace("\\", "/")
    image_pattern = os.path.join(temp_dir, "frame.%04d.png").replace("\\", "/")

    vp_state = None
    if optimize_viewport:
        _log(u"ビューポート最適化を適用(完了後に復帰します)")
        vp_state = save_viewport_state(panel)
        apply_optimized_state(vp_state)
    ff_state = None
    if from_render_settings:
        width, height = render_settings_size()
        ff_state = apply_final_frame(panel)
        _log(u"From Render Settings: {}x{} (オーバースキャン 1.0 / パン・ズーム無効)".format(width, height))

    try:
        _log(u"PNG 連番を生成中... ({}-{}, {}x{})".format(
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

        cmd = build_ffmpeg_command(ffmpeg_exe, image_pattern, output_path,
                                   fps, start_frame, crf=crf, preset=preset)
        _log(u"ffmpeg で MP4 化中... (crf={}, preset={})".format(crf, preset))
        kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if sys.platform.startswith("win"):
            try:
                si = subprocess.STARTUPINFO()
                si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                kwargs["startupinfo"] = si
            except Exception:
                pass
        proc = subprocess.Popen(cmd, **kwargs)
        _, err = proc.communicate()
        if proc.returncode != 0:
            try:
                err = err.decode("utf-8", "replace")
            except Exception:
                pass
            _log(u"ffmpeg エラー:\n{}".format(err))
            return False, tr(u"ffmpeg が失敗しました(Script Editor を確認)。"), output_path

        _log(u"完了: {}".format(output_path))
        if keep_frames:
            _log(u"PNG 連番: {}".format(temp_dir))
        if open_after:
            _open_file(output_path)
        return True, tr(u"完了: {}").format(output_path), output_path

    except Exception as e:
        _log(u"Playblast(MP4) に失敗: {}".format(e))
        return False, tr(u"失敗: {}").format(e), output_path

    finally:
        restore_final_frame(ff_state)
        if vp_state:
            restore_viewport_state(vp_state)
        try:
            cmds.refresh(force=True)
        except Exception:
            pass
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
    """
    def _log(msg):
        text = u"{} {}".format(_TAG, msg)
        if log is not None:
            try:
                log(text)
                return
            except Exception:
                pass
        print(text)

    if cmds is None:
        return False, tr(u"Maya 外では実行できません。"), ""
    if not panel or not cmds.modelPanel(panel, exists=True):
        return False, tr(u"対象パネルが見つかりません。"), ""

    kw = _maya_playblast_options()
    kw["editorPanelName"] = panel
    if from_render_settings:
        width, height = render_settings_size()
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

    vp_state = None
    if optimize_viewport:
        _log(u"ビューポート最適化を適用(完了後に復帰します)")
        vp_state = save_viewport_state(panel)
        apply_optimized_state(vp_state)
    ff_state = apply_final_frame(panel) if from_render_settings else None
    if ff_state:
        _log(u"From Render Settings: {}x{} (オーバースキャン 1.0 / パン・ズーム無効)".format(width, height))
    try:
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
        restore_final_frame(ff_state)
        if vp_state:
            restore_viewport_state(vp_state)
        try:
            cmds.refresh(force=True)
        except Exception:
            pass


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
