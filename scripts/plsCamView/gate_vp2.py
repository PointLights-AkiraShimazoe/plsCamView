# -*- coding: utf-8 -*-
u"""
plsCamView.gate_vp2   【実験・既定 OFF・UI なし】
=========================================================
ゲート(マスク / 枠 / 内側ゲート)と構図ガイドを **Viewport 2.0 の内側、HUD より前** に描く経路。

背景: Maya の HUD(Frame / カメラ名 / fps / 軸)は VP2 の描画面の中に Maya 自身が描く。Qt の透明
ウィンドウ(gate_overlay)はその描画面の上に載るので、HUD の「上」にしか置けない。HUD の「下」に
ゲートを敷くには、ゲートも VP2 の描画の中で、HUD より先に描く必要がある。

方式(plsFxView の C++ と同じ順序): パネルのレンダラ**オーバーライド**を 1 つ登録し、
    MSceneRender(シーン + addPostUIDrawables にゲート/ガイド) → MHUDRender(HUD) → MPresentTarget
の順に実行する。ゲートの描画内容は gate_overlay.build_ops(Qt オーバーレイと同じ命令リスト)を
MUIDrawManager へ再生するだけで、描画定義は二重化しない。

【明示呼び出しのみ。自動では何もしない】
    from plsCamView import gate_vp2
    gate_vp2.enable("modelPanel4")     # そのパネルを VP2 内描画へ(Qt オーバーレイはそのパネルだけ停止)
    gate_vp2.disable("modelPanel4")    # 元のレンダラオーバーライドへ戻し、Qt オーバーレイを復帰
    gate_vp2.disable_all()

【実 Maya でしか確認できない点(クラウドでは未確認。docs/HUD前面表示_残務.md)】
    ・自作オーバーライドが標準 VP2(SSAO / AA / 選択ハイライト等)と同じ見た目でシーンを描くか
    ・addPostUIDrawables が HUD より前(MHUDRender より先)に実際に描かれるか
    ・MUIDrawManager の 2D 座標原点・rect2d の寸法規約・アルファ合成・HiDPI 倍率
    ・setup() 内で cmds / M3dView を呼んでよいか、ポップアウト・再ドック・パネル破棄後の挙動
"""
from __future__ import absolute_import

import math

try:
    from maya import cmds
    import maya.api.OpenMaya as om2
    import maya.api.OpenMayaRender as omr
    import maya.api.OpenMayaUI as omui2
except Exception:                                  # Maya 外
    cmds = None
    om2 = None
    omr = None
    omui2 = None

from . import gate_overlay as go

OVERRIDE_NAME = "plsCamView_gateBehindHud"
DASH = 6.0                                         # 内側ゲートの破線(Qt 側 CustomDashLine [6, 6] × 線幅 1)

# panel -> {"editor", "prev"(切替前の rendererOverrideName), "manager"(そのパネルを抑止している OverlayManager),
#           "pending"}
#   pending: None=稼働中 / "switching"=切替の途中 / "override"=オーバーライドの復帰が未完(disable で再試行) /
#            "qt"=オーバーライドは戻したが Qt 抑止の解除が未完(disable で再試行)
_state = {}
_override = None       # 登録に成功した MRenderOverride(登録に失敗したら None のまま)


# --------------------------------------------------------------------------
#  命令リスト → MUIDrawManager(純粋な幾何。Maya 無しで試験できる)
# --------------------------------------------------------------------------
def _rgba(rgb, alpha):
    r, g, b = [max(0.0, min(1.0, float(c))) for c in list(rgb)[:3]]
    return (r, g, b, max(0.0, min(1.0, float(alpha))))


def ring_strips(outer, hole):
    u"""outer から hole を除いた領域を、重ならない最大 4 枚の矩形(x, y, w, h)で返す(塗りの二重合成を避ける)。
    hole は outer にクリップする。hole が outer と交わらなければ outer 全体。"""
    ox, oy, ow, oh = outer
    hx, hy, hw, hh = hole
    x0, y0 = max(ox, hx), max(oy, hy)
    x1, y1 = min(ox + ow, hx + hw), min(oy + oh, hy + hh)
    if x1 <= x0 or y1 <= y0:
        return [tuple(outer)] if ow > 0 and oh > 0 else []
    out = []
    if y0 > oy:
        out.append((ox, oy, ow, y0 - oy))                       # 上
    if oy + oh > y1:
        out.append((ox, y1, ow, oy + oh - y1))                  # 下
    if x0 > ox:
        out.append((ox, y0, x0 - ox, y1 - y0))                  # 左(穴の高さ分)
    if ox + ow > x1:
        out.append((x1, y0, ox + ow - x1, y1 - y0))             # 右
    return out


