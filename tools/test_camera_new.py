# -*- coding: utf-8 -*-
"""FX-CAMERA-NEW-20261030-01: カメラ切替の「New」(新規カメラ作成)の試験。Cam / Fx 共通(PKG_DIR で対象パッケージを選ぶ)。

実 Maya / GPU は使わない。test_show_views.py の StubCmds / FakeWin(実物の ModelViewport / ViewSlot / ViewManager / CameraBar と、
実物の Window メソッド)の上に、カメラ作成・選択・Undo チャンクを記録する小さなスタブを足している。
これは「コード経路」の確認であり、実 Maya でのカメラ作成・Undo・描画の証明ではない。

使い方: PKG_DIR=<scripts/パッケージ> python3 tests/test_camera_new.py
"""
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_show_views as T            # noqa: E402  (PKG_DIR を読んでパッケージを読み込む)
from test_show_views import (StubCmds, FakeWin, viewsmod, vpmod, ui, i18n, app, qt)   # noqa: E402

QtCore, QtGui, QtWidgets = qt.QtCore, qt.QtGui, qt.QtWidgets
try:
    from PySide6 import QtTest
except Exception:                       # pragma: no cover
    from PySide2 import QtTest

FakeWin.set_camera = T.WindowCls.set_camera          # 互換 API(Window.set_camera)も実物で試す


class CamStub(StubCmds):
    u"""カメラ・選択・Undo を持つスタブ。cmds.camera() は Maya の重複回避どおり、既存名と被らない名前を返す。"""

    def __init__(self, cams=None):
        StubCmds.__init__(self)
        self.cams = list(["persp", "front", "camA", "top"] if cams is None else cams)   # 全て transform 名。top だけ平行投影扱い
        self.ortho = {"top"}
        self.sel = []
        self.seq = []                 # camera / select / undoInfo の呼出し順
        self.created = []
        self.camera_args = []
        self.camera_fail = None       # None / "raise" / "empty"
        self.panel_cam_fail = False   # modelPanel -e camera と lookThru を失敗させる
        self.open_raises = False
        self.close_raises = False
        self.select_raises = False
        self.ls_raises = False
        self.dirty_sel_on_fail = False   # camera() が失敗しても選択を変えてしまう(Maya で起こり得る)
        self.deleted = []
        self.cam_writes = []          # modelPanel -e camera の全記録
        self.on_create = None         # 作成の途中(Maya のシーン通知相当)で呼ばれる

    def listCameras(self, **kw):
        if kw.get("perspective"):
            return [c for c in self.cams if c not in self.ortho]
        return [c for c in self.cams if c in self.ortho]

    def objExists(self, name):
        return str(name).lstrip("|") in self.cams

    def ls(self, *a, **kw):
        if kw.get("selection"):
            if self.ls_raises:
                raise RuntimeError("ls failed")
            return list(self.sel)
        out = []
        for n in a:
            if str(n).lstrip("|") in self.cams:
                out.append("|" + str(n).lstrip("|") if kw.get("long") else str(n))
        return out

    def select(self, *a, **kw):
        self.seq.append("select")
        if self.select_raises:
            raise RuntimeError("select failed")
        if kw.get("clear"):
            self.sel = []
        elif a:
            self.sel = list(a[0]) if isinstance(a[0], (list, tuple)) else [a[0]]

    def undoInfo(self, **kw):
        self.calls.append("undoInfo")
        if kw.get("openChunk"):
            if self.open_raises:
                raise RuntimeError("openChunk failed")
            self.seq.append("openChunk")
        elif kw.get("closeChunk"):
            self.seq.append("closeChunk")
            if self.close_raises:
                raise RuntimeError("closeChunk failed")
        else:
            self.seq.append("undoInfo?" + repr(sorted(kw)))

    def camera(self, *a, **kw):
        self.camera_args.append((a, kw))
        self.seq.append("camera")
        if self.on_create:
            self.on_create()
        if self.camera_fail and self.dirty_sel_on_fail:
            self.sel = ["strayNode"]
        if self.camera_fail == "raise":
            raise RuntimeError("camera failed")
        if self.camera_fail == "empty":
            return []
        n = 1
        while "camera%d" % n in self.cams:
            n += 1
        name = "camera%d" % n
        self.cams.append(name)
        self.created.append(name)
        self.sel = [name]                     # cmds.camera は新カメラを選択する
        return [name, name + "Shape"]

    def delete(self, *a, **kw):
        self.deleted.append(a)

    def modelPanel(self, name=None, **kw):
        if kw.get("e") and kw.get("camera"):
            if self.panel_cam_fail:
                raise RuntimeError("camera switch failed")
            self.cam_writes.append((name, kw["camera"]))
        return StubCmds.modelPanel(self, name, **kw)

    def lookThru(self, *a, **kw):
        if self.panel_cam_fail:
            raise RuntimeError("lookThru failed")


