# -*- coding: utf-8 -*-
u"""
plsCamView.ui
=============
分離カメラビュー本体の UI。

    cmds.window                      … Maya のウィンドウ(メインから分離)
      └ cmds.paneLayout              … 2 ペイン(ビュー領域 / ツールボックス)
           ├ paneLayout(ビュー領域)  … 最大 4 ビュー。各ビュー = formLayout[カメラバー(Qt) + modelPanel]
           └ formLayout              … この中に Qt でツールボックスを描く

ビューポート側を Qt のウィンドウに付け替えないのは、Maya が組み立てる UI パスが
壊れて `updateModelPanelBar` が構文エラーになり、アイコンバーやメニューが
機能しなくなるため(viewport.py の説明を参照)。
ツールボックスは Maya レイアウト配下の QWidget として作るので、Maya の UI ツリーは
壊れない。

ツールボックスの内容
    - ドック位置(上下左右のアイコンボタン)
    - Views(ビュー数 1〜4 / 配置: 横並び・縦並び・グリッド / カメラ一覧の再取得)
      ※カメラ選択と Playblast 対象・ポップアウトは各ビュー上部のバー(views.py)
    カードの順は Views → Show → (Shadow) → Effects → Playblast。
    Playblast の書き出し設定は折り畳み(Settings)にまとめ、
    Force Playblast Target / 完了後に開く / 実行ボタンだけを常時見せる。
    - Screen-space Ambient Occlusion
    - Anti-aliasing
    - Shadow
    - Show(All / None / Polygon + Joint / NurbsCurve)
    - Force Playblast Target
    - Playblast 出力(Maya 標準 / MP4 + Playblaster と同じオプション)
"""
from __future__ import absolute_import

from .qt import QtCore, QtGui, QtWidgets, to_qwidget, attach_widget   # noqa: F401
from . import settings as st
from . import viewport as vp
from . import vp2
from . import playblast_hook as pbh
from . import mp4blast, multiblast
from . import gate_overlay as go
from . import views as vw
from . import style
from . import i18n
from .i18n import tr

try:
    from maya import cmds
except Exception:
    cmds = None


WINDOW_NAME = "plsCamViewWin"
WINDOW_TITLE = u"PLS CamView"
PANE_NAME = "plsCamViewPane"

_DOCK_ORDER = [("left", u"左"), ("top", u"上"), ("bottom", u"下"), ("right", u"右")]

# attributeQuery でレンジが取れなかった場合のフォールバック
_SLIDER_FALLBACK = {
    "ssaoAmount":       (0.0, 2.0),
    "ssaoRadius":       (0.0, 48.0),
    "ssaoFilterRadius": (0.0, 32.0),
}


# ==========================================================================
#  小物
# ==========================================================================
def _attr_range(key):
    u"""hardwareRenderingGlobals のアトリビュートのスライダ範囲を推定。"""
    lo, hi = _SLIDER_FALLBACK.get(key, (0.0, 1.0))
    if cmds is None:
        return lo, hi
    attr = vp2.ATTR.get(key, key)
    for flag in ("softRange", "range"):
        try:
            r = cmds.attributeQuery(attr, node=vp2.NODE, **{flag: True})
            if r and len(r) == 2 and r[1] > r[0]:
                return float(r[0]), float(r[1])
        except Exception:
            continue
    return lo, hi


def _combo_text_width(combo):
    u"""コンボの最長項目が欠けない幅(実フォント計測 + 矢印・枠 px(36))。ToolBox のスタイルが
    届いた後(全カードを _body へ入れた後)に呼ぶ。固定値だと UI フォント差で欠ける(0.9.1)。"""
    combo.ensurePolished()
    fm = combo.fontMetrics()
    widest = max([fm.horizontalAdvance(combo.itemText(i)) for i in range(combo.count())] or [0])
    return widest + style.px(36)


def _field_label(text, width=80):
    lab = QtWidgets.QLabel(text)
    lab.setObjectName("fieldLabel")
    lab.setMinimumWidth(style.px(width))
    lab.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
    return lab


def _note(text):
    lab = QtWidgets.QLabel(text)
    lab.setObjectName("note")
    lab.setWordWrap(True)
    return lab


def _rgb3(v, default):
    u"""設定値を 3 要素の float タプルに(欠損・長さ違いは default)。"""
    try:
        t = tuple(float(x) for x in v)
        if len(t) == 3:
            return t
    except Exception:
        pass
    return tuple(float(x) for x in default)


def _per_gate(v, default):
    u"""インナーゲートごとの値 3 つに(0.2.15 以前の単一値・単一色は 3 つに複製、欠損は default)。"""
    try:
        if v is None:
            raise ValueError
        if isinstance(v, (int, float)):
            return [v, v, v]
        v = list(v)
        if len(v) == 3 and all(isinstance(x, (int, float)) for x in v) and not isinstance(default[0], (list, tuple)):
            return v
        if len(v) == 3 and isinstance(default[0], (list, tuple)) and all(isinstance(x, (int, float)) for x in v):
            return [list(v)] * 3   # 旧形式の単一色
        v = (v + list(default))[:3]
        return v
    except Exception:
        return list(default)




class ColorButton(QtWidgets.QPushButton):
    u"""色見本ボタン。クリックで QColorDialog。value() は [r, g, b](0..1)。"""

    colorChanged = QtCore.Signal(object)

    def __init__(self, rgb=(1.0, 1.0, 1.0), parent=None):
        super(ColorButton, self).__init__(parent)
        self._rgb = [float(c) for c in rgb]
        self.setObjectName("plsColorButton")   # スタイルをこのボタンだけに限定(子の QColorDialog に継承させない)
        self.setFixedSize(style.px(40), style.px(20))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def _refresh(self):
        r, g, b = [int(max(0.0, min(1.0, c)) * 255) for c in self._rgb]
        self.setStyleSheet(style.scale_css(
            u"#plsColorButton{{background:rgb({},{},{});border:1px solid #666;border-radius:3px;"
            u"padding:0px;min-height:0px;min-width:0px;}}".format(r, g, b)))

    def value(self):
        return list(self._rgb)

    def setValue(self, rgb):
        self._rgb = [float(c) for c in rgb][:3]
        self._refresh()

    def _pick(self):
        q = QtGui.QColor.fromRgbF(*[max(0.0, min(1.0, c)) for c in self._rgb])
        col = QtWidgets.QColorDialog.getColor(q, self.window(), tr(u"Color"))
        if col.isValid():
            self.setValue([col.redF(), col.greenF(), col.blueF()])
            self.colorChanged.emit(self.value())


class IconToggle(QtWidgets.QToolButton):
    u"""Photoshop の「線 / 塗り」のような小さなアイコンの ON/OFF ボタン。kind: "stroke" / "fill"。"""

    def __init__(self, kind, tooltip=u"", parent=None):
        super(IconToggle, self).__init__(parent)
        self._kind = kind
        self.setCheckable(True)
        self.setFixedSize(style.px(24), style.px(20))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setStyleSheet(style.scale_css(
            u"QToolButton{border:1px solid #555;border-radius:3px;background:#2a2d33;}"
            u"QToolButton:checked{border:1px solid #8ab4ff;background:#3a4252;}"))

    def paintEvent(self, event):
        super(IconToggle, self).paintEvent(event)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        on = self.isChecked()
        col = QtGui.QColor(230, 230, 230) if on else QtGui.QColor(130, 130, 130)
        # アイコンはボタン中央に UI 倍率どおりの大きさで描く(0.9.1 r5。固定座標だと縮小時に偏る)
        sz = 11.0 * style.px(100) / 100.0
        r = QtCore.QRectF((self.width() - sz) / 2.0, (self.height() - sz) / 2.0, sz, sz)
        if self._kind == "fill":
            p.setPen(QtCore.Qt.NoPen)
            p.setBrush(col)
            p.drawRect(r)
        else:
            pen = QtGui.QPen(col, 1.5)
            p.setPen(pen)
            p.setBrush(QtCore.Qt.NoBrush)
            p.drawRect(r)
            p.setBrush(QtGui.QColor(42, 45, 51))
            p.setPen(QtCore.Qt.NoPen)
            p.drawRect(r.adjusted(3, 3, -3, -3))
        p.end()


class SliderRow(QtWidgets.QWidget):
    u"""[ラベル][数値フィールド][スライダ] の 1 行。"""

    valueChanged = QtCore.Signal(object)

    def __init__(self, label, minimum, maximum, decimals=0, parent=None):
        super(SliderRow, self).__init__(parent)
        self._decimals = decimals
        self._min = float(minimum)
        self._max = float(maximum)
        self._steps = 1000 if decimals else max(1, int(self._max - self._min))

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(style.px(8))

        self.label = _field_label(label)

        if decimals:
            self.field = style.FitDoubleSpinBox()
            self.field.setDecimals(decimals)
            self.field.setSingleStep(0.01)
            self.field.setMinimum(self._min)
            self.field.setMaximum(self._max)
        else:
            self.field = style.FitSpinBox()
            self.field.setMinimum(int(self._min))
            self.field.setMaximum(int(self._max))
        self.field.setFit(style.px(64))      # 現行幅。最悪値の表示が収まらない欄だけ style.FitSpinBox が広げる
        self.field.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.field.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)

        self.slider = style.Slider(QtCore.Qt.Horizontal)   # FX-WHEEL-GUARD: ホイールはフォーカス時だけ
        self.slider.setMinimumWidth(style.px(56))
        self.slider.setMinimum(0)
        self.slider.setMaximum(self._steps)
        self.slider.setCursor(QtCore.Qt.PointingHandCursor)

        lay.addWidget(self.label)
        lay.addWidget(self.field)
        lay.addWidget(self.slider, 1)

        self.field.valueChanged.connect(self._on_field)
        self.slider.valueChanged.connect(self._on_slider)

    # ------------------------------------------------------------------
    def _to_slider(self, v):
        if self._max <= self._min:
            return 0
        r = (float(v) - self._min) / (self._max - self._min)
        return int(round(max(0.0, min(1.0, r)) * self._steps))

    def _from_slider(self, s):
        r = float(s) / float(self._steps or 1)
        v = self._min + r * (self._max - self._min)
        return v if self._decimals else int(round(v))

    def _on_field(self, v):
        self.slider.blockSignals(True)
        self.slider.setValue(self._to_slider(v))
        self.slider.blockSignals(False)
        self.valueChanged.emit(self.value())

    def _on_slider(self, s):
        v = self._from_slider(s)
        self.field.blockSignals(True)
        self.field.setValue(v)
        self.field.blockSignals(False)
        self.valueChanged.emit(self.value())

    # ------------------------------------------------------------------
    def value(self):
        v = self.field.value()
        return float(v) if self._decimals else int(v)

    def setValue(self, v):
        self.field.blockSignals(True)
        self.slider.blockSignals(True)
        try:
            self.field.setValue(float(v) if self._decimals else int(v))
            self.slider.setValue(self._to_slider(v))
        except Exception:
            pass
        self.field.blockSignals(False)
        self.slider.blockSignals(False)

    def setEnabledRow(self, on):
        self.label.setEnabled(on)
        self.field.setEnabled(on)
        self.slider.setEnabled(on)


