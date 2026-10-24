# -*- coding: utf-8 -*-
u"""
plsCamView.gate_overlay
=======================
VP2 のビューポートの上に、レゾリューションゲート(マスク / 枠 / 内側ゲート)と構図ガイド
(三分割 / 黄金・白銀グリッド / アーマチュア / 中心)を描く透明オーバーレイ(v1.8.0)。

方式: 入力を素通しする半透明のツールウィンドウ(フレーム無し)を、ビューポートの Qt ウィジェットに
ぴったり重ねて追従させる。VP2 のレンダラ設定には触れない。Playblast には写らない(画面確認専用)。
ゲート矩形の計算は plsFxView(C++ の computeGate)と同じ: カメラの viewing frustum(ビューの縦横比・
オーバースキャン・パン/ズーム込み)と rendering frustum(レンダー解像度の縦横比)の比で求める。
ガイドの線は plsFxView の PSGate と同じ定義(比率矩形で計算して枠に引き伸ばす)。
"""
from __future__ import absolute_import

import math

from .qt import QtCore, QtGui, QtWidgets, to_qwidget, wrapInstance, omui
from .i18n import tr

try:
    from maya import cmds
    import maya.api.OpenMaya as om2
except Exception:                                  # Maya 外
    cmds = None
    om2 = None


GOLDEN = (1.0 + math.sqrt(5.0)) * 0.5
SILVER = math.sqrt(2.0)

DEFAULTS = {
    "gateEnabled": False,
    "gateMaskColor": [0.0, 0.0, 0.0],
    "gateMaskOpacity": 0.6,
    "gateLineColor": [1.0, 1.0, 1.0],
    "gateLineWidth": 1.0,
    "innerGateEnabled": [False, False, False],
    "innerGatePercent": [90.0, 80.0, 70.0],
    "innerGateColor": [[1.0, 0.85, 0.2], [0.3, 0.9, 1.0], [1.0, 0.45, 0.6]],
    "innerGateOpacity": [0.3, 0.3, 0.3],      # 塗りの不透明度
    "innerGateStroke": [True, True, True],
    "innerGateFill": [False, False, False],
    "innerGateDashed": True,
    "guideThirds": False,
    "guideGrid": False,
    "guideArmature": False,
    "guideCenter": False,
    "guideRatio": 0,          # 0 黄金 φ / 1 白銀 √2
    "guideFit": 0,            # 0 ゲート / 1..3 内側ゲート N / 4 ビュー全体
    "guideThirdsColor": [0.3, 0.5, 1.0],
    "guideGridColor": [1.0, 0.25, 0.25],
    "guideArmatureColor": [1.0, 0.9, 0.2],
    "guideOpacity": 0.8,
    "guideWidth": 1.0,
}


def _qcolor(rgb, alpha=1.0):
    r, g, b = [max(0.0, min(1.0, float(c))) for c in list(rgb)[:3]]
    return QtGui.QColor.fromRgbF(r, g, b, max(0.0, min(1.0, float(alpha))))


def _per_gate(v, default):
    u"""ゲートごとの値 3 つに(単一値・単一色は複製)。"""
    try:
        if v is None:
            raise ValueError
        if isinstance(v, (int, float)):
            return [v, v, v]
        v = list(v)
        single_color = (len(v) == 3 and all(isinstance(x, (int, float)) for x in v)
                        and isinstance(default[0], (list, tuple)))
        if single_color:
            return [list(v)] * 3
        if len(v) == 3 and not isinstance(default[0], (list, tuple)):
            return v
        return (v + list(default))[:3]
    except Exception:
        return list(default)


def any_drawing(cfg):
    u"""この設定で何か描くものがあるか。"""
    return bool(cfg.get("gateEnabled") or cfg.get("guideThirds") or cfg.get("guideGrid")
                or cfg.get("guideArmature") or cfg.get("guideCenter"))


# --------------------------------------------------------------------------
#  ゲート矩形(ビューポート px、左上原点)
# --------------------------------------------------------------------------
def _camera_shape(panel):
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


