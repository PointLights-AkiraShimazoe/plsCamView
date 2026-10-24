# -*- coding: utf-8 -*-
u"""
plsCamView.viewport
===================
Maya の modelPanel の生成 / カメラ切替 / 表示フラグ制御。

【重要な設計上の制約】
    modelPanel は Maya の UI ツリーに属していなければならない。
    Qt 側で別のウィンドウ(QMainWindow など)へ付け替えると、Maya が組み立てる
    UI フルパスが壊れ、

        // Error: updateModelPanelBar plsCamViewWindow||paneLayout10|modelPanel10;
        // Error: Line 1.38: Syntax error

    のようにアイコンバー(ツールセット)やメニューの更新が失敗する。
    そのため、このツールではウィンドウ自体を Maya の `cmds.window` で作り、
    modelPanel は Maya のレイアウト(paneLayout)の子のまま扱う。
    Qt はツールボックス側の描画にだけ使う。
"""
from __future__ import absolute_import

try:
    from maya import cmds
except Exception:
    cmds = None

from .i18n import tr


# ==========================================================================
#  カメラ
# ==========================================================================
def list_cameras(include_startup=True):
    u"""シーン内のカメラ(transform 名)を返す。"""
    if cmds is None:
        return []
    try:
        cams = cmds.listCameras(perspective=True) or []
        cams += cmds.listCameras(orthographic=True) or []
    except Exception:
        cams = []

    out = []
    for c in cams:
        if not include_startup and is_startup_camera(c):
            continue
        if c not in out:
            out.append(c)
    return out


def is_startup_camera(cam):
    u"""persp / top / front / side などの起動時カメラか。"""
    if cmds is None:
        return False
    try:
        shape = cam
        if cmds.objectType(cam) == "transform":
            shapes = cmds.listRelatives(cam, shapes=True, fullPath=False) or []
            if shapes:
                shape = shapes[0]
        return bool(cmds.camera(shape, q=True, startupCamera=True))
    except Exception:
        return False


def camera_exists(cam):
    if cmds is None or not cam:
        return False
    try:
        return bool(cmds.objExists(cam))
    except Exception:
        return False


# ==========================================================================
#  Show プリセット
# ==========================================================================
SHOW_PRESETS = {
    "all":     u"All",
    "none":    u"None",
    "polygon": u"Polygon",
}

# 「Polygon」で ON にするフラグ
_POLYGON_ONLY_FLAGS = ["polymeshes"]

# 別スイッチで制御するフラグ(プリセット適用後に上書き)
EXTRA_FLAGS = {
    "showJoints":      "joints",
    "showNurbsCurves": "nurbsCurves",
}


def _pick_source_panel():
    u"""
    コピー元にする既存の modelPanel を選ぶ。
    modelPanel の -copy フラグは Maya 標準の Tear Off Copy と同じ仕組みで、
    メニュー構成・ツールセット・表示設定をそのまま引き継いだパネルを作れる。
    """
    if cmds is None:
        return None
    try:
        p = cmds.getPanel(withFocus=True)
        if p and cmds.getPanel(typeOf=p) == "modelPanel":
            return p
    except Exception:
        pass
    try:
        for p in (cmds.getPanel(type="modelPanel") or []):
            try:
                if cmds.modelPanel(p, q=True, exists=True):
                    return p
            except Exception:
                continue
    except Exception:
        pass
    return None


