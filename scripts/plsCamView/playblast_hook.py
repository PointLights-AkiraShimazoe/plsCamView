# -*- coding: utf-8 -*-
u"""
plsCamView.playblast_hook
=========================
「Force Playblast Target」の実装。

Maya の Playblast は "フォーカスのあるパネル" を対象にするため、分離ウィンドウの
ビューは、そこをクリックしていないと Playblast の対象にならない。
ON の間だけ MEL のグローバルプロシージャ `performPlayblast` をラップして、
実行直前に対象パネルへフォーカスを移してからオリジナル処理を呼ぶ。

    install()   : ラップを仕掛ける
                    1. オリジナルの performPlayblast.mel を source して場所を特定
                    2. proc 名を plsCamViewOrig_performPlayblast にリネームした
                       コピーを一時ファイル経由で source(= オリジナルの退避)
                    3. 自前の performPlayblast を定義し、内部で退避版を呼ぶ
    uninstall() : オリジナルの performPlayblast.mel を再 source して完全復元

フォーカス移動が効かない環境のために、二段構えにしている。

    1) ウィンドウをアクティブ化 + `setFocus` でパネルにフォーカスを移す
    2) それでも `getPanel -withFocus` が対象パネルにならない場合は、
       Maya 標準の処理には渡さず、`editorPanelName` を明示した playblast を
       ツール側で実行する(Playblast オプションの設定は optionVar から復元)

いずれの経路を通ったかは Script Editor にログを出す。
"""
from __future__ import absolute_import

import os
import re

try:
    from maya import cmds
    from maya import mel
except Exception:
    cmds = None
    mel = None

from .i18n import tr

_ORIG_PROC = "plsCamViewOrig_performPlayblast"
_TARGET_PROC = "performPlayblast"

# このモジュールの完全修飾名(plsCamView.playblast_hook など)。
# MEL から呼び戻すために使うので、パッケージをどこに置いても動くよう動的に取る。
MODULE_PATH = __name__

_orig_cmds_playblast = None   # maya.cmds.playblast の元関数
_orig_pm_playblast = None     # pymel.core.playblast の元関数
_orig_cmds_getPanel = None    # maya.cmds.getPanel の元関数
_orig_pm_getPanel = None      # pymel.core.getPanel の元関数
_force_active_panel = True    # getPanel(withFocus=True) を差し替えるか

_panel_getter = None       # 引数なしで modelPanel 名を返す callable
_window_activator = None   # 引数なしでツールウィンドウを前面化する callable
_fallback_enabled = True   # auto モードでフォーカス移動失敗時にツール側で実行するか
_mode = "direct"           # "direct" / "auto"
_installed = False
_orig_mel_path = None
_verbose = False   # 詳細ログ(切り分け用)


# ==========================================================================
#  ログ
# ==========================================================================
def _info(msg):
    u"""常に出す情報ログ。"""
    try:
        print(u"[plsCamView] {}".format(msg))
    except Exception:
        pass


def _log(msg):
    u"""詳細ログ(settings の playblastVerbose が True のときだけ出す)。"""
    if not _verbose:
        return
    _info(msg)


def _warn(msg):
    text = u"[plsCamView] {}".format(msg)
    if cmds is not None:
        try:
            cmds.warning(text)
            return
        except Exception:
            pass
    print(text)


# ==========================================================================
#  オリジナル performPlayblast の退避
# ==========================================================================
def _find_orig_mel():
    u"""オリジナル performPlayblast.mel のフルパスを返す(見つからなければ None)。"""
    if mel is None:
        return None
    try:
        mel.eval('source "performPlayblast";')
    except Exception:
        pass
    try:
        info = mel.eval('whatIs "{}";'.format(_TARGET_PROC)) or ""
    except Exception:
        return None
    marker = "found in: "
    if marker not in info:
        _log(u"whatIs performPlayblast -> {}".format(info))
        return None
    path = info.split(marker, 1)[1].strip().replace("\\", "/")
    if not os.path.isfile(path):
        _log(u"performPlayblast.mel が実ファイルとして見つかりません: {}".format(path))
        return None
    return path