def compute_gate(panel, width, height):
    u"""(x, y, w, h) をビューポート px で返す。失敗時は None。"""
    if cmds is None or om2 is None or width <= 0 or height <= 0:
        return None
    shape = _camera_shape(panel)
    if not shape:
        return None
    try:
        sel = om2.MSelectionList()
        sel.add(shape)
        fn = om2.MFnCamera(sel.getDagPath(0))
        aspect = float(width) / float(height)
        vl, vr, vb, vt = fn.getViewingFrustum(aspect, True, False, True)   # overscan / squeeze / panZoom
        dev = float(cmds.getAttr("defaultResolution.deviceAspectRatio") or aspect)
        rl, rr, rb, rt = fn.getRenderingFrustum(dev)
    except Exception:
        return None
    vw = vr - vl
    vh = vt - vb
    if abs(vw) < 1e-12 or abs(vh) < 1e-12:
        return None
    x0 = (rl - vl) / vw
    x1 = (rr - vl) / vw
    y0 = (vt - rt) / vh          # 上端(画面は上が 0)
    y1 = (vt - rb) / vh
    return (x0 * width, y0 * height, (x1 - x0) * width, (y1 - y0) * height)


# --------------------------------------------------------------------------
#  オーバーレイ本体
# --------------------------------------------------------------------------
class GateOverlay(QtWidgets.QWidget):
    u"""1 つの modelPanel に重ねる透明ウィンドウ。"""

    POLL_MS = 200
    _FLAGS = (QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowDoesNotAcceptFocus)

    def __init__(self, panel, view_widget):
        super(GateOverlay, self).__init__(view_widget.window(), self._FLAGS)
        self.panel = panel
        self._view = view_widget
        self._top = view_widget.window()
        self._disposed = False
        self._syncing = False
        self._cfg = dict(DEFAULTS)
        self._gate = None
        self._last_key = None
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        try:
            self.setWindowFlag(QtCore.Qt.WindowTransparentForInput, True)
        except Exception:
            pass
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self._view.installEventFilter(self)
        top = self._view.window()
        if top is not None and top is not self._view:
            top.installEventFilter(self)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.POLL_MS)
        self._timer.timeout.connect(self._poll)
        self._sync_timer = QtCore.QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync_geometry)
        self._view.destroyed.connect(self.detach)
        self.hide()

    # ------------------------------------------------------------------
    def _retarget_top(self):
        u"""_view の属するトップレベルが変わっていたら(attach 直後の再親付け・ポップアウト・再ドック)、
        eventFilter と Qt の親を新しいトップへ移す。filter を移さないと移動イベントが古いウィンドウに
        しか届かず、ゲートが置き去りになる(v1.8.1 本人報告「移動するとゲートが遅れて付いてくる」で
        修正)。Qt の親も移さないと、旧トップが破棄された時にこのオーバーレイが Qt の親子関係で
        一緒に破棄され、生きているビューのゲートが消える(v1.8.1 の「親は生成時のまま」は
        この寿命問題があり撤回。親を常に現在のトップへ移せば、破棄されるのは非親ウィンドウだけ)。
        setParent はウィンドウフラグと可視状態をリセットするので両方を復元する。
        戻り値: 付け替えたら True。"""
        try:
            top = self._view.window()
        except RuntimeError:
            return False
        if top is None or top is self._top:
            return False
        old = self._top
        self._top = top
        try:
            if old is not None and old is not self._view and not _dead(old):
                old.removeEventFilter(self)
        except RuntimeError:
            pass
        if top is not self._view:
            top.installEventFilter(self)
        was_visible = self.isVisible()
        try:
            if self.parent() is not top:
                self.setParent(top, self._FLAGS)
        except RuntimeError:
            return True
        if was_visible:
            self.show()          # setParent は hide するので復元
            self.raise_()        # 新しいウィンドウの手前へ一度上げる(アクティブ化はしない)
        return True

    # ------------------------------------------------------------------
    def set_config(self, cfg):
        if self._disposed:
            return
        c = dict(DEFAULTS)
        c.update(cfg or {})
        self._cfg = c
        if any_drawing(c):
            self._sync_geometry()
            if not self.isVisible():
                self.show()
            if not self._timer.isActive():
                self._timer.start()
            self._last_key = None
            self._poll(force=True)
        else:
            self._timer.stop()
            self.hide()

    def detach(self):
        if self._disposed:
            return
        self._disposed = True
        self._timer.stop()
        self._sync_timer.stop()
        for widget in (self._view, self._top):
            try:
                if widget is not None:
                    widget.removeEventFilter(self)
            except RuntimeError:
                pass
        self.hide()
        self.deleteLater()

    def view_alive(self):
        try:
            return self._view is not None and self._view.isVisible() is not None
        except Exception:
            return False

    # ------------------------------------------------------------------
    def eventFilter(self, obj, ev):
        if getattr(self, '_disposed', True):
            return False
        t = ev.type()
        if t in (QtCore.QEvent.Resize, QtCore.QEvent.Move):
            # ドラッグ中は次のイベントループを待たず、画面位置・ゲートを揃える。
            self._sync_geometry()
        elif t in (QtCore.QEvent.LayoutRequest, QtCore.QEvent.Show,
                 QtCore.QEvent.WindowStateChange, QtCore.QEvent.WindowActivate):
            if not self._sync_timer.isActive():
                self._sync_timer.start(0)
        elif t in (QtCore.QEvent.Hide, QtCore.QEvent.Close):
            if obj is self._view or obj is self._top:
                self.hide()
        return False

    def _sync_geometry(self):
        if self._disposed or self._syncing or not any_drawing(self._cfg):
            return
        self._syncing = True
        try:
            # 先にトップレベルの付け替えを検出する(再親付け後も移動イベントを受け続けるため)。
            self._retarget_top()
            if not self._view.isVisible() or self._top.isMinimized():
                self.hide()
                return
            g = QtCore.QRect(self._view.mapToGlobal(QtCore.QPoint(0, 0)), self._view.size())
            if g.width() <= 0 or g.height() <= 0:
                self.hide()
                return
            resized = self.size() != g.size()
            if self.geometry() != g:
                self.setGeometry(g)
            if not self.isVisible():
                self.show()
                self.raise_()
            if resized:
                self._poll(force=True)
        except RuntimeError:
            self.hide()
        finally:
            self._syncing = False

    def _poll(self, force=False):
        u"""カメラ属性(オーバースキャン等)やレンダー解像度の変化を拾って再描画。
        v1.8.1: 位置の検証も行う。イベントを取りこぼした場合(再親付け直後・ドッキング操作中など)でも
        POLL_MS 以内に画面位置を揃え、_sync_geometry 内の _retarget_top で以降の移動イベントを
        受けられる状態へ戻す(間隔は従来のまま。主経路はあくまで Move/Resize イベント)。"""
        if self._disposed:
            return
        try:
            if not self._view.isVisible():
                return
        except Exception:
            self._timer.stop()
            return
        try:
            g = QtCore.QRect(self._view.mapToGlobal(QtCore.QPoint(0, 0)), self._view.size())
            if g.width() > 0 and g.height() > 0 and self.geometry() != g:
                self._sync_geometry()
        except RuntimeError:
            pass
        w, h = self.width(), self.height()
        gate = compute_gate(self.panel, w, h)
        key = (w, h, None if gate is None else tuple(round(v, 2) for v in gate))
        if force or key != self._last_key:
            self._last_key = key
            self._gate = gate
            self.update()

    # ------------------------------------------------------------------
    def paintEvent(self, event):
        cfg = self._cfg
        w, h = float(self.width()), float(self.height())
        if w <= 0 or h <= 0:
            return
        gate = self._gate or (0.0, 0.0, w, h)
        gx, gy, gw, gh = gate
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)

        if cfg.get("gateEnabled"):
            # マスク(ゲート外)
            mo = float(cfg.get("gateMaskOpacity", 0.6))
            if mo > 0.0:
                path = QtGui.QPainterPath()
                path.addRect(QtCore.QRectF(0, 0, w, h))
                inner = QtGui.QPainterPath()
                inner.addRect(QtCore.QRectF(gx, gy, gw, gh))
                p.fillPath(path.subtracted(inner), _qcolor(cfg.get("gateMaskColor", [0, 0, 0]), mo))
            # 内側ゲート
            ens = _per_gate(cfg.get("innerGateEnabled"), DEFAULTS["innerGateEnabled"])
            pcts = _per_gate(cfg.get("innerGatePercent"), DEFAULTS["innerGatePercent"])
            cols = _per_gate(cfg.get("innerGateColor"), DEFAULTS["innerGateColor"])
            ops = _per_gate(cfg.get("innerGateOpacity"), DEFAULTS["innerGateOpacity"])
            sts = _per_gate(cfg.get("innerGateStroke"), DEFAULTS["innerGateStroke"])
            fls = _per_gate(cfg.get("innerGateFill"), DEFAULTS["innerGateFill"])
            dashed = bool(cfg.get("innerGateDashed", True))
            for k in range(3):
                if not ens[k]:
                    continue
                pct = float(pcts[k]) * 0.01
                sw, sh = gw * pct, gh * pct
                sx, sy = gx + (gw - sw) * 0.5, gy + (gh - sh) * 0.5
                rect = QtCore.QRectF(sx, sy, sw, sh)
                if fls[k]:
                    # 塗り: 内側ゲートの外側(レゾリューションゲート内)
                    outer = QtGui.QPainterPath()
                    outer.addRect(QtCore.QRectF(gx, gy, gw, gh))
                    hole = QtGui.QPainterPath()
                    hole.addRect(rect)
                    p.fillPath(outer.subtracted(hole), _qcolor(cols[k], ops[k]))
                if sts[k]:
                    pen = QtGui.QPen(_qcolor(cols[k], 1.0), 1.0)
                    if dashed:
                        pen.setStyle(QtCore.Qt.CustomDashLine)
                        pen.setDashPattern([6.0, 6.0])
                    p.setPen(pen)
                    p.setBrush(QtCore.Qt.NoBrush)
                    p.drawRect(rect)
            # 外枠
            lw = float(cfg.get("gateLineWidth", 1.0))
            if lw > 0.0:
                p.setPen(QtGui.QPen(_qcolor(cfg.get("gateLineColor", [1, 1, 1]), 1.0), lw))
                p.setBrush(QtCore.Qt.NoBrush)
                p.drawRect(QtCore.QRectF(gx, gy, gw, gh))

        # ---- 構図ガイド ----
        if cfg.get("guideThirds") or cfg.get("guideGrid") or cfg.get("guideArmature") or cfg.get("guideCenter"):
            fit = int(cfg.get("guideFit", 0) or 0)
            fx, fy, fw, fh = gx, gy, gw, gh
            if 1 <= fit <= 3:
                pcts = _per_gate(cfg.get("innerGatePercent"), DEFAULTS["innerGatePercent"])
                pct = float(pcts[fit - 1]) * 0.01
                fw, fh = gw * pct, gh * pct
                fx, fy = gx + (gw - fw) * 0.5, gy + (gh - fh) * 0.5
            elif fit == 4:
                fx, fy, fw, fh = 0.0, 0.0, w, h
            R = SILVER if int(cfg.get("guideRatio", 0) or 0) == 1 else GOLDEN
            a = 1.0 / (1.0 + R)              # グリッド分割位置(黄金 0.382 / 白銀 0.414)
            e = 1.0 / (1.0 + R * R)          # アーマチュアの目(黄金 0.276 / 白銀 0.333)
            rc = 1.0 - 1.0 / (R * R)         # reciprocal の着地(黄金 0.618 / 白銀 0.5)
            op = float(cfg.get("guideOpacity", 0.8))
            gwd = float(cfg.get("guideWidth", 1.0))

            def seg(x0, y0, x1, y1):
                return QtCore.QLineF(fx + x0 * fw, fy + y0 * fh, fx + x1 * fw, fy + y1 * fh)

            def draw(lines, rgb):
                p.setPen(QtGui.QPen(_qcolor(rgb, op), gwd))
                p.drawLines(lines)

            if cfg.get("guideThirds"):
                t1, t2 = 1.0 / 3.0, 2.0 / 3.0
                draw([seg(t1, 0, t1, 1), seg(t2, 0, t2, 1), seg(0, t1, 1, t1), seg(0, t2, 1, t2)],
                     cfg.get("guideThirdsColor", DEFAULTS["guideThirdsColor"]))
            if cfg.get("guideGrid"):
                draw([seg(a, 0, a, 1), seg(1 - a, 0, 1 - a, 1), seg(0, a, 1, a), seg(0, 1 - a, 1, 1 - a)],
                     cfg.get("guideGridColor", DEFAULTS["guideGridColor"]))
            if cfg.get("guideArmature"):
                draw([seg(0, 0, 1, 1), seg(0, 1, 1, 0),
                      seg(1, 0, rc, 1), seg(0, 0, 1 - rc, 1),       # 右上 → 下辺 / 左上 → 下辺
                      seg(0, 1, 1 - rc, 0), seg(1, 1, rc, 0),       # 左下 → 上辺 / 右下 → 上辺
                      seg(e, 0, e, 1), seg(1 - e, 0, 1 - e, 1), seg(0, e, 1, e), seg(0, 1 - e, 1, 1 - e)],
                     cfg.get("guideArmatureColor", DEFAULTS["guideArmatureColor"]))
            if cfg.get("guideCenter"):
                cx, cy, r = fx + fw * 0.5, fy + fh * 0.5, 12.0
                p.setPen(QtGui.QPen(_qcolor([1, 1, 1], op), gwd))
                p.drawLines([QtCore.QLineF(cx - r, cy, cx + r, cy), QtCore.QLineF(cx, cy - r, cx, cy + r)])
        p.end()