class CameraNew(unittest.TestCase):
    def setUp(self):
        T.ShowViews.setUp(self)
        self.use()

    _restore = T.ShowViews._restore
    flags_of = T.ShowViews.flags_of
    user_show = T.ShowViews.user_show

    def build(self, n=2, data=None, cameras=None):
        win = T.ShowViews.build(self, n, data, cameras)
        win.refresh_cameras()               # Window の起動と同じ: build_from_settings のあとに候補を流し込む
        self.stub.calls[:] = []
        return win

    def use(self, **kw):
        self.stub = CamStub(**kw)
        for m in (vpmod, viewsmod, ui):
            m.cmds = self.stub
        return self.stub

    # -- 操作 ----------------------------------------------------------
    def bar(self, win, i):
        return win.views.views[i].bar

    def new_index(self, bar):
        idx = [i for i in range(bar.combo.count()) if bar.combo.is_new_index(i)]
        self.assertEqual(len(idx), 1, "New 項目はちょうど 1 件")
        self.assertEqual(idx[0], bar.combo.count() - 1, "New は最後")
        return idx[0]

    def pick_new(self, bar):
        u"""利用者がポップアップで New を選んだ(currentIndexChanged → activated の順)。"""
        i = self.new_index(bar)
        bar.combo.setCurrentIndex(i)
        bar.combo.activated.emit(i)

    def pick(self, bar, text):
        u"""利用者がポップアップで実カメラを選んだ。"""
        i = [j for j in bar.combo.real_indices() if bar.combo.itemText(j) == text][0]
        bar.combo.setCurrentIndex(i)
        bar.combo.activated.emit(i)

    def cam(self, win, i):
        return win.views.views[i].viewport.get_camera()

    def cams_of(self, win):
        return [self.cam(win, i) for i in range(len(win.views.views))]

    def shown(self, win, i):
        return self.bar(win, i).combo.display_text()

    # ==================================================================
    def test_combo_has_one_new_item_marked_by_data(self):
        win = self.build(2)
        for i in range(2):
            b = self.bar(win, i)
            self.assertEqual(b.real_cameras(), vpmod.list_cameras(True))
            self.new_index(b)
            self.assertFalse(b.combo.is_new_index(b.combo.currentIndex()), "起動直後に New が選択されていない")
            self.assertEqual(self.stub.created, [])

    def test_new_creates_one_camera_and_switches_only_operated_view(self):
        win = self.build(3, cameras=["persp", "front", "camA"])
        self.user_show(win, 1, "nurbsCurves", False)             # 他ビューの Show(標準 Show で変えた状態)
        self.user_show(win, 2, "lights", False)
        before_flags = [self.flags_of(win, i) for i in range(3)]
        before_cams = self.cams_of(win)
        self.stub.sel = ["pCube1", "pSphere1.f[0:3]"]
        self.stub.writes[:] = []
        calls = self.count_camera_changed(win)
        self.pick_new(self.bar(win, 0))
        self.assertEqual(calls, [win.views.views[0]])                              # 通常の切替と同じ通知が、操作ビューにだけ 1 回
        self.assertEqual(self.stub.created, ["camera1"])
        self.assertEqual(self.cam(win, 0).lstrip("|"), "camera1")                  # 操作したビューは新カメラ
        self.assertEqual(self.cams_of(win)[1:], before_cams[1:])                   # 他ビューの使用カメラは保持
        self.assertEqual([v.state["camera"] for v in win.views.views[1:]], before_cams[1:])
        self.assertEqual([self.flags_of(win, i) for i in range(3)], before_flags)  # Show は不変
        self.assertEqual(self.stub.show_writes(), [])
        for i in range(3):                                                         # 全ビューの候補に反映
            self.assertIn("camera1", self.bar(win, i).real_cameras())
        self.assertEqual(self.shown(win, 0), "camera1")
        self.assertEqual(self.shown(win, 1), before_cams[1])
        self.assertEqual(self.shown(win, 2), before_cams[2])
        self.assertEqual(win.views.views[0].state["camera"].lstrip("|"), "camera1")
        self.assertEqual(self.stub.sel, ["pCube1", "pSphere1.f[0:3]"])             # 選択は保全
        self.assertEqual(self.stub.warnings, [])
        self.assertFalse(win.views._creating_camera)

    def test_name_left_to_maya_and_no_options(self):
        self.use(cams=["persp", "camera1"])                     # camera1 が既にある → Maya の重複回避で camera2
        win = self.build(1)
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.created, ["camera2"])
        self.assertEqual(self.stub.camera_args, [((), {})], "名前・オプションを渡さない(Maya 標準の既定どおり)")
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.created, ["camera2", "camera3"])
        self.assertIn("camera1", self.stub.cams)                 # 既存ノードはそのまま
        self.assertEqual(self.stub.deleted, [])

    def test_undo_is_one_chunk_without_flush_or_setting_change(self):
        win = self.build(1)
        self.stub.sel = ["pCube1"]
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.seq, ["openChunk", "camera", "select", "closeChunk"])
        self.assertNotIn("flushUndo", self.stub.calls)
        self.assertEqual([s for s in self.stub.seq if s.startswith("undoInfo?")], [])   # state / infinity 等は触らない

    def test_empty_selection_restored_as_empty(self):
        win = self.build(1)
        self.stub.sel = []
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.sel, [])

    def assert_aborted_before_creation(self, win, prev, sel_before, nodes):
        self.assertEqual(self.stub.created, [])
        self.assertNotIn("camera", self.stub.seq)
        self.assertNotIn("select", self.stub.seq)                # 何も作っていないので選択にも触れない
        self.assertNotIn("closeChunk", self.stub.seq)            # 開けていないチャンクは閉じない
        self.assertEqual(self.stub.cams, nodes)
        self.assertEqual(self.stub.deleted, [])
        self.assertEqual(self.stub.sel, sel_before)
        self.assertEqual(self.cam(win, 0), prev)
        self.assertEqual(self.shown(win, 0), prev)
        self.assertEqual(len(self.stub.warnings), 1, self.stub.warnings)
        self.assertFalse(win.views._creating_camera)

    def test_open_chunk_failure_aborts_before_creation(self):
        win = self.build(2)
        prev, nodes = self.cam(win, 0), list(self.stub.cams)
        self.stub.open_raises = True
        self.stub.sel = ["pCube1"]
        self.stub.warnings[:] = []
        self.pick_new(self.bar(win, 0))
        self.assert_aborted_before_creation(win, prev, ["pCube1"], nodes)
        self.assertEqual(self.stub.seq, [])                      # openChunk の失敗以外は何も呼ばない(openChunk は記録前に例外)
        self.stub.open_raises = False                            # 復旧後は通常どおり作成できる
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.created, ["camera1"])

    def test_selection_query_failure_aborts_before_creation(self):
        win = self.build(2)
        prev, nodes = self.cam(win, 0), list(self.stub.cams)
        self.stub.sel = ["pCube1"]
        self.stub.ls_raises = True
        self.stub.warnings[:] = []
        self.pick_new(self.bar(win, 0))
        self.assert_aborted_before_creation(win, prev, ["pCube1"], nodes)
        self.assertNotIn("openChunk", self.stub.seq)             # 選択を取得できないなら Undo チャンクも開かない
        self.stub.ls_raises = False
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.created, ["camera1"])

    def test_creation_failure_still_restores_selection_and_closes_chunk(self):
        for mode in ("raise", "empty"):
            win = self.build(1)
            prev, nodes = self.cam(win, 0), list(self.stub.cams)
            self.stub.sel = ["pCube1", "pSphere1.f[0:3]"]
            self.stub.camera_fail = mode
            self.stub.dirty_sel_on_fail = True                   # 失敗しても選択が変わってしまう
            self.stub.seq[:] = []
            self.stub.warnings[:] = []
            self.pick_new(self.bar(win, 0))
            self.assertEqual(self.stub.sel, ["pCube1", "pSphere1.f[0:3]"], mode)       # 成功ノードの有無に関わらず復元を試みる
            self.assertEqual(self.stub.seq, ["openChunk", "camera", "select", "closeChunk"], mode)
            self.assertEqual(self.stub.created, [], mode)
            self.assertEqual(self.stub.cams, nodes, mode)
            self.assertEqual(self.cam(win, 0), prev, mode)
            self.assertEqual(len(self.stub.warnings), 1, self.stub.warnings)
            self.stub.camera_fail = None
            self.stub.dirty_sel_on_fail = False

    def _created_but_not_ok(self, **flags):
        win = self.build(2)
        prev0, prev1 = self.cam(win, 0), self.cam(win, 1)
        self.stub.sel = ["pCube1"]
        for k, v in flags.items():
            setattr(self.stub, k, v)
        self.stub.seq[:] = []
        self.stub.warnings[:] = []
        calls = self.count_camera_changed(win)
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.created, ["camera1"])         # 作成済みのノードは残す
        self.assertEqual(self.stub.deleted, [])
        self.assertEqual(calls, [])                              # 通常成功の通知(新カメラへの切替)は進めない
        self.assertEqual(self.cam(win, 0), prev0)
        self.assertEqual(self.cam(win, 1), prev1)
        self.assertEqual(self.shown(win, 0), prev0)              # 表示は直前のカメラへ戻る
        self.assertFalse(self.bar(win, 0).combo.is_new_index(self.bar(win, 0).combo.currentIndex()))
        for i in range(2):
            self.assertIn("camera1", self.bar(win, i).real_cameras())     # 候補には出る
        self.assertEqual(len(self.stub.warnings), 1, self.stub.warnings)
        self.assertIn("camera1", self.stub.warnings[0])
        self.assertEqual(self.stub.seq.count("closeChunk"), 1)             # チャンクは必ず閉じを試みる
        self.assertFalse(win.views._creating_camera)
        return win

    def test_selection_restore_failure_is_not_success(self):
        self._created_but_not_ok(select_raises=True)

    def test_close_chunk_failure_is_not_success(self):
        self._created_but_not_ok(close_raises=True)
        self.assertEqual(self.stub.sel, ["pCube1"])              # 選択の復元自体はできている

    def test_restore_and_close_failure_give_one_warning(self):
        self._created_but_not_ok(select_raises=True, close_raises=True)

    def test_result_object_tells_created_and_failed_states(self):
        r = vpmod.create_new_camera()                            # 正常: 作成・復元・終了まで成功
        self.assertTrue(r.ok)
        self.assertEqual((r.node.lstrip("|"), r.problems, r.aborted), ("camera1", [], False))
        self.stub.select_raises = True
        r = vpmod.create_new_camera()                            # 作成済み・保全に失敗
        self.assertFalse(r.ok)
        self.assertEqual(r.node.lstrip("|"), "camera2")
        self.assertEqual(len(r.problems), 1)
        self.assertFalse(r.aborted)
        self.stub.select_raises = False
        self.stub.ls_raises = True                               # 作成前に中止
        r = vpmod.create_new_camera()
        self.assertEqual((r.node, r.aborted, r.ok), (None, True, False))
        self.stub.ls_raises = False
        self.stub.camera_fail = "raise"                          # 作成失敗(ノードなし)
        r = vpmod.create_new_camera()
        self.assertEqual((r.node, r.aborted, r.ok, r.problems), (None, False, False, []))
        self.assertEqual(self.stub.created, ["camera1", "camera2"])
        self.stub.camera_fail = "empty"                          # 空の戻り値 = ノードなし(作成済み扱いにしない)
        r = vpmod.create_new_camera()
        self.assertEqual((r.node, r.aborted, r.ok, r.problems), (None, False, False, []))

    # ---- 左右ボタン ---------------------------------------------------
    def test_step_buttons_ignore_new_and_wrap_on_real_count(self):
        win = self.build(1, cameras=["persp"])
        b = self.bar(win, 0)
        reals = b.real_cameras()
        n = len(reals)
        self.assertGreaterEqual(n, 3)
        seen = [self.shown(win, 0)]
        for _ in range(n * 2 + 1):
            b.nextBtn.click()
            seen.append(self.shown(win, 0))
            self.assertFalse(b.combo.is_new_index(b.combo.currentIndex()))
        order = [reals[(reals.index("persp") + k) % n] for k in range(len(seen))]
        self.assertEqual(seen, order)                            # 実カメラだけを巡回し、末尾で先頭へ戻る
        for _ in range(n * 2 + 1):
            b.prevBtn.click()
            self.assertFalse(b.combo.is_new_index(b.combo.currentIndex()))
        self.assertEqual(self.shown(win, 0), "persp")            # 同じ回数戻した = 元の位置
        self.assertEqual(self.cam(win, 0), self.shown(win, 0))   # ビューも追従
        self.assertEqual(self.stub.created, [])

    def test_step_wraps_last_to_first_and_first_to_last(self):
        win = self.build(1, cameras=["persp"])
        b = self.bar(win, 0)
        reals = b.real_cameras()
        self.pick(b, reals[-1])
        b.nextBtn.click()
        self.assertEqual(self.shown(win, 0), reals[0])
        b.prevBtn.click()
        self.assertEqual(self.shown(win, 0), reals[-1])
        self.assertEqual(self.stub.created, [])

    def test_arrows_follow_real_camera_count_zero_one_two(self):
        win = self.build(1)
        b = self.bar(win, 0)
        self.stub.cams[:] = []
        win.refresh_cameras()
        self.assertEqual(b.real_cameras(), [])
        self.assertEqual(b.combo.count(), 1)                      # New だけ
        self.assertFalse(b.prevBtn.isEnabled() or b.nextBtn.isEnabled())
        b.nextBtn.click()
        self.assertEqual(self.stub.created, [])
        self.pick_new(b)                                          # 実カメラ 0 件でも New は選べる
        self.assertEqual(self.stub.created, ["camera1"])
        self.assertEqual(b.real_cameras(), ["camera1"])
        self.assertEqual(self.shown(win, 0), "camera1")
        self.assertFalse(b.prevBtn.isEnabled() or b.nextBtn.isEnabled())    # 実 1 件 = 巡回なし(New を数えない)
        b.nextBtn.click()
        b.prevBtn.click()
        self.assertEqual(self.shown(win, 0), "camera1")
        self.pick_new(b)                                          # 実 1 件でも選べる
        self.assertEqual(self.stub.created, ["camera1", "camera2"])
        self.assertTrue(b.prevBtn.isEnabled() and b.nextBtn.isEnabled())    # 実 2 件で有効
        b.nextBtn.click()
        self.assertEqual(self.shown(win, 0), "camera1")
        b.nextBtn.click()
        self.assertEqual(self.shown(win, 0), "camera2")
        self.assertEqual(self.stub.created, ["camera1", "camera2"])

    # ---- 実カメラ名が New ----------------------------------------------
    def test_real_camera_named_New_is_not_the_create_action(self):
        self.use(cams=["persp", "New"])
        win = self.build(1)
        b = self.bar(win, 0)
        self.assertEqual(b.real_cameras(), ["persp", "New"])
        self.assertEqual(b.combo.count(), 3)
        self.pick(b, "New")                                       # 実カメラ New を選ぶ
        self.assertEqual(self.stub.created, [])
        self.assertEqual(self.cam(win, 0), "New")
        self.assertEqual(self.shown(win, 0), "New")
        b.nextBtn.click()                                         # 巡回は 2 台で折り返す
        self.assertEqual(self.shown(win, 0), "persp")
        b.nextBtn.click()
        self.assertEqual(self.shown(win, 0), "New")
        self.assertEqual(self.stub.created, [])
        self.pick_new(b)                                          # 本物の作成項目
        self.assertEqual(self.stub.created, ["camera1"])
        self.assertEqual(self.cam(win, 0).lstrip("|"), "camera1")
        self.assertIn("New", b.real_cameras())                    # 実カメラ New は残る

    def test_item_text_equal_to_new_label_does_not_matter(self):
        label = None
        win = self.build(1)
        b = self.bar(win, 0)
        label = b.combo.itemText(self.new_index(b))
        self.stub.cams[:] = ["persp", label]                       # 作成項目と同じ表示文字列の実カメラ
        win.refresh_cameras()
        b = self.bar(win, 0)
        self.pick(b, label)
        self.assertEqual(self.stub.created, [])
        self.assertEqual(self.cam(win, 0), label)

    # ---- 作成しない経路 ---------------------------------------------------
    def count_camera_changed(self, win):
        calls = []
        orig = win.views.on_camera_changed
        win.views.on_camera_changed = lambda view: (calls.append(view), orig(view))[1]
        return calls

    def test_refresh_does_not_emit_camera_switches(self):
        u"""再構築(set_cameras)の途中で currentIndexChanged が cameraChanged になって、ビューが切り替わったり通知が飛んだりしない。"""
        win = self.build(3, cameras=["front", "camA", "persp"])
        calls = self.count_camera_changed(win)
        self.stub.cam_writes[:] = []
        before = self.cams_of(win)
        win.refresh_cameras()
        win._on_scene_changed()
        self.assertEqual(calls, [])
        panels = [v.viewport.panel for v in win.views.views]
        # 書くのは各ビューの現在のカメラだけ(2 回の更新 × 3 ビュー = 各ビューへ 2 回ずつ同じ値)
        self.assertEqual([c for (p, c) in self.stub.cam_writes], before + before)
        self.assertEqual([p for (p, c) in self.stub.cam_writes], panels + panels)
        self.assertEqual(self.cams_of(win), before)

    def test_refresh_rebuild_startup_stepping_never_create(self):
        win = self.build(2)
        for _ in range(3):
            win.refresh_cameras()
            win._on_scene_changed()
            win.views.refresh_cameras()
        win.views.set_count(3)
        win.views.set_count(2)
        win.views.build_from_settings()
        win.views.views[1].pop_out()
        win.refresh_cameras()
        win.views.views[1].dock()
        for b in (self.bar(win, 0), self.bar(win, 1)):
            b.nextBtn.click()
            b.prevBtn.click()
            b.set_cameras(b.real_cameras(), "front")             # 直接の再構築も
        self.assertEqual(self.stub.created, [])
        self.assertNotIn("camera", [s for s in self.stub.seq])

    def test_programmatic_new_selection_is_not_a_request(self):
        win = self.build(1)
        b = self.bar(win, 0)
        before = self.cam(win, 0)
        b.combo.setCurrentIndex(self.new_index(b))               # activated なし(プログラムからの選択)
        self.assertEqual(self.stub.created, [])
        self.assertEqual(self.cam(win, 0), before)
        self.assertEqual(self.shown(win, 0), before)              # 表示は直前の実カメラのまま

    def test_wheel_and_keys_do_not_reach_new(self):
        win = self.build(1)
        b = self.bar(win, 0)
        combo = b.combo
        combo.show()
        reals = b.real_cameras()
        for typ in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):   # New 項目の先頭文字を打つ(先頭一致検索で当たる。QTest.keyClicks は非 ASCII を送れないので直接送る)
            QtWidgets.QApplication.sendEvent(combo, QtGui.QKeyEvent(typ, 0, QtCore.Qt.NoModifier, "\uff0b"))
        self.assertFalse(combo.is_new_index(combo.currentIndex()))
        self.assertEqual(self.stub.created, [])
        for _ in range(len(reals) + 3):
            ev = QtGui.QWheelEvent(QtCore.QPointF(5, 5), QtCore.QPointF(5, 5), QtCore.QPoint(0, 0), QtCore.QPoint(0, -120),
                                   QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
            QtWidgets.QApplication.sendEvent(combo, ev)
            self.assertFalse(combo.is_new_index(combo.currentIndex()))
        self.assertEqual(self.shown(win, 0), reals[-1])           # 末尾の実カメラで止まる
        for key in (QtCore.Qt.Key_Down, QtCore.Qt.Key_Down, QtCore.Qt.Key_End, QtCore.Qt.Key_PageDown):
            QtTest.QTest.keyClick(combo, key)
            self.assertFalse(combo.is_new_index(combo.currentIndex()))
        QtTest.QTest.keyClicks(combo, "New")                      # 実カメラ名 "New" の先頭一致でも New 項目を選ばない
        self.assertFalse(combo.is_new_index(combo.currentIndex()))
        QtTest.QTest.keyClick(combo, QtCore.Qt.Key_Home)
        self.assertEqual(self.shown(win, 0), reals[0])
        self.assertEqual(self.stub.created, [])

    # ---- 失敗 ---------------------------------------------------------
    def _assert_reverted(self, win, i, prev, before_nodes, before_sel):
        self.assertEqual(self.stub.cams, before_nodes)            # 既存ノードを消していない
        self.assertEqual(self.stub.deleted, [])
        self.assertEqual(self.cam(win, i), prev)
        self.assertEqual(self.shown(win, i), prev)
        self.assertFalse(self.bar(win, i).combo.is_new_index(self.bar(win, i).combo.currentIndex()))
        self.assertEqual(self.stub.sel, before_sel)
        self.assertFalse(win.views._creating_camera)

    def test_creation_exception_reverts_and_deletes_nothing(self):
        win = self.build(2)
        self.pick(self.bar(win, 0), "front")
        prev = self.cam(win, 0)
        other = self.cam(win, 1)
        nodes = list(self.stub.cams)
        self.stub.sel = ["pCube1"]
        self.stub.camera_fail = "raise"
        self.stub.warnings[:] = []
        self.pick_new(self.bar(win, 0))
        self._assert_reverted(win, 0, prev, nodes, ["pCube1"])
        self.assertEqual(self.cam(win, 1), other)
        self.assertEqual(self.stub.created, [])
        self.assertEqual(len(self.stub.warnings), 1, self.stub.warnings)          # 警告は 1 件(言語は環境依存なので文面は見ない)
        self.assertIn("camera", self.stub.warnings[0].lower())
        self.assertEqual(self.stub.seq.count("openChunk"), self.stub.seq.count("closeChunk"))   # チャンクは必ず閉じる
        self.assertEqual(self.stub.show_writes(), [])
        self.stub.camera_fail = None                               # 失敗のあとも通常どおり作成できる(再入フラグ残りなし)
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.created, ["camera1"])

    def test_creation_returning_nothing_is_failure(self):
        win = self.build(1)
        prev = self.cam(win, 0)
        nodes = list(self.stub.cams)
        self.stub.camera_fail = "empty"
        self.pick_new(self.bar(win, 0))
        self._assert_reverted(win, 0, prev, nodes, [])

    def test_creation_ok_but_view_switch_fails_keeps_previous_and_other_views(self):
        win = self.build(2)
        prev = self.cam(win, 0)
        other = self.cam(win, 1)
        self.stub.panel_cam_fail = True
        self.stub.warnings[:] = []
        self.stub.sel = ["pCube1"]
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.created, ["camera1"])          # 作成した 1 台は残す(消さない)
        self.assertEqual(self.stub.deleted, [])
        self.assertEqual(self.cam(win, 0), prev)
        self.assertEqual(self.shown(win, 0), prev)
        self.assertEqual(self.cam(win, 1), other)
        self.assertIn("camera1", self.bar(win, 1).real_cameras())  # 候補には出る
        self.assertEqual(self.stub.sel, ["pCube1"])
        self.assertEqual(len([w for w in self.stub.warnings if "camera1" in w]), 1, self.stub.warnings)
        self.assertFalse(win.views._creating_camera)

    # ---- 再入 ---------------------------------------------------------
    def test_scene_notification_and_second_request_during_creation(self):
        win = self.build(2)
        b0 = self.bar(win, 0)
        prev1 = self.cam(win, 1)

        def during():                 # cmds.camera の最中に、Maya のシーン通知 + 2 回目の New 要求
            win._on_scene_changed()
            win.refresh_cameras()
            self.stub.on_create = None
            b0.combo.activated.emit(self.new_index(b0))
            self.bar(win, 1).combo.activated.emit(self.new_index(self.bar(win, 1)))
        self.stub.on_create = during
        self.pick_new(b0)
        self.assertEqual(self.stub.created, ["camera1"], "作成は 1 台だけ")
        self.assertEqual(self.cam(win, 0).lstrip("|"), "camera1")
        self.assertEqual(self.cam(win, 1), prev1)
        self.assertFalse(win.views._creating_camera)
        self.assertEqual(self.stub.seq.count("camera"), 1)

    def test_request_after_close_is_ignored(self):
        win = self.build(1)
        win.views.closing = True
        b = self.bar(win, 0)
        before = self.shown(win, 0)
        self.pick_new(b)
        self.assertEqual(self.stub.created, [])
        self.assertFalse(b.combo.is_new_index(b.combo.currentIndex()))             # 無視した場合も表示は New に残らない
        self.assertEqual(self.shown(win, 0), before)

    # ---- 単独 / 複数 / ポップアウト -----------------------------------------
    def test_single_view(self):
        win = self.build(1)
        self.pick_new(self.bar(win, 0))
        self.assertEqual(self.stub.created, ["camera1"])
        self.assertEqual(self.cam(win, 0).lstrip("|"), "camera1")

    def test_popped_out_view_operates_only_itself(self):
        win = self.build(3, cameras=["persp", "front", "camA"])
        win.views.views[1].pop_out()
        self.assertTrue(win.views.views[1].is_popped())
        self.user_show(win, 0, "nurbsCurves", False)
        flags = [self.flags_of(win, i) for i in range(3)]
        cams = self.cams_of(win)
        self.pick_new(self.bar(win, 1))
        self.assertEqual(self.stub.created, ["camera1"])
        now = self.cams_of(win)
        self.assertEqual(now[1].lstrip("|"), "camera1")
        self.assertEqual([now[0], now[2]], [cams[0], cams[2]])
        self.assertEqual([self.flags_of(win, i) for i in range(3)][0], flags[0])
        for i in range(3):
            self.assertIn("camera1", self.bar(win, i).real_cameras())
        win.views.views[1].dock()                                  # ドック後も同じ
        self.assertEqual(self.cams_of(win)[0], cams[0])
        self.assertEqual(self.stub.created, ["camera1"])

    def test_each_view_can_create_in_turn(self):
        win = self.build(3)
        for i in range(3):
            self.pick_new(self.bar(win, i))
        self.assertEqual(self.stub.created, ["camera1", "camera2", "camera3"])
        self.assertEqual([c.lstrip("|") for c in self.cams_of(win)], ["camera1", "camera2", "camera3"])

    # ---- 互換 API / i18n -----------------------------------------------
    def test_window_set_camera_compat_does_not_pollute_candidates(self):
        win = self.build(1)
        win.set_camera("front", save=False)
        b = self.bar(win, 0)
        self.assertEqual(self.cam(win, 0), "front")
        self.assertEqual(b.real_cameras(), vpmod.list_cameras(True))
        self.new_index(b)
        self.assertEqual(b.combo.count(), len(vpmod.list_cameras(True)) + 1)
        self.assertEqual(self.stub.created, [])

    # ---- 文字入力の先頭一致検索(実カメラの項目だけが対象。New は対象外) ----------------
    def type_text(self, combo, text, mods=None):
        u"""閉じたコンボへ文字を送る(QTest.keyClicks は非 ASCII を送れないので QKeyEvent を直接送る)。"""
        for ch in text:
            key = ord(ch.upper()) if ord(ch) < 128 else 0
            for typ in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
                QtWidgets.QApplication.sendEvent(combo, QtGui.QKeyEvent(typ, key, mods or QtCore.Qt.NoModifier, ch))

    def new_search(self):
        u"""別の検索として始める(検索の連続入力時間を過ぎるまで待つ)。"""
        QtTest.QTest.qWait(QtWidgets.QApplication.keyboardInputInterval() + 40)

    def short_interval(self):
        old = QtWidgets.QApplication.keyboardInputInterval()
        QtWidgets.QApplication.setKeyboardInputInterval(40)
        self.addCleanup(QtWidgets.QApplication.setKeyboardInputInterval, old)

    def test_type_ahead_selects_real_cameras_only(self):
        self.short_interval()
        win = self.build(1, cameras=["persp"])
        combo = self.bar(win, 0).combo
        self.type_text(combo, "f")
        self.assertEqual((self.shown(win, 0), self.cam(win, 0)), ("front", "front"))      # 閉じたまま文字で選べる(従来操作)
        self.new_search()
        self.type_text(combo, "T")                                 # 大文字小文字は問わない
        self.assertEqual(self.cam(win, 0), "top")
        self.new_search()
        self.type_text(combo, "zzz")                               # 候補なし = 何も変えない
        self.assertEqual(self.cam(win, 0), "top")
        self.assertEqual(self.stub.created, [])

    def test_type_ahead_multi_char_and_repeat_cycle(self):
        self.short_interval()
        self.stub.cams[:] = ["persp", "camA", "camB", "camC", "top"]
        win = self.build(1, cameras=["persp"])
        combo = self.bar(win, 0).combo
        self.type_text(combo, "cam")                                # 複数文字(連続入力)
        self.assertEqual(self.cam(win, 0), "camA")
        self.type_text(combo, "B")                                  # camb
        self.assertEqual(self.cam(win, 0), "camB")
        self.new_search()
        seen = []
        for _ in range(4):                                          # 同じ文字の反復 = 次の候補へ循環(New へは進まない)
            self.type_text(combo, "c")
            seen.append(self.cam(win, 0))
        self.assertEqual(seen, ["camC", "camA", "camB", "camC"])    # 現在 camB の次から
        self.assertEqual(self.stub.created, [])
        self.assertFalse(combo.is_new_index(combo.currentIndex()))

    def test_type_ahead_real_camera_named_New_and_plus_prefixed(self):
        self.short_interval()
        self.stub.cams[:] = ["persp", "New", u"\uff0bcam", "top"]
        win = self.build(1, cameras=["persp"])
        combo = self.bar(win, 0).combo
        self.type_text(combo, "n")                                  # 実カメラ New は検索で選べる(作成ではない)
        self.assertEqual(self.cam(win, 0), "New")
        self.assertEqual(self.stub.created, [])
        self.new_search()
        self.type_text(combo, u"\uff0b")                            # New 項目の先頭文字: ＋ で始まる実カメラを選ぶ
        self.assertEqual(self.cam(win, 0), u"\uff0bcam")
        self.assertEqual(self.stub.created, [])
        self.new_search()
        self.type_text(combo, u"\uff0b N")                          # ＋ New という文字列に当たる実カメラは無い = 候補なし(New 項目は対象外)
        self.assertEqual(self.cam(win, 0), u"\uff0bcam")
        self.new_search()
        self.type_text(combo, u"\uff0b\uff0b\uff0b")                  # 反復しても New へは進まない
        self.assertEqual(self.stub.created, [])
        self.assertFalse(combo.is_new_index(combo.currentIndex()))

    def test_type_ahead_ignores_shortcuts_and_space_opens_popup(self):
        self.short_interval()
        win = self.build(1, cameras=["persp"])
        combo = self.bar(win, 0).combo
        combo.show()
        self.type_text(combo, "f", mods=QtCore.Qt.ControlModifier)  # Ctrl+F などの修飾付きは検索しない
        self.assertEqual(self.cam(win, 0), "persp")
        self.new_search()
        QtTest.QTest.keyClick(combo, QtCore.Qt.Key_Space)           # 検索中でない Space = ポップアップを開く
        self.assertTrue(combo.view().isVisible())
        combo.hidePopup()
        self.assertEqual(self.stub.created, [])

    def test_popup_explicit_new_still_works_after_type_ahead(self):
        self.short_interval()
        win = self.build(1, cameras=["persp"])
        b = self.bar(win, 0)
        self.type_text(b.combo, "f")
        self.assertEqual(self.stub.created, [])
        self._popup_pick(b.combo, self.new_index(b))                # ポップアップでの明示確定は従来どおり
        self.assertEqual(self.stub.created, ["camera1"])
        self.assertEqual(self.cam(win, 0).lstrip("|"), "camera1")

    # ---- 実際の Qt ポップアップ操作(シグナル順の確認。emit での模擬ではない) -----------
    def _popup_pick(self, combo, index):
        u"""本物の QComboBox ポップアップを開き、キーボードで項目へ移動して Enter(= 利用者が項目を選ぶ)。
        Qt の実際のシグナル順(currentIndexChanged → activated)を通す。offscreen ではマウスのリリースが届かないためキー操作で行う。"""
        combo.show()
        combo.showPopup()
        QtTest.QTest.qWait(300)
        view = combo.view()
        cur = view.currentIndex().row()
        key = QtCore.Qt.Key_Down if index > cur else QtCore.Qt.Key_Up
        for _ in range(abs(index - cur)):
            QtTest.QTest.keyClick(view, key)
        QtTest.QTest.keyClick(view, QtCore.Qt.Key_Return)
        QtTest.QTest.qWait(50)

    def test_real_popup_pick_on_new_creates_once(self):
        win = self.build(2, cameras=["persp", "front"])
        b = self.bar(win, 0)
        other = self.cam(win, 1)
        self._popup_pick(b.combo, self.new_index(b))
        self.assertEqual(self.stub.created, ["camera1"])
        self.assertEqual(self.cam(win, 0).lstrip("|"), "camera1")
        self.assertEqual(self.cam(win, 1), other)
        self.assertFalse(b.combo.view().isVisible())
        self.assertFalse(b.combo.is_new_index(b.combo.currentIndex()))

    def test_real_popup_pick_on_real_camera_switches_without_creating(self):
        win = self.build(1, cameras=["persp"])
        b = self.bar(win, 0)
        self._popup_pick(b.combo, b.combo.real_indices()[1])
        self.assertEqual(self.stub.created, [])
        self.assertEqual(self.cam(win, 0), b.combo.itemText(b.combo.real_indices()[1]))

    def test_real_popup_pick_on_new_with_zero_real_cameras(self):
        win = self.build(1)
        self.stub.cams[:] = []
        win.refresh_cameras()
        b = self.bar(win, 0)
        self.assertEqual(b.combo.currentIndex(), 0)               # 唯一の項目 = New が既に current
        self._popup_pick(b.combo, 0)                              # 同じ項目の再選択でも activated で作成される
        self.assertEqual(self.stub.created, ["camera1"])

    def test_new_strings_translated(self):
        i18n.set_language("en")
        try:
            for ja in (u"新規カメラを作成できませんでした: {}",
                       u"新規カメラ {} を作成しましたが、このビューへ切り替えられませんでした",
                       u"新規カメラを作成して、このビューへ切り替える"):
                self.assertNotEqual(i18n.tr(ja), ja, ja)
        finally:
            i18n.set_language("system")

    def test_paint_uses_real_camera_name_not_new_label(self):
        win = self.build(1)
        b = self.bar(win, 0)
        b.combo.setCurrentIndex(self.new_index(b))
        self.assertEqual(b.combo.display_text(), b.combo.last_real)
        self.assertEqual(b.current_camera(), b.combo.last_real)
        b.combo.resize(200, 26)
        pm = b.combo.grab()                                       # 描画が例外にならない
        self.assertFalse(pm.isNull())


if __name__ == "__main__":
    unittest.main(verbosity=2)
