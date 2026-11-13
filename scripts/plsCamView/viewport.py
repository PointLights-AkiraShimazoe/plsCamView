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


class NewCameraResult(object):
    u"""create_new_camera() の結果。
    node     = 作成された transform(long name)。作成されなかったときは None
    problems = 選択の復元 / Undo チャンクの開始・終了などの失敗(空 = 全て成功)
    aborted  = 作成前に中止した(選択を取得できない / Undo チャンクを開始できない)。何も作っていない
    ok       = node があり、problems が空(作成・選択復元・チャンク終了まで全て成功)
    node があって ok でないときは「作成済み・保全に失敗」。作成済みのノードは残す。呼び出し側は新カメラへ切り替えない。"""

    def __init__(self):
        self.node = None
        self.problems = []
        self.aborted = False

    @property
    def ok(self):
        return bool(self.node) and not self.problems


def create_new_camera():
    u"""Maya 標準の新規カメラを 1 台作る。結果は NewCameraResult。名前は指定しない(Maya の重複回避に任せる)。
    元の選択を取得できない / Undo チャンクを開始できないときは、作成前に中止する(警告 1 件。何も作らない)。
    作成を試みたあとは、結果(成功 / 例外 / 空の戻り値)に関わらず、取得済みの選択の復元と closeChunk を試みる(cmds.camera は選択を変える)。
    復元・closeChunk の失敗は problems に入れて返す(成功扱いにしない)。作成済みノードは削除しない。flushUndo / undoInfo の設定変更はしない。"""
    res = NewCameraResult()

    def warn(msg):
        try:
            cmds.warning(u"[plsCamView] " + msg)
        except Exception:
            pass

    if cmds is None:
        res.aborted = True
        res.problems.append(u"maya.cmds")
        return res
    try:
        sel = cmds.ls(selection=True, long=True) or []
    except Exception as e:
        res.aborted = True
        res.problems.append(tr(u"選択を取得できません"))
        warn(tr(u"選択を取得できないため、新規カメラを作成しませんでした: {}").format(e))
        return res
    try:
        cmds.undoInfo(openChunk=True)
    except Exception as e:
        res.aborted = True
        res.problems.append(tr(u"Undo チャンクを開始できません"))
        warn(tr(u"Undo チャンクを開始できないため、新規カメラを作成しませんでした: {}").format(e))
        return res
    detail = None
    try:
        try:
            out = cmds.camera()
            node = out[0] if out else None
        except Exception as e:
            node = None
            detail = u"{}".format(e)
        if node:
            try:
                node = (cmds.ls(node, long=True) or [node])[0]
            except Exception:
                pass
            res.node = node
        elif detail is None:
            detail = tr(u"カメラが返されませんでした")
    finally:
        try:                                    # 成否に関わらず、作成前の選択へ戻す(失敗は problems へ)
            if sel:
                cmds.select(sel, replace=True)
            else:
                cmds.select(clear=True)
        except Exception:
            res.problems.append(tr(u"選択を復元できませんでした"))
        try:
            cmds.undoInfo(closeChunk=True)
        except Exception:
            res.problems.append(tr(u"Undo チャンクを閉じられませんでした"))
    if res.node:
        if res.problems:
            warn(tr(u"新規カメラ {} を作成しましたが、{}。このビューは切り替えません").format(res.node, u" / ".join(res.problems)))
    else:
        warn(tr(u"新規カメラを作成できませんでした: {}").format(u" / ".join([detail] + res.problems)))
    return res


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


# 新規 / 再構成ビューへ引き継ぐ Show フラグ(mp4blast の _VIEWPORT_SHOW_FLAGS と同じ一覧)
SHOW_STATE_FLAGS = [
    "nurbsCurves", "nurbsSurfaces", "controlVertices", "hulls",
    "polymeshes", "subdivSurfaces", "planes", "lights", "cameras",
    "imagePlane", "joints", "ikHandles", "deformers", "dynamics",
    "fluids", "hairSystems", "follicles", "nCloths", "nParticles",
    "nRigids", "dynamicConstraints", "locators", "dimensions",
    "pivots", "handles", "textures", "strokes", "motionTrails",
    "pluginShapes", "clipGhosts", "greasePencils", "particleInstancers",
    "grid", "manipulators",
]