class DockPicker(QtWidgets.QWidget):
    u"""上下左右のアイコンボタンでツールボックスの位置を選ぶ。"""

    changed = QtCore.Signal(str)

    def __init__(self, parent=None):
        super(DockPicker, self).__init__(parent)
        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setContentsMargins(0, style.px(2), 0, style.px(2))
        # 0.9.1: アイコン間隔を詰めて最上段(アイコン 4 つ+歯車+Language)を最も広いカード以下に保つ
        self._grid.setHorizontalSpacing(style.px(4))
        self._grid.setVerticalSpacing(style.px(6))

        self._buttons = {}
        self._order = []
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        for key, tip in _DOCK_ORDER:
            b = QtWidgets.QToolButton()
            b.setObjectName("dockBtn")
            b.setCheckable(True)
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setIcon(style.dock_icon(key))
            b.setIconSize(QtCore.QSize(style.px(30), style.px(30)))
            b.setFixedSize(style.px(40), style.px(36))
            b.setToolTip(tr(u"ツールボックスを{}に配置").format(tr(tip)))
            group.addButton(b)
            self._buttons[key] = b
            self._order.append(b)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))
        self.setCompact(False)

    def setCompact(self, compact):
        u"""compact=True で 2×2(上下配置用)、False で 1 行 4 個。"""
        g = self._grid
        for b in self._order:
            g.removeWidget(b)
        for i, b in enumerate(self._order):
            if compact:
                g.addWidget(b, i // 2, i % 2)
            else:
                g.addWidget(b, 0, i)
        for c in range(4):
            g.setColumnStretch(c, 0)
        g.setAlignment(QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop)

    def setCurrent(self, key):
        b = self._buttons.get(key)
        if b is None:
            return
        b.blockSignals(True)
        b.setChecked(True)
        b.blockSignals(False)


# ==========================================================================
#  ツールボックス
# ==========================================================================
def _hidden_gone(w):
    u"""g4: 並びから外す部品か(隠れていて、場所を取っておく指定 retainSizeWhenHidden も無い)。"""
    return not w.isVisibleTo(w.parentWidget()) and not w.sizePolicy().retainSizeWhenHidden()


class _FlowLayout(QtWidgets.QLayout):
    u"""左から並べ、幅が足りないときだけ次の行へ折り返すレイアウト(g3。PLAYBLAST の先頭行用)。"""

    # 高さは「直前に配置された幅」で決める(heightForWidth は使わない)。カードは縦を sizeHint で固定しているため、
    # heightForWidth だと折り返した分が sizeHint に入らず下が切れる。幅が変わって行数が変わったら次の回で取り直す。

    def __init__(self, parent=None, hspacing=8, vspacing=6):
        super(_FlowLayout, self).__init__(parent)
        self._items = []
        self._h = hspacing
        self._v = vspacing
        self._lastW = 0
        self._groups = []                          # 各項目の組番号。同じ組は、入る限り同じ行に置く
        self._nextGroup = 0
        self.setContentsMargins(0, 0, 0, 0)

    def newGroup(self):
        u"""次に足す項目から新しい組。組がその行に収まらなければ、組の頭で改行する(Multi と 合成/個別保持 を離さない)。"""
        self._nextGroup += 1

    def addItem(self, item):
        self._items.append(item)
        self._groups.append(self._nextGroup)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        if 0 <= i < len(self._items):
            self._groups.pop(i)
            return self._items.pop(i)
        return None

    def expandingDirections(self):
        return QtCore.Qt.Orientations()

    def _height_at(self, width):
        if width <= 0:
            return self._one_line()[1]
        return self._do_layout(QtCore.QRect(0, 0, width, 0), True)

    def _one_line(self):
        w = h = 0
        for it in self._items:
            if it.widget() is not None and _hidden_gone(it.widget()):
                continue
            s = it.sizeHint()
            w += s.width() + (self._h if w else 0)
            h = max(h, s.height())
        return w, h

    def setGeometry(self, rect):
        super(_FlowLayout, self).setGeometry(rect)
        self._lastW = rect.width()
        need = self._do_layout(rect, False)
        if need != rect.height():
            # 行数が変わった(幅・部品の表示が変わった)。sizeHint は新しい幅で答えるので、親に寸法の取り直しを頼む
            w = self.parentWidget()
            if w is not None:
                w.updateGeometry()

    def sizeHint(self):
        # 望む幅は 1 行分(上限 hint_cap)。実際の幅は親が決め、収まる分だけ 1 行に並ぶ
        w, _ = self._one_line()
        if getattr(self, "hint_groups", False):     # 望む幅 = いちばん広い組 1 つ分(組は割らずに 1 行へ)
            w = max(self._group_widths().values() or [0])
        return QtCore.QSize(max(self.minimumSize().width(), w), self._height_at(self._lastW))

    def _group_widths(self):
        gw = {}
        for it, g in zip(self._items, self._groups):
            wdg = it.widget()
            if wdg is not None and _hidden_gone(wdg):
                continue
            gw[g] = gw.get(g, -self._h) + it.sizeHint().width() + self._h
        return gw

    def minimumSize(self):
        w = h = 0
        for it in self._items:
            if it.widget() is not None and _hidden_gone(it.widget()):
                continue
            s = it.sizeHint()                       # 部品は sizeHint 未満に潰さない(折り返しで逃がす)
            w = max(w, s.width())
            h = max(h, s.height())
        return QtCore.QSize(w, max(h, self._height_at(self._lastW)))

    def _do_layout(self, rect, test):
        # 行ごとに集めてから、行の高さの中で上下中央に置く(見出しと入力欄の中心をそろえる)
        vis = []
        for it, g in zip(self._items, self._groups):
            wdg = it.widget()
            if wdg is not None and _hidden_gone(wdg):
                continue
            vis.append((it, g, it.sizeHint()))
        gw = {}                                    # 組ごとの 1 行の幅
        for it, g, s in vis:
            gw[g] = gw.get(g, -self._h) + s.width() + self._h
        lines, cur, x, prev = [], [], rect.x(), None
        full = rect.width()
        for it, g, s in vis:
            head = g != prev
            prev = g
            # 組の頭: 組ごと入らず、組が 1 行に収まる大きさなら、組の頭で改行する
            need = gw[g] if (head and gw[g] <= full) else s.width()
            if cur and x + need > rect.right() + 1:
                lines.append(cur)
                cur, x = [], rect.x()
            cur.append((it, x, s))
            x += s.width() + self._h
        if cur:
            lines.append(cur)
        y = rect.y()
        for n, line in enumerate(lines):
            lh = max(s.height() for _, _, s in line)
            if not test:
                for it, lx, s in line:
                    it.setGeometry(QtCore.QRect(QtCore.QPoint(lx, y + (lh - s.height()) // 2), s))
            y += lh + (self._v if n + 1 < len(lines) else 0)
        return y - rect.y()


class _PbScroll(QtWidgets.QScrollArea):
    u"""上下配置のときの PLAYBLAST カードの入れ物(g2)。縦だけスクロールする。
    幅 = 中身の幅 + スクロールバー分(バーが出ても中身を押し縮めない)。高さの最小は 1(ペインが低ければスクロール)。"""

    def __init__(self, parent=None):
        super(_PbScroll, self).__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Preferred)

    def _content_width(self):
        w = self.widget()
        if w is None:
            return 0
        return (max(w.sizeHint().width(), w.minimumSizeHint().width())
                + self.verticalScrollBar().sizeHint().width())

    def sizeHint(self):
        w = self.widget()
        return QtCore.QSize(self._content_width(), w.sizeHint().height() if w is not None else 0)

    def minimumSizeHint(self):
        return QtCore.QSize(self._content_width(), 1)

    def eventFilter(self, obj, e):
        # 中身の開閉で必要な幅・高さが変わったら、自分の寸法も取り直してもらう
        if obj is self.widget() and e.type() == QtCore.QEvent.LayoutRequest:
            self.updateGeometry()
        return super(_PbScroll, self).eventFilter(obj, e)


class ToolBox(QtWidgets.QWidget):

    def __init__(self, owner, parent=None):
        super(ToolBox, self).__init__(parent)
        self.setObjectName("plsRoot")
        self.owner = owner
        self._building = True
        self._horizontal = False
        self._pbSettingsRestore = None     # 横配置へ入るとき自動で畳む前の Settings の畳み状態(開いていたら False)。None = 戻す物なし
        self._pbAutoFold = False           # 横配置の出入りで Settings を自動で畳む / 戻している最中(利用者の操作ではない。保存しない)
        self._effectsRestore = None        # 横配置へ入るとき自動で畳む前の Effects の畳み状態(開いていたら False)。None = 戻す物なし
        self._effectsAutoFold = False      # 横配置の出入りで Effects を自動で畳む / 戻している最中(利用者の操作ではない。保存しない)
        # 言語はカードを作る前に復元する(v1.8.1。既定 system。仕様は i18n.py)
        i18n.set_language(str((owner.data or {}).get("language", "system")))
        # UI 倍率(0.9.x)。スタイル生成・固定寸法の計算より前に適用する。
        style.set_ui_scale((owner.data or {}).get("uiScale", style.UI_SCALE_DEFAULT))
        self.setStyleSheet(style.stylesheet())

        # 縦: [scroll(全カード)]   上下配置: [scroll(他カード)] [Playblast カード(固定・常に見える)]
        self._outer = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom, self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(style.px(8))
        # Maya のホスト(formLayout)へ最小サイズを要求しない。ホストより大きい最小値を返すと、
        # ホストの QLayout と _HostFitter(geometry 合わせ)が互いに上書きし合って Maya が固まる
        self._outer.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        # 最小サイズは明示値だけ(幅 300 / 高さ 1)。Qt は明示値があれば minimumSizeHint を見ないので
        # 中身の最小サイズが Maya 側へ伝わらない。sizePolicy は通常のまま(Ignored にすると paneLayout の
        # 初期配分で幅 0 扱いになり、保存した比率が効かないことがある)
        self.setMinimumSize(style.px(300), 1)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        # 中身の最小幅より狭いときの最終フォールバック(通常は各カードが既定幅に収まる)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self._outer.addWidget(self._scroll, 1)

        body = QtWidgets.QWidget()
        body.setObjectName("plsRoot")
        self._scroll.setWidget(body)
        self._body = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom, body)
        self._body.setContentsMargins(style.px(8), style.px(8), style.px(8), style.px(8))
        self._body.setSpacing(style.px(8))

        self.dockPicker = DockPicker()
        self.dockPicker.changed.connect(self._on_dock_changed)

        # Language はレイアウト切替アイコンと同じ行の右端(0.9.1 仕様)。適用案内
        # (_languageNote)は最小幅 300px・上下配置(2x2 アイコン)でも収まるよう 2 行目に出す。
        self._topRow = QtWidgets.QWidget()
        _topBox = QtWidgets.QVBoxLayout(self._topRow)
        _topBox.setContentsMargins(0, 0, 0, 0)
        _topBox.setSpacing(style.px(2))
        _dockRow = QtWidgets.QHBoxLayout()
        _dockRow.setContentsMargins(0, 0, 0, 0)
        _dockRow.setSpacing(style.px(4))   # 縦ドックの標準幅でもアイコン 4 つ+歯車+コンボが収まる間隔
        _dockRow.addWidget(self.dockPicker)
        _dockRow.addStretch(1)
        self.scaleBtn = QtWidgets.QToolButton()
        self.scaleBtn.setObjectName("dockBtn")
        self.scaleBtn.setText(u"⚙")
        self.scaleBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.scaleBtn.setFixedSize(style.px(36), style.px(36))
        self.scaleBtn.setToolTip(tr(u"表示設定 — UI 倍率(75〜125%)。適用は開き直しで行います"))
        self.scaleBtn.clicked.connect(self._show_scale_menu)
        _dockRow.addWidget(self.scaleBtn)
        _dockRow.addLayout(self._build_language_row())
        _topBox.addLayout(_dockRow)
        _topBox.addWidget(self._languageNote)

        self._cards = [
            self._topRow,
            self._build_views(),
            self._build_show(),
            self._build_shadow(),
            self._build_effects(),
            self._build_gate(),
            self._build_guides(),
            self._build_playblast(),
        ]
        self._pbCard = self._cards[-1]
        for w in self._cards:
            # g2: カードは縦を自然な高さ(sizeHint)で固定する。パネルが低いときはスクロールで見る。
            # (Preferred のままだと、中身が長いとき各カードが最小値まで縮み、数値欄やトグルが数 px 潰れる)
            pol = w.sizePolicy()
            pol.setVerticalPolicy(QtWidgets.QSizePolicy.Fixed)
            w.setSizePolicy(pol)
            self._body.addWidget(w)
        self._body.addStretch(1)

        # Language コンボの幅は実フォントの最長項目から決める(固定値だと DPI・フォント差で
        # 欠ける)。+36 は矢印と枠の分。全カードを _body へ入れて ToolBox のスタイルが届いた
        # 後に測る(親に入る前だと小さいフォントで測れて文字が欠ける)。
        self.languageCombo.setFixedWidth(_combo_text_width(self.languageCombo))
        # 0.9.1: Guides の比率 / 合わせる枠も同じ規則(英語や Windows フォントで項目名が欠けない)。
        # 既定の見た目幅は下限として保つ。どちらも単独の行なので広がっても他の項目を押さない。
        self.guideRatio.setFixedWidth(max(style.px(110), _combo_text_width(self.guideRatio)))
        self.guideFit.setFixedWidth(max(style.px(170), _combo_text_width(self.guideFit)))
        self._align_pb_labels()

        self._building = False

    def _build_language_row(self):
        u"""UI 言語の選択(v1.8.1 仕様)。0.9.1 でレイアウト切替アイコンと同じ行の右端へ移動
        (System / 日本語 / English・保存と翻訳適用の仕様は従来どおり)。選択は保存され、文言は
        次に開いたときに適用。ダイアログ・警告は即時に新しい言語になる。識別子・名前・パスは
        翻訳しない。適用案内(_languageNote)はここで作り、呼び出し側が行の下(2 行目)に置く。"""
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(style.px(4))
        self.languageCombo = style.ComboBox()
        for code, label in (("system", tr(u"System")), ("ja", u"日本語"), ("en", u"English")):
            self.languageCombo.addItem(label, code)
        # 「Language」の文字ラベルはツールチップへ畳む(最小幅 300px の行に収めるため。0.9.1)
        self.languageCombo.setToolTip(tr(u"Language — UI の表示言語。システム = Maya / OS の言語に従う"))
        self.languageCombo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        # 幅は親(スタイル)に入った後、__init__ 側で実フォントから決める(_fit_language_width)。
        current = str((self.owner.data or {}).get("language", "system"))
        idx = self.languageCombo.findData(current)
        self.languageCombo.setCurrentIndex(idx if idx >= 0 else 0)
        self.languageCombo.currentIndexChanged.connect(self._on_language)
        row.addWidget(self.languageCombo)
        self._languageNote = _note(u"")
        self._languageNote.setVisible(False)
        return row

    def _build_scale_menu(self):
        u"""UI 倍率メニュー(0.9.x)。選択は保存のみ。適用はユーザーの明示操作
        (メニューの「開き直して適用」を選ぶ / 次回起動)で行い、自動では開き直さない。"""
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(style.stylesheet())
        current = self._saved_ui_scale()
        # QActionGroup は PySide6 で QtGui へ移動(QtWidgets には無い)
        _ActionGroup = getattr(QtWidgets, "QActionGroup", None) or QtGui.QActionGroup
        group = _ActionGroup(menu)
        group.setExclusive(True)
        for pct in style.UI_SCALE_CHOICES:
            label = u"{}%".format(pct)
            if pct == style.UI_SCALE_DEFAULT:
                label += tr(u"(標準)")
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(pct == current)
            group.addAction(act)
            act.triggered.connect(lambda _=False, p=pct: self._on_ui_scale(p))
        menu.addSeparator()
        reset = menu.addAction(tr(u"標準({}%)へ戻す").format(style.UI_SCALE_DEFAULT))
        reset.triggered.connect(lambda _=False: self._on_ui_scale(style.UI_SCALE_DEFAULT))
        menu.addSeparator()
        apply_now = menu.addAction(tr(u"開き直して適用"))
        apply_now.setToolTip(tr(u"保存した倍率でウィンドウを開き直します(未保存の設定は自動保存されます)"))
        apply_now.triggered.connect(self._restart_tool)
        return menu

    def _show_scale_menu(self):
        menu = self._build_scale_menu()
        pos = self.scaleBtn.mapToGlobal(QtCore.QPoint(0, self.scaleBtn.height()))
        (menu.exec if hasattr(menu, "exec") else menu.exec_)(pos)

    def _saved_ui_scale(self):
        u"""保存済み UI 倍率(%)。手編集等で壊れた値でもメニューを落とさず既定へ。"""
        try:
            return int(round(float((self.owner.data or {}).get("uiScale", style.UI_SCALE_DEFAULT))))
        except Exception:
            return style.UI_SCALE_DEFAULT

    def _on_ui_scale(self, percent):
        percent = int(percent)
        if self._saved_ui_scale() == percent:
            return
        self.owner.data["uiScale"] = percent
        self.owner.save_settings()
        self._languageNote.setText(
            tr(u"UI 倍率 {}% を保存しました。歯車メニューの「開き直して適用」または次回起動で適用されます").format(percent))
        self._languageNote.setVisible(True)

    def _restart_tool(self):
        u"""ユーザーの明示操作による開き直し(plsCamView.restart() と同じ)。"""
        pkg = __name__.split(".")[0]

        def _go():
            try:
                import importlib
                importlib.import_module(pkg).restart()
            except Exception:
                pass
        QtCore.QTimer.singleShot(0, _go)

    def _on_language(self, *_):
        if self._building:
            return
        code = self.languageCombo.currentData() or "system"
        self.owner.data["language"] = code
        self.owner.save_settings()
        i18n.set_language(code)
        # 既に並んでいるラベルは作り直しが必要なので、その場では文言を変えずに案内だけ出す。
        self._languageNote.setText(tr(u"言語設定は次にウィンドウを開いたときに適用されます"))
        self._languageNote.setVisible(True)

    # ------------------------------------------------------------------
    def set_orientation(self, horizontal):
        u"""ツールボックスが上下に配置されたときはカードを横並びにする。"""
        d = (QtWidgets.QBoxLayout.LeftToRight if horizontal
             else QtWidgets.QBoxLayout.TopToBottom)
        if self._body.direction() == d:
            return
        self._body.setDirection(d)
        for w in self._cards:
            if horizontal:
                self._body.setAlignment(w, QtCore.Qt.AlignTop)
            else:
                self._body.setAlignment(w, QtCore.Qt.Alignment())
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setMinimumSize(1 if horizontal else style.px(300), 1)
        self._reflow(horizontal)
        self._horizontal = horizontal

        # Playblast カードは上下配置ではスクロール領域の外(右端)に固定して、常に押せるようにする
        pbs = self._pb_scroll()
        self._body.removeWidget(self._pbCard)
        self._outer.removeWidget(self._pbCard)
        self._pbHolderLay.removeWidget(self._pbCard)
        self._outer.removeWidget(pbs)
        self.dockPicker.setCompact(horizontal)
        if horizontal:
            self._outer.setDirection(QtWidgets.QBoxLayout.LeftToRight)
            self._outer.setContentsMargins(0, style.px(8), style.px(8), style.px(8))
            # g2: ペインが低いときは PLAYBLAST だけ縦スクロール(押し縮めて部品が重なるのを防ぐ)
            self._pbHolderLay.insertWidget(0, self._pbCard)
            self._outer.addWidget(pbs, 0)
            pbs.show()
            self._pbCard.show()
            # 高さを抑えるため、入ったときは畳んでおく(必要なら開けばペインが広がる)
            # 利用者が選んだ開閉状態(保存値 effectsCollapsed)は上書きしない。縦へ戻すときに元へ戻す(Settings と同じ方式)
            self._effectsRestore = None if self._effectsCard.isCollapsed() else False
            self._auto_fold_effects(True)
            # Settings も自動で畳むが、利用者が選んだ開閉状態(保存値)は上書きしない。縦へ戻すときに元へ戻す
            self._pbSettingsRestore = None if self.pbSettings.isCollapsed() else False
            self._auto_fold_pb_settings(True)
        else:
            self._outer.setDirection(QtWidgets.QBoxLayout.TopToBottom)
            self._outer.setContentsMargins(0, 0, 0, 0)
            pbs.hide()
            self._body.insertWidget(self._body.count() - 1, self._pbCard)   # stretch の手前
            self._pbCard.show()
            if self._pbSettingsRestore is not None:
                restore, self._pbSettingsRestore = self._pbSettingsRestore, None
                self._auto_fold_pb_settings(restore)
            if self._effectsRestore is not None:
                restore, self._effectsRestore = self._effectsRestore, None
                self._auto_fold_effects(restore)

    def _auto_fold_pb_settings(self, collapsed):
        u"""向きの切替で Settings を自動で畳む / 戻す。利用者の操作ではないので設定へは保存しない(高さの合わせ直しだけ行う)。"""
        self._pbAutoFold = True
        try:
            self.pbSettings.setCollapsed(collapsed)
        finally:
            self._pbAutoFold = False

    def _auto_fold_effects(self, collapsed):
        u"""向きの切替で Effects を自動で畳む / 戻す。利用者の操作ではないので設定へは保存しない(高さの合わせ直しだけ行う)。"""
        self._effectsAutoFold = True
        try:
            self._effectsCard.setCollapsed(collapsed)
        finally:
            self._effectsAutoFold = False

    def is_horizontal(self):
        return bool(getattr(self, "_horizontal", False))

    def _pb_scroll(self):
        u"""上下配置用の PLAYBLAST の入れ物(初回だけ作る)。中身 = [カード][余白]。カードは自然な高さのまま上寄せ。"""
        pbs = getattr(self, "_pbScroll", None)
        if pbs is None:
            pbs = _PbScroll()
            holder = QtWidgets.QWidget()
            holder.setObjectName("plsRoot")
            self._pbHolderLay = QtWidgets.QVBoxLayout(holder)
            self._pbHolderLay.setContentsMargins(0, 0, 0, 0)
            self._pbHolderLay.setSpacing(0)
            self._pbHolderLay.addStretch(1)
            pbs.setWidget(holder)
            pbs.hide()
            self._pbScroll = pbs
        return pbs

    def preferred_height(self):
        u"""上下配置のときに必要な高さ(スクロール無しで全カードが見える高さ)。"""
        try:
            # 折り畳み直後は LayoutRequest が未処理でサイズヒントが古いことがあるので先に流す
            QtWidgets.QApplication.sendPostedEvents()
            self._body.activate()
            self._outer.activate()
            body = self._scroll.widget()
            h = body.sizeHint().height() + 12
            pb = self._pbCard.sizeHint().height() + 16
            return max(h, pb) + 4
        except Exception:
            return 260

    # ------------------------------------------------------------------
    #  上下配置のときは「高さ最小・横に伸びる」ように各カードの中身を並べ替える
    # ------------------------------------------------------------------
    def _reflow(self, horizontal):
        self._reflow_views(horizontal)
        self._reflow_effects(horizontal)
        self._reflow_playblast(horizontal)

    def _reflow_views(self, horizontal):
        g = self._viewsGrid
        for w in (self._countRow, self._layoutBox, self.startupCamChk):
            g.removeWidget(w)
        self._layoutBoxLay.setDirection(
            QtWidgets.QBoxLayout.TopToBottom if horizontal else QtWidgets.QBoxLayout.LeftToRight)
        if horizontal:
            # [配置(縦積み)] [ 1 2 3 4  ⟳ ]
            #                [ 標準カメラ     ]
            g.addWidget(self._layoutBox, 0, 0, 2, 1, QtCore.Qt.AlignTop)
            g.addWidget(self._countRow, 0, 1)
            g.addWidget(self.startupCamChk, 1, 1, QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
            g.setColumnStretch(0, 0)
            g.setColumnStretch(1, 1)
        else:
            # [ 1 2 3 4  ⟳ ]
            # [配置(横並び)  ]
            # [標準カメラ    ]
            # (0.9.1: 配置と標準カメラを同じ行に置くと、英語/Windows フォントで
            #  標準右ドック幅を超えるため別行にする)
            g.addWidget(self._countRow, 0, 0, 1, 2)
            g.addWidget(self._layoutBox, 1, 0, 1, 2, QtCore.Qt.AlignLeft)
            g.addWidget(self.startupCamChk, 2, 0, 1, 2, QtCore.Qt.AlignLeft)
            g.setColumnStretch(0, 0)
            g.setColumnStretch(1, 1)

    def _reflow_effects(self, horizontal):
        lay = self._effectsFlow
        lay.setDirection(QtWidgets.QBoxLayout.LeftToRight if horizontal
                         else QtWidgets.QBoxLayout.TopToBottom)
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is not None:
                lay.setAlignment(w, QtCore.Qt.AlignTop if horizontal else QtCore.Qt.Alignment())

    def _reflow_playblast(self, horizontal):
        # g4: 上下配置(PLAYBLAST は内容の幅の縦スクロール)では、Multi / Time Range / 完了後に開く の行が
        # 列の幅を広げないよう、望む幅を「組 1 つ分」にする(入らない組は次の行へ。切替では変わらない)。
        for row in (getattr(self, "_pbMultiRow", None), getattr(self, "_pbRangeHead", None),
                    getattr(self, "_pngRow", None)):
            if row is not None:
                row.layout().hint_groups = bool(horizontal)
                row.updateGeometry()
        main, flow = self._pbMainCol, self._pbFlow
        main.removeWidget(self.pbSettings)
        flow.removeWidget(self.pbSettings)
        if horizontal:
            # [Force / Multi / Time Range / Output / 撮影オプション / 完了後に開く / 実行] | [Settings(数値。畳めば見出しだけ)]
            flow.setDirection(QtWidgets.QBoxLayout.LeftToRight)
            flow.addWidget(self.pbSettings, 1, QtCore.Qt.AlignTop)
        else:
            # Force / Multi / Time Range / Output / Settings / 撮影オプション / 完了後に開く / 実行(縦)
            flow.setDirection(QtWidgets.QBoxLayout.TopToBottom)
            main.insertWidget(main.indexOf(self.pbOutputBox) + 1, self.pbSettings)

    # ------------------------------------------------------------------
    def _on_dock_changed(self, key):
        if self._building:
            return
        self.owner.set_dock_area(key)

    # ------------------------------------------------------------------
    def _build_views(self):
        card = style.Card(tr(u"Views"))

        # ビュー数(1〜4)
        self.viewCountSeg = style.SegmentedControl(
            [(str(i), str(i)) for i in range(1, vw.MAX_VIEWS + 1)])
        self.viewCountSeg.setToolTip(tr(u"ビューの数"))
        self.viewCountSeg.setMinimumWidth(style.px(184))
        self.viewCountSeg.changed.connect(self._on_view_count)

        # 配置(横並び / 縦並び / グリッド)。上下配置のときは縦に積む(_reflow_views)
        self._layoutBox = QtWidgets.QWidget()
        row = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight, self._layoutBox)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(style.px(8))
        self._layoutBoxLay = row
        self._layoutBtns = {}
        group = QtWidgets.QButtonGroup(self)
        group.setExclusive(True)
        for key, tip in (("horizontal", u"横並び"), ("vertical", u"縦並び"), ("grid", u"グリッド")):
            b = QtWidgets.QToolButton()
            b.setObjectName("dockBtn")
            b.setCheckable(True)
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setIcon(vw.layout_icon(key))
            b.setIconSize(QtCore.QSize(style.px(30), style.px(30)))
            b.setFixedSize(style.px(40), style.px(36))
            b.setToolTip(tr(u"ビューを{}に配置").format(tr(tip)))
            group.addButton(b)
            self._layoutBtns[key] = b
            row.addWidget(b)
            b.clicked.connect(lambda _=False, k=key: self._on_view_layout(k))

        # 標準カメラ
        self.startupCamChk = style.ToggleSwitch(tr(u"標準カメラ"))
        self.startupCamChk.setToolTip(tr(u"persp / top / front / side をカメラ一覧に含める"))
        self.startupCamChk.toggled.connect(self._on_startup_cam_changed)

        # ビュー数 + カメラ一覧の再取得(1 行にまとめる)
        self._countRow = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(self._countRow)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(style.px(8))
        row.addWidget(self.viewCountSeg, 1)
        self.camRefreshBtn = QtWidgets.QToolButton()
        self.camRefreshBtn.setObjectName("dockBtn")
        self.camRefreshBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.camRefreshBtn.setIcon(style.camera_refresh_icon())
        self.camRefreshBtn.setIconSize(QtCore.QSize(style.px(30), style.px(30)))
        self.camRefreshBtn.setFixedSize(style.px(40), style.px(36))
        self.camRefreshBtn.setToolTip(tr(u"カメラ一覧を読み直す(カメラを追加・削除したとき)"))
        self.camRefreshBtn.clicked.connect(lambda: self.owner.refresh_cameras())
        row.addWidget(self.camRefreshBtn)

        self._viewsGrid = QtWidgets.QGridLayout()
        self._viewsGrid.setContentsMargins(0, 0, 0, 0)
        self._viewsGrid.setHorizontalSpacing(style.px(8))
        self._viewsGrid.setVerticalSpacing(style.px(10))
        card.addLayout(self._viewsGrid)
        self._reflow_views(False)
        return card

    def _on_view_count(self, key):
        if self._building:
            return
        self.owner.views.set_count(int(key))

    def _on_view_layout(self, key):
        if self._building:
            return
        self.owner.views.set_layout(key)

    def set_view_state(self, count, layout):
        u"""ビュー数と配置の表示をオーナーの状態に合わせる。"""
        self._building = True
        try:
            self.viewCountSeg.setCurrent(str(count))
            b = self._layoutBtns.get(layout)
            if b is not None:
                b.setChecked(True)
        finally:
            self._building = False

    def _on_startup_cam_changed(self, *_):
        if self._building:
            return
        self.owner.data["showStartupCameras"] = self.startupCamChk.isChecked()
        self.owner.refresh_cameras()

    # ------------------------------------------------------------------
    def _build_effects(self):
        card = style.CollapsibleCard(tr(u"Effects"))
        self.effectsMaster = style.ToggleSwitch(u"")
        self.effectsMaster.setToolTip(tr(u"OFF で SSAO・アンチエイリアス・線 AA をまとめて切る(個別の設定は保持)"))
        self.effectsMaster.toggled.connect(self._on_effects_master)
        card.setHeaderWidget(self.effectsMaster)
        self._effectsFlow = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom)
        self._effectsFlow.setContentsMargins(0, 0, 0, 0)
        self._effectsFlow.setSpacing(style.px(10))
        self._effectsFlow.addWidget(self._build_ssao())
        self._effectsFlow.addWidget(self._build_aa())
        card.addLayout(self._build_preset_row())
        card.addLayout(self._effectsFlow)
        card.collapsedChanged.connect(self._on_effects_collapsed)
        self._effectsCard = card
        return card

    # -- 調整プリセット(FX-PRESETS) ---------------------------------------------
    #  Effects の値と ON/OFF に名前を付けて保存 / 切替(保存先・キー集合は settings.py の PRESET_SPEC)。
    #  ＋ = 現在値を新しいプリセットとして保存 / ✓ = 選択中を現在値で更新 / ↺ = 選択中の保存値へ戻す
    #  (↺ は、選択中で、保存値と現在値が違うときだけ出る。Grade の「既定値 Reset」とは別)。
    def _preset_btn(self, glyph, tip, slot):
        b = QtWidgets.QToolButton()
        b.setObjectName("dockBtn")
        b.setText(glyph)
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.setFixedSize(style.px(28), style.px(28))
        b.setToolTip(tip)
        b.clicked.connect(slot)
        return b

    def _build_preset_row(self):
        box = QtWidgets.QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(style.px(2))
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(style.px(4))
        self.presetCombo = style.ComboBox()
        self.presetCombo.setToolTip(tr(u"調整プリセット(Effects の値と ON/OFF)。選ぶと保存した値を適用します"))
        self.presetCombo.currentIndexChanged.connect(self._on_preset_picked)
        row.addWidget(self.presetCombo, 1)
        self.presetNewBtn = self._preset_btn(u"\uff0b", tr(u"現在の値を新しいプリセットとして保存"), self._on_preset_new)
        self.presetUpdateBtn = self._preset_btn(u"\u2713", tr(u"選択中のプリセットを現在の値で更新"), self._on_preset_update)
        self.presetResetBtn = self._preset_btn(u"\u21ba", tr(u"選択中のプリセットの保存値へ戻す(保存値は変えません)"), self._on_preset_reset)
        for b in (self.presetNewBtn, self.presetUpdateBtn, self.presetResetBtn):
            row.addWidget(b)
        box.addLayout(row)
        self.presetMsg = QtWidgets.QLabel(u"")
        self.presetMsg.setObjectName("note")
        self.presetMsg.setVisible(False)
        box.addWidget(self.presetMsg)
        self._presetBox = box
        self.refresh_presets()
        return box

    def refresh_presets(self, message=None, error=False, short=None):
        u"""プリセット欄(一覧・選択・✓ の有効 / ↺ の出し分け)を現在の設定に合わせる。
        message があれば、short(短語。無ければ message)だけを出し、詳細の文章は tooltip へ。"""
        ops = getattr(self.owner, "presets", None)
        combo = getattr(self, "presetCombo", None)
        if combo is None:
            return
        names = ops.names() if ops is not None else []
        sel = ops.selected() if ops is not None else u""
        combo.blockSignals(True)
        try:
            want = [u""] + list(names)
            if [combo.itemData(i) for i in range(combo.count())] != want:
                combo.clear()
                combo.addItem(tr(u"— プリセット —"), u"")
                for n in names:
                    combo.addItem(n, n)
            i = combo.findData(sel)
            combo.setCurrentIndex(i if i >= 0 else 0)
        finally:
            combo.blockSignals(False)
        for w in (combo, self.presetNewBtn):
            w.setEnabled(ops is not None)
        self.presetUpdateBtn.setEnabled(bool(sel))
        self.presetResetBtn.setVisible(bool(sel) and ops is not None and ops.is_dirty())
        if message is not None:
            self.presetMsg.setText(short or message)
            self.presetMsg.setToolTip(message)
            self.presetMsg.setProperty("error", bool(error))
            self.presetMsg.setVisible(bool(message))
        else:
            self.presetMsg.setVisible(False)

    def _preset_done(self, ok, msg, pull=False):
        if pull:
            self.pull_effects(self.owner.data)       # 適用した値(失敗時は戻した値)を UI へ。保存済みの値は変えない
        ops = getattr(self.owner, "presets", None)
        short = tr(st.PRESET_SHORT.get(getattr(ops, "last_kind", u""), u"")) if ops is not None and msg else None
        self.refresh_presets(msg, error=not ok, short=short or None)
        if not ok and msg:
            try:
                cmds.warning(u"[plsCamView] " + msg)
            except Exception:
                pass

    def _ask_preset_name(self):
        u"""名前の入力(取消は None)。試験ではここを差し替える。"""
        text, ok = QtWidgets.QInputDialog.getText(self, tr(u"プリセットの保存"), tr(u"名前"))
        return text if ok else None

    def _on_preset_new(self, *_):
        ops = getattr(self.owner, "presets", None)
        if self._building or ops is None:
            return
        name = self._ask_preset_name()
        if name is None:
            return
        ok, msg = ops.save_new(name)
        self._preset_done(ok, msg)

    def _on_preset_update(self, *_):
        ops = getattr(self.owner, "presets", None)
        if self._building or ops is None:
            return
        ok, msg = ops.update_selected()
        self._preset_done(ok, msg)

    def _on_preset_picked(self, *_):
        ops = getattr(self.owner, "presets", None)
        if self._building or ops is None:
            return
        name = self.presetCombo.currentData() or u""
        if name == ops.selected():
            return
        ok, msg = ops.select(name)
        self._preset_done(ok, msg, pull=bool(name))

    def _on_preset_reset(self, *_):
        ops = getattr(self.owner, "presets", None)
        if self._building or ops is None:
            return
        ok, msg = ops.reset()
        self._preset_done(ok, msg, pull=True)

    def _on_effects_collapsed(self, collapsed):
        if self._building:
            return
        if not self._effectsAutoFold:
            self._effectsRestore = None           # 利用者が選んだ。向きを戻しても、この選択を優先する
            self.owner.data["effectsCollapsed"] = bool(collapsed)
            self.owner.save_settings()
        self._after_collapse_change()

    def _after_collapse_change(self):
        u"""上下配置では、畳む/開くのたびにペインの高さを中身に合わせる。"""
        if self.is_horizontal():
            fit = getattr(self.owner, "fit_toolbox_height", None)
            if fit:
                QtCore.QTimer.singleShot(0, fit)

    def _on_effects_master(self, *_):
        if self._building:
            return
        d = self.owner.data
        d["effectsMaster"] = self.effectsMaster.isChecked()
        if vp2.apply_all(d):
            vp2.refresh_viewport()
        self._update_effects_master()
        self.owner.save_settings()

    def _update_effects_master(self):
        on = self.effectsMaster.isChecked()
        self._ssaoCard.setEnabled(on)
        self._aaCard.setEnabled(on)

    # ------------------------------------------------------------------
    def _build_ssao(self):
        card = style.SubSection(tr(u"Screen-space Ambient Occlusion"))
        self._ssaoCard = card
        self.ssaoEnable = style.ToggleSwitch(tr(u"Enable"))
        self.ssaoEnable.toggled.connect(self._on_ssao)
        card.addWidget(self.ssaoEnable)

        lo, hi = _attr_range("ssaoAmount")
        self.ssaoAmount = SliderRow(tr(u"Amount"), lo, hi, decimals=3)
        lo, hi = _attr_range("ssaoRadius")
        self.ssaoRadius = SliderRow(tr(u"Radius"), lo, hi)
        lo, hi = _attr_range("ssaoFilterRadius")
        self.ssaoFilter = SliderRow(tr(u"Filter Radius"), lo, hi)
        for w in (self.ssaoAmount, self.ssaoRadius, self.ssaoFilter):
            w.valueChanged.connect(self._on_ssao)
            card.addWidget(w)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(style.px(8))
        self._ssaoSamplesLabel = _field_label(tr(u"Samples"))
        self.ssaoSamples = style.ComboBox()
        for v in vp2.SSAO_SAMPLE_CHOICES:
            self.ssaoSamples.addItem(str(v), v)
        self.ssaoSamples.setFixedWidth(style.px(76))
        self.ssaoSamples.currentIndexChanged.connect(self._on_ssao)
        row.addWidget(self._ssaoSamplesLabel)
        row.addWidget(self.ssaoSamples)
        row.addStretch(1)
        card.addLayout(row)

        return card

    def _on_ssao(self, *_):
        if self._building:
            return
        d = self.owner.data
        d["ssaoEnable"] = self.ssaoEnable.isChecked()
        d["ssaoAmount"] = self.ssaoAmount.value()
        d["ssaoRadius"] = self.ssaoRadius.value()
        d["ssaoFilterRadius"] = self.ssaoFilter.value()
        d["ssaoSamples"] = self.ssaoSamples.currentData()
        if vp2.apply_all(d):
            vp2.refresh_viewport()
        self._update_ssao_enabled()
        self.owner.save_settings()

    def _update_ssao_enabled(self):
        on = self.ssaoEnable.isChecked()
        for w in (self.ssaoAmount, self.ssaoRadius, self.ssaoFilter):
            w.setEnabledRow(on)
        self.ssaoSamples.setEnabled(on)
        self._ssaoSamplesLabel.setEnabled(on)

    # ------------------------------------------------------------------
    def _build_aa(self):
        card = style.SubSection(tr(u"Anti-aliasing"))
        self._aaCard = card
        self.aaEnable = style.ToggleSwitch(tr(u"Enable Anti-aliasing"))
        self.aaEnable.toggled.connect(self._on_aa)
        card.addWidget(self.aaEnable)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(style.px(8))
        self._aaSamplesLabel = _field_label(tr(u"Sample count"))
        self.aaSamples = style.ComboBox()
        for v in vp2.AA_SAMPLE_CHOICES:
            self.aaSamples.addItem(str(v), v)
        self.aaSamples.setFixedWidth(style.px(76))
        self.aaSamples.currentIndexChanged.connect(self._on_aa)
        row.addWidget(self._aaSamplesLabel)
        row.addWidget(self.aaSamples)
        row.addStretch(1)
        card.addLayout(row)

        self.lineAA = style.ToggleSwitch(tr(u"Line Anti-aliasing"))
        self.lineAA.toggled.connect(self._on_aa)
        card.addWidget(self.lineAA)

        return card

    def _on_aa(self, *_):
        if self._building:
            return
        d = self.owner.data
        d["aaEnable"] = self.aaEnable.isChecked()
        d["aaSampleCount"] = self.aaSamples.currentData()
        d["lineAAEnable"] = self.lineAA.isChecked()
        changed = vp2.apply_all(d)
        on = self.aaEnable.isChecked()
        self.aaSamples.setEnabled(on)
        self._aaSamplesLabel.setEnabled(on)
        if changed:
            vp2.refresh_viewport()
        self.owner.save_settings()

    # ------------------------------------------------------------------
    def _build_shadow(self):
        card = style.Card(tr(u"Shadow"))
        self.shadowChk = style.ToggleSwitch(tr(u"Shadows"))
        self.shadowChk.setToolTip(tr(u"ビューポートの Lighting > Shadows と同じ設定です。"))
        self.shadowChk.toggled.connect(self._on_shadow)
        card.addWidget(self.shadowChk)
        return card

    def _on_shadow(self, *_):
        if self._building:
            return
        self.owner.data["shadows"] = self.shadowChk.isChecked()
        self.owner.apply_shadows()

    # ------------------------------------------------------------------
    def _build_show(self):
        card = style.Card(tr(u"Show"))
        self.showSeg = style.SegmentedControl(
            [("all", tr(u"All")), ("none", tr(u"None")), ("polygon", tr(u"Polygon"))])
        self.showSeg.changed.connect(self._on_show_preset)
        card.addWidget(self.showSeg)
        card.addSeparator()

        self.jointChk = style.ToggleSwitch(u"Joint")
        self.curveChk = style.ToggleSwitch(u"NurbsCurve")
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(style.px(12))
        self.jointChk.toggled.connect(lambda on: self._on_show_flag("showJoints", on))
        self.curveChk.toggled.connect(lambda on: self._on_show_flag("showNurbsCurves", on))
        for c in (self.jointChk, self.curveChk):
            row.addWidget(c)
        row.addStretch(1)
        card.addLayout(row)
        return card

    def _on_show_preset(self, key):
        u"""プリセットが優先。押した時点で Joint / NurbsCurve もプリセットに従う。"""
        if self._building:
            return
        self.owner.data["showPreset"] = key
        self.owner.apply_show_preset(key)

    def _on_show_flag(self, key, on):
        u"""Joint / NurbsCurve のスイッチ。押したフラグだけを、全ビューへ 1 回適用する(他のフラグ・他の Show 設定は触らない)。"""
        if self._building:
            return
        self.owner.data[key] = bool(on)
        self.owner.apply_show_flag(key, bool(on))

    def set_show_switches(self, joints, curves):
        u"""全ビューの実値をスイッチに反映する(シグナルは飛ばさない)。
        値は True / False / "mixed"(ビューにより状態が異なる)/ "unknown"(取得できないビューがある)。
        mixed / unknown は中間表示で、押すと全ビュー ON にする。取得できないものを ON / OFF と断定しない。"""
        tips = {"mixed": tr(u"ビューにより状態が異なります(押すと全ビューを ON にします)"),
                "unknown": tr(u"状態を取得できないビューがあります(押すと全ビューを ON にします)")}
        self._building = True
        try:
            for chk, value in ((self.jointChk, joints), (self.curveChk, curves)):
                special = isinstance(value, str)
                chk.setChecked(False if special else bool(value))
                chk.setMixed(special)
                chk.setToolTip(tips.get(value, u"") if special else u"")
        finally:
            self._building = False

    # ------------------------------------------------------------------
    def _build_gate(self):
        card = style.CollapsibleCard(tr(u"Gate"))
        self.gateChk = style.ToggleSwitch(u"")
        self.gateChk.setToolTip(tr(u"レゾリューションゲート(レンダー解像度の範囲)を各ビューの上に描く(オーバーレイ)"))
        self.gateChk.toggled.connect(self._on_gate)
        card.setHeaderWidget(self.gateChk)

        def color_row(label, btn, extra=None):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(style.px(8))
            row.addWidget(_field_label(label))
            row.addWidget(btn)
            if extra is not None:
                row.addWidget(extra)
            row.addStretch(1)
            return row

        sec = style.CollapsibleSection(tr(u"Mask / Frame"))
        self.gateMaskSec = sec
        self.gateMaskColor = ColorButton((0, 0, 0))
        self.gateMaskColor.colorChanged.connect(self._on_gate)
        sec.addLayout(color_row(tr(u"Mask color"), self.gateMaskColor))
        self.gateMaskOpacity = SliderRow(tr(u"Mask opacity"), 0.0, 1.0, decimals=2)
        self.gateLineColor = ColorButton((1, 1, 1))
        self.gateLineColor.colorChanged.connect(self._on_gate)
        sec.addWidget(self.gateMaskOpacity)
        sec.addLayout(color_row(tr(u"Frame color"), self.gateLineColor))
        self.gateLineWidth = SliderRow(tr(u"Frame width"), 0.0, 8.0, decimals=1)
        sec.addWidget(self.gateLineWidth)
        card.addWidget(sec)

        sec2 = style.CollapsibleSection(tr(u"Inner gates"))
        self.innerGatesSec = sec2
        self.innerGateEnabled = []
        # ゲートごとに 1 行: [Gate N %][slider] [線][塗り] [色] [塗りの Opacity](0.2.16)
        self.innerGatePercent = []
        self.innerGateColor = []
        self.innerGateOpacity = []
        self.innerGateStroke = []
        self.innerGateFill = []
        self._innerGateRows = []
        _defcol = ((1, 0.85, 0.2), (0.3, 0.9, 1.0), (1, 0.45, 0.6))
        for k in range(3):
            en = QtWidgets.QCheckBox()
            en.setToolTip(tr(u"このゲートを描く"))
            en.setCursor(QtCore.Qt.PointingHandCursor)
            en.toggled.connect(self._on_gate)
            pct = SliderRow(u"{} {}".format(tr(u"Gate"), k + 1), 1.0, 100.0, decimals=1)
            pct.label.setMinimumWidth(style.px(48))
            pct.field.setSuffix(u" %")
            pct.field.setFit(style.px(72))       # "100.0 %" は 85% で文字領域 45px に対し 53px 必要(欠けの原因)
            st_ = IconToggle("stroke", tr(u"線(1px、Dashed で破線)"))
            fl = IconToggle("fill", tr(u"塗り: このゲートの外側(レゾリューションゲート内)を色で覆う"))
            col = ColorButton(_defcol[k])
            op = style.FitDoubleSpinBox()
            op.setDecimals(2)
            op.setRange(0.0, 1.0)
            op.setSingleStep(0.05)
            op.setFit(style.px(64))
            op.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            op.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            op.setToolTip(tr(u"塗りの不透明度"))
            st_.toggled.connect(self._on_gate)
            fl.toggled.connect(self._on_gate)
            col.colorChanged.connect(self._on_gate)
            op.valueChanged.connect(self._on_gate)
            # 既定の右ドック幅(約333px)に収めるため 2 行構成(0.9.x 狭幅対応。項目は不変):
            #   1 行目: [有効][Gate N % スライダ]  2 行目: [線][塗り][色][塗り Opacity]
            r1 = QtWidgets.QHBoxLayout()
            r1.setSpacing(style.px(6))
            r1.addWidget(en)
            r1.addWidget(pct, 1)
            sec2.addLayout(r1)
            r2 = QtWidgets.QHBoxLayout()
            r2.setSpacing(style.px(6))
            r2.addSpacing(style.px(22))
            r2.addWidget(st_)
            r2.addWidget(fl)
            r2.addWidget(col)
            r2.addWidget(op)
            r2.addStretch(1)
            sec2.addLayout(r2)
            self.innerGateEnabled.append(en)
            self.innerGatePercent.append(pct)
            self.innerGateColor.append(col)
            self.innerGateOpacity.append(op)
            self.innerGateStroke.append(st_)
            self.innerGateFill.append(fl)
            self._innerGateRows.append((pct, st_, fl, col, op))
        self.innerGateDashed = style.ToggleSwitch(tr(u"Dashed"))
        self.innerGateDashed.toggled.connect(self._on_gate)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(style.px(8))
        row.addWidget(_field_label(u""))
        row.addWidget(self.innerGateDashed)
        row.addStretch(1)
        sec2.addLayout(row)
        card.addWidget(sec2)

        card.addWidget(_note(tr(u"画面上のオーバーレイ(Playblast には写りません)")))

        self._gateRows = [self.gateMaskOpacity, self.gateLineWidth] + self.innerGatePercent
        for w in self._gateRows:
            w.valueChanged.connect(self._on_gate)
        for key, sec_ in (("gateMaskCollapsed", self.gateMaskSec), ("innerGatesCollapsed", self.innerGatesSec)):
            sec_.collapsedChanged.connect(lambda c, k=key: self._on_gate_section_collapsed(k, c))
        self._gateWidgets = self._gateRows + [self.gateMaskColor, self.gateLineColor,
                                              self.innerGateDashed]
        return card

    def _build_guides(self):
        u"""構図ガイド。v1.8.1: Gate の子セクションではなく、Gate と同階層の独立カード
        (仕様。Gate を畳んでも Guides に届く)。設定キー・描画の意味は従来のまま。"""
        card = style.CollapsibleCard(tr(u"Guides"))
        self.guidesSec = card            # 既存の保存キー guidesCollapsed / 要約表示をそのまま使う
        self.guidesChk = style.ToggleSwitch(u"")
        self.guidesChk.setToolTip(tr(u"構図ガイド全体の ON/OFF(各系統のスイッチはそのまま保持)"))
        self.guidesChk.toggled.connect(self._on_guide)
        card.setHeaderWidget(self.guidesChk)
        self.guideThirds = style.ToggleSwitch(tr(u"三分割"))
        self.guideGrid = style.ToggleSwitch(tr(u"比率グリッド"))
        self.guideArmature = style.ToggleSwitch(tr(u"アーマチュア"))
        self.guideCenter = style.ToggleSwitch(tr(u"中心"))
        self.guideThirds.setToolTip(tr(u"1/3・2/3 の縦横線"))
        self.guideGrid.setToolTip(tr(u"黄金比 0.382/0.618(白銀比 0.414/0.586)の縦横線"))
        self.guideArmature.setToolTip(tr(u"対角線 2 本 + 各隅から対角線への垂線 4 本 + 交点(目)を通る縦横 4 本。\n黄金比(または白銀比)の矩形で計算して枠に引き伸ばす(MoveSpirit と同じ)"))
        self.guideRatio = style.ComboBox()
        self.guideRatio.addItem(tr(u"黄金比 φ"), 0)
        self.guideRatio.addItem(tr(u"白銀比 √2"), 1)
        self.guideRatio.setFixedWidth(style.px(110))
        self.guideThirdsColor = ColorButton((0.3, 0.5, 1.0))
        self.guideGridColor = ColorButton((1.0, 0.25, 0.25))
        self.guideArmatureColor = ColorButton((1.0, 0.9, 0.2))
        # [三分割 ■] / [比率グリッド ■] / [アーマチュア ■] / [中心] を 1 列に縦積み → [Ratio] → [Fit to] → Opacity / Width
        # (0.9.1: 2 列グリッドは列幅=各列最長ラベルの和になり、Windows の UI フォントでは
        #  標準右ドック幅を超えた。1 列ならフォント差があっても最長 1 項目分の幅で収まる)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(style.px(12))
        grid.setVerticalSpacing(style.px(6))
        grid.setContentsMargins(0, 0, 0, 0)
        cells = ((self.guideThirds, self.guideThirdsColor), (self.guideGrid, self.guideGridColor),
                 (self.guideArmature, self.guideArmatureColor), (self.guideCenter, None))
        for i, (tgl, btn) in enumerate(cells):
            cell = QtWidgets.QHBoxLayout()
            cell.setSpacing(style.px(6))
            cell.addWidget(tgl)
            if btn is not None:
                cell.addWidget(btn)
                btn.colorChanged.connect(self._on_guide)
            cell.addStretch(1)
            grid.addLayout(cell, i, 0)
            tgl.toggled.connect(self._on_guide)
        grid.setColumnStretch(0, 1)
        card.addLayout(grid)
        self.guideRatio.currentIndexChanged.connect(self._on_guide)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(style.px(8))
        row.addWidget(_field_label(tr(u"Ratio"), 48))
        row.addWidget(self.guideRatio)
        row.addStretch(1)
        card.addLayout(row)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(style.px(8))
        row.addWidget(_field_label(tr(u"Fit to"), 48))
        self.guideFit = style.ComboBox()
        for v, label in ((0, tr(u"レゾリューションゲート")), (1, tr(u"内側ゲート 1")), (2, tr(u"内側ゲート 2")),
                         (3, tr(u"内側ゲート 3")), (4, tr(u"ビュー全体"))):
            self.guideFit.addItem(label, v)
        self.guideFit.setFixedWidth(style.px(170))
        self.guideFit.setToolTip(tr(u"ガイドを合わせる矩形。内側ゲートは Inner gates の % を使う(本数が足りなくても計算には使える)"))
        self.guideFit.currentIndexChanged.connect(self._on_guide)
        row.addWidget(self.guideFit)
        row.addStretch(1)
        card.addLayout(row)
        self.guideOpacity = SliderRow(tr(u"Opacity"), 0.0, 1.0, decimals=2)
        self.guideWidth = SliderRow(tr(u"Width"), 0.5, 6.0, decimals=1)
        self._guideRows = [self.guideOpacity, self.guideWidth]
        for w in self._guideRows:
            w.valueChanged.connect(self._on_guide)
            card.addWidget(w)
        card.collapsedChanged.connect(lambda c: self._on_gate_section_collapsed("guidesCollapsed", c))
        return card

    def _on_gate(self, *_):
        if self._building:
            return
        d = self.owner.data
        d["gateEnabled"] = self.gateChk.isChecked()
        d["gateMaskColor"] = self.gateMaskColor.value()
        d["gateMaskOpacity"] = self.gateMaskOpacity.value()
        d["gateLineColor"] = self.gateLineColor.value()
        d["gateLineWidth"] = self.gateLineWidth.value()
        d["innerGateEnabled"] = [w.isChecked() for w in self.innerGateEnabled]
        d["innerGatePercent"] = [w.value() for w in self.innerGatePercent]
        d["innerGateColor"] = [w.value() for w in self.innerGateColor]
        d["innerGateOpacity"] = [w.value() for w in self.innerGateOpacity]
        d["innerGateStroke"] = [w.isChecked() for w in self.innerGateStroke]
        d["innerGateFill"] = [w.isChecked() for w in self.innerGateFill]
        d["innerGateDashed"] = self.innerGateDashed.isChecked()
        self.owner.apply_gate()
        self._update_gate_enabled()

    def _on_guide(self, *_):
        if self._building:
            return
        d = self.owner.data
        d["guidesEnabled"] = self.guidesChk.isChecked()
        d["guideThirds"] = self.guideThirds.isChecked()
        d["guideGrid"] = self.guideGrid.isChecked()
        d["guideArmature"] = self.guideArmature.isChecked()
        d["guideCenter"] = self.guideCenter.isChecked()
        d["guideRatio"] = int(self.guideRatio.currentData() or 0)
        d["guideFit"] = int(self.guideFit.currentData() or 0)
        d["guideThirdsColor"] = self.guideThirdsColor.value()
        d["guideGridColor"] = self.guideGridColor.value()
        d["guideArmatureColor"] = self.guideArmatureColor.value()
        d["guideOpacity"] = self.guideOpacity.value()
        d["guideWidth"] = self.guideWidth.value()
        self._update_gate_summaries()
        self.owner.apply_gate()

    def _on_gate_section_collapsed(self, key, collapsed):
        if self._building:
            return
        self.owner.data[key] = bool(collapsed)
        self.owner.save_settings()

    def _update_gate_summaries(self):
        u"""畳んだサブセクションの見出し右に出す要約(ユーザー表示なので翻訳対象。数値・px は原表記)。"""
        try:
            self.gateMaskSec.setSummary(tr(u"mask {:.2f} / frame {:.1f}px").format(
                self.gateMaskOpacity.value(), self.gateLineWidth.value()))
            parts = [u"{}: {:g}%".format(k + 1, self.innerGatePercent[k].value())
                     for k in range(3) if self.innerGateEnabled[k].isChecked()]
            self.innerGatesSec.setSummary(u" · ".join(parts) if parts else tr(u"off"))
            names = []
            if self.guidesChk.isChecked():
                for tgl, name in ((self.guideThirds, tr(u"三分割")), (self.guideGrid, tr(u"グリッド")),
                                  (self.guideArmature, tr(u"アーマチュア")), (self.guideCenter, tr(u"中心"))):
                    if tgl.isChecked():
                        names.append(name)
            self.guidesSec.setSummary(u" · ".join(names) if names else tr(u"off"))
        except Exception:
            pass

    def _update_gate_enabled(self):
        self._update_gate_summaries()
        on = self.gateChk.isChecked()
        for w in self._gateWidgets:
            w.setEnabled(on)
        for k, ws in enumerate(self._innerGateRows):
            self.innerGateEnabled[k].setEnabled(on)
            gate_on = on and self.innerGateEnabled[k].isChecked()
            for w in ws:
                w.setEnabled(gate_on)

    def _build_playblast(self):
        card = style.Card(tr(u"Playblast"))

        def _lab(text):
            lab = QtWidgets.QLabel(text)
            lab.setObjectName("fieldLabel")
            lab.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            return lab

        def _narrow(w):
            w.setFit(style.px(60), hpad=4, fixed=False)       # 伸びてよい。最悪値(FPS 240.00 など)が収まる最小幅は保証
            w.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            w.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            # 左右の余白を詰めて数字(FPS 30.00 など)の入る幅を確保する。狭いドックでも切れないように
            w.setStyleSheet(style.scale_css("QSpinBox, QDoubleSpinBox { padding: 4px 4px; }"))
            return w

        # ---- 見出し: [chevron][▍Playblast][畳んだときの要約 ......] ---------------
        # カード全体を畳める。畳むと見出しだけになり、要約(形式 / 解像度 / FPS)を見出しの右に出す。
        self._pbCardCollapsed = False
        head = card.body.itemAt(0).layout()
        self._pbChevron = style.ChevronButton()
        self._pbChevron.clicked.connect(self._toggle_pb_card)
        head.insertWidget(0, self._pbChevron, 0, QtCore.Qt.AlignVCenter)
        title = getattr(card, "_titleLabel", None)
        if title is not None:
            title.setCursor(QtCore.Qt.PointingHandCursor)
            title.mousePressEvent = lambda e: self._toggle_pb_card()
        self._pbCardSummary = style.ElidedLabel(u"")
        self._pbCardSummary.setObjectName("subSummary")
        self._pbCardSummary.setCursor(QtCore.Qt.PointingHandCursor)
        self._pbCardSummary.mousePressEvent = lambda e: self._toggle_pb_card()
        self._pbCardSummary.setVisible(False)
        head.addWidget(self._pbCardSummary, 1)

        self._pbBody = QtWidgets.QWidget()
        body_lay = QtWidgets.QVBoxLayout(self._pbBody)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(style.px(10))
        card.addWidget(self._pbBody)

        # 縦: [Force][Multi][Time Range][Output][Settings(数値)][撮影オプション][完了後に開く][実行]
        # 横(上下配置): [main 列] | [Settings(数値)]
        self._pbFlow = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom)
        self._pbFlow.setContentsMargins(0, 0, 0, 0)
        self._pbFlow.setSpacing(style.px(10))
        body_lay.addLayout(self._pbFlow)
        self._pbMain = QtWidgets.QWidget()
        self._pbMainCol = QtWidgets.QVBoxLayout(self._pbMain)
        self._pbMainCol.setContentsMargins(0, 0, 0, 0)
        self._pbMainCol.setSpacing(style.px(10))
        self._pbFlow.addWidget(self._pbMain)

        # g3(2026-11-08 本人指定): 直下 = ショットごとに触る物。めったに変えない物は SETTINGS(畳める)へ。
        # 切替が数値の「元」を決める所(From Render Settings → 幅/高さ、FPS のシーン → FPS)は、
        # 同じ行の下に字下げで置き、ON の間は数値欄を隠して元の値を表示する。
        def _flow(*widgets, **kw):
            u"""左から並べ、幅が足りないときだけ折り返す行。indent は 1 行目の字下げ(px)。"""
            row = QtWidgets.QWidget()
            lay = _FlowLayout(row, style.px(6), style.px(4))
            row._indent = None
            if kw.get("indent"):
                sp = QtWidgets.QWidget()
                sp.setFixedSize(kw["indent"], 1)
                lay.addWidget(sp)
                row._indent = sp
            for w in widgets:
                if w is not None:
                    lay.addWidget(w)
            return row

        def _pair(*widgets):
            u"""折り返しで離したくない部品の組(「幅 [1920]」など)。"""
            box = QtWidgets.QWidget()
            lay = QtWidgets.QHBoxLayout(box)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(style.px(6))
            for w in widgets:
                lay.addWidget(w)
            return box

        def _label(text, align=False, min_w=0):
            lab = QtWidgets.QLabel(text)
            lab.setObjectName("fieldLabel")
            if min_w:
                lab.setMinimumWidth(style.px(min_w))
            if align:
                self._pbAlignLabels.append(lab)       # SETTINGS の見出し列(後で最長の文字幅に揃える)
            return lab

        def _row(label_text, *widgets, **kw):
            if kw.get("hbox"):                        # 左に見出し・右端に部品(Time Range の見出し行)
                row = QtWidgets.QWidget()
                lay = QtWidgets.QHBoxLayout(row)
                lay.setContentsMargins(0, 0, 0, 0)
                lay.setSpacing(style.px(6))
                lay.addWidget(_label(label_text))
                lay.addStretch(1)
                for w in widgets:
                    lay.addWidget(w)
                return row
            lab = _label(label_text, kw.get("align", False), kw.get("label_w", 0)) if label_text is not None else None
            return _flow(lab, *widgets, indent=kw.get("indent", 0))

        self._pbAlignLabels = []
        _narrow0 = _narrow

        def _narrow(w):                               # g3: 行は sizeHint の幅で並ぶので、最悪値の文字と枠の間を広めに取る
            w = _narrow0(w)
            w._fit_slack = 12
            return w

        self.forceChk = style.ToggleSwitch(tr(u"Force Playblast Target"))
        self.forceChk.setToolTip(
            tr(u"Force Playblast Target: ON の間、このビューがアクティブでなくても\n"
               u"Maya 標準/外部のPlayblastは最後に追加した対象1つ。複数出力はこのツールの実行ボタン。"))
        self.forceChk.toggled.connect(self._on_force)
        self.multiEnabled = style.ToggleSwitch(tr(u"Multi"))
        self.multiEnabled.setToolTip(tr(u"ONで複数の対象を選択。OFFでは最後に選択した対象1つに戻します。"))
        self.multiEnabled.toggled.connect(self._on_multi_option)
        self.multiCombine = style.ToggleSwitch(tr(u"合成"))
        self.multiCombine.setToolTip(tr(u"選択した複数ビューの位置・比率で動画を合成（_Multi.mp4）。画像は引き伸ばしません。"))
        self.multiKeep = style.ToggleSwitch(tr(u"個別保持"))
        self.multiKeep.setToolTip(tr(u"合成と一緒に各カメラの出力も保存。合成OFFなら常に個別保存。失敗時は途中出力を保全。"))
        # g4(2026-11-10 本人指定): 1 行目 = Force だけ。2 行目 = [Multi][合成][個別保持]。
        # Multi は最初から 2 行目の先頭に固定し、ON で右の 2 つが出るだけ(隠れている間も場所は取っておく
        # = Multi の位置も行の数も変わらない)。個別保持は 合成 OFF の間は押せない。
        for w in (self.multiCombine, self.multiKeep):
            pol = w.sizePolicy()
            pol.setRetainSizeWhenHidden(True)
            w.setSizePolicy(pol)
            w.setVisible(False)                   # Multi OFF が既定(ON にすると _on_multi_option が表示する)
        self._pbTopRow = QtWidgets.QWidget()      # 互換の名前(Force の行と Multi の行をまとめた入れ物)
        tv = QtWidgets.QVBoxLayout(self._pbTopRow)
        tv.setContentsMargins(0, 0, 0, 0)
        tv.setSpacing(style.px(8))
        fr = QtWidgets.QHBoxLayout()
        fr.setContentsMargins(0, 0, 0, 0)
        fr.addWidget(self.forceChk)
        fr.addStretch(1)
        tv.addLayout(fr)
        self._pbMultiRow = QtWidgets.QWidget()
        mr = _FlowLayout(self._pbMultiRow, style.px(6), style.px(8))   # 狭い幅のときだけ折り返す(切替では変わらない)
        mr.addWidget(self.multiEnabled)
        mr.newGroup()
        mr.addWidget(self.multiCombine)
        mr.addWidget(self.multiKeep)
        tv.addWidget(self._pbMultiRow)
        self._pbMainCol.addWidget(self._pbTopRow)
        self.multiCombine.toggled.connect(self._on_multi_option)
        self.multiKeep.toggled.connect(self._on_multi_option)

        # 状態表示は持たない(Script Editor に出す)。互換のため文字列だけ保持する。
        self._forceStateText = u""
        self._targetText = u""

        # ---- Time Range ----------------------------------------------------------
        # シーン範囲 ON: 撮影時点の再生範囲(playbackOptions の min / max)。範囲の欄は出さない。
        # OFF: 「範囲 [開始] → [終了]  N フレーム」(整数フレーム。開始 ≤ 終了)。
        self._pbRangeCustom = (1, 24)
        self._pbRangeSyncing = False
        self.pbRangeBox = QtWidgets.QWidget()
        rb = QtWidgets.QVBoxLayout(self.pbRangeBox)
        rb.setContentsMargins(0, 0, 0, 0)
        rb.setSpacing(style.px(6))
        self.pbRangeScene = style.ToggleSwitch(tr(u"シーン範囲"))
        self.pbRangeScene.setToolTip(tr(u"ON: 撮影時点のシーンの再生範囲を使う。OFF: 開始 / 終了フレームを指定する。"))
        self.pbRangeScene.setChecked(True)       # 既定 = シーン範囲(従来の動作)
        self.pbStart = _narrow(style.FitSpinBox())
        self.pbStart.setRange(-99999, 99999)
        self.pbStart.setToolTip(tr(u"開始"))
        self.pbEnd = _narrow(style.FitSpinBox())
        self.pbEnd.setRange(-99999, 99999)
        self.pbEnd.setToolTip(tr(u"終了"))
        arrow = QtWidgets.QLabel(u"→")
        arrow.setObjectName("fieldLabel")
        # g4: 1 行 = [Time Range][シーン範囲][開始 → 終了]。開始・終了はシーン範囲 OFF のときだけ見え、
        # 隠れている間も場所は取っておく(切替でスイッチも行も動かない)。フレーム数は欄の tooltip。
        self._pbRangeRow = _pair(self.pbStart, arrow, self.pbEnd)
        pol = self._pbRangeRow.sizePolicy()
        pol.setRetainSizeWhenHidden(True)
        self._pbRangeRow.setSizePolicy(pol)
        self._pbRangeCount = QtWidgets.QLabel(u"", self._pbRangeRow)   # 互換(表示はしない。文言は tooltip へ)
        self._pbRangeCount.hide()
        trow = _flow(_label(tr(u"Time Range")), self.pbRangeScene)
        trow.layout()._h = style.px(8)
        trow.layout().newGroup()
        trow.layout().addWidget(self._pbRangeRow)
        self._pbRangeHead = trow
        rb.addWidget(trow)
        self._pbMainCol.addWidget(self.pbRangeBox)

        # ---- 出力先(直下) ----------------------------------------------------------
        self.mp4Output = QtWidgets.QLineEdit()
        self.mp4Output.setPlaceholderText(tr(u"自動"))
        self.mp4Output.setToolTip(tr(u"出力先。空なら <プロジェクト>/movies/<シーン>_<カメラ>"))
        self.mp4OutputBtn = QtWidgets.QPushButton(u"…")
        self.mp4OutputBtn.setFixedWidth(style.px(40))
        self.mp4OutputBtn.setStyleSheet(style.scale_css("padding: 6px 2px;"))
        self.mp4OutputBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.mp4OutputBtn.setToolTip(tr(u"出力先を選択"))
        self.mp4OutputBtn.clicked.connect(self._browse_output)
        self.pbOutputBox = QtWidgets.QWidget()
        ob = QtWidgets.QHBoxLayout(self.pbOutputBox)
        ob.setContentsMargins(0, 0, 0, 0)
        ob.setSpacing(style.px(6))
        ocap = QtWidgets.QLabel(tr(u"出力先"))
        ocap.setObjectName("fieldLabel")
        ob.addWidget(ocap)
        ob.addWidget(self.mp4Output, 1)
        ob.addWidget(self.mp4OutputBtn)
        self._pbMainCol.addWidget(self.pbOutputBox)

        # ---- SETTINGS(畳める): めったに変えない物 ----------------------------------
        self.pbSettings = style.CollapsibleSection(tr(u"Settings"))
        self.pbSettings.collapsedChanged.connect(self._on_pb_settings_collapsed)
        self.pbSettings.collapsedChanged.connect(lambda c: (not c) and self._update_mp4_enabled())   # 開いた時点の値で
        self._pbMainCol.addWidget(self.pbSettings)
        self.mp4Box = QtWidgets.QWidget()
        self._mp4Flow = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom, self.mp4Box)
        self._mp4Flow.setContentsMargins(0, 0, 0, 0)
        self._mp4Flow.setSpacing(style.px(8))
        self._mp4Grid = self.mp4Box               # 互換(旧 grid の参照名)

        # 出力形式
        self.outputSeg = style.SegmentedControl(
            [("maya", tr(u"Maya 標準")), ("mp4", u"MP4")])
        self.outputSeg.changed.connect(self._on_output_mode)
        self._mp4Flow.addWidget(_row(tr(u"出力形式"), self.outputSeg, align=True))

        # 解像度: From Render Settings / OFF のときだけ 幅・高さ
        self.mp4FromRender = style.ToggleSwitch(tr(u"レンダー設定"))   # 行の見出しが「解像度」なので短く。原名は tooltip
        self.mp4FromRender.setToolTip(
            tr(u"Maya 標準 Playblast の「Display size: From Render Settings」と同じ。\n"
               u"幅/高さをレンダー設定の解像度にし、オーバースキャン 1.0・パン/ズーム無効で書き出す\n"
               u"= レゾリューションゲート(最終描画範囲)ぴったりの動画。幅/高さの欄は無視される。"))
        self._mp4Flow.addWidget(_row(tr(u"解像度"), self.mp4FromRender, align=True))
        # g4: 幅・高さの欄は隠さない。レンダー設定 ON の間は押せない状態でレンダー設定の値を表示する
        self._customSize = None                   # ON の間に預かる利用者の指定値(OFF で戻す)
        self._customFps = None
        self.mp4Width = _narrow(style.FitSpinBox())
        self.mp4Width.setRange(16, 16384)
        self.mp4Height = _narrow(style.FitSpinBox())
        self.mp4Height.setRange(16, 16384)
        self._sizeRow = _flow(_pair(_label(tr(u"幅")), self.mp4Width), _pair(_label(tr(u"高さ")), self.mp4Height),
                              indent=style.px(16))
        self._sizeRow.layout()._h = style.px(12)
        self._mp4Flow.addWidget(self._sizeRow)

        # FPS: シーン / OFF のときだけ FPS 欄
        self.mp4UseSceneFps = style.ToggleSwitch(tr(u"シーン"))
        self.mp4UseSceneFps.setToolTip(tr(u"ON: シーンの時間単位から FPS を決める"))
        # g4: FPS 欄は同じ行の右。シーン ON の間は押せない状態でシーンの FPS を表示する
        self.mp4Fps = _narrow(style.FitDoubleSpinBox())
        self.mp4Fps.setRange(1.0, 240.0)
        self.mp4Fps.setDecimals(2)
        self._fpsRow = _row(u"FPS", self.mp4UseSceneFps, self.mp4Fps, align=True)
        self._mp4Flow.addWidget(self._fpsRow)

        # 品質
        self.mp4Quality = _narrow(style.FitSpinBox())
        self.mp4Quality.setRange(1, 100)
        self.mp4Quality.setToolTip(tr(u"playblast の quality(1-100)"))
        _qlab = _label(tr(u"品質"), True)

        # MP4 のときだけ: CRF / プリセット / PNG を残す
        self.mp4Crf = _narrow(style.FitSpinBox())
        self.mp4Crf.setRange(0, 51)
        self.mp4Crf.setToolTip(tr(u"H.264 品質(0-51)。低いほど高画質。18-23 推奨(MP4 のみ)"))
        self._crfLabel = QtWidgets.QLabel(u"CRF")
        self._crfLabel.setObjectName("fieldLabel")
        self.mp4Preset = style.ComboBox()
        for name in mp4blast.PRESETS:
            self.mp4Preset.addItem(name)
        self.mp4Preset.setToolTip(tr(u"x264 プリセット。遅いほど同じ CRF で小さくなる(MP4 のみ)"))
        self.mp4Preset.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mp4Preset.setMinimumContentsLength(6)
        self._presetLabel = QtWidgets.QLabel(tr(u"プリセット"))
        self._presetLabel.setObjectName("fieldLabel")
        self.mp4KeepFrames = style.ToggleSwitch(tr(u"PNG を残す"))
        self.mp4KeepFrames.setToolTip(tr(u"中間の PNG 連番(一時フォルダ)を削除しない(MP4 のみ)"))
        # g4: [品質][q] [CRF][c] [プリセット][p] を 1 行(幅が足りないときだけ折り返す)。CRF / プリセットは MP4 のときだけ
        # g4r2: 4 つを別々に並べ、組(見出し+欄)ごとにまとめる。最小幅では組の中で折り返せる(パネル最小幅を広げない)。
        # CRF / プリセットは MP4 以外では隠すが、場所は取ったまま(形式を切り替えても高さ・折り返しが変わらない)
        for w in (self._crfLabel, self.mp4Crf, self._presetLabel, self.mp4Preset):
            pol = w.sizePolicy()
            pol.setRetainSizeWhenHidden(True)
            w.setSizePolicy(pol)
        for lab in (self._crfLabel, self._presetLabel):
            lab.setContentsMargins(style.px(8), 0, 0, 0)
        self._mp4OnlyWidgets = (self._crfLabel, self.mp4Crf, self._presetLabel, self.mp4Preset)
        self._qualityRow = _flow(_qlab, self.mp4Quality)
        ql = self._qualityRow.layout()
        ql.newGroup()
        ql.addWidget(self._crfLabel)
        ql.addWidget(self.mp4Crf)
        ql.newGroup()
        ql.addWidget(self._presetLabel)
        ql.addWidget(self.mp4Preset)
        self._mp4Flow.addWidget(self._qualityRow)

        self.pbSettings.addWidget(self.mp4Box)

        # ---- 撮影オプション(独立して折り畳み。s3) -----------------------------------
        self.pbCaptureBox = style.CollapsibleSection(tr(u"撮影オプション"))
        self.pbCaptureBox.collapsedChanged.connect(self._on_pb_capture_collapsed)
        cap = self.pbCaptureBox
        self.mp4Ornaments = style.ToggleSwitch(tr(u"装飾 (HUD)"))
        self.mp4Ornaments.setToolTip(tr(u"showOrnaments: HUD やカメラ名などを写す"))
        cap.addWidget(self.mp4Ornaments)
        self.mp4OffScreen = style.ToggleSwitch(tr(u"オフスクリーン"))
        self.mp4OffScreen.setToolTip(tr(u"offScreen: 他ウィンドウの重なりに影響されない"))
        cap.addWidget(self.mp4OffScreen)
        self.mp4Optimize = style.ToggleSwitch(tr(u"ビューポート最適化"))
        self.mp4Optimize.setToolTip(
            tr(u"書き出し中のみ、画角をレンダー枠に固定 / Polygon のみ表示 /\n"
               u"Use All Lights / SSAO・線 AA・MSAA を ON にし、完了後に元へ戻します。"))
        cap.addWidget(self.mp4Optimize)
        for w in (self.mp4Ornaments, self.mp4OffScreen, self.mp4Optimize):
            w.toggled.connect(self._update_capture_summary)
        self._pbMainCol.addWidget(self.pbCaptureBox)

        # ---- 常に見えるもの: 完了後に開く / 実行 -------------------------------------
        self.mp4OpenAfter = style.ToggleSwitch(tr(u"完了後に開く"))
        # g4: 連番(PNG)を残す は 完了後に開く の右隣(MP4 以外では押せない。隠さない)
        pol = self.mp4KeepFrames.sizePolicy()     # g4r2: MP4 以外では隠す(場所は取ったまま。押せないだけだと
        pol.setRetainSizeWhenHidden(True)         # SETTINGS を畳んでいる時にどこで有効にするのか分からない)
        self.mp4KeepFrames.setSizePolicy(pol)
        self._pngRow = _flow(self.mp4OpenAfter)
        self._pngRow.layout()._h = style.px(10)
        self._pngRow.layout().newGroup()
        self._pngRow.layout().addWidget(self.mp4KeepFrames)
        self._pbMainCol.addWidget(self._pngRow)
        self.pbBtn = QtWidgets.QPushButton(tr(u"Playblast 実行"))
        self.pbBtn.setObjectName("primary")
        self.pbBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.pbBtn.clicked.connect(lambda: self.owner.do_playblast(False))
        self._pbMainCol.addWidget(self.pbBtn)
        self._pbMainCol.addStretch(1)

        # ---- 値の変更を設定へ ---------------------------------------------
        for w in (self.mp4Width, self.mp4Height, self.mp4Crf, self.mp4Quality):
            w.valueChanged.connect(self._on_mp4_option)
        self.mp4Fps.valueChanged.connect(self._on_mp4_option)
        self.mp4Preset.currentIndexChanged.connect(self._on_mp4_option)
        self.mp4Output.editingFinished.connect(self._on_mp4_option)
        for w in (self.mp4UseSceneFps, self.mp4Ornaments, self.mp4OffScreen,
                  self.mp4Optimize, self.mp4KeepFrames, self.mp4OpenAfter):
            w.toggled.connect(self._on_mp4_option)
        self.mp4UseSceneFps.toggled.connect(self._update_mp4_enabled)
        self.mp4FromRender.toggled.connect(self._on_mp4_option)
        self.mp4FromRender.toggled.connect(self._update_mp4_enabled)
        self.pbRangeScene.toggled.connect(self._on_range_scene)
        self.pbStart.valueChanged.connect(lambda v: self._on_range_edit("start"))
        self.pbEnd.valueChanged.connect(lambda v: self._on_range_edit("end"))
        self._update_mp4_enabled()
        self._refresh_range_display()

        return card

    # ---- Playblast カード全体の折り畳み / Time Range -------------------------
    def _align_pb_labels(self):
        u"""g3: SETTINGS の見出し列(出力形式 / 解像度 / FPS / 品質 / CRF / プリセット)を最長の文字幅に揃える。
        全カードがツールボックスに入りスタイルが届いた後に測る(言語・UI 倍率で幅が変わる)。"""
        labs = getattr(self, "_pbAlignLabels", [])
        if not labs:
            return
        w = max(lab.fontMetrics().horizontalAdvance(lab.text()) for lab in labs) + style.px(6)
        for lab in labs:
            lab.setFixedWidth(w)
        sp = getattr(getattr(self, "_pngRow", None), "_indent", None)
        if sp is not None:                                   # PNG を残すは値の列に揃える(1 行目の字下げ)
            sp.setFixedSize(w + style.px(6), 1)

    def _toggle_pb_card(self):
        self._set_pb_card_collapsed(not self._pbCardCollapsed)

    def _set_pb_card_collapsed(self, collapsed):
        collapsed = bool(collapsed)
        changed = collapsed != self._pbCardCollapsed
        self._pbCardCollapsed = collapsed
        self._pbBody.setVisible(not collapsed)
        self._pbChevron.setCollapsed(collapsed)
        self._pbCardSummary.setVisible(collapsed)
        if not changed or self._building:
            return
        self.owner.data["playblastCollapsed"] = collapsed
        self.owner.save_settings()
        self._after_collapse_change()

    def _scene_range(self):
        u"シーンの再生範囲(整数フレーム)。書出し側の normalize と同じ四捨五入。取れなければ指定値。"
        try:
            s, e = mp4blast.frame_range()
            return mp4blast.blastsize.normalize_range(s, e)
        except Exception:
            return self._pbRangeCustom

    def _export_range(self):
        u"書出し直前に呼ぶ。Scene ON なら現在のシーン範囲を取り直して表示へ反映し、その値を返す(表示 = 採用範囲)。"
        self._refresh_range_display()
        return self._scene_range() if self.pbRangeScene.isChecked() else self._pbRangeCustom

    def showEvent(self, ev):
        super(ToolBox, self).showEvent(ev)
        try:
            self._refresh_range_display()        # 表示した時点でシーン範囲の変更を拾う(タイマーは使わない)
            self._update_mp4_enabled()           # g4: レンダー設定 / シーン FPS の表示も取り直す
        except Exception:
            pass

    def _refresh_range_display(self):
        u"""シーン範囲 ON のときは現在の再生範囲を(編集不可で)見せる。OFF のときは指定値。"""
        scene = self.pbRangeScene.isChecked()
        s, e = self._scene_range() if scene else self._pbRangeCustom
        self._pbRangeSyncing = True
        try:
            self.pbStart.setValue(s)
            self.pbEnd.setValue(e)
        finally:
            self._pbRangeSyncing = False
        self.pbStart.setEnabled(not scene)
        self.pbEnd.setEnabled(not scene)
        # g4r3(本人指定): 開始・終了は隠さない。シーン範囲 ON の間は押せない状態で、シーンの再生範囲を表示する
        self._update_range_count()

    def _update_range_count(self):
        try:
            n = int(self.pbEnd.value()) - int(self.pbStart.value()) + 1
            text = tr(u"{} フレーム").format(max(n, 0))
            self._pbRangeCount.setText(text)
            self.pbStart.setToolTip(tr(u"開始") + u"  (" + text + u")")
            self.pbEnd.setToolTip(tr(u"終了") + u"  (" + text + u")")
        except Exception:
            pass

    def _on_range_scene(self, *_):
        self._refresh_range_display()
        self._on_mp4_option()

    def _on_range_edit(self, which):
        if self._pbRangeSyncing or self.pbRangeScene.isChecked():
            return
        s, e = self.pbStart.value(), self.pbEnd.value()
        if s > e:                      # 触った側に合わせて、開始 ≤ 終了を保つ
            if which == "start":
                e = s
            else:
                s = e
            self._pbRangeSyncing = True
            try:
                self.pbStart.setValue(s)
                self.pbEnd.setValue(e)
            finally:
                self._pbRangeSyncing = False
        self._pbRangeCustom = (s, e)
        self._update_range_count()
        self._on_mp4_option()

    @staticmethod
    def _saved_range(data):
        try:
            s, e = int(data.get("playblastStart", 1)), int(data.get("playblastEnd", 24))
        except (TypeError, ValueError):
            return 1, 24
        s = max(-99999, min(99999, s))
        e = max(-99999, min(99999, e))
        return (s, e) if s <= e else (e, s)

    def _on_pb_settings_collapsed(self, collapsed):
        if self._building:
            return
        if not self._pbAutoFold:
            self._pbSettingsRestore = None        # 利用者が選んだ。向きを戻しても、この選択を優先する
            self.owner.data["playblastSettingsCollapsed"] = bool(collapsed)
            self.owner.save_settings()
        self._after_collapse_change()

    def _on_pb_capture_collapsed(self, collapsed):
        u"""撮影オプションの開閉(s3)。自動で畳む経路は無いので、ここへ来るのは利用者の操作だけ。保存する。"""
        if self._building:
            return
        self.owner.data["playblastCaptureCollapsed"] = bool(collapsed)
        self.owner.save_settings()
        self._after_collapse_change()

    def _update_capture_summary(self, *_):
        u"""撮影オプションの見出しの右に出す要約(ON の項目名。全部 OFF なら「すべて OFF」)。"""
        try:
            on = [w.text() for w in (self.mp4Ornaments, self.mp4OffScreen, self.mp4Optimize) if w.isChecked()]
            self.pbCaptureBox.setSummary(u" / ".join(on) if on else tr(u"すべて OFF"))
        except Exception:
            pass

    def _update_pb_summary(self):
        u"""Settings を畳んだときに見出しの右へ出す要約(形式 / 解像度 / FPS)。"""
        try:
            mode = self.outputSeg.current() or "maya"
            # g3: 「MP4 · 1920×1080(RS) · 24fps(シーン)」。値の表記は翻訳しない(i18n の取り決め)
            if self.mp4UseSceneFps.isChecked():
                fps = self._scene_fps_text().replace(u" fps", u"fps") + u"(scene)"
            else:
                fps = u"{:g}fps".format(self.custom_fps())
            if self.mp4FromRender.isChecked():
                size = self._render_size_text() + u"(RS)"
            else:
                size = u"{}×{}".format(*self.custom_size())
            parts = [u"MP4" if mode == "mp4" else u"Maya", size, fps]
            if mode == "mp4":
                parts.append(u"CRF {}".format(self.mp4Crf.value()))
            text = u" · ".join(parts)
            self.pbSettings.setSummary(text)
            if not self.pbRangeScene.isChecked():
                text += u"  {}-{}".format(*self._pbRangeCustom)
            self._pbCardSummary.setText(text)
        except Exception:
            pass

    def _on_multi_option(self, *_):
        multi = self.multiEnabled.isChecked()
        self.multiCombine.setVisible(multi)
        self.multiKeep.setVisible(multi)                       # g4: 2 つ同時に出す(場所は常に取ってある)
        self.multiKeep.setEnabled(self.multiCombine.isChecked())   # 合成 OFF なら常に個別保存 = 押す意味がない
        if not self._building:
            self.owner.data["playblastMulti"] = multi
            if self.owner.views is not None:
                self.owner.views._normalize_targets()
                self.owner.views._update_target_marks()
                self.owner.on_target_changed()
            self.owner.data["playblastCombine"] = self.multiCombine.isChecked()
            self.owner.data["playblastKeepIndividuals"] = self.multiKeep.isChecked()
            self.owner.save_settings()

    def _on_force(self, *_):
        if self._building:
            return
        self.owner.set_force_playblast(self.forceChk.isChecked())

    def _on_output_mode(self, key):
        self._apply_output_mode(key)
        self._update_pb_summary()
        if self._building:
            return
        self.owner.data["outputMode"] = key
        self.owner.save_settings()

    def _apply_output_mode(self, key):
        is_mp4 = (key == "mp4")
        # 書き出し設定は両モード共通。エンコード系(CRF / プリセット / PNG)は MP4 のみ有効
        for w in (self.mp4Crf, self._crfLabel, self.mp4Preset, self._presetLabel,
                  self.mp4KeepFrames):
            w.setEnabled(is_mp4)
        for w in self._mp4OnlyWidgets:                     # g4: CRF / プリセットは品質の行の右(場所は取ったまま隠す)
            w.setVisible(is_mp4)
        self.mp4KeepFrames.setVisible(is_mp4)              # g4r2: 押せないではなく隠す
        # g4r2(本人指定): 利用者がしたいことは形式に関係なく「Playblast 実行」。文言は切り替えない
        self.pbBtn.setText(tr(u"Playblast 実行"))

    def _update_mp4_enabled(self, *_):
        on = not self.mp4UseSceneFps.isChecked()
        self.mp4Fps.setEnabled(on)
        rs = not self.mp4FromRender.isChecked()
        self.mp4Width.setEnabled(rs)
        self.mp4Height.setEnabled(rs)
        # g4: 欄は隠さない。切替 ON の間は元(シーン / レンダー設定)の値を入れて見せる(状態のプレビュー)。
        # 利用者の指定値は預かっておき、OFF に戻すと元の値へ戻す(保存も指定値)。
        if not rs:
            if self._customSize is None:
                self._customSize = (self.mp4Width.value(), self.mp4Height.value())
            src = self._render_size()
            if src:
                self._set_quiet(self.mp4Width, src[0])
                self._set_quiet(self.mp4Height, src[1])
        elif self._customSize is not None:
            self._set_quiet(self.mp4Width, self._customSize[0])
            self._set_quiet(self.mp4Height, self._customSize[1])
            self._customSize = None
        if not on:
            if self._customFps is None:
                self._customFps = self.mp4Fps.value()
            f = self._scene_fps()
            if f:
                self._set_quiet(self.mp4Fps, f)
        elif self._customFps is not None:
            self._set_quiet(self.mp4Fps, self._customFps)
            self._customFps = None

    @staticmethod
    def _set_quiet(w, v):
        w.blockSignals(True)
        try:
            w.setValue(v)
        finally:
            w.blockSignals(False)

    @staticmethod
    def _render_size():
        try:
            w, h = mp4blast.render_settings_size()
            return int(w), int(h)
        except Exception:
            return None

    @staticmethod
    def _scene_fps():
        try:
            return float(mp4blast.scene_fps())
        except Exception:
            return None

    def custom_size(self):
        u"""利用者の指定値(レンダー設定 ON の間は預かっている値)。"""
        if self._customSize is not None:
            return self._customSize
        return self.mp4Width.value(), self.mp4Height.value()

    def custom_fps(self):
        return self._customFps if self._customFps is not None else self.mp4Fps.value()

    @staticmethod
    def _scene_fps_text():
        try:
            return u"{:g} fps".format(mp4blast.scene_fps())
        except Exception:
            return u"scene"

    @staticmethod
    def _render_size_text():
        try:
            return u"{}×{}".format(*mp4blast.render_settings_size())
        except Exception:
            return u"Render Settings"

    def mp4_options(self):
        u"""UI の値を mp4blast.run() のキーワード引数にして返す。"""
        rng = self._export_range()      # Scene ON: 今のシーン範囲を表示へ反映して採用 / OFF: 指定値
        return dict(
            width=self.custom_size()[0],
            height=self.custom_size()[1],
            fps=None if self.mp4UseSceneFps.isChecked() else self.custom_fps(),
            crf=self.mp4Crf.value(),
            preset=self.mp4Preset.currentText(),
            quality=self.mp4Quality.value(),
            show_ornaments=self.mp4Ornaments.isChecked(),
            off_screen=self.mp4OffScreen.isChecked(),
            optimize_viewport=self.mp4Optimize.isChecked(),
            keep_frames=self.mp4KeepFrames.isChecked(),
            open_after=self.mp4OpenAfter.isChecked(),
            output_path=self.mp4Output.text().strip() or None,
            mode=self.owner.data.get("outputMode", "maya"),
            from_render_settings=self.mp4FromRender.isChecked(),
            start_frame=rng[0],
            end_frame=rng[1],
        )

    def _on_mp4_option(self, *_):
        self._update_pb_summary()
        if self._building:
            return
        d = self.owner.data
        d["mp4Width"], d["mp4Height"] = self.custom_size()   # g4: 表示中のレンダー設定 / シーンの値は保存しない
        d["mp4Fps"] = self.custom_fps()
        d["mp4UseSceneFps"] = self.mp4UseSceneFps.isChecked()
        d["mp4Crf"] = self.mp4Crf.value()
        d["mp4Preset"] = self.mp4Preset.currentText()
        d["mp4Quality"] = self.mp4Quality.value()
        d["mp4ShowOrnaments"] = self.mp4Ornaments.isChecked()
        d["mp4OffScreen"] = self.mp4OffScreen.isChecked()
        d["mp4FromRenderSettings"] = self.mp4FromRender.isChecked()
        d["mp4OptimizeViewport"] = self.mp4Optimize.isChecked()
        d["mp4KeepFrames"] = self.mp4KeepFrames.isChecked()
        d["mp4OpenAfter"] = self.mp4OpenAfter.isChecked()
        d["mp4OutputPath"] = self.mp4Output.text().strip()
        d["playblastRangeScene"] = self.pbRangeScene.isChecked()
        d["playblastStart"], d["playblastEnd"] = self._pbRangeCustom
        self.owner.save_settings()

    def _browse_output(self):
        current = self.mp4Output.text().strip()
        if not current:
            try:
                current = mp4blast.default_output_path(self.owner.target_camera())
            except Exception:
                current = ""
        try:
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, tr(u"MP4 の出力先"), current, u"MP4 (*.mp4)")
        except Exception:
            path = ""
        if path:
            self.mp4Output.setText(path.replace("\\", "/"))
            self._on_mp4_option()

    # ------------------------------------------------------------------
    def pull(self, data):
        u"""設定 dict -> UI(シグナルを飛ばさずに反映)。"""
        self._building = True
        try:
            self.dockPicker.setCurrent(data.get("dockArea", "right"))
            self.startupCamChk.setChecked(bool(data.get("showStartupCameras", True)))

            self.gateChk.setChecked(bool(data.get("gateEnabled", False)))
            self.gateMaskSec.setCollapsed(bool(data.get("gateMaskCollapsed", False)))
            self.innerGatesSec.setCollapsed(bool(data.get("innerGatesCollapsed", False)))
            self.guidesSec.setCollapsed(bool(data.get("guidesCollapsed", False)))
            self.gateMaskColor.setValue(data.get("gateMaskColor", [0, 0, 0]))
            self.gateMaskOpacity.setValue(float(data.get("gateMaskOpacity", 0.6)))
            self.gateLineColor.setValue(data.get("gateLineColor", [1, 1, 1]))
            self.gateLineWidth.setValue(float(data.get("gateLineWidth", 1.0)))
            ens = data.get("innerGateEnabled")
            if ens is None:   # 旧設定(Count)からの移行
                n = int(data.get("innerGateCount", 0) or 0)
                ens = [k < n for k in range(3)]
            ens = _per_gate(ens, [False, False, False])
            for k in range(3):
                self.innerGateEnabled[k].setChecked(bool(ens[k]))
            pct = list(data.get("innerGatePercent", [90, 80, 70])) + [90, 80, 70]
            for k, w in enumerate(self.innerGatePercent):
                w.setValue(float(pct[k]))
            cols = _per_gate(data.get("innerGateColor"), [[1, 0.85, 0.2], [0.3, 0.9, 1.0], [1, 0.45, 0.6]])
            ops = _per_gate(data.get("innerGateOpacity"), [0.3, 0.3, 0.3])
            sts = _per_gate(data.get("innerGateStroke"), [True, True, True])
            fls = _per_gate(data.get("innerGateFill"), [False, False, False])
            for k in range(3):
                self.innerGateColor[k].setValue(_rgb3(cols[k], (1, 0.85, 0.2)))
                self.innerGateOpacity[k].setValue(float(ops[k]))
                self.innerGateStroke[k].setChecked(bool(sts[k]))
                self.innerGateFill[k].setChecked(bool(fls[k]))
            self.innerGateDashed.setChecked(bool(data.get("innerGateDashed", True)))
            self.guidesChk.setChecked(bool(data.get("guidesEnabled", True)))
            self.guideThirds.setChecked(bool(data.get("guideThirds", False)))
            self.guideGrid.setChecked(bool(data.get("guideGrid", False)))
            self.guideArmature.setChecked(bool(data.get("guideArmature", False)))
            self.guideCenter.setChecked(bool(data.get("guideCenter", False)))
            i = self.guideRatio.findData(int(data.get("guideRatio", 0)))
            self.guideRatio.setCurrentIndex(i if i >= 0 else 0)
            i = self.guideFit.findData(int(data.get("guideFit", 0)))
            self.guideFit.setCurrentIndex(i if i >= 0 else 0)
            self.guideThirdsColor.setValue(data.get("guideThirdsColor", [0.3, 0.5, 1.0]))
            self.guideGridColor.setValue(data.get("guideGridColor", [1.0, 0.25, 0.25]))
            self.guideArmatureColor.setValue(data.get("guideArmatureColor", [1.0, 0.9, 0.2]))
            self.guideOpacity.setValue(float(data.get("guideOpacity", 0.8)))
            self.guideWidth.setValue(float(data.get("guideWidth", 1.0)))

            self._pull_effects_block(data)

            self.showSeg.setCurrent(data.get("showPreset", "all"))
            self.jointChk.setChecked(bool(data.get("showJoints", False)))
            self.curveChk.setChecked(bool(data.get("showNurbsCurves", False)))

            self.forceChk.setChecked(bool(data.get("forcePlayblastTarget", False)))

            self._customSize = None                   # g4: 預かり値を捨ててから指定値を入れる(最後に表示を作り直す)
            self._customFps = None
            self.mp4Width.setValue(int(data.get("mp4Width", 1920)))
            self.mp4Height.setValue(int(data.get("mp4Height", 1080)))
            self.mp4Fps.setValue(float(data.get("mp4Fps", 30.0)))
            self.mp4UseSceneFps.setChecked(bool(data.get("mp4UseSceneFps", True)))
            self.mp4Crf.setValue(int(data.get("mp4Crf", 18)))
            i = self.mp4Preset.findText(str(data.get("mp4Preset", "slow")))
            self.mp4Preset.setCurrentIndex(i if i >= 0 else self.mp4Preset.findText("slow"))
            self.mp4Quality.setValue(int(data.get("mp4Quality", 100)))
            self.mp4Ornaments.setChecked(bool(data.get("mp4ShowOrnaments", False)))
            self.mp4FromRender.setChecked(bool(data.get("mp4FromRenderSettings", False)))
            self.mp4OffScreen.setChecked(bool(data.get("mp4OffScreen", False)))
            self.mp4Optimize.setChecked(bool(data.get("mp4OptimizeViewport", True)))
            self.mp4KeepFrames.setChecked(bool(data.get("mp4KeepFrames", False)))
            self.mp4OpenAfter.setChecked(bool(data.get("mp4OpenAfter", True)))
            self.mp4Output.setText(data.get("mp4OutputPath", "") or "")
            self._pbRangeCustom = self._saved_range(data)
            self.pbRangeScene.setChecked(bool(data.get("playblastRangeScene", True)))
            self.multiEnabled.setChecked(bool(data.get("playblastMulti", False)))
            self.multiCombine.setChecked(bool(data.get("playblastCombine", False)))
            self.multiKeep.setChecked(bool(data.get("playblastKeepIndividuals", True)))
            self._on_multi_option()
            mode = data.get("outputMode", "maya")
            if mode not in ("maya", "mp4"):
                mode = "maya"
            self.outputSeg.setCurrent(mode)
            self._apply_output_mode(mode)
            self.pbSettings.setCollapsed(bool(data.get("playblastSettingsCollapsed", True)))
            self._pbSettingsRestore = None
            self.pbCaptureBox.setCollapsed(bool(data.get("playblastCaptureCollapsed", True)))
            self._set_pb_card_collapsed(bool(data.get("playblastCollapsed", False)))
        finally:
            self._building = False
        self._refresh_range_display()
        self._update_pb_summary()
        self._update_capture_summary()
        self._update_mp4_enabled()
        self._update_gate_enabled()
        self._update_ssao_enabled()
        on = self.aaEnable.isChecked()
        self.aaSamples.setEnabled(on)
        self._aaSamplesLabel.setEnabled(on)
        self._update_effects_master()
        self.refresh_presets()

    def _pull_effects_block(self, data, fold=True):
        u"""設定 dict -> Effects / Shadow の UI(pull と pull_effects が共有。_building を立てて呼ぶ)。"""
        self.effectsMaster.setChecked(bool(data.get("effectsMaster", True)))
        if fold:                                  # 設定の読み込み: 正本は保存値。自動の畳みの戻し先は破棄(Settings と同じ)
            self._effectsCard.setCollapsed(bool(data.get("effectsCollapsed", False)))
            self._effectsRestore = None
        self.ssaoEnable.setChecked(bool(data.get("ssaoEnable", False)))
        self.ssaoAmount.setValue(data.get("ssaoAmount", 1.0))
        self.ssaoRadius.setValue(data.get("ssaoRadius", 16))
        self.ssaoFilter.setValue(data.get("ssaoFilterRadius", 16))
        i = self.ssaoSamples.findData(int(data.get("ssaoSamples", 16)))
        self.ssaoSamples.setCurrentIndex(i if i >= 0 else 0)

        self.aaEnable.setChecked(bool(data.get("aaEnable", False)))
        i = self.aaSamples.findData(int(data.get("aaSampleCount", 8)))
        self.aaSamples.setCurrentIndex(i if i >= 0 else 0)
        self.lineAA.setChecked(bool(data.get("lineAAEnable", False)))

        self.shadowChk.setChecked(bool(data.get("shadows", False)))

    def pull_effects(self, data):
        u"""Effects / Shadow の UI だけを設定 dict に合わせる(プリセットの切替 / Reset 用。Playblast 等の欄には触れない)。"""
        self._building = True
        try:
            self._pull_effects_block(data, fold=False)     # プリセット / Reset は値と ON/OFF だけ。カードの開閉(自動の畳みを含む)は変えない
        finally:
            self._building = False
        self._update_ssao_enabled()
        on = self.aaEnable.isChecked()
        self.aaSamples.setEnabled(on)
        self._aaSamplesLabel.setEnabled(on)
        self._update_effects_master()
        self.refresh_presets()

    def set_force_state_text(self, text):
        u"""UI には出さない(ラベルを持つと親無しの小窓になるため)。文字列だけ保持。"""
        self._forceStateText = text or u""

    def set_target_text(self, text):
        self._targetText = text or u""