def dash_segments(rect, dash=DASH):
    u"""矩形の外周(左上 → 右 → 下 → 左 → 上へ連続)を dash 長の on/off で刻んだ線分 (x0, y0, x1, y1) のリスト。"""
    x, y, w, h = rect
    pts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h), (x, y)]
    segs, on, carry = [], True, dash                             # carry: 現在の on/off の残り長
    for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
        L = math.hypot(bx - ax, by - ay)
        if L <= 0:
            continue
        ux, uy = (bx - ax) / L, (by - ay) / L
        pos = 0.0
        while pos < L - 1e-9:
            step = min(carry, L - pos)
            if on:
                segs.append((ax + ux * pos, ay + uy * pos, ax + ux * (pos + step), ay + uy * (pos + step)))
            pos += step
            carry -= step
            if carry <= 1e-9:
                on = not on
                carry = dash
    return segs


def flatten(ops, view_h):
    u"""命令リストを、描画先に依らない基本図形へ展開する(y は下原点へ反転済み)。
    ("fill", (cx, cy, hw, hh), rgba) = 塗り矩形(中心と半寸法) / ("line", (x0, y0, x1, y1), rgba, width)。"""
    out = []
    H = float(view_h)

    def L(x0, y0, x1, y1, col, wd):
        out.append(("line", (x0, H - y0, x1, H - y1), col, wd))

    for op in ops:
        kind = op[0]
        if kind == "ring":
            _, outer, hole, rgb, alpha = op
            col = _rgba(rgb, alpha)
            for (x, y, w, h) in ring_strips(outer, hole):
                out.append(("fill", (x + w * 0.5, H - (y + h * 0.5), w * 0.5, h * 0.5), col))
        elif kind == "rect":
            _, rect, rgb, alpha, width, dashed = op
            col = _rgba(rgb, alpha)
            if dashed:
                for s in dash_segments(rect):
                    L(s[0], s[1], s[2], s[3], col, width)
            else:
                x, y, w, h = rect
                for s in ((x, y, x + w, y), (x + w, y, x + w, y + h), (x + w, y + h, x, y + h), (x, y + h, x, y)):
                    L(s[0], s[1], s[2], s[3], col, width)
        elif kind == "lines":
            _, lines, rgb, alpha, width = op
            col = _rgba(rgb, alpha)
            for (x0, y0, x1, y1) in lines:
                L(x0, y0, x1, y1, col, width)
    return out


def replay(ops, dm, view_h, point=None, vector=None, color=None):
    u"""命令リストを MUIDrawManager(dm)へ描く。point / vector / color は MPoint / MVector / MColor(試験では差し替え)。
    HUD 用の 2D 描画マネージャと同じく、原点は下端左・単位は px と仮定(実機で要確認)。"""
    point = point or om2.MPoint
    vector = vector or om2.MVector
    color = color or om2.MColor
    n = 0
    for prim in flatten(ops, view_h):
        dm.beginDrawable()
        if prim[0] == "fill":
            (cx, cy, hw, hh), col = prim[1], prim[2]
            dm.setColor(color(col))
            dm.rect2d(point(cx, cy), vector(0.0, 1.0), hw, hh, True)     # scaleX / scaleY は半寸法と仮定(要確認)
        else:
            (x0, y0, x1, y1), col, wd = prim[1], prim[2], prim[3]
            dm.setColor(color(col))
            dm.setLineWidth(float(wd))
            dm.line2d(point(x0, y0), point(x1, y1))
        dm.endDrawable()
        n += 1
    return n