# プリセットが「対象オブジェクト種別」として個別に確定するフラグ。
# 製品の意図: All = これらを全て表示 / None = 全て非表示 / Polygon = polymeshes だけ表示(nurbsCurves / nurbsSurfaces もプリセットで確定する)。
# allObjects コマンドは NURBS などを除外すると Maya 2022 の資料にあるが、それはコマンドの仕様であって製品の仕様ではない。
# プリセットは allObjects を書いたあと、これらを 1 つずつ書いて読み戻す。allObjects が NURBS を変える Maya でも変えない Maya でも結果は同じ。
# ここに無い種別(planes / imagePlane / dynamics / fluids / nCloths など)は allObjects に任せ、個別には確認しない(確認済みの集合はこの 10 種だけ)。
PRESET_OBJECT_FLAGS = ("polymeshes", "subdivSurfaces", "nurbsCurves", "nurbsSurfaces", "lights", "cameras",
                       "joints", "ikHandles", "locators", "deformers")
# プリセットが触れない表示補助(従来の独立設定を保全)。allObjects が万一変えてしまったときだけ、プリセット操作の中で元の値へ戻す。
PRESET_PRESERVED_FLAGS = ("controlVertices", "hulls", "grid", "manipulators")

# 失敗の表記: 「flag」= 書いたが反映されていない(または書込み例外) / 「flag(未取得)」= 読み戻せず確認できない(成功にしない)
#             SHOW_INVALID・SHOW_NO_SOURCE = ビュー無効・複製元なし
# 例外の型(TypeError など)だけで「その Maya にフラグが無い」とは断定しない(引数・内部エラーでも起こる)。読めない = 不明として扱う。
SHOW_INVALID = u"ビュー無効"
SHOW_NO_SOURCE = u"複製元なし"
WHY_UNREAD = u"未取得"


def show_issue(flag, why=None):
    return u"{}({})".format(flag, why) if why else flag