def _parse_signature(src):
    u"""
    オリジナルの performPlayblast の宣言から、戻り値型と引数リストを取り出す。

    Maya のバージョンによって
        global proc performPlayblast(int $option)
        global proc string performPlayblast(int $option)
    のように戻り値型が異なり、シグネチャを合わせずに再定義すると
        // Warning: New procedure definition for "performPlayblast" has a
        //          different argument list and/or return type.
    が出てラッパーが正しく呼ばれない。
    """
    m = re.search(
        r"global\s+proc\s+(?:([A-Za-z_][A-Za-z0-9_]*(?:\s*\[\s*\])?)\s+)?"
        r"performPlayblast\s*\(([^)]*)\)", src)
    if not m:
        return {"ret": "", "params": "int $option", "names": ["$option"]}
    ret = (m.group(1) or "").replace(" ", "")
    params = (m.group(2) or "").strip()
    names = re.findall(r"\$\w+", params)
    return {"ret": ret, "params": params, "names": names}


def _default_return(ret):
    r = (ret or "").replace(" ", "")
    if r in ("string[]", "int[]", "float[]", "vector[]"):
        return "{}"
    if r == "string":
        return '""'
    if r == "vector":
        return "<<0,0,0>>"
    if r in ("int", "float"):
        return "0"
    return ""


def _build_wrapper(sig, verbose=False):
    u"""オリジナルとシグネチャを揃えたラッパー MEL を組み立てる。"""
    ret = sig["ret"]
    params = sig["params"] or ""
    names = sig["names"]
    first = names[0] if names else None
    call_args = ", ".join(names)

    if first:
        py_call = ('python("__import__(\'{mod}\', None, None, [\'x\'])'
                   '._on_pre_playblast(" + {first} + ")")').format(
                       mod=MODULE_PATH, first=first)
    else:
        py_call = ('python("__import__(\'{mod}\', None, None, [\'x\'])'
                   '._on_pre_playblast(0)")').format(mod=MODULE_PATH)

    lines = []
    lines.append("global proc {ret}performPlayblast({params})".format(
        ret=(ret + " ") if ret else "", params=params))
    lines.append("{")
    if verbose:
        lines.append('    print("[plsCamView] performPlayblast wrapper entered.\\n");')
    lines.append("    int $plsHandled = 0;")
    lines.append("    $plsHandled = {};".format(py_call))
    if verbose:
        lines.append('    print("[plsCamView] handled=" + $plsHandled + "\\n");')
    if ret:
        lines.append("    if ($plsHandled == 0) {")
        lines.append("        return {}({});".format(_ORIG_PROC, call_args))
        lines.append("    }")
        lines.append("    return {};".format(_default_return(ret)))
    else:
        lines.append("    if ($plsHandled == 0) {")
        lines.append("        {}({});".format(_ORIG_PROC, call_args))
        lines.append("    }")
    lines.append("}")
    return "\n".join(lines)


def _make_backup_proc(orig_path):
    u"""
    performPlayblast.mel を読み、proc 名 performPlayblast を
    plsCamViewOrig_performPlayblast にリネームしたコピーを source する。
    \\b 境界を使うので performPlayblastOptions などは影響を受けない。
    戻り値はオリジナルのシグネチャ情報(失敗時は None)。
    """
    global _found_optvars

    with open(orig_path, "r", encoding="utf-8", errors="replace") as f:
        src = f.read()

    sig = _parse_signature(src)
    try:
        _found_optvars = _extract_optvars(src)
    except Exception:
        _found_optvars = []

    renamed = re.sub(r"\bperformPlayblast\b", _ORIG_PROC, src)
    if _ORIG_PROC not in renamed:
        return None

    tmp_dir = None
    if cmds is not None:
        try:
            tmp_dir = cmds.internalVar(userTmpDir=True)
        except Exception:
            tmp_dir = None
    if not tmp_dir:
        import tempfile
        tmp_dir = tempfile.gettempdir()
    tmp_path = os.path.join(tmp_dir, "plsCamView_performPlayblast_orig.mel").replace("\\", "/")

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(renamed)

    mel.eval('source "{}";'.format(tmp_path))

    info = mel.eval('whatIs "{}";'.format(_ORIG_PROC)) or ""
    ok = ("found in" in info) or ("procedure" in info.lower())
    if not ok:
        _log(u"whatIs {} -> {}".format(_ORIG_PROC, info))

    try:
        os.remove(tmp_path)
    except Exception:
        pass
    return sig if ok else None