# --------------------------------------------------------------------------
#  レンダラオーバーライド(実 Maya 専用。Maya 外では作らない)
# --------------------------------------------------------------------------
def _view_size(panel):
    u"""パネルの 3D ビューの描画サイズ(デバイス px)。取れなければ None。"""
    try:
        editor = cmds.modelPanel(panel, q=True, modelEditor=True)
        view = omui2.M3dView.getM3dViewFromModelEditor(editor)
        w, h = int(view.portWidth()), int(view.portHeight())
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def _make_override():
    u"""MRenderOverride を作る(omr が使えるときだけ)。操作の順は SceneRender → HUDRender → PresentTarget。
    設定はパネルごとの manager(_state[panel]["manager"])から読む。override 自体はパネルに依らず 1 つで、manager は持たない。"""
    class _GateScene(omr.MSceneRender):
        def __init__(self, name, owner):
            omr.MSceneRender.__init__(self, name)
            self.owner = owner

        def hasUIDrawables(self):
            return True

        def renderFilterOverride(self):
            return omr.MSceneRender.kRenderAllItems          # PostSceneUIItems を含める(要確認)

        def addPostUIDrawables(self, drawManager, frameContext):
            o = self.owner
            if not o.size or o.manager is None:
                return
            w, h = o.size
            try:
                cfg = o.manager.config()
            except Exception:
                return
            if not go.any_drawing(cfg):
                return
            replay(go.build_ops(cfg, float(w), float(h), o.gate), drawManager, h)

    class _GateOverride(omr.MRenderOverride):
        def __init__(self, name):
            omr.MRenderOverride.__init__(self, name)
            self.panel = None
            self.manager = None
            self.size = None
            self.gate = None
            self._ops = [_GateScene("plsCamView_gateScene", self), omr.MHUDRender(), omr.MPresentTarget("plsCamView_present")]
            self._i = 0

        def supportedDrawAPIs(self):
            return omr.MRenderer.kAllDevices

        def uiName(self):
            return u"plsCamView ゲート(HUD前面・実験)"

        def setup(self, destination):
            self._i = 0
            self.panel = destination
            rec = _state.get(destination)
            self.manager = rec["manager"] if rec else None      # 描くパネルの manager(他パネルの設定は見ない)
            self.size = _view_size(destination)
            self.gate = go.compute_gate(destination, self.size[0], self.size[1]) if self.size else None
            return self

        def cleanup(self):
            self._i = 0
            return self

        def startOperationIterator(self):
            self._i = 0
            return True

        def renderOperation(self):
            return self._ops[self._i]

        def nextRenderOperation(self):
            self._i += 1
            return self._i < len(self._ops)

    return _GateOverride(OVERRIDE_NAME)


def _manager(manager):
    if manager is not None:
        return manager
    try:
        import importlib
        pkg = importlib.import_module(__package__)
        return pkg._instance.overlays
    except Exception:
        return None


def _warn(msg):
    try:
        cmds.warning(msg)
    except Exception:
        pass


def _usable(mgr):
    u"""抑止と設定の取得ができる manager か(できないものでは成功にしない)。"""
    return mgr is not None and callable(getattr(mgr, "set_suppressed", None)) and callable(getattr(mgr, "config", None))


def _query(editor):
    return cmds.modelEditor(editor, q=True, rendererOverrideName=True) or ""


def _restore_override(editor, prev):
    u"""**いま自分のオーバーライドが設定されているときだけ** prev へ戻す。
    "ok"=戻して確認できた / "foreign"=別のものに変わっていた(本人・別ツール。何も書かない) /
    "unknown"=照会できず確認できない(何も書かない) / "failed"=戻せなかった(再試行できる)。"""
    try:
        cur = _query(editor)
    except Exception:
        return "unknown"
    if cur != OVERRIDE_NAME:
        return "foreign"
    try:
        cmds.modelEditor(editor, e=True, rendererOverrideName=prev)
        return "ok" if _query(editor) == prev else "failed"
    except Exception:
        return "failed"


def _disable_record(panel, rec):
    u"""rec の復帰を、未完の段から進める(オーバーライドの復帰 → Qt 抑止の解除)。完了したときだけ状態を捨てる。
    どちらかが済まなければ、残りの段を pending に記録して False(disable で再試行できる)。"""
    if rec["pending"] != "qt":
        r = _restore_override(rec["editor"], rec["prev"])
        if r in ("unknown", "failed"):
            rec["pending"] = "override"
            return False
        rec["pending"] = "qt"
    try:
        ok = rec["manager"].set_suppressed(panel, False) is True
    except Exception:
        ok = False
    if not ok:
        rec["pending"] = "qt"
        return False
    _state.pop(panel, None)
    return True


def _reenable(panel, rec, mgr):
    u"""既に enable 済みのパネル。冪等: 何も書き換えず、抑止だけ確認して True。prev は上書きしない。"""
    if mgr is not rec["manager"] or rec["pending"] is not None:
        return False                                  # 別の manager・復帰途中。先に disable
    try:
        cur = _query(rec["editor"])
    except Exception:
        return False
    if cur != OVERRIDE_NAME:                          # 本人/別ツールが変えた: 上書きも復元もしない。こちらの抑止だけ外して状態を捨てる
        _disable_record(panel, rec)
        return False
    try:
        return mgr.set_suppressed(panel, True) is True
    except Exception:
        return False