def preset_expectations(preset):
    u"""プリセットが個別に確定する {flag: 期待値}(PRESET_OBJECT_FLAGS 全部)。All = 全て True / None = 全て False / Polygon = polymeshes だけ True。"""
    want = dict((f, preset == "all") for f in PRESET_OBJECT_FLAGS)
    if preset == "polygon":
        for f in _POLYGON_ONLY_FLAGS:
            want[f] = True
    return want


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
        self.state_source = None     # 複製元の出所: "explicit"(呼出側が指定) / "auto"(フォーカス中のパネル) / None
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
                    self.state_source = "explicit"
            except Exception:
                src = None
        if src is None and self._use_copy:
            src = _pick_source_panel()
            if src:
                self.state_source = "auto"
        if src:
            try:
                self._panel = cmds.modelPanel(copy=src, **kwargs)
            except Exception:
                self._panel = None
        if not self._panel:
            self.state_source = None          # 複製できなかった(素の新規パネル)
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
    def _show_editor(self):
        u"""Show 設定の対象 modelEditor。保持している名前が無効なら modelPanel から引き直す。"""
        ed = self._editor or self._panel
        try:
            if ed and cmds.modelEditor(ed, exists=True):
                return ed
        except Exception:
            pass
        try:
            fresh = cmds.modelPanel(self._panel, q=True, modelEditor=True)
            if fresh:
                self._editor = fresh
                return fresh
        except Exception:
            pass
        return ed

    def query_show_flag(self, flag):
        u"""(状態, 値)。状態: "ok"(値は bool) / "invalid"(ビュー無効) / "error"(取得例外・None など = 不明)。
        不明を True / False へ丸めない。例外の型(TypeError を含む)で「フラグが無い」とは断定しない。"""
        if not self.is_valid():
            return ("invalid", None)
        try:
            v = cmds.modelEditor(self._show_editor(), q=True, **{flag: True})
        except Exception:
            return ("error", None)
        if isinstance(v, (bool, int)):
            return ("ok", bool(v))
        return ("error", None)

    def _check_flag(self, flag, want):
        u"""読み戻して want と一致するか。一致なら None、そうでなければ失敗の記述。読み戻せない = 成功にしない。"""
        st, v = self.query_show_flag(flag)
        if st == "ok":
            return None if v == bool(want) else flag
        return show_issue(flag, WHY_UNREAD)

    def _set_flag_checked(self, ed, flag, want):
        u"""1 フラグを書いて読み戻す。成功なら None、失敗なら記述(書込み例外は「反映されていない」)。"""
        try:
            cmds.modelEditor(ed, e=True, **{flag: bool(want)})
        except Exception:
            return flag
        return self._check_flag(flag, want)

    def apply_show(self, preset, extras=None):
        u"""
        preset : "all" / "none" / "polygon"(対象と期待値は preset_expectations / PRESET_OBJECT_FLAGS)
          all     = PRESET_OBJECT_FLAGS(nurbsCurves / nurbsSurfaces を含む 10 種)を全て ON
          none    = 同 10 種を全て OFF
          polygon = polymeshes だけ ON、他の 9 種は OFF
          手順: 表示補助(PRESET_PRESERVED_FLAGS)の元の値を読む -> allObjects を書く -> 10 種を 1 つずつ書いて読み戻す -> 表示補助を確認。
          allObjects が NURBS を変える / 変えない どちらの Maya でも結果は同じ。
          PRESET_PRESERVED_FLAGS(CV / hull / grid / manipulator)は触れない。allObjects が変えてしまったときだけ元の値へ戻す。
          **保全対象の元の値を 1 つでも読めないビューは、書込み前に失敗(該当 flag の「未取得」)として返し、そのビューには何も書かない**
          (戻せないまま成功を返さないため。allObjects・10 種・extras とも書かない)。
          10 種と保全分以外の種別(fluids など)は allObjects に任せ、個別には確認しない。
        extras : {"showJoints": bool, "showNurbsCurves": bool}(指定があるときだけ。個別に書いて読み戻す)
        戻り値: 失敗の記述の一覧(空 = 10 種と保全分を全て反映・確認済み。ビュー無効は [SHOW_INVALID])
        """
        if not self.is_valid():
            return [SHOW_INVALID]
        ed = self._show_editor()
        keep, unread = {}, []
        for flag in PRESET_PRESERVED_FLAGS:          # 保全する表示補助の元の値
            st, v = self.query_show_flag(flag)
            if st == "ok":
                keep[flag] = v
            else:
                unread.append(show_issue(flag, WHY_UNREAD))
        if unread:
            return unread                            # 元の値を読めない = 保全できない。このビューには何も書かない
        failed = []
        try:
            cmds.modelEditor(ed, e=True, allObjects=(preset == "all"))
        except Exception:
            failed.append("allObjects")              # 個別の 10 種は以降で書くので、これだけを 1 件で報告する
        want = preset_expectations(preset)
        for flag in PRESET_OBJECT_FLAGS:
            r = self._set_flag_checked(ed, flag, want[flag])
            if r:
                failed.append(r)
        for flag in PRESET_PRESERVED_FLAGS:
            st, now = self.query_show_flag(flag)
            if st == "ok" and now == keep[flag]:
                continue                              # allObjects が触れていない(通常)
            r = self._set_flag_checked(ed, flag, keep[flag])   # 触れてしまった / 読めない: 元の値へ戻して確認
            if r:
                failed.append(r)
        if extras:
            failed.extend(self.apply_show_extras(extras))
        return failed

    def apply_show_extras(self, extras):
        u"""Joint / NurbsCurve など、extras に含まれる個別スイッチのフラグだけを書き、読み戻して確かめる。
        戻り値: 失敗の記述の一覧(空 = 全て反映・確認済み。ビュー無効は [SHOW_INVALID])。"""
        if not extras:
            return []
        if not self.is_valid():
            return [SHOW_INVALID]
        failed = []
        ed = self._show_editor()
        for key, flag in EXTRA_FLAGS.items():
            if key in extras:
                r = self._set_flag_checked(ed, flag, extras[key])
                if r:
                    failed.append(r)
        return failed

    def get_show_flag(self, flag):
        u"""True / False。取得できない(無効・例外・None)ときは None(互換用。区別が要るときは query_show_flag)。"""
        st, v = self.query_show_flag(flag)
        return v if st == "ok" else None

    def copy_show_state_from(self, other, flags=None):
        u"""別のビューの Show の実状態を、個別フラグでこのビューへ写す(新規ビューの引継ぎ用。allObjects は使わない)。
        複製元の flag を読めないとき(例外の型を問わない)は、黙って飛ばさず失敗(未取得)にする。書けない / 反映されないときも失敗。
        戻り値: 失敗の記述の一覧(空 = 写した全 flag を読み戻して確認済み)。"""
        if not self.is_valid():
            return [SHOW_INVALID]
        if other is None or not other.is_valid():
            return [SHOW_NO_SOURCE]
        failed = []
        ed = self._show_editor()
        for flag in (flags or SHOW_STATE_FLAGS):
            st, value = other.query_show_flag(flag)
            if st != "ok":
                failed.append(show_issue(flag, WHY_UNREAD))
                continue
            r = self._set_flag_checked(ed, flag, value)
            if r:
                failed.append(r)
        return failed

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