# ==========================================================================
#  フォールバック playblast(editorPanelName を明示して実行)
# ==========================================================================
#  (playblast フラグ名, optionVar 名, 型)
#  optionVar 名は実機の performPlayblast.mel から確認したもの
#  (playblastOffscreen は s が小文字。playblast コマンドのフラグは offScreen)
_PB_OPTVARS = [
    ("format",        "playblastFormat",        "str"),
    ("compression",   "playblastCompression",   "str"),
    ("quality",       "playblastQuality",       "int"),
    ("percent",       "playblastScale",         "percent"),
    ("showOrnaments", "playblastShowOrnaments", "bool"),
    ("viewer",        "playblastViewerOn",      "bool"),
    ("offScreen",     "playblastOffscreen",     "bool"),
    ("framePadding",  "playblastPadding",       "int"),
    ("clearCache",    "playblastClearCache",    "bool"),
    ("sequenceTime",  "playblastUseSequenceTime", "bool"),
]

# performPlayblast.mel から実際に読み取った optionVar 名(install 時に記録)
_found_optvars = []


def _extract_optvars(src):
    u"""performPlayblast.mel が参照している optionVar 名を洗い出す(調査用)。"""
    names = set()
    for pat in (r'optionVar\s+-q(?:uery)?\s+"([A-Za-z_][A-Za-z0-9_]*)"',
                r'optionVar\s+-q(?:uery)?\s+([A-Za-z_][A-Za-z0-9_]*)',
                r'`optionVar\s+-ex(?:ists)?\s+"?([A-Za-z_][A-Za-z0-9_]*)"?'):
        for m in re.finditer(pat, src):
            names.add(m.group(1))
    return sorted(names)


def _optvar(name):
    try:
        if cmds.optionVar(exists=name):
            return cmds.optionVar(q=name)
    except Exception:
        pass
    return None


def _collect_playblast_options():
    u"""Maya の Playblast 設定(optionVar)から playblast コマンドの引数を組み立てる。"""
    kw = {}
    for flag, var, kind in _PB_OPTVARS:
        v = _optvar(var)
        if v is None or v == "":
            continue
        try:
            if kind == "int":
                kw[flag] = int(v)
            elif kind == "bool":
                kw[flag] = bool(int(v))
            elif kind == "percent":
                f = float(v)
                kw[flag] = int(round(f * 100.0)) if f <= 1.0 else int(round(f))
            else:
                kw[flag] = v
        except Exception:
            continue

    # 時間範囲(Start/End 指定が ON のときだけ)
    try:
        use_se = _optvar("playblastUseStartEnd")
        if use_se is not None and int(use_se):
            st_ = _optvar("playblastStartTime")
            en_ = _optvar("playblastEndTime")
            if st_ is not None and en_ is not None:
                kw["startTime"] = float(st_)
                kw["endTime"] = float(en_)
    except Exception:
        pass

    # 出力サイズ
    #   playblastDisplaySizeSource
    #       0 = From Window        … 何も渡さない(ビューポートのサイズ)
    #       1 = Custom             … playblastWidth / playblastHeight
    #       2 = From Render Settings … defaultResolution.width / height
    try:
        src = _optvar("playblastDisplaySizeSource")
        src = int(src) if src is not None else 0
        wh = None
        if src == 1:
            pw, ph = _optvar("playblastWidth"), _optvar("playblastHeight")
            if pw and ph and int(pw) > 0 and int(ph) > 0:
                wh = (int(pw), int(ph))
        elif src == 2:
            try:
                wh = (int(cmds.getAttr("defaultResolution.width")),
                      int(cmds.getAttr("defaultResolution.height")))
            except Exception:
                wh = None
        if wh:
            kw["widthHeight"] = wh
    except Exception:
        pass

    # 保存先(「Save to file」が ON のときだけファイル名を渡す)
    try:
        save = _optvar("playblastSaveToFile")
        fname = _optvar("playblastFile")
        if save is not None and int(save) and fname:
            kw["filename"] = fname
            kw["forceOverwrite"] = True
    except Exception:
        pass
    return kw