def enable(panel, manager=None):
    u"""panel を VP2 内描画へ切り替える。成功 True。
    ・manager が無い/抑止できないものなら何も変えずに False。
    ・同じパネルの再 enable は冪等(元の rendererOverrideName を保持し、書き換えない)。
    ・記録が無いのに自分の名前が既に設定されているパネル(モジュール再読込などで記録を失った)は、元の設定が不明なので
      登録・切替・抑止のいずれもせず False(短い警告のみ)。元を推測して標準へ戻すことはしない。
    ・切替・抑止の確認に失敗したら、自分のオーバーライドが設定されているときだけ元へ戻す(別のものに変わっていたら触らない)。
      戻せなかった/確認できなかったときは状態を残し(status で pending)、disable で再試行できる。"""
    global _override
    if cmds is None or omr is None or not panel:
        return False
    mgr = _manager(manager)
    if not _usable(mgr):
        return False
    rec = _state.get(panel)
    if rec is not None:
        return _reenable(panel, rec, mgr)
    try:
        editor = cmds.modelPanel(panel, q=True, modelEditor=True)
        cur = _query(editor)
    except Exception:
        return False
    if cur == OVERRIDE_NAME:                          # 記録が無いのに自分の名前が設定済み(再読込などで記録を失った)。元の設定が不明
        _warn(u"gate_vp2: このパネルは既に %s に設定されていますが、元の設定が分からないため何も変更しません。"
              u"Renderer メニューで手動で戻してから enable してください。" % OVERRIDE_NAME)
        return False                                  # 登録・切替・抑止のいずれも行わない(元を捏造して標準へ戻すことはしない)
    try:
        if _override is None:
            ov = _make_override()
            omr.MRenderer.registerOverride(ov)
            _override = ov                            # 登録に成功してから保持(失敗なら None のまま。再試行で登録し直す)
    except Exception:
        return False
    rec = {"editor": editor, "prev": cur, "manager": mgr, "pending": "switching"}
    _state[panel] = rec
    try:
        cmds.modelEditor(editor, e=True, rendererOverrideName=OVERRIDE_NAME)
        now = _query(editor)
    except Exception:
        _disable_record(panel, rec)                   # 結果を確認できない: 確認できるときだけ戻し、無理なら pending を残す
        return False
    if now != OVERRIDE_NAME:                          # 切替が効いていない、または他が変えた。何も書き戻さない
        _state.pop(panel, None)
        return False
    try:
        ok = mgr.set_suppressed(panel, True) is True
    except Exception:
        ok = False
    if not ok:                                        # 抑止できない = 二重描画になる。切替を戻す
        _disable_record(panel, rec)
        return False
    rec["pending"] = None
    return True


def disable(panel, manager=None):
    u"""panel を元の rendererOverrideName へ戻し、Qt の抑止を解除する。両方済んだときだけ True(状態を捨てる)。
    途中で失敗したら状態を残して False(もう一度 disable で、済んでいない段から再試行する)。
    戻す時点で別のオーバーライドに変わっていたら、それは上書きせず、抑止の解除だけ行う。"""
    rec = _state.get(panel)
    if rec is None:
        mgr = _manager(manager)
        try:
            if _usable(mgr):
                mgr.set_suppressed(panel, False)      # 状態が無いときの保険(失敗しても何も失わない)
        except Exception:
            pass
        return False
    return _disable_record(panel, rec)


def disable_all(manager=None):
    u"""全パネルを disable。成功したパネル名のリスト。失敗したパネルは状態を残す(status() の pending)。"""
    return [p for p in list(_state) if disable(p, manager)]


def status():
    u"""{panel: {"prev": 元の名前, "pending": None/"override"/"qt", "checked": 存在を確認できたか}}。
    パネルの破棄を**確認できた**ときだけ状態を外す(照会の例外は破棄とみなさず、checked=False で残す)。"""
    out = {}
    for panel in list(_state):
        rec = _state[panel]
        checked = True
        try:
            exists = bool(cmds.modelPanel(panel, exists=True))
        except Exception:
            exists, checked = True, False
        if not exists:
            try:
                rec["manager"].set_suppressed(panel, False)
            except Exception:
                pass
            _state.pop(panel, None)
            continue
        out[panel] = {"prev": rec["prev"], "pending": rec["pending"], "checked": checked}
    return out