class ModelViewport(object):
    u"""Maya のレイアウト配下に作る modelPanel のラッパー。"""

    def __init__(self, parent_layout, label=u"plsCamView", use_copy=True, copy_from=None):
        u"""
        copy_from : 複製元の modelPanel 名(ポップアウト / 再ドッキングで表示設定を引き継ぐ)。
                    None なら、use_copy に従ってフォーカス中のパネルを複製元にする。
        """
        self._parent = parent_layout
        self._label = label
        self._use_copy = bool(use_copy)
        self._copy_from = copy_from
        self._panel = None
        self._editor = None
        self._create()

    # ------------------------------------------------------------------
    def _create(self):
        if cmds is None:
            return
        kwargs = {"label": self._label, "parent": self._parent, "menuBarVisible": True}
        src = None
        if self._copy_from:
            try:
                if cmds.modelPanel(self._copy_from, exists=True):
                    src = self._copy_from
            except Exception:
                src = None
        if src is None and self._use_copy:
            src = _pick_source_panel()
        if src:
            try:
                self._panel = cmds.modelPanel(copy=src, **kwargs)
            except Exception:
                self._panel = None
        if not self._panel:
            self._panel = cmds.modelPanel(**kwargs)

        try:
            cmds.modelPanel(self._panel, e=True, menuBarVisible=True)
        except Exception:
            pass

        # アイコンバー(ツールセット)を確実に展開しておく
        try:
            bar = cmds.modelPanel(self._panel, q=True, barLayout=True)
            if bar:
                cmds.frameLayout(bar, e=True, collapse=False)
        except Exception:
            pass

        try:
            self._editor = cmds.modelPanel(self._panel, q=True, modelEditor=True)
        except Exception:
            self._editor = self._panel

    # ------------------------------------------------------------------
    @property
    def panel(self):
        return self._panel

    @property
    def editor(self):
        return self._editor

    def is_valid(self):
        if cmds is None or not self._panel:
            return False
        try:
            return bool(cmds.modelPanel(self._panel, exists=True))
        except Exception:
            return False

    def destroy(self):
        if cmds is None or not self._panel:
            return
        try:
            if cmds.modelPanel(self._panel, exists=True):
                cmds.deleteUI(self._panel, panel=True)
        except Exception:
            try:
                cmds.deleteUI(self._panel)
            except Exception:
                pass
        self._panel = None
        self._editor = None

    # ------------------------------------------------------------------
    #  カメラ
    # ------------------------------------------------------------------
    def set_camera(self, cam):
        if not self.is_valid() or not camera_exists(cam):
            return False
        try:
            cmds.modelPanel(self._panel, e=True, camera=cam)
            return True
        except Exception:
            pass
        try:
            cmds.lookThru(self._panel, cam)
            return True
        except Exception as e:
            try:
                cmds.warning(u"[plsCamView] " + tr(u"カメラ切替に失敗: {}").format(e))
            except Exception:
                pass
        return False

    def get_camera(self):
        if not self.is_valid():
            return None
        try:
            return cmds.modelPanel(self._panel, q=True, camera=True)
        except Exception:
            return None

    # ------------------------------------------------------------------
    #  Show
    # ------------------------------------------------------------------
    def apply_show(self, preset, extras=None):
        u"""
        preset : "all" / "none" / "polygon"
        extras : {"showJoints": bool, "showNurbsCurves": bool}
        """
        if not self.is_valid():
            return
        ed = self._editor or self._panel
        try:
            if preset == "all":
                cmds.modelEditor(ed, e=True, allObjects=True)
            else:
                cmds.modelEditor(ed, e=True, allObjects=False)
                if preset == "polygon":
                    for flag in _POLYGON_ONLY_FLAGS:
                        try:
                            cmds.modelEditor(ed, e=True, **{flag: True})
                        except Exception:
                            pass
        except Exception as e:
            try:
                cmds.warning(u"[plsCamView] " + tr(u"Show プリセット適用に失敗: {}").format(e))
            except Exception:
                pass

        # 追加スイッチ(指定があるときだけ。プリセットの方が優先されるため、
        # プリセットボタンからの呼び出しでは extras=None で呼ぶ)
        if extras:
            self.apply_show_extras(extras)

    def apply_show_extras(self, extras):
        u"""Joint / NurbsCurve など、個別スイッチのフラグだけを適用する。"""
        if not self.is_valid() or not extras:
            return
        ed = self._editor or self._panel
        for key, flag in EXTRA_FLAGS.items():
            if key in extras:
                try:
                    cmds.modelEditor(ed, e=True, **{flag: bool(extras[key])})
                except Exception:
                    pass

    def get_show_flag(self, flag):
        if not self.is_valid():
            return None
        ed = self._editor or self._panel
        try:
            return cmds.modelEditor(ed, q=True, **{flag: True})
        except Exception:
            return None

    # ------------------------------------------------------------------
    #  Shadow (Lighting > Shadows)
    # ------------------------------------------------------------------
    def set_shadows(self, on):
        if not self.is_valid():
            return False
        ed = self._editor or self._panel
        try:
            cmds.modelEditor(ed, e=True, shadows=bool(on))
            return True
        except Exception as e:
            try:
                cmds.warning(u"[plsCamView] " + tr(u"Shadow の切替に失敗: {}").format(e))
            except Exception:
                pass
        return False

    def get_shadows(self):
        if not self.is_valid():
            return None
        ed = self._editor or self._panel
        try:
            return bool(cmds.modelEditor(ed, q=True, shadows=True))
        except Exception:
            return None

    # ------------------------------------------------------------------
    def focus(self):
        u"""この modelPanel に Maya のフォーカスを移す(Playblast 対象化)。"""
        if not self.is_valid():
            return False
        try:
            cmds.setFocus(self._panel)
            return True
        except Exception:
            return False