def _direct_playblast(panel, reason=u""):
    u"""editorPanelName を明示して playblast を実行する(確実にターゲットを固定)。"""
    kw = _collect_playblast_options()
    kw["editorPanelName"] = panel
    if reason:
        _log(reason)
    _info(u"Playblast を実行します(editorPanelName={}): {}".format(panel, kw))
    try:
        result = _raw_playblast(**kw)
        _info(u"Playblast 完了: {}".format(result))
        return True
    except Exception as e:
        _warn(tr(u"Playblast の実行に失敗: {}").format(e))
        return False


# 旧名(互換)
_fallback_playblast = _direct_playblast


# ==========================================================================
#  cmds.playblast / pymel.playblast の差し替え
# ==========================================================================
#  Python で書かれた外部ツール(自作 Playblaster など)は cmds.playblast を
#  直接呼ぶため、MEL の performPlayblast をフックしても捕まえられない。
#  そこで関数自体を差し替え、editorPanelName が未指定なら対象パネルを注入する。
_PANEL_FLAGS = ("editorPanelName", "epn")

#  playblast の query 専用フラグ。これらが指定された呼び出しには
#  editorPanelName を注入してはいけない。
_PB_QUERY_FLAGS = ("activeEditor", "ae", "activeSoundTrack", "ast")

#  `cmds.playblast(activeEditor=True)` は「playblast が実際にキャプチャする
#  エディタ」を返す query で、外部ツールが撮影対象を特定する定番の手段。
#  ここが元のアクティブビューを返すと、撮影前の表示設定の変更だけが
#  別ビューに向かってしまうため、こちらも差し替える。
_ACTIVE_EDITOR_FLAGS = ("activeEditor", "ae")


def _target_panel():
    try:
        if _panel_getter is None:
            return None
        panel = _panel_getter()
        if panel and cmds.modelPanel(panel, exists=True):
            return panel
    except Exception:
        pass
    return None


def _inject_panel(kwargs):
    u"""editorPanelName が無ければ対象パネルを差し込む。差し込んだら True。"""
    if any(k in kwargs for k in _PANEL_FLAGS):
        return False
    if kwargs.get("q") or kwargs.get("query"):
        return False        # query 呼び出しには触らない
    if any(k in kwargs for k in _PB_QUERY_FLAGS):
        return False        # query 専用フラグ付きの呼び出しにも触らない
    panel = _target_panel()
    if not panel:
        return False
    kwargs["editorPanelName"] = panel
    return True


def _active_editor_override(kwargs):
    u"""
    `playblast(activeEditor=True)` に対して、このビューのエディタ名を返す。
    差し替えない場合は None。
    """
    if not _force_active_panel:
        return None
    if not any(kwargs.get(k) for k in _ACTIVE_EDITOR_FLAGS):
        return None
    panel = _target_panel()
    if not panel:
        return None
    # modelPanel はパネル名と同じ名前の modelEditor を持つ。
    # 念のため modelEditor として存在するものを返す。
    try:
        ed = cmds.modelPanel(panel, q=True, modelEditor=True)
        if ed and cmds.modelEditor(ed, exists=True):
            return ed
    except Exception:
        pass
    return panel


