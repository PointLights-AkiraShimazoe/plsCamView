# -*- coding: utf-8 -*-
"""FX-SHOW-20261030-01: Show(表示)制御の試験。Cam / Fx 共通(PKG_DIR で対象パッケージを選ぶ)。

実 Maya / GPU は使わない。状態を持つ小さな `cmds` スタブ(modelPanel / modelEditor のフラグを保持し、
`allObjects`・`-copy`・読み戻しを Maya と同じ向きで模す)の上で、実物の ModelViewport / ViewSlot / ViewManager /
ToolBox と、実物の Window の Show 関連メソッドを動かす。
これは「コード経路」の確認であり、実 Maya の描画結果の証明ではない。

使い方: ツール直下(plsCamView / plsFxView の名前のフォルダ)で python3 tools/test_show_views.py
        (別の場所なら PKG_DIR=<scripts/パッケージ> を指定)
"""
import importlib
import os
import re
import sys
import types
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = Path(os.environ.get("PKG_DIR") or (ROOT / "scripts" / ROOT.name)).resolve()
PACKAGE = PKG_DIR.name
pkg = types.ModuleType(PACKAGE)
pkg.__path__ = [str(PKG_DIR)]
sys.modules[PACKAGE] = pkg
try:
    import ast
    _src = (PKG_DIR / "__init__.py").read_text(encoding="utf-8")
    for _node in ast.parse(_src).body:
        if isinstance(_node, ast.Assign) and getattr(_node.targets[0], "id", "") == "GRADE_DEFAULTS":
            pkg.GRADE_DEFAULTS = ast.literal_eval(_node.value)
except Exception:
    pass
qt = importlib.import_module(PACKAGE + ".qt")
style = importlib.import_module(PACKAGE + ".style")
i18n = importlib.import_module(PACKAGE + ".i18n")
settings = importlib.import_module(PACKAGE + ".settings")
vpmod = importlib.import_module(PACKAGE + ".viewport")
viewsmod = importlib.import_module(PACKAGE + ".views")
ui = importlib.import_module(PACKAGE + ".ui")
QW = qt.QtWidgets
app = QW.QApplication.instance() or QW.QApplication([])
IS_FX = PACKAGE == "plsFxView"
WindowCls = ui.PlsFxViewWindow if IS_FX else ui.PlsCamViewWindow

# allObjects「コマンド」の対象(スタブ条件)。Maya 2022 modelEditor は「NURBS, CVs, hulls, grids and manipulators を除く」と説明(実 Maya 未確認のモデル)。
# これは製品プリセットの仕様ではない(製品の意図は PRESET_OBJECT_FLAGS)。実 Maya での allObjects の範囲が不明なため、3 条件で同じ期待値になることを確かめる:
#   doc        = 資料どおり(NURBS / CV / hull / grid / manipulator を変えない)
#   nurbs      = NURBS(curves / surfaces)も変える
#   everything = 表示補助(CV / hull / grid / manipulator)まで変える
ALLOBJ_DOC_EXCLUDED = ("nurbsCurves", "nurbsSurfaces", "controlVertices", "hulls", "grid", "manipulators")
NURBS_FLAGS = ("nurbsCurves", "nurbsSurfaces")
DISPLAY_AIDS = ("controlVertices", "hulls", "grid", "manipulators")
ALLOBJ_SCOPES = ("doc", "nurbs", "everything")
OTHER_FLAGS = ("shadows", "displayLights", "hud", "rendererOverrideName", "menuBarVisible")
# Maya で「許可されない」変更(オブジェクトの可視性・ディスプレイレイヤー・Isolate Select)を検知する
FORBIDDEN = ("isolateSelect", "displayLayer", "setAttr", "hide", "showHidden", "layerButton", "createDisplayLayer",
             "editDisplayLayerMembers", "editDisplayLayerGlobals")