# --------------------------------------------------------------------------
#  パネル → オーバーレイの管理
# --------------------------------------------------------------------------
class OverlayManager(object):
    u"""modelPanel ごとに GateOverlay を 1 つ持ち、同じ設定を配る。"""

    def __init__(self):
        self._overlays = {}
        self._cfg = dict(DEFAULTS)

    def set_config(self, cfg):
        self._cfg = dict(DEFAULTS)
        self._cfg.update(cfg or {})
        for panel in list(self._overlays.keys()):
            self._apply(panel)

    def ensure(self, panel):
        u"""panel にオーバーレイを付ける(既にあれば設定だけ配る)。"""
        if cmds is None or not panel:
            return None
        ov = self._overlays.get(panel)
        if ov is not None:
            try:
                if ov._view is not None and not _dead(ov._view):
                    self._apply(panel)
                    return ov
            except Exception:
                pass
            self.remove(panel)
        view = _view_widget(panel)
        if view is None:
            return None
        try:
            ov = GateOverlay(panel, view)
        except Exception as e:
            cmds.warning(u"[plsCamView] " + tr(u"ゲートオーバーレイを作れませんでした: {}").format(e))
            return None
        self._overlays[panel] = ov
        self._apply(panel)
        return ov

    def remove(self, panel):
        ov = self._overlays.pop(panel, None)
        if ov is not None:
            try:
                ov.detach()
            except Exception:
                pass

    def remove_all(self):
        for panel in list(self._overlays.keys()):
            self.remove(panel)

    def refresh(self):
        u"""ビューの作り直し・カメラ切替の後に呼ぶ(消えたパネルを掃除し、残りを再同期)。"""
        for panel in list(self._overlays.keys()):
            try:
                alive = cmds.modelPanel(panel, exists=True)
            except Exception:
                alive = False
            if not alive:
                self.remove(panel)
                continue
            ov = self._overlays[panel]
            try:
                ov._last_key = None
                ov._sync_geometry()
                ov._poll(force=True)
            except Exception:
                pass

    def _apply(self, panel):
        ov = self._overlays.get(panel)
        if ov is None:
            return
        try:
            ov.set_config(self._cfg)
        except Exception:
            pass


def _dead(widget):
    try:
        widget.objectName()
        return False
    except Exception:
        return True


def _view_widget(panel):
    u"""modelPanel の 3D ビュー部分の QWidget。M3dView.widget() が本命(ツールバーを含まない)、
    取れなければ modelEditor / modelPanel のコントロール。"""
    try:
        editor = cmds.modelPanel(panel, q=True, modelEditor=True)
    except Exception:
        editor = None
    if editor and omui is not None:
        try:
            view = omui.M3dView.getM3dViewFromModelEditor(editor)
            ptr = view.widget()
            if ptr:
                return wrapInstance(int(ptr), QtWidgets.QWidget)
        except Exception:
            pass
    for name in (editor, panel):
        if not name:
            continue
        wdg = to_qwidget(name)
        if wdg is not None:
            return wdg
    return None