#  外部ツールは「アクティブなビューを取得 → そのビューの設定を変更 → playblast」
#  という手順を踏むことが多い。playblast だけ差し替えても、設定変更は元の
#  アクティブビューに向かってしまうため、パネルの取得自体も差し替える。
_WITH_FOCUS_FLAGS = ("withFocus", "wf")


def _patch_get_panel(orig):
    def _patched(*args, **kwargs):
        if _force_active_panel and any(kwargs.get(k) for k in _WITH_FOCUS_FLAGS):
            panel = _target_panel()
            if panel:
                return panel
        return orig(*args, **kwargs)
    _patched.__name__ = "getPanel"
    _patched._plsCamViewPatched = True
    return _patched


_python_patches = []

def _active_original(fn):
    # 他方のツールがまだ外側を使っている場合、解除済みの内側だけを飛ばす。
    while hasattr(fn, "_plsPlayblastState") and not fn._plsPlayblastState["active"]:
        fn = fn._plsPlayblastState["original"]
    return fn

def _patch_function(module, name, factory):
    original = _active_original(getattr(module, name))
    callback = factory(original)
    state = {"active": True, "original": original}
    def wrapped(*args, **kwargs):
        return (callback if state["active"] else original)(*args, **kwargs)
    wrapped.__name__ = name
    wrapped._plsPlayblastState = state
    _python_patches.append((module, name, wrapped, state))
    setattr(module, name, wrapped)
    return original

def _patch_playblast(original):
    def call(*args, **kwargs):
        editor = _active_editor_override(kwargs)
        if editor is not None:
            return editor
        _inject_panel(kwargs)
        return original(*args, **kwargs)
    return call

def _install_python_patch():
    global _orig_cmds_playblast, _orig_pm_playblast
    global _orig_cmds_getPanel, _orig_pm_getPanel
    import maya.cmds as native
    if _orig_cmds_playblast is None:
        _orig_cmds_playblast = _patch_function(native, "playblast", _patch_playblast)
    if _force_active_panel and _orig_cmds_getPanel is None:
        _orig_cmds_getPanel = _patch_function(native, "getPanel", _patch_get_panel)
    try:
        import pymel.core as pm
    except Exception as error:
        _log(u"任意のPyMEL連携を省略: {}".format(error))
        pm = None
    if pm is not None:
        if _orig_pm_playblast is None and hasattr(pm, "playblast"):
            _orig_pm_playblast = _patch_function(pm, "playblast", _patch_playblast)
        if _force_active_panel and _orig_pm_getPanel is None and hasattr(pm, "getPanel"):
            _orig_pm_getPanel = _patch_function(pm, "getPanel", _patch_get_panel)
    return bool(_python_patches)

def _uninstall_python_patch():
    global _orig_cmds_playblast, _orig_pm_playblast
    global _orig_cmds_getPanel, _orig_pm_getPanel
    for module, name, wrapped, state in reversed(_python_patches):
        state["active"] = False
        if getattr(module, name, None) is wrapped:
            setattr(module, name, _active_original(state["original"]))
    _python_patches[:] = []
    _orig_cmds_playblast = _orig_pm_playblast = None
    _orig_cmds_getPanel = _orig_pm_getPanel = None

def _mel_hooks():
    hooks = getattr(cmds, "_plsPlayblastHooks", None)
    if hooks is None:
        hooks = []
        cmds._plsPlayblastHooks = hooks
    return hooks

def _raw_playblast(**kw):
    u"""差し替えを経由せずに playblast を実行する。"""
    fn = _orig_cmds_playblast if _orig_cmds_playblast is not None else cmds.playblast
    return fn(**kw)