class StubCmds(object):
    u"""状態を持つ最小の maya.cmds。modelPanel / modelEditor の Show フラグを保持する。"""

    def __init__(self):
        self.panels = {}
        self.focus = None
        self.n = 0
        self.writes = []          # (editor, {flag: value})  modelEditor -e の呼出し全記録
        self.calls = []           # 全呼出し名
        self.warnings = []
        self.jobs = {}
        self.locked = {}          # editor -> {flag,...}: 書込みを無視する(読み戻し検証用)
        self.q_none = set()       # (editor, flag): 問合せが None を返す
        self.q_raise = set()      # (editor, flag): 問合せが RuntimeError
        self.w_raise = set()      # (editor, flag): 書込みが RuntimeError
        self.unsupported = set()  # (editor, flag): 書込み・問合せとも TypeError(引数 / 内部エラー等。「フラグが無い」とは断定されない)
        self.allobj_scope = "doc"  # allObjects コマンドが変える範囲(ALLOBJ_SCOPES)
        self.fail_panels = set()

    # -- 内部 ----------------------------------------------------------
    def allobj_flags(self):
        if self.allobj_scope == "everything":
            return list(vpmod.SHOW_STATE_FLAGS)
        ex = [f for f in ALLOBJ_DOC_EXCLUDED if not (self.allobj_scope == "nurbs" and f in NURBS_FLAGS)]
        return [f for f in vpmod.SHOW_STATE_FLAGS if f not in ex]

    def _new(self, prefix):
        self.n += 1
        return "{}{}".format(prefix, self.n)

    def _panel_of(self, name):
        if name in self.panels:
            return name
        for p, d in self.panels.items():
            if d["editor"] == name:
                return p
        return None

    # -- panel / editor ------------------------------------------------
    def modelPanel(self, name=None, **kw):
        self.calls.append("modelPanel")
        if "exists" in kw and name is not None:
            return self._panel_of(name) is not None
        if name is None:
            copy = kw.get("copy")
            p = self._new("modelPanel")
            flags = {f: True for f in vpmod.SHOW_STATE_FLAGS}
            if copy and self._panel_of(copy):
                flags = dict(self.panels[self._panel_of(copy)]["flags"])
            self.panels[p] = {"editor": p.replace("modelPanel", "modelEditor"), "camera": "persp", "flags": flags}
            self.focus = p
            return p
        p = self._panel_of(name)
        if kw.get("q"):
            if p is None:
                raise RuntimeError("no panel " + name)
            if kw.get("modelEditor"):
                return self.panels[p]["editor"]
            if kw.get("camera"):
                return self.panels[p]["camera"]
            if kw.get("control"):
                return p
            return None
        if kw.get("e") and p is not None and kw.get("camera"):
            self.panels[p]["camera"] = kw["camera"]
        return None

    def modelEditor(self, name, **kw):
        self.calls.append("modelEditor")
        if "exists" in kw:
            return self._panel_of(name) is not None
        p = self._panel_of(name)
        if p is None:
            raise RuntimeError("no editor " + str(name))
        d = self.panels[p]
        flags = d["flags"]
        ed = d["editor"]
        for k in kw:
            if k in ("q", "e"):
                continue
            if (ed, k) in self.unsupported or (k not in flags and k != "allObjects" and k not in OTHER_FLAGS):
                raise TypeError("Invalid flag '{}'".format(k))
        if kw.get("q"):
            for k, v in kw.items():
                if k in ("q", "e") or not v:
                    continue
                if (ed, k) in self.q_raise:
                    raise RuntimeError("query failed")
                if (ed, k) in self.q_none:
                    return None
                if k == "rendererOverrideName":
                    return ""
                if k == "allObjects":
                    return all(flags[f] for f in self.allobj_flags())
                return flags.get(k)
            return None
        wr = {k: v for k, v in kw.items() if k != "e"}
        for k in wr:
            if (ed, k) in self.w_raise:
                raise RuntimeError("write failed")
        self.writes.append((name, wr))
        lock = self.locked.get(d["editor"], set())
        for k, v in wr.items():
            if k == "allObjects":
                for f in self.allobj_flags():
                    if f not in lock:
                        flags[f] = bool(v)
            elif k in flags and k not in lock:
                flags[k] = bool(v)
        return None

    def getPanel(self, **kw):
        self.calls.append("getPanel")
        if kw.get("withFocus"):
            return self.focus
        if kw.get("typeOf"):
            return "modelPanel" if self._panel_of(kw["typeOf"]) else None
        if kw.get("type") == "modelPanel":
            return list(self.panels)
        return None

    def deleteUI(self, name, **kw):
        self.calls.append("deleteUI")
        p = self._panel_of(name)
        if p:
            del self.panels[p]
            if self.focus == p:
                self.focus = None

    # -- scene / scriptJob ---------------------------------------------
    def listCameras(self, **kw):
        return ["persp", "front", "camA"] if kw.get("perspective") else ["top"]

    def objExists(self, name):
        return True

    def objectType(self, name):
        return "transform"

    def listRelatives(self, *a, **k):
        return []

    def camera(self, *a, **k):
        return False

    def scriptJob(self, **kw):
        self.calls.append("scriptJob")
        if "kill" in kw:
            self.jobs.pop(kw["kill"], None)
            return None
        if "exists" in kw:
            return kw["exists"] in self.jobs
        self.n += 1
        self.jobs[self.n] = kw
        return self.n

    def warning(self, msg):
        self.warnings.append(msg)

    def window(self, *a, **kw):
        self.calls.append("window")
        if kw.get("exists"):
            return True
        if kw.get("q"):
            if kw.get("width"):
                return 960
            if kw.get("height"):
                return 600
            if kw.get("widthHeight"):
                return [960, 600]
            if kw.get("topLeftCorner"):
                return [10, 10]
            return None
        if kw.get("e"):
            return None
        return self._new("window")

    # -- その他のUI: 何もしない ------------------------------------------
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)

        def _f(*a, **k):
            self.calls.append(name)
            if name in ("formLayout", "paneLayout", "text", "frameLayout", "columnLayout"):
                return self._new(name)
            return None
        return _f

    def show_warnings(self):
        return [w for w in self.warnings if "Show" in w]

    def show_writes(self):
        u"""modelEditor への書込みのうち Show 系(allObjects と各 Show フラグ)だけ。Shadow など別機能は除く。"""
        keys = set(vpmod.SHOW_STATE_FLAGS) | {"allObjects"}
        return [(ed, {k: v for k, v in wr.items() if k in keys}) for ed, wr in self.writes
                if any(k in keys for k in wr)]

    def forbidden(self):
        return [c for c in self.calls if c in FORBIDDEN]


class FakeWin(object):
    u"""Window の Show 関連の実物メソッドを、軽い土台(data / ToolBox / ViewManager)の上で動かす。"""

    title = u"PLS View"
    _closing = False

    def __init__(self, data):
        self.data = dict(settings.DEFAULTS, **data)
        self.saves = 0
        self.views = None
        self.toolbox = None
        self._scriptJobs = []
        self.shadow_calls = 0

    def exists(self):
        return True

    def save_settings(self, *a, **k):
        self.saves += 1

    def target_camera(self):
        v = self.views.target_view() if self.views else None
        return v.camera() if v else None

    def apply_shadows(self, save=True):
        self.shadow_calls += 1

    def apply_effects(self, save=True):
        pass

    def _fx(self):
        return types.SimpleNamespace(after_scene_change=lambda *a, **k: None)

    def _view_panels(self):
        return []

    def show_main_window(self):
        pass

    def _update_target_text(self):
        pass

    def _restore_view_manip(self, *a, **k):         # Fx の ActiveViewChanged 初期化(Show と無関係)
        pass

    class _Overlays(object):
        def refresh(self):
            pass

    overlays = _Overlays()


for _n in ("apply_view_settings", "on_views_changed", "on_target_changed", "_show_viewports", "_warn_show",
           "_show_flag_state", "sync_show_switches", "apply_show", "apply_show_preset", "apply_show_flag",
           "apply_show_extras", "_on_scene_changed", "refresh_cameras", "_setup_script_jobs", "_kill_script_jobs",
           "_on_playback_range_changed", "_on_active_view_changed"):
    if hasattr(WindowCls, _n):
        setattr(FakeWin, _n, getattr(WindowCls, _n))