# ==========================================================================
#  旧バージョンが残した UI の掃除
# ==========================================================================
#  v1.1 以前は QMainWindow(objectName="plsCamViewWindow") に modelPanel を
#  埋め込んでいた。この構成は Maya の UI パスを壊すため v1.2 で廃止したが、
#  reload だけでは古いウィンドウが残ることがあるので明示的に掃除する。
_LEGACY_WINDOW_OBJECT = "plsCamViewWindow"
_LEGACY_HIDDEN_HOST = "plsCamViewHiddenHost"


def cleanup_stale_ui():
    u"""旧バージョン / 前回の残骸ウィンドウを閉じる。"""
    # --- 旧 Qt ウィンドウ ---
    try:
        app = QtWidgets.QApplication.instance()
        if app is not None:
            for w in app.topLevelWidgets():
                try:
                    if w.objectName() == _LEGACY_WINDOW_OBJECT:
                        # deleteLater は次のイベントループで効くため、
                        # 名前を変えて二重に拾わないようにする
                        w.setObjectName(_LEGACY_WINDOW_OBJECT + "_closed")
                        w.close()
                        w.setParent(None)
                        w.deleteLater()
                        print(u"[plsCamView] 旧バージョンのウィンドウを閉じました。")
                except Exception:
                    continue
    except Exception:
        pass

    if cmds is None:
        return
    # --- 旧 隠しホストウィンドウ / 現行ウィンドウ ---
    for name in (_LEGACY_HIDDEN_HOST, WINDOW_NAME):
        try:
            if cmds.window(name, exists=True):
                cmds.deleteUI(name, window=True)
        except Exception:
            pass