def _raw_get_panel(**kw):
    u"""差し替えを経由せずに getPanel を呼ぶ(診断・検証用)。"""
    fn = _orig_cmds_getPanel if _orig_cmds_getPanel is not None else cmds.getPanel
    return fn(**kw)


# ==========================================================================
#  Python 側フック本体(MEL のラッパーから呼ばれる)
# ==========================================================================
def _focus_panel(panel):
    if _window_activator is not None:
        try:
            _window_activator()
        except Exception:
            pass
    try:
        cmds.setFocus(panel)
    except Exception as e:
        _log(u"setFocus に失敗: {}".format(e))
    try:
        return _raw_get_panel(withFocus=True)
    except Exception:
        return None


def _on_pre_playblast(option=0):
    u"""
    MEL のラッパーから呼ばれる。

    戻り値
        0 : Maya 標準の performPlayblast をそのまま続行させる
        1 : ツール側で Playblast を実行済みなので、標準処理は行わない

    モード(settings.playblastMode)
        "direct" : 常に editorPanelName を明示してツール側で実行する(既定)
                   `getPanel -withFocus` が切り替わっても、playblast が実際に見る
                   "active 3D view" は追従しないことがあるため、判定に頼らない。
        "auto"   : フォーカス移動が効いていれば Maya 標準の処理に任せ、
                   効いていないときだけツール側で実行する。
    """
    try:
        _log(u"_on_pre_playblast(option={}) 呼び出し / mode={} / getter={}".format(
            option, _mode, "OK" if _panel_getter else "None"))
        if cmds is None or _panel_getter is None:
            _warn(tr(u"Playblast のターゲット情報が失われています。"
                     u"Force Playblast Target を OFF→ON し直してください。"))
            return 0
        panel = _panel_getter()
        if not panel or not cmds.modelPanel(panel, exists=True):
            _warn(tr(u"対象パネルが見つかりません: {}").format(panel))
            return 0

        # オプションボックス(□)は標準のダイアログを出す。フォーカスだけ移す。
        if int(option) != 0:
            _focus_panel(panel)
            return 0

        cur = _focus_panel(panel)

        if _mode != "auto":
            return 1 if _direct_playblast(panel) else 0

        # --- auto モード ---
        if cur == panel:
            if _verbose:
                _log(u"Playblast のターゲットを {} に切り替えました(標準処理へ)。".format(panel))
            return 0

        _log(u"フォーカスが {} のままです(目標: {})。".format(cur, panel))
        if not _fallback_enabled:
            _warn(tr(u"Playblast のターゲットを強制できませんでした。"
                     u"ツールの [Playblast 実行] ボタンをご利用ください。"))
            return 0
        return 1 if _direct_playblast(panel) else 0
    except Exception as e:
        # ここで例外を投げると Playblast 自体が止まるので握りつぶす
        _log(u"Force Playblast Target の処理に失敗: {}".format(e))
        return 0


# ==========================================================================
#  公開 API
# ==========================================================================
def is_installed():
    return _installed


def set_fallback_enabled(on):
    global _fallback_enabled
    _fallback_enabled = bool(on)