class ShowViews(unittest.TestCase):
    def setUp(self):
        self.stub = StubCmds()
        self._saved = {}
        for m in (vpmod, viewsmod, ui):
            self._saved[m] = getattr(m, "cmds", None)
            m.cmds = self.stub
        # Qt のカメラバーを Maya の formLayout へ載せる部分(実 Maya の UI 層)は、載せられたことにする
        self._saved_attach = viewsmod.attach_widget
        viewsmod.attach_widget = lambda host, widget: (host, None)
        self.addCleanup(self._restore)

    def _restore(self):
        viewsmod.attach_widget = self._saved_attach
        for m, v in self._saved.items():
            m.cmds = v
        app.processEvents()

    # -- 構築 ----------------------------------------------------------
    def build(self, n=2, data=None, cameras=None):
        win = FakeWin(dict(data or {}))
        win.data["views"] = [{"camera": (cameras or ["persp"] * n)[i], "poppedOut": False} for i in range(n)]
        tb = ui.ToolBox(win)
        self.addCleanup(tb.deleteLater)
        win.toolbox = tb
        tb.pull(dict(settings.DEFAULTS, **win.data))
        win.views = viewsmod.ViewManager(win, "mainLayout", title=win.title)
        win.views.build_from_settings()
        self.addCleanup(lambda: win.views.destroy_all())
        self.stub.writes[:] = []
        self.stub.calls[:] = []
        return win

    def polygon(self, win):
        u"""Polygon プリセットを押す(製品の意図: polymeshes だけ表示。curve / surface も非表示になる)。"""
        win.apply_show_preset("polygon")

    def flag(self, win, i, name):
        return win.views.views[i].viewport.get_show_flag(name)

    def user_show(self, win, i, name, value):
        u"""Maya 標準の Show メニューの操作(= そのビューの modelEditor へ直接書く)。"""
        self.stub.modelEditor(win.views.views[i].viewport.editor, e=True, **{name: value})

    def flags_of(self, win, i):
        return dict(self.stub.panels[win.views.views[i].viewport.panel]["flags"])

    def all_curves(self, win):
        return [self.flag(win, i, "nurbsCurves") for i in range(len(win.views.views))]

    # ==================================================================
    #  1. 単独ビューと複数ビュー全件(押したフラグだけを全ビューへ)
    # ==================================================================
    def test_single_view_curve_toggle(self):
        win = self.build(1)
        self.polygon(win)
        win.toolbox.curveChk.setChecked(True)
        self.assertTrue(self.flag(win, 0, "nurbsCurves"))
        self.assertFalse(self.flag(win, 0, "joints"))

    def test_curve_toggle_reaches_all_views(self):
        for n in (2, 3, 4):
            win = self.build(n)
            self.polygon(win)
            self.assertEqual(self.all_curves(win), [False] * n)
            win.toolbox.curveChk.setChecked(True)
            self.assertEqual(self.all_curves(win), [True] * n, "NurbsCurve が全ビューへ届いていない (n={})".format(n))
            win.toolbox.curveChk.setChecked(False)
            self.assertEqual(self.all_curves(win), [False] * n)

    def test_toggle_writes_only_the_pressed_flag(self):
        win = self.build(3)
        self.polygon(win)
        self.user_show(win, 1, "joints", True)            # ビュー 2 だけ利用者が Joint を ON
        before = [self.flags_of(win, i) for i in range(3)]
        self.stub.writes[:] = []
        win.toolbox.curveChk.setChecked(True)
        written = set()
        for _, wr in self.stub.show_writes():
            written.update(wr)
        self.assertEqual(written, {"nurbsCurves"}, written)      # joints / allObjects など他は書かない
        after = [self.flags_of(win, i) for i in range(3)]
        for i in range(3):
            b, a = dict(before[i]), dict(after[i])
            b.pop("nurbsCurves"), a.pop("nurbsCurves")
            self.assertEqual(a, b, "view {} の curve 以外が変わった".format(i + 1))
        self.assertEqual([self.flag(win, i, "joints") for i in range(3)], [False, True, False])

    def test_joint_toggle_independent_of_curve(self):
        win = self.build(2)
        self.polygon(win)
        win.toolbox.curveChk.setChecked(True)
        win.toolbox.jointChk.setChecked(True)
        win.toolbox.jointChk.setChecked(False)
        self.assertEqual(self.all_curves(win), [True, True])
        self.assertEqual([self.flag(win, i, "joints") for i in range(2)], [False, False])

    # ==================================================================
    #  2. Polygon 適用 → 標準 Show で curve ON → 各種更新後も ON
    # ==================================================================
    def _polygon_then_user_curve_on(self, n=2):
        win = self.build(n, data={"showPreset": "polygon", "showJoints": False, "showNurbsCurves": False})
        self.polygon(win)
        for i in range(n):
            self.user_show(win, i, "nurbsCurves", True)
        self.assertEqual(self.all_curves(win), [True] * n)
        return win

    def test_standard_show_survives_camera_change(self):
        win = self._polygon_then_user_curve_on(3)
        for v in win.views.views:
            v._on_camera_changed("camA")
        self.assertEqual(self.all_curves(win), [True] * 3)
        win.views.views[0]._on_camera_changed("front")
        self.assertEqual(self.all_curves(win), [True] * 3)

    def test_standard_show_survives_scene_notification_and_refresh(self):
        win = self._polygon_then_user_curve_on(2)
        for _ in range(3):
            win._on_scene_changed()
            win.refresh_cameras()
            win.views.refresh_cameras()
            win.on_views_changed()
            win.apply_view_settings(win.views.views[0])
            win.apply_view_settings(win.views.views[1])
        self.assertEqual(self.all_curves(win), [True, True])
        # スイッチも実値(ON)へ追従している
        self.assertTrue(win.toolbox.curveChk.isChecked())
        self.assertFalse(win.toolbox.curveChk.isMixed())

    def test_standard_show_survives_view_count_change(self):
        win = self._polygon_then_user_curve_on(2)
        win.views.set_count(3)
        self.assertEqual(self.all_curves(win), [True] * 3)
        win.views.set_count(4)
        win.views.set_count(1)
        self.assertEqual(self.all_curves(win), [True])
        win.views.set_count(2)
        self.assertEqual(self.all_curves(win), [True, True])

    def test_standard_show_survives_popout_dock_and_window_close(self):
        win = self._polygon_then_user_curve_on(2)
        slot = win.views.views[1]
        slot.pop_out()
        self.assertTrue(slot.is_popped())
        self.assertEqual(self.all_curves(win), [True, True])
        win.on_views_changed()
        win._on_scene_changed()
        self.assertEqual(self.all_curves(win), [True, True])
        # ポップアウト中のビューへも切替が届く
        win.toolbox.curveChk.setChecked(False)
        self.assertEqual(self.all_curves(win), [False, False])
        win.toolbox.curveChk.setChecked(True)
        slot.dock()
        self.assertFalse(slot.is_popped())
        self.assertEqual(self.all_curves(win), [True, True])
        slot.pop_out()
        slot._on_window_closed()            # ポップアウトを × で閉じた
        self.assertEqual(self.all_curves(win), [True, True])

    def test_no_show_write_from_notifications(self):
        win = self._polygon_then_user_curve_on(2)
        self.stub.writes[:] = []
        win._on_scene_changed()
        win.refresh_cameras()
        win.on_views_changed()
        win.views.views[0]._on_camera_changed("camA")
        self.assertEqual(self.stub.show_writes(), [], self.stub.show_writes())       # Show は 1 回も書かない

    def test_r5_style_resync_would_fail(self):
        u"""対照: 旧挙動(通知で保存済み preset を全ビューへ再適用)なら、標準 Show の変更は消える。
        この試験自体が「スタブで原因を再現できる」ことの確認(修正側のコードは再適用しない)。"""
        win = self._polygon_then_user_curve_on(2)
        win.apply_show(save=False)          # 旧 _on_scene_changed / apply_view_settings 相当の再適用
        self.assertEqual(self.all_curves(win), [False, False])

    # ==================================================================
    #  3. All / Polygon / None / Joint / Curve の独立
    # ==================================================================
    def test_presets_and_switches(self):
        win = self.build(2)
        win.apply_show_preset("all")
        self.assertTrue(win.toolbox.jointChk.isChecked() and win.toolbox.curveChk.isChecked())
        win.apply_show_preset("none")
        self.assertFalse(win.toolbox.jointChk.isChecked() or win.toolbox.curveChk.isChecked())
        self.assertFalse(win.toolbox.jointChk.isMixed() or win.toolbox.curveChk.isMixed())
        win.apply_show_preset("polygon")
        self.assertEqual([self.flag(win, i, "polymeshes") for i in range(2)], [True, True])
        for fl in vpmod.PRESET_OBJECT_FLAGS:
            if fl != "polymeshes":
                self.assertEqual([self.flag(win, i, fl) for i in range(2)], [False, False], fl)
        win.toolbox.curveChk.setChecked(True)
        self.assertEqual([self.flag(win, i, "polymeshes") for i in range(2)], [True, True])   # Polygon は保たれる
        self.assertEqual([self.flag(win, i, "joints") for i in range(2)], [False, False])
        win.toolbox.jointChk.setChecked(True)
        self.assertEqual(self.all_curves(win), [True, True])
        win.toolbox.curveChk.setChecked(False)
        self.assertEqual([self.flag(win, i, "joints") for i in range(2)], [True, True])
        self.assertEqual(self.stub.show_warnings(), [])

    def test_preset_reads_all_views_not_target_view(self):
        win = self.build(2)
        win.views.target_index = 0
        # polygon の後、ビュー 2 だけ利用者が curve ON → 代表(ビュー 1)は OFF だが全体は mixed
        self.polygon(win)
        self.user_show(win, 1, "nurbsCurves", True)
        win.sync_show_switches()
        self.assertTrue(win.toolbox.curveChk.isMixed())
        self.assertFalse(win.toolbox.jointChk.isMixed())

    # ==================================================================
    #  4. ビューごとに状態が違うとき(上書きしない / mixed)
    # ==================================================================
    def test_mixed_state_displayed_and_not_overwritten(self):
        win = self.build(3)
        self.polygon(win)
        self.user_show(win, 0, "joints", True)
        self.user_show(win, 2, "joints", True)
        before = [self.flags_of(win, i) for i in range(3)]
        data_before = dict(win.data)
        win.sync_show_switches()
        win.on_views_changed()
        win._on_scene_changed()
        self.assertTrue(win.toolbox.jointChk.isMixed())
        self.assertEqual([self.flags_of(win, i) for i in range(3)], before)          # 実値は触らない
        self.assertEqual(win.data["showJoints"], data_before["showJoints"])           # 保存値も UI 代表値で上書きしない

    def test_mixed_click_turns_all_on_then_off(self):
        win = self.build(3)
        self.polygon(win)
        self.user_show(win, 1, "joints", True)
        win.sync_show_switches()
        sw = win.toolbox.jointChk
        self.assertTrue(sw.isMixed() and not sw.isChecked())
        sw.click()
        self.assertEqual([self.flag(win, i, "joints") for i in range(3)], [True, True, True])
        self.assertFalse(sw.isMixed())
        self.assertTrue(sw.isChecked())
        sw.click()
        self.assertEqual([self.flag(win, i, "joints") for i in range(3)], [False, False, False])

    def test_mixed_switch_paint_differs(self):
        sw = style.ToggleSwitch(u"NurbsCurve")
        self.addCleanup(sw.deleteLater)
        sw.resize(sw.sizeHint())
        sw.show()
        app.processEvents()
        off = sw.grab().toImage()
        sw.setChecked(True)
        sw._anim.stop()
        sw._set_knob(1.0)
        on = sw.grab().toImage()
        sw.setChecked(False)
        sw.setMixed(True)
        mixed = sw.grab().toImage()
        self.assertNotEqual(off, mixed)
        self.assertNotEqual(on, mixed)
        self.assertNotEqual(off, on)
        sw.setMixed(False)
        self.assertFalse(sw.isMixed())

    # ==================================================================
    #  5. 新規 / 再構成ビューの継承
    # ==================================================================
    def test_new_view_inherits_sibling_state_not_saved_state(self):
        win = self.build(1, data={"showPreset": "all", "showJoints": True, "showNurbsCurves": True})
        self.polygon(win)
        self.user_show(win, 0, "nurbsCurves", True)
        win.data["showPreset"] = "all"        # 保存値は古いまま(利用者が標準 Show で変えた後)
        self.stub.panels[win.views.views[0].viewport.panel]["flags"]["lights"] = False
        win.views.set_count(3)
        want = self.flags_of(win, 0)
        for i in (1, 2):
            self.assertEqual(self.flags_of(win, i), want, "新規ビュー {} が兄弟の実状態を継承していない".format(i + 1))
        self.assertTrue(self.flag(win, 2, "nurbsCurves"))
        self.assertFalse(self.flag(win, 2, "lights"))

    def test_first_view_is_seeded_from_saved_settings_once(self):
        win = self.build(1, data={"showPreset": "polygon", "showJoints": True, "showNurbsCurves": True})
        self.assertTrue(self.flag(win, 0, "polymeshes"))
        self.assertTrue(self.flag(win, 0, "joints"))
        self.assertTrue(self.flag(win, 0, "nurbsCurves"))
        self.assertFalse(self.flag(win, 0, "lights"))             # polygon preset 由来
        self.stub.writes[:] = []
        win._on_scene_changed()
        win.views.views[0]._on_camera_changed("camA")
        self.assertEqual(self.stub.show_writes(), [])

    def test_restore_at_startup_applies_saved_state_to_all(self):
        win = self.build(2, data={"showPreset": "polygon", "showJoints": False, "showNurbsCurves": True})
        win.apply_show(save=False)            # _restore() 相当(起動時だけ)
        self.assertEqual(self.all_curves(win), [True, True])
        self.assertEqual([self.flag(win, i, "polymeshes") for i in range(2)], [True, True])
        self.assertEqual([self.flag(win, i, "lights") for i in range(2)], [False, False])

    def test_popout_uses_maya_copy_not_saved_state(self):
        win = self.build(2, data={"showPreset": "all", "showNurbsCurves": False})
        self.user_show(win, 0, "nurbsCurves", False)
        self.user_show(win, 0, "lights", False)
        slot = win.views.views[0]
        slot.pop_out()
        self.assertEqual(slot.viewport.state_source, "explicit")
        self.assertFalse(self.flag(win, 0, "lights"))
        self.assertFalse(self.flag(win, 0, "nurbsCurves"))

    # ==================================================================
    #  6. 反映できなかったとき黙らない
    # ==================================================================
    def test_readback_failure_warns_and_shows_mixed(self):
        win = self.build(3)
        self.polygon(win)
        locked_editor = win.views.views[1].viewport.editor
        self.stub.locked[locked_editor] = {"nurbsCurves"}
        self.stub.warnings[:] = []
        win.toolbox.curveChk.setChecked(True)
        w = self.stub.show_warnings()
        self.assertEqual(len(w), 1, w)
        self.assertIn("View 2", w[0])
        self.assertIn("nurbsCurves", w[0])
        self.assertEqual(self.all_curves(win), [True, False, True])
        self.assertTrue(win.toolbox.curveChk.isMixed())          # 嘘の ON を表示しない

    # ==================================================================
    #  7. 禁止操作 / 持続フィルター / scriptJob
    # ==================================================================
    def test_no_isolate_displaylayer_visibility_calls(self):
        win = self._polygon_then_user_curve_on(2)
        win.toolbox.curveChk.setChecked(False)
        win.toolbox.jointChk.setChecked(True)
        win.views.set_count(3)
        win.views.views[0].pop_out()
        win._on_scene_changed()
        win.views.set_count(1)
        self.assertEqual(self.stub.forbidden(), [])

    def test_scriptjobs_unchanged_and_killed(self):
        win = self.build(2)
        win._setup_script_jobs()
        events = sorted(kw["event"][0] for kw in self.stub.jobs.values())
        known = ["SceneOpened", "NewSceneOpened", "playbackRangeChanged", "playbackRangeSliderChanged",
                 "SceneOpened", "NewSceneOpened"]
        if IS_FX:
            known.append("ActiveViewChanged")        # PB-r5 / 0.2.44 既存(Show とは無関係)
        self.assertEqual(events, sorted(known))
        win._kill_script_jobs()
        self.assertEqual(self.stub.jobs, {})

    def test_no_persistent_filter_in_sources(self):
        u"""Show を封じる持続フィルター / 監視 / 新しい通知経路を、ソースに足していない(静的)。"""
        for name in ("viewport.py", "views.py", "ui.py"):
            text = (PKG_DIR / name).read_text(encoding="utf-8")
            for pat in (r"SelectionChanged", r"modelEditorChanged", r"addDrawFilter", r"scriptJob\(\s*attributeChange",
                        r"\bcallbacks?\.add", r"MMessage", r"MEventMessage", r"MUiMessage"):
                self.assertIsNone(re.search(pat, text), (name, pat))
        # Show のために timer を足していない: viewport.py の QTimer は PB-r5 / 0.2.44 既存の HUD 復帰(Fx のみ)だけ
        text = (PKG_DIR / "viewport.py").read_text(encoding="utf-8")
        self.assertEqual(text.count("QTimer"), 1 if IS_FX else 0)

    def test_destroy_all_removes_panels(self):
        win = self.build(3)
        self.assertEqual(len(self.stub.panels), 3)
        win.views.destroy_all()
        self.assertEqual(win.views.views, [])
        self.assertEqual(win._show_viewports(), [])
        win.sync_show_switches()          # 破棄後に呼ばれても落ちない(読み取りのみ)

    # ==================================================================
    #  8. i18n
    # ==================================================================
    def test_new_strings_translated(self):
        i18n.set_language("en")
        try:
            for ja in (u"ビューにより状態が異なります(押すと全ビューを ON にします)",
                       u"状態を取得できないビューがあります(押すと全ビューを ON にします)",
                       u"Show を反映・確認できなかったビュー: {}"):
                self.assertNotEqual(i18n.tr(ja), ja, ja)
        finally:
            i18n.set_language("system")


    # ==================================================================
    #  9. 不明を成功にしない(r2): 無効 / 取得失敗 / 未対応 / 無反映 / 一部・全件失敗 / copy 失敗
    # ==================================================================
    def ed(self, win, i):
        return win.views.views[i].viewport.editor

    def vpt(self, win, i):
        return win.views.views[i].viewport

    def test_invalid_panel_is_failure_not_success(self):
        win = self.build(3)
        a, bad = self.vpt(win, 0), self.vpt(win, 1)
        del self.stub.panels[bad.panel]                  # ビュー 2 のパネルが消えた
        self.assertEqual(bad.query_show_flag("nurbsCurves"), ("invalid", None))
        self.assertEqual(bad.apply_show("all"), [vpmod.SHOW_INVALID])
        self.assertEqual(bad.apply_show("polygon", {"showJoints": True}), [vpmod.SHOW_INVALID])
        self.assertEqual(bad.apply_show_extras({"showJoints": True}), [vpmod.SHOW_INVALID])
        self.assertEqual(bad.copy_show_state_from(a), [vpmod.SHOW_INVALID])
        self.assertEqual(a.copy_show_state_from(bad), [vpmod.SHOW_NO_SOURCE])      # 複製元が無効
        self.assertEqual(a.copy_show_state_from(None), [vpmod.SHOW_NO_SOURCE])     # 複製元なしを黙って飛ばさない
        self.assertEqual(a.apply_show_extras({}), [])                              # 指定なしは何もしない = 成功
        win.data["showNurbsCurves"] = True
        state, issues = win._show_flag_state("nurbsCurves")
        self.assertEqual(state, "unknown")
        self.assertEqual(issues, [(2, vpmod.SHOW_INVALID)])
        self.stub.warnings[:] = []
        win.toolbox.curveChk.setChecked(True)
        w = self.stub.show_warnings()
        self.assertEqual(len(w), 1, w)
        self.assertIn("View 2", w[0])
        self.assertIn(vpmod.SHOW_INVALID, w[0])
        self.assertEqual(w[0].count("View 2"), 1)

    def test_query_none_or_exception_is_unread_not_success(self):
        for mode in ("q_none", "q_raise"):
            win = self.build(3)
            self.polygon(win)
            ed2 = self.ed(win, 1)
            getattr(self.stub, mode).add((ed2, "nurbsCurves"))
            st, v = self.vpt(win, 1).query_show_flag("nurbsCurves")
            self.assertEqual((st, v), ("error", None), mode)
            self.assertIsNone(self.vpt(win, 1).get_show_flag("nurbsCurves"))
            self.assertEqual(self.vpt(win, 1).apply_show_extras({"showNurbsCurves": True}),
                             [vpmod.show_issue("nurbsCurves", vpmod.WHY_UNREAD)], mode)   # 書けても読めない = 確認できない
            for i in (0, 2):
                self.user_show(win, i, "nurbsCurves", True)
            state, issues = win._show_flag_state("nurbsCurves")
            self.assertEqual(state, "unknown", (mode, state))     # 残りが全て True でも「全 ON」と断定しない
            win.sync_show_switches()
            sw = win.toolbox.curveChk
            self.assertTrue(sw.isMixed() and not sw.isChecked(), mode)
            self.assertIn(i18n.tr(u"状態を取得できないビューがあります(押すと全ビューを ON にします)"), sw.toolTip())

    def test_typeerror_is_unknown_never_all_on_and_never_skipped(self):
        u"""TypeError は引数 / 内部エラーでも起こるので、「フラグが無い」と断定して集計から外したり、copy で黙って飛ばしたりしない。
        1 ビューでも読めなければ、残りが全て同じ値でも全 ON / 全 OFF と断定せず、実値として保存もしない。"""
        self.assertFalse(hasattr(vpmod, "WHY_UNSUPPORTED"))
        for flag, key, chk in (("nurbsCurves", "showNurbsCurves", "curveChk"), ("joints", "showJoints", "jointChk")):
            for others in (True, False):
                win = self.build(3)
                self.polygon(win)
                for i in (0, 2):
                    self.user_show(win, i, flag, others)
                self.stub.unsupported.add((self.ed(win, 1), flag))
                self.assertEqual(self.vpt(win, 1).query_show_flag(flag), ("error", None))
                self.assertIsNone(self.vpt(win, 1).get_show_flag(flag))
                self.assertEqual(self.vpt(win, 1).apply_show_extras({key: True}), [flag])      # 書込み TypeError = 反映されていない
                state, issues = win._show_flag_state(flag)
                self.assertEqual(state, "unknown", (flag, others))                              # 読めたビューが全て同じでも断定しない
                self.assertEqual(issues, [(2, vpmod.show_issue(flag, vpmod.WHY_UNREAD))])
                win.data[key] = (not others)                                                    # 保存値(利用者の指定)
                win.sync_show_switches()
                sw = getattr(win.toolbox, chk)
                self.assertTrue(sw.isMixed() and not sw.isChecked(), (flag, others))
                self.assertIn(i18n.tr(u"状態を取得できないビューがあります(押すと全ビューを ON にします)"), sw.toolTip())
                self.assertEqual(win.data[key], (not others), "unknown を実値として保存してはいけない")
                # 全ビュー TypeError でも unknown(保存値 fallback を実値にしない)
                for i in (0, 2):
                    self.stub.unsupported.add((self.ed(win, i), flag))
                self.assertEqual(win._show_flag_state(flag)[0], "unknown")
        # copy: 複製元の flag が TypeError でも黙って飛ばさず、失敗(未取得)にする。他の flag は写る
        win2 = self.build(2)
        self.stub.unsupported.add((self.ed(win2, 0), "lights"))
        self.user_show(win2, 0, "cameras", False)
        failed = self.vpt(win2, 1).copy_show_state_from(self.vpt(win2, 0))
        self.assertEqual(failed, ["lights(未取得)"])
        self.assertTrue(self.flag(win2, 1, "lights"))              # 触らない
        self.assertFalse(self.flag(win2, 1, "cameras"))            # 写った

    def test_write_not_reflected_and_write_exception(self):
        win = self.build(2)
        self.polygon(win)
        self.stub.locked[self.ed(win, 1)] = {"nurbsCurves"}
        self.assertEqual(self.vpt(win, 1).apply_show_extras({"showNurbsCurves": True}), ["nurbsCurves"])
        self.stub.locked.clear()
        self.stub.w_raise.add((self.ed(win, 1), "nurbsCurves"))
        self.assertEqual(self.vpt(win, 1).apply_show_extras({"showNurbsCurves": True}), ["nurbsCurves"])
        self.assertEqual(self.vpt(win, 0).apply_show_extras({"showNurbsCurves": True}), [])

    def test_partial_failure_is_never_all_on(self):
        win = self.build(3)
        self.polygon(win)
        for i in range(3):
            self.user_show(win, i, "nurbsCurves", True)
        win.sync_show_switches()
        self.assertTrue(win.toolbox.curveChk.isChecked() and not win.toolbox.curveChk.isMixed())     # 全部読めて ON なら ON
        self.stub.q_none.add((self.ed(win, 2), "nurbsCurves"))
        win.sync_show_switches()
        sw = win.toolbox.curveChk
        self.assertTrue(sw.isMixed() and not sw.isChecked())        # 1 ビュー読めない → 全 ON と断定しない
        self.stub.q_none.clear()
        win.sync_show_switches()
        self.assertTrue(sw.isChecked() and not sw.isMixed())

    def test_all_failure_does_not_show_or_save_fallback(self):
        for saved in (True, False):
            win = self.build(2, data={"showNurbsCurves": saved, "showJoints": saved})
            for i in range(2):
                for fl in ("nurbsCurves", "joints"):
                    self.stub.q_none.add((self.ed(win, i), fl))
            win.data["showNurbsCurves"] = saved
            win.data["showJoints"] = saved
            win.sync_show_switches()
            for sw in (win.toolbox.curveChk, win.toolbox.jointChk):
                self.assertTrue(sw.isMixed(), saved)                     # 保存値(ON/OFF)を実値として出さない
                self.assertFalse(sw.isChecked(), saved)
            self.assertEqual(win.data["showNurbsCurves"], saved)       # 保存値は触らない(実値で上書きも、実値扱いもしない)
            win.apply_show_preset("none")
            self.assertEqual(win._show_flag_state("joints")[0], "unknown")

    def test_one_warning_per_operation_none_for_notifications(self):
        win = self.build(3)
        self.polygon(win)
        self.stub.q_none.add((self.ed(win, 2), "nurbsCurves"))
        self.stub.warnings[:] = []
        win._on_scene_changed()
        win.refresh_cameras()
        win.on_views_changed()
        win.views.views[0]._on_camera_changed("camA")
        win.sync_show_switches()
        self.assertEqual(self.stub.show_warnings(), [], "通知で警告を連打している")
        win.toolbox.curveChk.setChecked(True)               # 操作: 1 件にまとめる(View 3 だけ)
        w = self.stub.show_warnings()
        self.assertEqual(len(w), 1, w)
        self.assertIn("View 3", w[0])
        self.assertNotIn("View 1", w[0])
        self.assertEqual(w[0].count("View 3"), 1)           # 書込み側と同期側の同じ記述を重ねない
        self.stub.warnings[:] = []
        win.apply_show_preset("polygon")
        w = self.stub.show_warnings()
        self.assertEqual(len(w), 1, w)

    def test_presets_follow_product_intent_for_every_allobjects_scope(self):
        u"""Polygon = polymeshes だけ / None = 全て非表示 / All = 全て表示。nurbsCurves / nurbsSurfaces も含む。
        allObjects コマンドが NURBS を変える / 変えない(3 条件)どちらでも、結果と警告なしは同じ。"""
        for scope in ALLOBJ_SCOPES:
            win = self.build(2)
            self.stub.allobj_scope = scope
            n = vpmod.PRESET_OBJECT_FLAGS
            self.assertIn("nurbsCurves", n)
            self.assertIn("nurbsSurfaces", n)
            for i in range(2):
                for fl in NURBS_FLAGS:
                    self.user_show(win, i, fl, True)              # NURBS が ON の状態から押す(利用者の報告どおり)
            self.stub.warnings[:] = []
            win.apply_show_preset("polygon")
            for i in range(2):
                self.assertEqual({fl: self.flag(win, i, fl) for fl in n},
                                 dict((fl, fl == "polymeshes") for fl in n), (scope, i, "polygon"))
            self.assertFalse(win.toolbox.curveChk.isChecked() or win.toolbox.curveChk.isMixed(), scope)
            self.assertFalse(win.data["showNurbsCurves"], scope)
            for i in range(2):
                for fl in NURBS_FLAGS:
                    self.user_show(win, i, fl, True)
            win.apply_show_preset("none")
            for i in range(2):
                self.assertEqual({fl: self.flag(win, i, fl) for fl in n}, dict((fl, False) for fl in n), (scope, i, "none"))
            win.apply_show_preset("all")
            for i in range(2):
                self.assertEqual({fl: self.flag(win, i, fl) for fl in n}, dict((fl, True) for fl in n), (scope, i, "all"))
            self.assertTrue(win.toolbox.curveChk.isChecked() and win.toolbox.jointChk.isChecked(), scope)
            self.assertEqual(self.stub.show_warnings(), [], scope)

    def test_presets_preserve_display_aids_for_every_allobjects_scope(self):
        u"""grid / manipulators / CV / hull(表示補助)は、プリセットで変わらない。allObjects が変えてしまう条件(everything)でも元へ戻す。"""
        for scope in ALLOBJ_SCOPES:
            win = self.build(2)
            self.stub.allobj_scope = scope
            before = []
            for i in range(2):
                for k, fl in enumerate(DISPLAY_AIDS):
                    self.user_show(win, i, fl, (k + i) % 2 == 0)       # ビューごと・flag ごとに違う値
                before.append({fl: self.flag(win, i, fl) for fl in DISPLAY_AIDS})
            self.stub.warnings[:] = []
            for preset in ("all", "none", "polygon", "all"):
                self.stub.writes[:] = []
                win.apply_show_preset(preset)
                for i in range(2):
                    self.assertEqual({fl: self.flag(win, i, fl) for fl in DISPLAY_AIDS}, before[i], (scope, preset, i))
                written = set()
                for _, wr in self.stub.show_writes():
                    written.update(wr)
                self.assertTrue(written <= set(["allObjects"]) | set(vpmod.PRESET_OBJECT_FLAGS) | set(vpmod.PRESET_PRESERVED_FLAGS))
                if scope != "everything":                               # allObjects が触れないなら、表示補助へは 1 度も書かない
                    self.assertFalse(written & set(DISPLAY_AIDS), (scope, preset))
            self.assertEqual(self.stub.show_warnings(), [], scope)

    def test_preset_verifies_each_flag_and_reports_partial_failure(self):
        win = self.build(2)
        a = self.vpt(win, 1)
        for preset in ("all", "none", "polygon"):
            self.assertEqual(a.apply_show(preset), [], preset)
        # 反映されない(NURBS を含む対象 flag)・読み戻せない・書込み不能は、成功にせず flag 名を返す
        for fl in ("lights", "nurbsCurves", "nurbsSurfaces"):
            self.user_show(win, 1, fl, True)
            self.stub.locked[self.ed(win, 1)] = {fl}
            self.assertEqual(a.apply_show("none"), [fl], fl)
            self.stub.locked.clear()
        self.user_show(win, 1, "polymeshes", False)
        self.stub.locked[self.ed(win, 1)] = {"polymeshes"}
        self.assertEqual(a.apply_show("polygon"), ["polymeshes"])
        self.stub.locked.clear()
        self.stub.q_none.add((self.ed(win, 1), "joints"))
        self.assertEqual(a.apply_show("none"), ["joints(未取得)"])
        self.stub.q_none.clear()
        # allObjects の書込み失敗だけなら 1 件。10 種は個別に書くので状態は正しい(部分集合の成功を全成功と言わない: 1 件は失敗として残る)
        for fl in vpmod.PRESET_OBJECT_FLAGS:
            self.user_show(win, 1, fl, True)
        self.stub.w_raise.add((self.ed(win, 1), "allObjects"))
        self.assertEqual(a.apply_show("none"), ["allObjects"])
        self.assertEqual({fl: self.flag(win, 1, fl) for fl in vpmod.PRESET_OBJECT_FLAGS},
                         dict((fl, False) for fl in vpmod.PRESET_OBJECT_FLAGS))
        self.stub.w_raise.clear()
        # TypeError でも「フラグが無い」とは断定せず、失敗として返す(書込み = 反映されていない)
        self.stub.unsupported.add((self.ed(win, 1), "nurbsSurfaces"))
        self.assertEqual(a.apply_show("polygon"), ["nurbsSurfaces"])
        self.stub.unsupported.clear()
        # 元へ戻せなかった表示補助は失敗として報告する(allObjects が変える条件)
        self.stub.allobj_scope = "everything"
        self.user_show(win, 1, "grid", False)
        self.stub.w_raise.add((self.ed(win, 1), "grid"))
        self.assertEqual(a.apply_show("all"), ["grid"])
        self.stub.w_raise.clear()

    def test_unreadable_preserved_flag_blocks_writes_to_that_view_only(self):
        u"""保全対象(CV / hull / grid / manipulator)の元の値を読めないビューは、書込み前に失敗(flag(未取得))として返し、何も書かない。
        他のビューは通常どおり処理され、警告は 1 操作 1 件。成功扱い(failed=[])にしない。"""
        inject = (("q_none", None), ("q_raise", None), ("unsupported", None))     # None / 例外 / TypeError
        for mode, _ in inject:
            for scope in ALLOBJ_SCOPES:
                win = self.build(3)
                self.stub.allobj_scope = scope
                for i in range(3):
                    for fl in NURBS_FLAGS:
                        self.user_show(win, i, fl, True)
                    self.user_show(win, i, "grid", False)                   # 元の表示補助の値(allObjects が触れうる)
                bad = self.vpt(win, 1)
                before_bad = self.flags_of(win, 1)
                getattr(self.stub, mode).add((self.ed(win, 1), "grid"))
                getattr(self.stub, mode).add((self.ed(win, 1), "manipulators"))
                # viewport 単体: 書込みなしで失敗を返す(extras も書かない)
                self.stub.writes[:] = []
                r = bad.apply_show("none", {"showJoints": True, "showNurbsCurves": True})
                self.assertEqual(r, ["grid(未取得)", "manipulators(未取得)"], (mode, scope, r))
                self.assertEqual(self.stub.writes, [], (mode, scope))
                self.assertEqual(self.flags_of(win, 1), before_bad, (mode, scope))
                # Window 操作: 他のビューは通常どおり、警告は 1 件に集約
                self.stub.writes[:] = []
                self.stub.warnings[:] = []
                win.apply_show_preset("polygon")
                self.assertEqual([w for w in self.stub.writes if self.stub._panel_of(w[0]) == bad.panel], [], (mode, scope))
                self.assertEqual(self.flags_of(win, 1), before_bad, (mode, scope))
                for i in (0, 2):
                    f = {fl: self.flag(win, i, fl) for fl in vpmod.PRESET_OBJECT_FLAGS}
                    self.assertEqual(f, dict((fl, fl == "polymeshes") for fl in vpmod.PRESET_OBJECT_FLAGS), (mode, scope, i))
                    self.assertFalse(self.flag(win, i, "grid"), (mode, scope, i))        # 保全(元の値のまま)
                w = self.stub.show_warnings()
                self.assertEqual(len(w), 1, w)
                self.assertIn("View 2", w[0])
                self.assertIn("grid(未取得)", w[0])
                self.assertNotIn("View 1", w[0])
                self.assertNotIn("View 3", w[0])
        # 1 つでも読めなければ、そのビューは書かない(読めない flag が 1 つだけでも)
        win = self.build(2)
        self.stub.q_none.add((self.ed(win, 0), "hulls"))
        self.stub.writes[:] = []
        self.assertEqual(self.vpt(win, 0).apply_show("all"), ["hulls(未取得)"])
        self.assertEqual(self.stub.writes, [])
        # 起動時の復元(保存済みの状態の適用)も同じ扱い: 読めないビューには書かず、読めるビューには適用される
        win = self.build(2, data={"showPreset": "polygon"})
        self.stub.q_none.add((self.ed(win, 1), "manipulators"))
        self.stub.writes[:] = []
        self.stub.warnings[:] = []
        win.apply_show(save=False)
        self.assertEqual([w for w in self.stub.writes if self.stub._panel_of(w[0]) == self.vpt(win, 1).panel], [])
        self.assertTrue(self.flag(win, 0, "polymeshes"))
        w = self.stub.show_warnings()
        self.assertEqual(len(w), 1, w)
        self.assertIn("View 2", w[0])

    def test_preset_does_not_reforce_later_standard_show(self):
        win = self.build(2)
        win.apply_show_preset("polygon")
        self.user_show(win, 0, "lights", True)               # 標準 Show で後から変える
        self.user_show(win, 1, "joints", True)
        self.stub.writes[:] = []
        win._on_scene_changed()
        win.on_views_changed()
        win.views.views[0]._on_camera_changed("camA")
        self.assertEqual(self.stub.show_writes(), [])
        self.assertTrue(self.flag(win, 0, "lights"))
        self.assertTrue(self.flag(win, 1, "joints"))

    def test_copy_failures_reported(self):
        win = self.build(2)
        src, dst = self.vpt(win, 0), self.vpt(win, 1)
        self.stub.q_raise.add((self.ed(win, 0), "lights"))
        self.stub.locked[self.ed(win, 1)] = {"cameras"}
        self.stub.unsupported.add((self.ed(win, 1), "joints"))
        self.user_show(win, 0, "locators", False)
        self.user_show(win, 0, "cameras", False)                 # 複製先は書込みを無視する(cameras)ので、元と違えば無反映になる
        failed = dst.copy_show_state_from(src)
        self.assertIn("lights(未取得)", failed)                  # 複製元を読めない
        self.assertIn("cameras", failed)                         # 書いたが反映されていない
        self.assertIn("joints", failed)                          # 複製先への書込みが TypeError = 反映されていない(「フラグが無い」とは断定しない)
        self.assertEqual(len(failed), 3, failed)
        self.assertFalse(self.flag(win, 1, "locators"))        # 失敗しなかった flag は写っている

    def test_new_view_copy_failure_warns_once(self):
        win = self.build(1)
        self.stub.q_raise.add((self.ed(win, 0), "lights"))
        self.stub.warnings[:] = []
        win.views.set_count(2)
        w = self.stub.show_warnings()
        self.assertEqual(len(w), 1, w)
        self.assertIn("View 2", w[0])
        self.assertIn("lights(未取得)", w[0])


if __name__ == "__main__":
    unittest.main(verbosity=2)