# ==========================================================================
#  メインウィンドウ(Maya の window)
# ==========================================================================
class PlsCamViewWindow(object):

    def __init__(self):
        self.data = st.load()
        self.presets = st.PresetOps(self)       # 調整プリセット(FX-PRESETS)
        # v1.8.2: ビュー領域のプレースホルダ(ViewManager 内の cmds.text)は ToolBox 生成より
        # 前に作られるため、保存済み言語をここで復元する(restart()/直接生成の経路も含む。
        # ToolBox 側の set_language は従来どおり残る)。
        i18n.set_language(str((self.data or {}).get("language", "system")))
        self._scriptJobs = []
        self._closing = False
        self._savePending = False
        self._saveTimerArmed = False
        self._win = None
        self._pane = None
        self._tbHost = None
        self.views = None          # vw.ViewManager
        self.toolbox = None
        self.overlays = go.OverlayManager()   # ゲート / 構図ガイドのオーバーレイ(ビューごと)
        self.overlays.set_config(self._gate_config())
        self._build()

    @property
    def viewport(self):
        u"""互換用: Playblast 対象ビューの ModelViewport。"""
        v = self.views.target_view() if self.views else None
        return v.viewport if v else None

    # ------------------------------------------------------------------
    def _build(self):
        if cmds is None:
            raise RuntimeError(tr(u"plsCamView は Maya 上でのみ動作します。"))

        cleanup_stale_ui()

        w, h = self.data.get("windowSize", [1280, 800])
        self._win = cmds.window(WINDOW_NAME, title=WINDOW_TITLE,
                                widthHeight=(int(w), int(h)))
        self._pane = cmds.paneLayout(parent=self._win, configuration="vertical2")

        # ビュー領域(Maya の UI ツリーのまま。複数ビューは views.py が管理)
        self.views = vw.ViewManager(self, self._pane, title=WINDOW_TITLE)

        # ツールボックス(Maya レイアウトの中に Qt で描く)
        self._tbHost = cmds.formLayout(parent=self._pane)
        self.toolbox = ToolBox(self)
        host, self._hostFitter = attach_widget(self._tbHost, self.toolbox)
        if host is None:
            cmds.warning(u"[plsCamView] " + tr(
                u"ツールボックスの生成に失敗しました"
                u"(Maya レイアウト {} を QWidget として取得できません)。").format(self._tbHost))
        else:
            print(u"[plsCamView] toolbox host={} layout={} size={}x{}".format(
                self._tbHost,
                type(host.layout()).__name__ if host.layout() else None,
                host.width(), host.height()))

        # 閉じたときの後始末
        try:
            cmds.window(self._win, e=True, closeCommand=self._on_close)
        except Exception:
            pass
        try:
            self._scriptJobs.append(
                cmds.scriptJob(uiDeleted=[self._win, self._on_close]))
        except Exception:
            pass

        self._restore()
        self._setup_script_jobs()

        cmds.showWindow(self._win)
        self._restore_window_position()
        # ウィンドウ表示前はホストのサイズが確定しないため、表示後に合わせ直す。
        # paneLayout の比率も、表示後に Maya が初期配分で上書きすることがあるので再適用する
        for delay in (0, 120, 400):
            QtCore.QTimer.singleShot(delay, self._fit_toolbox)
        for delay in (50, 250):
            QtCore.QTimer.singleShot(delay, self._reapply_toolbox_percent)

    def _reapply_toolbox_percent(self):
        if self._closing or not self._pane:
            return
        key = self.data.get("dockArea", "right")
        try:
            self._apply_toolbox_percent(key in ("top", "bottom"), key in ("left", "top"))
        except Exception:
            pass

    # ------------------------------------------------------------------
    def _fit_toolbox(self, verbose=False):
        u"""ツールボックスをホスト(Maya の formLayout)いっぱいに広げる。"""
        if self._closing or self.toolbox is None:
            return
        try:
            host = to_qwidget(self._tbHost)
            if host is None or self.toolbox.parent() is not host:
                return
            hw, hh = max(1, host.width()), max(1, host.height())
            if self.toolbox.width() != hw or self.toolbox.height() != hh:
                self.toolbox.setGeometry(0, 0, hw, hh)
            if not self.toolbox.isVisible():
                self.toolbox.show()
            if verbose:
                print(u"[plsCamView] toolbox fit: host={}x{} toolbox={}x{}".format(
                    hw, hh, self.toolbox.width(), self.toolbox.height()))
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  復元 / 保存
    # ------------------------------------------------------------------
    def _restore(self):
        d = self.data

        if d.get("applyVp2OnStartup", True):
            vp2.apply_all(d)
        else:
            d.update(vp2.read_all())

        self.toolbox.pull(d)
        self.views.build_from_settings()
        self.refresh_cameras()
        self.apply_show(save=False)
        self.apply_shadows(save=False)
        self.toolbox.set_view_state(self.views.count(), self.views.layout)
        self._update_target_text()
        self.set_dock_area(d.get("dockArea", "right"), save=False)

        if d.get("forcePlayblastTarget", False):
            self.set_force_playblast(True, from_restore=True)
        else:
            self.toolbox.set_force_state_text(u"")

    def _restore_window_position(self):
        pos = self.data.get("windowTopLeft")
        if not pos:
            return
        try:
            cmds.window(self._win, e=True, topLeftCorner=(int(pos[0]), int(pos[1])))
        except Exception:
            pass

    def _collect(self):
        d = self.data
        try:
            if cmds.window(self._win, exists=True):
                d["windowSize"] = [cmds.window(self._win, q=True, width=True),
                                   cmds.window(self._win, q=True, height=True)]
                d["windowTopLeft"] = list(
                    cmds.window(self._win, q=True, topLeftCorner=True))
        except Exception:
            pass
        try:
            d[self._percent_key()] = self._query_toolbox_percent()
        except Exception:
            pass
        if self.views is not None:
            try:
                d["views"] = self.views.collect()
                d["viewLayout"] = self.views.layout
                d["playblastView"] = self.views.target_index
                d["playblastViews"] = list(self.views.target_indices)
            except Exception:
                pass
        cam = self.target_camera()
        if cam:
            d["camera"] = cam
        return d

    def target_camera(self):
        v = self.views.target_view() if self.views else None
        return v.camera() if v else self.data.get("camera")

    def save_settings(self):
        u"""設定を保存する。連続呼び出し(スライダ操作など)は 300ms にまとめて 1 回だけ書く。"""
        if self._closing:
            return
        getattr(self, "_preset_sync", lambda: None)()      # 調整プリセット欄の同期(Window の一部だけを借りる試験用の代役にも耐える)
        self._savePending = True
        if not self._saveTimerArmed:
            self._saveTimerArmed = True
            QtCore.QTimer.singleShot(300, self._flush_save)

    def _flush_save(self):
        self._saveTimerArmed = False
        if not self._savePending or self._closing:
            return
        self._savePending = False
        try:
            st.save(self._collect())
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  調整プリセット(FX-PRESETS。ロジックは settings.PresetOps)
    # ------------------------------------------------------------------
    def _preset_sync(self):
        u"""プリセット欄(選択 / ↺ の出し分け)を現在の値に合わせる。失敗しても本体の動作は止めない。"""
        try:
            tb = getattr(self, "toolbox", None)
            if tb is not None:
                tb.refresh_presets()
        except Exception:
            pass

    def _preset_apply_current(self):
        u"""プリセットで書き換えた現在値を VP2 / ビューへ適用し、**読み戻して** 一致を確かめる。合わなければ False。"""
        d = self.data
        try:
            vp2.apply_all(d)
        except Exception as e:
            cmds.warning(u"[plsCamView] " + tr(u"プリセットの適用に失敗しました: {}").format(e))
            return False
        master = bool(d.get("effectsMaster", True))
        ok = True
        for key in st.PRESET_KEYS:
            if key not in vp2.ATTR or not vp2.has(key):
                continue
            want = d.get(key)
            if not master and key in vp2._MASTER_GATED:
                want = False
            cur = vp2.get(key)
            if cur is None or not vp2._same(cur, want):
                ok = False
        if not self.apply_shadows(save=False):
            ok = False
        vp2.refresh_viewport()
        if not ok:
            cmds.warning(u"[plsCamView] " + tr(u"Maya へ反映できないプリセットの項目があります"))
        return ok


    def exists(self):
        try:
            return bool(cmds and self._win and cmds.window(self._win, exists=True))
        except Exception:
            return False

    # ------------------------------------------------------------------
    #  ドック位置(paneLayout の構成切替)
    # ------------------------------------------------------------------
    def set_dock_area(self, key, save=True):
        if not key or not self._pane:
            return
        # 今の向きの比率を覚えてから切り替える(左右と上下で比率は別々に持つ)。
        # 起動時(save=False)はまだ比率を適用していないので、ここで読むと Maya の初期値で上書きしてしまう
        if save:
            try:
                self.data[self._percent_key()] = self._query_toolbox_percent()
            except Exception:
                pass
        self.data["dockArea"] = key
        horizontal = key in ("top", "bottom")
        tb_first = key in ("left", "top")

        try:
            cmds.paneLayout(self._pane, e=True,
                            configuration="horizontal2" if horizontal else "vertical2")
            views_pane = self.views.views_pane
            first = self._tbHost if tb_first else views_pane
            second = views_pane if tb_first else self._tbHost
            cmds.paneLayout(self._pane, e=True, setPane=(first, 1))
            cmds.paneLayout(self._pane, e=True, setPane=(second, 2))
        except Exception as e:
            cmds.warning(u"[plsCamView] " + tr(u"ツールボックス位置の変更に失敗: {}").format(e))

        self.toolbox.set_orientation(horizontal)
        if horizontal:
            # 中身の高さが確定してから合わせる(同期だと畳む前の高さで計算してしまう)。
            # 保存した高さがあればそれを使う(_apply_toolbox_percent 側で判定)
            QtCore.QTimer.singleShot(0, self._reapply_toolbox_percent)
        else:
            self._apply_toolbox_percent(horizontal, tb_first)
        self.toolbox.dockPicker.setCurrent(key)
        for delay in (0, 120):
            QtCore.QTimer.singleShot(delay, self._fit_toolbox)
        if save:
            self.save_settings()

    def _toolbox_pane_index(self):
        return 1 if self.data.get("dockArea", "right") in ("left", "top") else 2

    def _percent_key(self, horizontal=None):
        if horizontal is None:
            horizontal = self.data.get("dockArea", "right") in ("top", "bottom")
        return "toolboxPercentH" if horizontal else "toolboxPercent"

    def fit_toolbox_height(self):
        u"""上下配置のとき、ツールボックスのペインを中身の高さぴったりにする。"""
        if self._closing or not self._pane:
            return
        key = self.data.get("dockArea", "right")
        if key not in ("top", "bottom"):
            return
        self.data["toolboxPercentH"] = None
        self._apply_toolbox_percent(True, key == "top")
        for delay in (0, 120):
            QtCore.QTimer.singleShot(delay, self._fit_toolbox)

    def _apply_toolbox_percent(self, horizontal, tb_first):
        key = self._percent_key(horizontal)
        pct = self.data.get(key)
        if horizontal and pct is None:
            # 上下配置で保存値が無い(初回 / 折り畳みを変えた直後)ときは、中身が収まる高さにする
            try:
                win_h = float(cmds.window(self._win, q=True, height=True) or 800)
                pct = (self.toolbox.preferred_height() + 8) / win_h * 100.0
            except Exception:
                pct = 30.0
        if pct is None:
            pct = 26.0
        pct = max(8.0, min(60.0, float(pct)))
        tb = 1 if tb_first else 2
        other = 2 if tb_first else 1
        try:
            if horizontal:
                cmds.paneLayout(self._pane, e=True, paneSize=(tb, 100, pct))
                cmds.paneLayout(self._pane, e=True, paneSize=(other, 100, 100 - pct))
            else:
                cmds.paneLayout(self._pane, e=True, paneSize=(tb, pct, 100))
                cmds.paneLayout(self._pane, e=True, paneSize=(other, 100 - pct, 100))
        except Exception:
            pass

    def _query_toolbox_percent(self):
        u"""スプリッターをドラッグした後の比率を取得する。"""
        fallback = self.data.get(self._percent_key(), 26)
        try:
            sizes = cmds.paneLayout(self._pane, q=True, paneSize=True)
        except Exception:
            return fallback
        if not sizes or len(sizes) < 4:
            return fallback
        idx = self._toolbox_pane_index()
        horizontal = self.data.get("dockArea", "right") in ("top", "bottom")
        # paneSize は [w1, h1, w2, h2] の % で返る
        val = sizes[(idx - 1) * 2 + (1 if horizontal else 0)]
        try:
            val = float(val)
        except Exception:
            return fallback
        return val if 5.0 < val < 95.0 else fallback

    # ------------------------------------------------------------------
    #  カメラ
    # ------------------------------------------------------------------
    def refresh_cameras(self, select=None):
        u"""全ビューのカメラ一覧を読み直す(select は互換用: 対象ビューのカメラ)。"""
        if select and self.views.target_view() is not None:
            self.views.target_view().state["camera"] = select
        self.views.refresh_cameras()
        self.data["camera"] = self.target_camera() or self.data.get("camera")

    def set_camera(self, cam, save=True):
        u"""互換用: Playblast 対象ビューのカメラを切り替える。"""
        v = self.views.target_view()
        if v is None or v.viewport is None:
            return
        if v.viewport.set_camera(cam):
            v.state["camera"] = cam
            v.bar.set_cameras(v.bar.real_cameras(), cam)
            self.data["camera"] = cam
            self.apply_view_settings(v)
            if save:
                self.save_settings()

    # ------------------------------------------------------------------
    #  ViewManager からの通知
    # ------------------------------------------------------------------
    def apply_view_settings(self, view, seed_show=False):
        u"""1 つのビューへ Shadow / ゲートオーバーレイを適用する(ビュー作成・カメラ切替時)。
        **Show は書き戻さない**(カメラ切替などで、利用者が標準 Show で変えた状態を古い設定へ戻さないため)。
        seed_show=True は「引継ぎ元が無い新規ビュー」だけ: 保存済みの Show を 1 度だけ適用する。"""
        vpt = view.viewport if view is not None else None
        if vpt is None or not hasattr(vpt, "apply_show"):
            return
        d = self.data
        try:
            if seed_show:
                failed = vpt.apply_show(d.get("showPreset", "all"),
                                        {"showJoints": d.get("showJoints", False),
                                         "showNurbsCurves": d.get("showNurbsCurves", False)})
                if failed:
                    self._warn_show([(view.index + 1, failed)])
            vpt.set_shadows(d.get("shadows", False))
        except Exception:
            pass
        try:
            self.overlays.ensure(vpt.panel)
            QtCore.QTimer.singleShot(300, self.overlays.refresh)   # Maya がレイアウトを確定した後に位置合わせ
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  ゲート / 構図ガイド(オーバーレイ)
    # ------------------------------------------------------------------
    def _gate_config(self):
        d = self.data
        cfg = {}
        for key in go.DEFAULTS:
            if key in d:
                cfg[key] = d[key]
        if not d.get("guidesEnabled", True):
            for key in ("guideThirds", "guideGrid", "guideArmature", "guideCenter"):
                cfg[key] = False
        return cfg

    def apply_gate(self, save=True):
        u"""Gate カードの値を全ビューのオーバーレイへ配る。"""
        try:
            self.overlays.set_config(self._gate_config())
        except Exception as e:
            cmds.warning(u"[plsCamView] " + tr(u"ゲートの適用に失敗: {}").format(e))
        if save:
            self.save_settings()

    def on_views_changed(self):
        if self._closing:
            return
        try:
            self.sync_show_switches()      # 読み取りのみ
        except Exception:
            pass
        try:
            self.toolbox.set_view_state(self.views.count(), self.views.layout)
        except Exception:
            pass
        try:
            self.overlays.refresh()
        except Exception:
            pass
        self._update_target_text()
        self.save_settings()

    def on_target_changed(self):
        self._update_target_text()
        self.save_settings()

    def _update_target_text(self):
        v = self.views.target_view() if self.views else None
        if v is None:
            self.toolbox.set_target_text(u"")
            return
        cam = v.camera() or u"-"
        self.toolbox.set_target_text(u"対象: View {} ({}){}".format(
            v.index + 1, cam, u" ※ポップアウト中" if v.is_popped() else u""))

    def show_main_window(self):
        try:
            if self.exists():
                cmds.showWindow(self._win)
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  Show / Shadow
    # ------------------------------------------------------------------
    def _show_viewports(self):
        u"""(ビュー番号, ModelViewport) を全ビュー分(ポップアウト中も含む)。"""
        out = []
        for v in (getattr(self.views, "views", None) or []):
            vpt = getattr(v, "viewport", None)
            if vpt is not None and isinstance(vpt, vp.ModelViewport):
                out.append((v.index + 1, vpt))
        return out

    def _warn_show(self, failed):
        u"""反映・確認できなかったビュー / フラグを黙らず知らせる(1 回の操作につき 1 件。同じビューはまとめる)。
        通知(シーン切替・カメラ切替など)からは呼ばない(警告の連打を避ける)。"""
        merged, order = {}, []
        for idx, items in (failed or []):
            if idx not in merged:
                merged[idx] = []
                order.append(idx)
            for it in items:
                if it not in merged[idx]:
                    merged[idx].append(it)
        order = [i for i in sorted(order) if merged[i]]
        if order:
            try:
                cmds.warning(u"[plsCamView] " + tr(u"Show を反映・確認できなかったビュー: {}").format(
                    u", ".join(u"View {} ({})".format(i, u", ".join(merged[i])) for i in order)))
            except Exception:
                pass

    def _show_flag_state(self, flag):
        u"""全ビューの実値を集計して (状態, 問題の一覧[(ビュー番号, 記述)]) を返す。
        状態: True(全ビュー読めて全 ON) / False(全ビュー読めて全 OFF) / "mixed"(全ビュー読めて、ビューの間で異なる) /
              "unknown"(読めないビュー(無効・例外・None・TypeError を含む)が 1 つでもある = 全 ON/OFF と断定しない。全件失敗も同じ)。
        全ての対象ビューを確認できないときは、読めたビューが全て同じ値でも True / False にしない(読めないビューの値は不明)。
        例外の型だけで「フラグが無い」と判断して集計から外すことはしない。"""
        values, issues, unread = [], [], 0
        for idx, vpt in self._show_viewports():
            st, v = vpt.query_show_flag(flag)
            if st == "ok":
                values.append(bool(v))
            elif st == "invalid":
                unread += 1
                issues.append((idx, vp.SHOW_INVALID))
            else:
                unread += 1
                issues.append((idx, vp.show_issue(flag, vp.WHY_UNREAD)))
        if unread or not values:
            return "unknown", issues
        if all(values):
            return True, issues
        if not any(values):
            return False, issues
        return "mixed", issues

    def sync_show_switches(self):
        u"""全ビューの現在の Show 状態を読み、スイッチへ反映する。**読み取りのみ**(ビューへは何も書かない)。
        利用者が標準 Show で変えた状態をそのまま表示する。取得できないものは保存値で埋めず unknown 表示にし、
        保存値(self.data)は「全ビューが読めて一致した」ときだけ実値へ合わせる(mixed / unknown では触らない)。
        戻り値: 問題の一覧[(ビュー番号, [記述])](操作側がまとめて警告する。通知側は使わない)。"""
        shown, issues = {}, {}
        for key, flag in vp.EXTRA_FLAGS.items():
            state, iss = self._show_flag_state(flag)
            for idx, it in iss:
                issues.setdefault(idx, []).append(it)
            if state is True or state is False:
                self.data[key] = state
            shown[key] = state
        try:
            self.toolbox.set_show_switches(shown["showJoints"], shown["showNurbsCurves"])
        except Exception:
            pass
        return sorted(issues.items())

    def apply_show(self, save=True):
        u"""プリセット -> 追加スイッチ の順に適用する(**起動時の状態復元専用**。通知やカメラ切替からは呼ばない)。"""
        d = self.data
        extras = {"showJoints": d.get("showJoints", False),
                  "showNurbsCurves": d.get("showNurbsCurves", False)}
        failed = []
        for idx, vpt in self._show_viewports():
            f = vpt.apply_show(d.get("showPreset", "all"), extras)
            if f:
                failed.append((idx, f))
        self._warn_show(failed)
        if save:
            self.save_settings()

    def apply_show_preset(self, key, save=True):
        u"""
        プリセットのみを、全ビューへ 1 回適用する(対象と期待値は ModelViewport.apply_show の説明)。
        適用後は全ビューの実値を集計してスイッチへ反映する(代表ビューの値では決めない。不一致は mixed、取得不能は unknown)。
        書込みの失敗・取得できなかったビューは、この操作で 1 件にまとめて警告する。
        """
        failed = []
        for idx, vpt in self._show_viewports():
            f = vpt.apply_show(key, None)
            if f:
                failed.append((idx, f))
        failed.extend((i, f) for i, f in self.sync_show_switches())
        self._warn_show(failed)
        if save:
            self.save_settings()

    def apply_show_flag(self, key, on, save=True):
        u"""Joint / NurbsCurve のうち key のフラグだけを、全ビューへ 1 回適用する(ビューごとの状態が違っても、
        押したフラグ以外の Show は一切書かない)。適用後に全ビューの実値からスイッチを同期する。
        self.data[key] は「利用者が最後に指定した値」(実値ではない)。実値として表示するのは読めたときだけ。"""
        on = bool(on)
        self.data[key] = on
        failed = []
        for idx, vpt in self._show_viewports():
            f = vpt.apply_show_extras({key: on})
            if f:
                failed.append((idx, f))
        failed.extend((i, f) for i, f in self.sync_show_switches())
        self._warn_show(failed)
        if save:
            self.save_settings()

    def apply_show_extras(self, save=True):
        u"""互換用: Joint / NurbsCurve の保存値を全ビューへ反映する(UI は apply_show_flag を使う)。"""
        d = self.data
        extras = {"showJoints": d.get("showJoints", False),
                  "showNurbsCurves": d.get("showNurbsCurves", False)}
        failed = []
        for idx, vpt in self._show_viewports():
            f = vpt.apply_show_extras(extras)
            if f:
                failed.append((idx, f))
        self._warn_show(failed)
        if save:
            self.save_settings()

    def apply_shadows(self, save=True):
        u"""全ビューへ Shadow を適用する。1 つでも失敗したら False(呼出元の多くは戻り値を使わない)。"""
        ok = True
        for vpt in self.views.each_viewport():
            if not vpt.set_shadows(self.data.get("shadows", False)):
                ok = False
        if save:
            self.save_settings()
        return ok

    # ------------------------------------------------------------------
    #  Playblast
    # ------------------------------------------------------------------
    def _panel_getter(self):
        try:
            return self.views.target_panel()
        except Exception:
            return None

    def activate_window(self):
        u"""対象ビューのウィンドウを前面に出して Maya のフォーカスもそのパネルへ移す。"""
        v = self.views.target_view() if self.views else None
        if v is not None:
            v.activate()
            return
        self.show_main_window()

    def set_force_playblast(self, on, from_restore=False):
        self.data["forcePlayblastTarget"] = bool(on)
        if on:
            ok = pbh.install(
                self._panel_getter,
                window_activator=self.activate_window,
                fallback=bool(self.data.get("playblastFallback", True)),
                mode=self.data.get("playblastMode", "direct"),
                force_active_panel=bool(self.data.get("forceActivePanel", True)),
                verbose=bool(self.data.get("playblastVerbose", False)))
            if ok:
                self.toolbox.set_force_state_text(
                    u"Maya 標準 / 外部ツール(Python) からの Playblast も"
                    u"このビューを対象にします。")
            else:
                self.toolbox.set_force_state_text(
                    u"MEL の performPlayblast はフックできませんでした"
                    u"(Python 経由の Playblast は固定されます)。")
        else:
            pbh.uninstall()
            self.toolbox.set_force_state_text(u"")
        if not from_restore:
            self.save_settings()

    def do_playblast(self, options=False):
        panel = self._panel_getter()
        if options:
            pbh.playblast_options(panel, window_activator=self.activate_window)
            return
        # Maya 標準 / MP4 のどちらも、ツールボックスの書き出し設定で実行する
        self.do_playblast_mp4()

    def do_playblast_mp4(self, **overrides):
        u"""ツールボックスの書き出し設定で対象ビューを撮る(mode: maya / mp4)。"""
        if getattr(self, "_playblastBusy", False):
            return False, tr(u"書き出し中です。"), ""
        panel = self._panel_getter()
        if not panel:
            return False, tr(u"対象パネルがありません。"), ""
        try:
            self.activate_window()
        except Exception:
            pass
        kw = self.toolbox.mp4_options()
        kw.update(overrides)
        kw.setdefault("camera", self.target_camera())
        combine = kw.pop("combine", self.data.get("playblastCombine", False))
        keep_individuals = kw.pop("keep_individuals", self.data.get("playblastKeepIndividuals", True))
        if self.data.get("playblastMulti", False) and self.views and len(self.views.selected_views()) > 1:
            return self._playblast_multiple(kw, combine, keep_individuals)
        result = mp4blast.run(panel, **kw)
        ok, msg, _ = result
        try:
            if ok:
                cmds.inViewMessage(amg=u"<hl>plsCamView</hl>: " + msg,
                                   pos="botCenter", fade=True)
            else:
                cmds.warning(u"[plsCamView] " + msg)
        except Exception:
            pass
        return result

    def _playblast_multiple(self, options, combine, keep_individuals):
        try:
            targets = self.views.playblast_targets(geometry=combine)
        except Exception as exc:
            cmds.warning(str(exc))
            return False, str(exc), ""
        progress = QtWidgets.QProgressDialog(tr(u"準備中"), tr(u"取消"), 0, 0, self.toolbox)
        progress.setWindowTitle(tr(u"複数カメラ Playblast"))
        progress.setWindowModality(QtCore.Qt.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.show()
        self._playblastBusy = True
        def update(text):
            progress.setLabelText(text)
            QtWidgets.QApplication.processEvents()
        try:
            result = multiblast.run(targets, combine=combine, keep_individuals=keep_individuals,
                                    cancelled=progress.wasCanceled, progress=update, **options)
        finally:
            progress.close()
            progress.deleteLater()
            self._playblastBusy = False
        ok, message, _ = result
        if ok:
            cmds.inViewMessage(amg=message, pos="botCenter", fade=True)
        else:
            cmds.warning(message)
        return result

    def diagnose(self):
        pbh.diagnose(self._panel_getter())

    # ------------------------------------------------------------------
    #  scriptJob
    # ------------------------------------------------------------------
    def _setup_script_jobs(self):
        if cmds is None:
            return
        for ev in ("SceneOpened", "NewSceneOpened"):
            try:
                jid = cmds.scriptJob(event=[ev, self._on_scene_changed],
                                     killWithScene=False)
                self._scriptJobs.append(jid)
            except Exception:
                pass
        # Time Range(Scene ON)の表示を、Maya の再生範囲の変更・シーン切替に追従させる(イベント駆動。タイマーなし)
        for ev in ("playbackRangeChanged", "playbackRangeSliderChanged", "SceneOpened", "NewSceneOpened"):
            try:
                jid = cmds.scriptJob(event=[ev, self._on_playback_range_changed],
                                     killWithScene=False)
                self._scriptJobs.append(jid)
            except Exception:
                pass

    def _on_scene_changed(self, *_):
        if self._closing or not self.exists():
            return
        try:
            self.refresh_cameras()
            self.sync_show_switches()     # 読み取りのみ(標準 Show の変更を古い設定へ戻さない)
            self.apply_shadows(save=False)
        except Exception:
            pass

    def _on_playback_range_changed(self, *_):
        if self._closing or not self.exists():
            return
        try:
            if self.toolbox is not None:
                self.toolbox._refresh_range_display()
        except Exception:
            pass

    def _kill_script_jobs(self):
        if cmds is None:
            return
        for jid in self._scriptJobs:
            try:
                if cmds.scriptJob(exists=jid):
                    cmds.scriptJob(kill=jid, force=True)
            except Exception:
                pass
        self._scriptJobs = []

    # ------------------------------------------------------------------
    #  終了処理
    # ------------------------------------------------------------------
    def _on_close(self, *_):
        if self._closing:
            return
        try:
            st.save(self._collect())
        except Exception:
            pass
        self._closing = True
        try:
            self._kill_script_jobs()
        except Exception:
            pass
        try:
            self.overlays.remove_all()
        except Exception:
            pass
        try:
            if self.views is not None:
                self.views.destroy_all()
        except Exception:
            pass
        try:
            pbh.uninstall()
        except Exception:
            pass
        try:
            from . import _clear_instance
            _clear_instance()
        except Exception:
            pass

    def show(self):
        if self.exists():
            cmds.showWindow(self._win)

    def close(self):
        self._on_close()
        try:
            if self.exists():
                cmds.deleteUI(self._win, window=True)
        except Exception:
            pass