def install(panel_getter, window_activator=None, fallback=True, mode="direct",
            force_active_panel=True, verbose=False):
    u"""
    panel_getter     : 引数なしで modelPanel 名を返す callable
    window_activator : 引数なしでツールウィンドウを前面化する callable(任意)
    mode             : "direct"(常にツール側で実行 / 既定) or "auto"
    force_active_panel : getPanel(withFocus=True) もこのパネルを返すようにするか
    """
    global _panel_getter, _window_activator, _installed, _orig_mel_path
    global _fallback_enabled, _mode, _found_optvars, _force_active_panel, _verbose

    _panel_getter = panel_getter
    _window_activator = window_activator
    _fallback_enabled = bool(fallback)
    _mode = "auto" if str(mode).lower() == "auto" else "direct"
    _force_active_panel = bool(force_active_panel)
    _verbose = bool(verbose)

    # Python 経由(自作ツールなど)の playblast を先に押さえる。
    # MEL のフックが失敗してもこちらは効く。
    _install_python_patch()

    if mel is None:
        return False
    if _installed:
        return True

    try:
        orig = _find_orig_mel()
        if not orig:
            _warn(tr(u"performPlayblast.mel が見つからないため、標準 Playblast のフックを"
                     u"行えませんでした。ツール内の [Playblast 実行] ボタンをご利用ください。"))
            return False
        _orig_mel_path = orig

        sig = _make_backup_proc(orig)
        if not sig:
            _warn(tr(u"performPlayblast の退避に失敗したため、標準 Playblast のフックを"
                     u"行えませんでした。ツール内の [Playblast 実行] ボタンをご利用ください。"))
            return False

        wrapper = _build_wrapper(sig, verbose=_verbose)
        mel.eval(wrapper)
        # 確認に失敗したラッパーを復元先として登録しない。
        info = mel.eval('whatIs "{}";'.format(_TARGET_PROC)) or ""
        hooks = _mel_hooks()
        hooks[:] = [row for row in hooks if row[0] != MODULE_PATH]
        hooks.append((MODULE_PATH, wrapper))
        _installed = True
        _log(u"Force Playblast Target: 標準 Playblast をフックしました。"
             u"(mode={} / module={} / signature='{}performPlayblast({})' / whatIs={})".format(
                 _mode, MODULE_PATH, (sig["ret"] + " ") if sig["ret"] else "",
                 sig["params"], info))
        if _found_optvars:
            _log(u"performPlayblast.mel が参照している optionVar: {}".format(
                ", ".join(_found_optvars)))
        return True
    except Exception as e:
        _warn(tr(u"Playblast フックの導入に失敗: {}").format(e))
        _installed = False
        return False
    finally:
        if not _installed:
            try:
                if _mel_hooks():
                    mel.eval(_mel_hooks()[-1][1])
                elif _orig_mel_path:
                    mel.eval('source "{}";'.format(_orig_mel_path))
            except Exception as restore_error:
                _warn(tr(u"先行ツールのPlayblastフック復元に失敗: {}").format(restore_error))


def uninstall():
    u"""オリジナルの performPlayblast / playblast 関数を復元する。"""
    global _installed, _panel_getter, _window_activator
    _uninstall_python_patch()
    if mel is None:
        _installed = False
        _panel_getter = None
        _window_activator = None
        return True
    if not _installed:
        _panel_getter = None
        _window_activator = None
        return True
    try:
        hooks = _mel_hooks()
        mine = [row for row in hooks if row[0] == MODULE_PATH]
        was_last = bool(hooks and hooks[-1][0] == MODULE_PATH)
        hooks[:] = [row for row in hooks if row[0] != MODULE_PATH]
        if mine and not was_last:
            return True
        if hooks:
            mel.eval(hooks[-1][1])
        elif _orig_mel_path and os.path.isfile(_orig_mel_path):
            mel.eval('source "{}";'.format(_orig_mel_path))
        else:
            mel.eval('source "performPlayblast";')
        _log(u"Force Playblast Target: 標準 Playblast を元に戻しました。")
    except Exception as e:
        _warn(tr(u"Playblast フックの解除に失敗: {}").format(e))
        return False
    finally:
        _installed = False
        _panel_getter = None
        _window_activator = None
    return True


# ==========================================================================
#  ツール内のボタン用
# ==========================================================================
def playblast_now(panel, window_activator=None):
    u"""指定パネルを対象に、Maya 標準の Playblast 設定で実行する。"""
    if cmds is None:
        return False
    if not panel or not cmds.modelPanel(panel, exists=True):
        _warn(tr(u"Playblast の対象パネルが見つかりません。"))
        return False
    if window_activator is not None:
        try:
            window_activator()
        except Exception:
            pass
    try:
        cmds.setFocus(panel)
    except Exception:
        pass
    # ボタンからの実行は常に editorPanelName を明示する(確実にこのビューを撮る)
    return _direct_playblast(panel)


def playblast_options(panel, window_activator=None):
    u"""Playblast のオプションボックスを開く。"""
    if cmds is None or mel is None:
        return False
    try:
        if window_activator is not None:
            try:
                window_activator()
            except Exception:
                pass
        if panel and cmds.modelPanel(panel, exists=True):
            cmds.setFocus(panel)
        mel.eval("performPlayblast 1;")
        return True
    except Exception as e:
        _warn(tr(u"Playblast オプションの表示に失敗: {}").format(e))
        return False


def diagnose(panel):
    u"""Script Editor に現在の状態を出力する(切り分け用)。"""
    patched = []
    try:
        import maya.cmds as _c
        if getattr(_c.playblast, "_plsCamViewPatched", False):
            patched.append("maya.cmds.playblast")
    except Exception:
        pass
    try:
        import pymel.core as _pm
        if getattr(_pm.playblast, "_plsCamViewPatched", False):
            patched.append("pymel.core.playblast")
    except Exception:
        pass
    try:
        import maya.cmds as _c
        if getattr(_c.getPanel, "_plsCamViewPatched", False):
            patched.append("maya.cmds.getPanel")
    except Exception:
        pass
    try:
        import pymel.core as _pm
        if getattr(_pm.getPanel, "_plsCamViewPatched", False):
            patched.append("pymel.core.getPanel")
    except Exception:
        pass

    lines = [u"---- plsCamView / Force Playblast Target 診断 ----",
             u"module        : {}".format(MODULE_PATH),
             u"MEL フック     : {}".format(_installed),
             u"Python 差し替え: {}".format(", ".join(patched) if patched else u"なし"),
             u"mode          : {}".format(_mode),
             u"target panel  : {}".format(panel)]
    if cmds is not None:
        try:
            lines.append(u"playblast 引数 : {}".format(_collect_playblast_options()))
        except Exception:
            pass
    if _found_optvars:
        lines.append(u"mel の optionVar: {}".format(", ".join(_found_optvars)))
        vals = []
        for n in _found_optvars:
            v = _optvar(n)
            if v is not None:
                vals.append(u"{}={}".format(n, v))
        if vals:
            lines.append(u"optionVar の現在値: {}".format(", ".join(vals)))
    if cmds is not None:
        try:
            lines.append(u"panel exists  : {}".format(
                bool(panel and cmds.modelPanel(panel, exists=True))))
        except Exception:
            pass
        try:
            lines.append(u"withFocus(現在): {}".format(_raw_get_panel(withFocus=True)))
        except Exception:
            pass
        try:
            cmds.setFocus(panel)
            lines.append(u"withFocus(setFocus 後): {}".format(
                _raw_get_panel(withFocus=True)))
        except Exception as e:
            lines.append(u"setFocus 失敗: {}".format(e))
    if mel is not None:
        try:
            lines.append(u"whatIs performPlayblast: {}".format(
                mel.eval('whatIs "performPlayblast";')))
        except Exception:
            pass

    # Playblast の起動経路(メニュー/シェルフが何を呼んでいるか)
    if cmds is not None:
        for name in ("PlayblastWindow", "PlayblastWindowOptions", "Playblast",
                     "PlayblastOptions"):
            try:
                if cmds.runTimeCommand(name, exists=True):
                    lang = cmds.runTimeCommand(name, q=True, commandLanguage=True)
                    cmd = cmds.runTimeCommand(name, q=True, command=True)
                    lines.append(u"runTimeCommand {} ({}): {}".format(name, lang, cmd))
            except Exception:
                continue

    lines.append(u"※ Playblast を実行しても『performPlayblast ラッパーに入りました』が"
                 u"出ない場合、その起動経路は performPlayblast を通っていません。")
    text = u"\n".join(lines)
    print(text)
    return text
