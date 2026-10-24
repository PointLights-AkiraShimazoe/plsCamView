# -*- coding: utf-8 -*-
u"""
plsCamView.style
================
見た目まわり(カラーパレット / スタイルシート / カスタムウィジェット)。

デザイン方針は "AuthKit (Dark / Frosted glass)" に準拠する。
ほぼ黒の地(#05060f)にフロストガラスの面を重ね、境界は固い線ではなく
半透明のハーフラインで表現する。彩色は Void Violet(#663af3)のみで、
これは CTA(Playblast 実行)にだけ使う。ON/OFF などの状態差は
彩色を増やさず、フロストの明度差で表現している。

外部の画像ファイルは使わず、アイコンはすべてコードで描画する
(フォルダ完結・DPI 非依存のため)。
"""
from __future__ import absolute_import

import math

from .qt import QtCore, QtGui, QtWidgets


# ==========================================================================
#  カラーパレット (AuthKit / Dark)
# ==========================================================================
C = {
    # 面
    "bg":          "#05060f",                       # Midnight Canvas
    "card":        "rgba(186, 214, 247, 0.03)",     # Frosted Glass
    "cardHover":   "rgba(186, 214, 247, 0.05)",
    "input":       "rgba(199, 211, 234, 0.06)",     # Text Input
    "elevated":    "#2f343e",                       # Steel Plate

    # 境界(固い線は使わない = 常に半透明のハーフライン)
    "border":      "rgba(186, 215, 247, 0.12)",     # Glass Edge
    "borderSoft":  "rgba(186, 215, 247, 0.08)",
    "borderFocus": "rgba(186, 215, 247, 0.24)",

    # 文字 (Ice -> Frost -> Moon -> Fog の順に落とす)
    "textHi":      "#d8ecf8",                       # Ice Highlight
    "text":        "#d1e4fa",                       # Frost Glow
    "textDim":     "#c7d3ea",                       # Moon Mist
    "textFaint":   "#9da7ba",                       # Fog Veil

    # 唯一の彩色(CTA 専用)
    "accent":      "#7a56f5",
    "accentDeep":  "#663af3",                       # Void Violet
    "accentSoft":  "rgba(102, 58, 243, 0.22)",

    # フロストの明度差(状態表現に使う)
    "frost06":     "rgba(186, 214, 247, 0.06)",
    "frost12":     "rgba(186, 214, 247, 0.12)",
    "frost18":     "rgba(186, 214, 247, 0.18)",
    "frost34":     "rgba(186, 214, 247, 0.34)",

    "knob":        "#ffffff",
    "trackOff":    "rgba(199, 211, 234, 0.10)",
    "button":      "rgba(186, 214, 247, 0.06)",
    "buttonHover": "rgba(186, 214, 247, 0.12)",
}

FONT_FAMILY = (
    u'"Untitled Sans", "Inter", "Segoe UI", '
    u'"Yu Gothic UI", "Meiryo UI", "Hiragino Sans", sans-serif'
)
# 全大文字ラベル(Eyebrow)用
MONO_FAMILY = (
    u'"dotDigital", "JetBrains Mono", "Roboto Mono", '
    u'"Consolas", "Yu Gothic UI", monospace'
)

# 角丸(用途で厳格に使い分ける)
R_PILL = 17       # ボタン(pill)。Qt は極端に大きい radius を扱えないため
                  # 実高さの半分弱を指定して pill 形状にする(高さ 36〜38px 想定)。
R_CARD = 16       # カード / モーダル
R_INPUT = 6       # 入力欄 / バッジ


# --------------------------------------------------------------------------
def _qc(r, g, b, a=1.0):
    u"""paintEvent 用の QColor(アルファ付き)。"""
    return QtGui.QColor(r, g, b, int(round(255 * a)))


# ==========================================================================
#  スタイルシート
# ==========================================================================
_STYLESHEET_CACHE = None


def stylesheet():
    u"""QSS 文字列(1 回だけ組み立ててキャッシュ。ToolBox と各 CameraBar が使う)。"""
    global _STYLESHEET_CACHE
    if _STYLESHEET_CACHE is None:
        _STYLESHEET_CACHE = _build_stylesheet()
    return _STYLESHEET_CACHE


def _build_stylesheet():
    return u"""
* {{
    font-family: {font};
    font-size: 16px;
    color: {text};
}}

QWidget#plsRoot, QScrollArea, QScrollArea > QWidget > QWidget {{
    background: {bg};
}}

/* ---- カード(Glass Card) --------------------------------------------- */
QFrame#card {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(186, 214, 247, 0.055),
                stop:0.45 rgba(186, 214, 247, 0.028),
                stop:1 rgba(186, 214, 247, 0.022));
    border: 1px solid {border};
    border-radius: {rCard}px;
}}
QLabel#cardTitle {{
    font-family: {mono};
    color: {textHi};
    font-size: 14px;
    font-weight: 700;
    letter-spacing: 1.4px;
    background: transparent;
    border: none;
}}
QLabel#note {{
    color: {textFaint};
    font-size: 14px;
    background: transparent;
    border: none;
}}
QLabel#fieldLabel {{
    color: {textDim};
    font-size: 15px;
    background: transparent;
    border: none;
}}
QLabel#fieldLabel:disabled, QLabel#note:disabled {{
    color: {textFaint};
}}
QFrame#hline {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 rgba(186, 215, 247, 0.0),
                stop:0.5 rgba(186, 215, 247, 0.12),
                stop:1 rgba(186, 215, 247, 0.0));
    border: none;
    max-height: 1px;
    min-height: 1px;
}}
/* ---- カード内のサブセクション(ネスト表示) ------------------------------- */
QFrame#subsection {{
    background: rgba(186, 214, 247, 0.030);
    border: 1px solid rgba(186, 215, 247, 0.10);
    border-left: 3px solid rgba(186, 215, 247, 0.28);
    border-radius: {rInput}px;
}}
QFrame#subsection:disabled {{
    border-left: 3px solid rgba(186, 215, 247, 0.10);
}}
QLabel#subTitle {{
    font-family: {mono};
    color: {text};
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.2px;
    background: transparent;
    border: none;
}}
QLabel#subSummary {{
    color: {textFaint};
    font-size: 13px;
    background: transparent;
    border: none;
}}
QLabel#subTitle:disabled {{
    color: {textFaint};
}}
QToolButton#chevron {{
    background: transparent;
    border: none;
    padding: 0px;
}}

/* ---- 入力系(radius 6px) --------------------------------------------- */
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {{
    background: {input};
    border: 1px solid {border};
    border-radius: {rInput}px;
    padding: 4px 8px;
    min-height: 22px;
    color: {textHi};
    selection-background-color: {accentDeep};
}}
QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {{
    border-color: {borderFocus};
    background: {frost06};
}}
QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {{
    border-color: {borderFocus};
}}
QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {textFaint};
    border-color: {borderSoft};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox::down-arrow {{
    image: none;
    border: none;
    width: 0px;
    height: 0px;
}}
QComboBox QAbstractItemView {{
    background: {elevated};
    border: 1px solid {border};
    border-radius: {rInput}px;
    padding: 4px;
    outline: none;
    color: {text};
    selection-background-color: {accentDeep};
    selection-color: #ffffff;
}}

/* ---- ボタン(Pill) ---------------------------------------------------- */
QPushButton {{
    background: {button};
    border: 1px solid {border};
    border-radius: {rPill}px;
    padding: 6px 14px;
    min-height: 22px;
    color: #ffffff;
    font-weight: 500;
}}
QPushButton:hover  {{ background: {buttonHover}; }}
QPushButton:pressed{{ background: {frost18}; }}
QPushButton:disabled {{
    background: rgba(199, 211, 234, 0.03);
    border-color: {borderSoft};
    color: {textFaint};
}}

/* Void Violet は CTA(Playblast 実行)のみ。行内で radius を混ぜないため
   こちらも pill を維持する。 */
QPushButton#primary {{
    background: {accentDeep};
    border: 1px solid rgba(186, 215, 247, 0.18);
    color: #ffffff;
    font-weight: 600;
    padding: 6px 20px;
}}
QPushButton#primary:hover  {{ background: {accent}; }}
QPushButton#primary:pressed{{ background: #5730d6; }}
QPushButton#primary:disabled {{
    background: rgba(102, 58, 243, 0.28);
    color: rgba(255, 255, 255, 0.45);
}}

/* ---- セグメンテッドコントロール(Show プリセット) -------------------- */
QPushButton[seg="true"] {{
    background: {button};
    border: 1px solid {border};
    border-radius: {rPill}px;
    padding: 5px 6px;
    color: {textDim};
    font-weight: 500;
    margin: 0px;
}}
QPushButton[seg="true"]:hover   {{ background: {buttonHover}; color: {textHi}; }}
QPushButton[seg="true"]:checked {{
    background: {frost34};
    border-color: {borderFocus};
    color: #ffffff;
    font-weight: 600;
}}

/* ---- ドック位置ボタン(Icon Tile) ------------------------------------- */
QToolButton#dockBtn {{
    background: {button};
    border: 1px solid {border};
    border-radius: {rPill}px;
    padding: 3px;
}}
QToolButton#dockBtn:hover {{ background: {buttonHover}; }}
QToolButton#dockBtn:checked {{
    background: {frost18};
    border: 1px solid {borderFocus};
}}

/* ---- スライダ -------------------------------------------------------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {input};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {frost34};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal:disabled {{ background: rgba(199, 211, 234, 0.08); }}
QSlider::handle:horizontal {{
    background: {textHi};
    width: 13px;
    height: 13px;
    margin: -5px 0;
    border-radius: 7px;
}}
QSlider::handle:horizontal:hover     {{ background: #ffffff; }}
QSlider::handle:horizontal:disabled  {{ background: {textFaint}; }}

/* ---- スクロールバー -------------------------------------------------- */
QScrollArea {{ border: none; }}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px 0px 2px 0px;
}}
QScrollBar::handle:vertical {{
    background: rgba(199, 211, 234, 0.16);
    border-radius: 5px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(199, 211, 234, 0.28); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: none; }}

/* ---- ドックウィジェット ---------------------------------------------- */
QDockWidget {{
    titlebar-close-icon: none;
    titlebar-normal-icon: none;
    font-size: 12px;
    color: {textDim};
}}
QDockWidget::title {{
    background: {bg};
    padding: 5px 8px;
    text-align: left;
}}
QMainWindow::separator {{
    background: {bg};
    width: 4px;
    height: 4px;
}}

QToolTip {{
    background: #0b0d18;
    color: {text};
    border: 1px solid {border};
    border-radius: {rInput}px;
    padding: 5px 8px;
}}
""".format(font=FONT_FAMILY, mono=MONO_FAMILY,
           rPill=R_PILL, rCard=R_CARD, rInput=R_INPUT, **C)


# ==========================================================================
#  ドック位置アイコン(コード描画)
# ==========================================================================
def make_dock_icon(side, size=30, active=False):
    u"""
    ビューポートとツールボックスの位置関係を示すアイコンを描画して返す。
    side : "left" / "right" / "top" / "bottom"
    彩色は使わず、フロストの明度差だけで選択状態を表す。
    """
    ratio = 2  # 高 DPI 対策
    pm = QtGui.QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(float(ratio))
    pm.fill(QtCore.Qt.transparent)

    # QPainter は pixmap の devicePixelRatio を考慮するので、
    # 以降は論理座標(size x size)で描けばよい。
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)

    if active:
        frame_col = _qc(216, 236, 248, 0.85)     # Ice Highlight
        bar_col = _qc(186, 214, 247, 0.80)
    else:
        frame_col = _qc(157, 167, 186, 0.70)     # Fog Veil
        bar_col = _qc(199, 211, 234, 0.34)
    view_col = QtGui.QColor("#05060f")

    m = 4.0
    rect = QtCore.QRectF(m, m + 1.5, size - m * 2, size - (m + 1.5) * 2)
    radius = 3.5

    # ビューポート(下地)
    path = QtGui.QPainterPath()
    path.addRoundedRect(rect, radius, radius)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(view_col)
    p.drawPath(path)

    # ツールボックス部分(下地の角丸でクリップして描く)
    t = 0.34
    if side == "left":
        bar = QtCore.QRectF(rect.x(), rect.y(), rect.width() * t, rect.height())
    elif side == "right":
        bar = QtCore.QRectF(rect.right() - rect.width() * t, rect.y(),
                            rect.width() * t, rect.height())
    elif side == "top":
        bar = QtCore.QRectF(rect.x(), rect.y(), rect.width(), rect.height() * t)
    else:  # bottom
        bar = QtCore.QRectF(rect.x(), rect.bottom() - rect.height() * t,
                            rect.width(), rect.height() * t)

    p.save()
    p.setClipPath(path)
    p.setBrush(bar_col)
    p.drawRect(bar)
    p.restore()

    # 外枠
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(frame_col, 1.2))
    p.drawRoundedRect(rect, radius, radius)
    p.end()

    return pm


def dock_icon(side):
    icon = QtGui.QIcon()
    icon.addPixmap(make_dock_icon(side, active=False), QtGui.QIcon.Normal, QtGui.QIcon.Off)
    icon.addPixmap(make_dock_icon(side, active=True), QtGui.QIcon.Normal, QtGui.QIcon.On)
    icon.addPixmap(make_dock_icon(side, active=True), QtGui.QIcon.Active, QtGui.QIcon.On)
    return icon


# ==========================================================================
#  カメラ関連アイコン(コード描画)
# ==========================================================================
def _camera_path(rect):
    u"""カメラ本体(角丸の箱 + 上部のファインダー + レンズ)のパスを返す。"""
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()
    body = QtGui.QPainterPath()
    body.addRoundedRect(QtCore.QRectF(x, y + h * 0.22, w, h * 0.68), h * 0.14, h * 0.14)
    bump = QtGui.QPainterPath()
    bump.addRoundedRect(QtCore.QRectF(x + w * 0.30, y + h * 0.06, w * 0.34, h * 0.26),
                        h * 0.08, h * 0.08)
    body = body.united(bump)
    lens = QtGui.QPainterPath()
    cx, cy, r = x + w * 0.50, y + h * 0.58, h * 0.20
    lens.addEllipse(QtCore.QPointF(cx, cy), r, r)
    return body, lens


def make_camera_pixmap(size=18, color=None):
    u"""コンボボックス用の小さなカメラアイコン。"""
    ratio = 2
    pm = QtGui.QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(float(ratio))
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    col = color or QtGui.QColor(C["textHi"])
    body, lens = _camera_path(QtCore.QRectF(1, 1, size - 2, size - 2))
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(col)
    p.drawPath(body)
    p.setBrush(QtGui.QColor(C["bg"]))
    p.drawPath(lens)
    p.setPen(QtGui.QPen(col, 1.2))
    p.setBrush(QtCore.Qt.NoBrush)
    r = (size - 2) * 0.11
    p.drawEllipse(QtCore.QPointF(1 + (size - 2) * 0.5, 1 + (size - 2) * 0.58), r, r)
    p.end()
    return pm


def make_camera_refresh_icon(size=30, active=False):
    u"""
    「カメラ一覧を読み直す」アイコン: カメラ本体の右上に円環矢印(リフレッシュ)を重ねる。
    彩色は使わず、フロストの明度差だけで状態を表す。
    """
    ratio = 2
    pm = QtGui.QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(float(ratio))
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)

    if active:
        cam_col = _qc(216, 236, 248, 0.95)
        arrow_col = _qc(255, 255, 255, 1.0)
    else:
        cam_col = _qc(199, 211, 234, 0.72)
        arrow_col = _qc(216, 236, 248, 0.92)
    bg = QtGui.QColor(C["bg"])

    # カメラ本体(左下寄り)
    cam_rect = QtCore.QRectF(size * 0.12, size * 0.26, size * 0.60, size * 0.54)
    body, lens = _camera_path(cam_rect)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(cam_col)
    p.drawPath(body)
    p.setBrush(bg)
    p.drawPath(lens)
    p.setPen(QtGui.QPen(cam_col, 1.3))
    p.setBrush(QtCore.Qt.NoBrush)
    r = cam_rect.height() * 0.10
    p.drawEllipse(QtCore.QPointF(cam_rect.x() + cam_rect.width() * 0.5,
                                 cam_rect.y() + cam_rect.height() * 0.58), r, r)

    # リフレッシュ矢印(右上)。地色で縁取りしてカメラから浮かせる
    cx, cy, rr = size * 0.73, size * 0.28, size * 0.165
    arc = QtCore.QRectF(cx - rr, cy - rr, rr * 2, rr * 2)
    start_deg, sweep_deg = 50.0, -265.0          # 時計回りに 265°(上に切れ目、終点に矢じり)
    end = math.radians(start_deg + sweep_deg)
    ex, ey = cx + rr * math.cos(end), cy - rr * math.sin(end)
    # 終点での進行方向(時計回り)。矢じりは進行方向を向く塗りつぶし三角
    dx, dy = math.sin(end), math.cos(end)
    px, py = -dy, dx                         # 法線
    tip = QtCore.QPointF(ex + dx * rr * 0.55, ey + dy * rr * 0.55)
    base = QtCore.QPointF(ex - dx * rr * 0.25, ey - dy * rr * 0.25)
    hw = rr * 0.55
    head = QtGui.QPainterPath()
    head.moveTo(tip)
    head.lineTo(base.x() + px * hw, base.y() + py * hw)
    head.lineTo(base.x() - px * hw, base.y() - py * hw)
    head.closeSubpath()
    for col, width, fill in ((bg, size * 0.14, True), (arrow_col, size * 0.058, True)):
        pen = QtGui.QPen(col, width)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        p.drawArc(arc, int(start_deg * 16), int(sweep_deg * 16))
        p.setPen(QtGui.QPen(col, width * 0.5, QtCore.Qt.SolidLine, QtCore.Qt.RoundCap, QtCore.Qt.RoundJoin))
        p.setBrush(col)
        p.drawPath(head)
    p.end()
    return pm


def camera_refresh_icon():
    icon = QtGui.QIcon()
    icon.addPixmap(make_camera_refresh_icon(active=False), QtGui.QIcon.Normal, QtGui.QIcon.Off)
    icon.addPixmap(make_camera_refresh_icon(active=True), QtGui.QIcon.Active, QtGui.QIcon.Off)
    return icon


def make_arrow_pixmap(direction, size=16, color=None):
    u"""カメラ切り替え用の < / > 。"""
    ratio = 2
    pm = QtGui.QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(float(ratio))
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(color or QtGui.QColor(C["text"]), 2.2)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    p.setPen(pen)
    cx, cy = size / 2.0, size / 2.0
    w, h = 2.8, 4.8
    path = QtGui.QPainterPath()
    if direction == "left":
        path.moveTo(cx + w, cy - h); path.lineTo(cx - w, cy); path.lineTo(cx + w, cy + h)
    else:
        path.moveTo(cx - w, cy - h); path.lineTo(cx + w, cy); path.lineTo(cx - w, cy + h)
    p.drawPath(path)
    p.end()
    return pm


# ==========================================================================
#  トグルスイッチ
# ==========================================================================
class ToggleSwitch(QtWidgets.QCheckBox):
    u"""
    QCheckBox 互換のトグルスイッチ。
    isChecked / setChecked / stateChanged / toggled はそのまま使える。
    ON/OFF は彩色ではなくフロストの明度差で表す。
    """

    TRACK_W = 40
    TRACK_H = 22
    PAD = 2

    def __init__(self, text=u"", parent=None):
        super(ToggleSwitch, self).__init__(text, parent)
        self._knob = 0.0
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setMinimumHeight(self.TRACK_H + 2)

        self._anim = QtCore.QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(130)
        self._anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    # -- アニメーション用プロパティ ------------------------------------
    def _get_knob(self):
        return self._knob

    def _set_knob(self, v):
        self._knob = float(v)
        self.update()

    knobPos = QtCore.Property(float, _get_knob, _set_knob)

    def _animate(self, on):
        try:
            self._anim.stop()
            self._anim.setStartValue(self._knob)
            self._anim.setEndValue(1.0 if on else 0.0)
            self._anim.start()
        except Exception:
            self._knob = 1.0 if on else 0.0
            self.update()

    def showEvent(self, e):
        # コードから setChecked された分を確実に反映
        self._knob = 1.0 if self.isChecked() else 0.0
        super(ToggleSwitch, self).showEvent(e)

    # -- サイズ / 当たり判定 --------------------------------------------
    def sizeHint(self):
        fm = self.fontMetrics()
        try:
            tw = fm.horizontalAdvance(self.text())
        except AttributeError:
            tw = fm.width(self.text())
        w = self.TRACK_W + (10 + tw if self.text() else 0)
        return QtCore.QSize(w, max(self.TRACK_H + 2, fm.height() + 4))

    def hitButton(self, pos):
        return self.rect().contains(pos)

    # -- 描画 -------------------------------------------------------------
    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        enabled = self.isEnabled()
        h = self.TRACK_H
        y = (self.height() - h) / 2.0
        track = QtCore.QRectF(0, y, self.TRACK_W, h)

        if self.isChecked():
            col = _qc(186, 214, 247, 0.34 if enabled else 0.14)
            knob_col = _qc(255, 255, 255, 1.0 if enabled else 0.45)
        else:
            col = _qc(199, 211, 234, 0.10 if enabled else 0.05)
            knob_col = _qc(157, 167, 186, 1.0 if enabled else 0.45)
        p.setPen(QtGui.QPen(_qc(186, 215, 247, 0.12), 1.0))
        p.setBrush(col)
        p.drawRoundedRect(track.adjusted(0.5, 0.5, -0.5, -0.5),
                          h / 2.0, h / 2.0)

        # ノブ
        d = h - self.PAD * 2
        x = track.x() + self.PAD + self._knob * (self.TRACK_W - d - self.PAD * 2)
        knob = QtCore.QRectF(x, y + self.PAD, d, d)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(knob_col)
        p.drawEllipse(knob)

        # テキスト
        if self.text():
            p.setPen(QtGui.QColor(C["text"] if enabled else C["textFaint"]))
            r = QtCore.QRectF(self.TRACK_W + 10, 0,
                              self.width() - self.TRACK_W - 10, self.height())
            p.drawText(r, QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, self.text())
        p.end()


# ==========================================================================
#  カード / セグメンテッドコントロール
# ==========================================================================
class ComboBox(QtWidgets.QComboBox):
    u"""ドロップダウン矢印を自前で描く QComboBox(QSS だけだと矢印が消えるため)。"""

    def __init__(self, parent=None):
        super(ComboBox, self).__init__(parent)
        self.setCursor(QtCore.Qt.PointingHandCursor)

    def paintEvent(self, event):
        super(ComboBox, self).paintEvent(event)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)

        w, h = 8.0, 4.5
        cx = self.width() - 13.0
        cy = self.height() / 2.0 + 0.5
        path = QtGui.QPainterPath()
        path.moveTo(cx - w / 2.0, cy - h / 2.0)
        path.lineTo(cx + w / 2.0, cy - h / 2.0)
        path.lineTo(cx, cy + h / 2.0)
        path.closeSubpath()

        col = QtGui.QColor(C["textDim"] if self.isEnabled() else C["textFaint"])
        p.fillPath(path, col)
        p.end()


def make_title_label(title, name="cardTitle"):
    u"""カード / サブセクションの見出しラベル(全大文字・字間広め)。"""
    lab = QtWidgets.QLabel(title.upper())
    lab.setObjectName(name)
    # QSS の letter-spacing は Qt では効かないのでフォント側で指定する
    try:
        f = lab.font()
        f.setLetterSpacing(QtGui.QFont.PercentageSpacing, 112.0)
        lab.setFont(f)
    except Exception:
        pass
    return lab


class TitleMark(QtWidgets.QWidget):
    u"""見出しの左に置く短い縦バー(見出しの視認性を上げる)。"""

    def __init__(self, parent=None):
        super(TitleMark, self).__init__(parent)
        self.setFixedSize(4, 14)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setPen(QtCore.Qt.NoPen)
        p.setBrush(_qc(186, 214, 247, 0.55))
        p.drawRoundedRect(QtCore.QRectF(self.rect()), 2, 2)
        p.end()


def make_title_row(title, name="cardTitle"):
    u"""[▍TITLE] の見出し行。戻り値 (layout, label)。"""
    row = QtWidgets.QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    row.addWidget(TitleMark(), 0, QtCore.Qt.AlignVCenter)
    lab = make_title_label(title, name)
    row.addWidget(lab, 0, QtCore.Qt.AlignVCenter)
    return row, lab


class Card(QtWidgets.QFrame):
    u"""タイトル付きのカード(Glass Card)。中身は addWidget / addLayout で足す。"""

    def __init__(self, title, parent=None):
        super(Card, self).__init__(parent)
        self.setObjectName("card")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 14)
        outer.setSpacing(10)

        if title:
            row, self._titleLabel = make_title_row(title)
            outer.addLayout(row)
        self.body = outer

        # 影(QGraphicsDropShadowEffect)は付けない。カードごとに 28px ブラーを毎回の再描画で
        # 計算するため、トグルのアニメーションやスライダ操作のたびに重くなる。
        # ほぼ黒の地の上では見た目の差もほとんど無い。

    def addWidget(self, w):
        self.body.addWidget(w)
        return w

    def addLayout(self, l):
        self.body.addLayout(l)
        return l

    def addSeparator(self):
        line = QtWidgets.QFrame()
        line.setObjectName("hline")
        line.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.body.addWidget(line)
        return line


class ChevronButton(QtWidgets.QToolButton):
    u"""折り畳み用の開閉ボタン。フォント任せの ▾ は小さく薄いので、太い線で自前描画する。"""

    SIZE = 22

    def __init__(self, parent=None):
        super(ChevronButton, self).__init__(parent)
        self.setObjectName("chevron")
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setFixedSize(self.SIZE, self.SIZE)
        self._collapsed = False
        self._hover = False
        self.setToolTip(u"折り畳み / 展開")

    def setCollapsed(self, collapsed):
        self._collapsed = bool(collapsed)
        self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super(ChevronButton, self).enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super(ChevronButton, self).leaveEvent(e)

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # 背景の小さな丸(常時うっすら、ホバーで明るく)
        p.setPen(QtGui.QPen(_qc(186, 215, 247, 0.28 if self._hover else 0.16), 1.0))
        p.setBrush(_qc(186, 214, 247, 0.20 if self._hover else 0.10))
        p.drawRoundedRect(r, 6, 6)
        # シェブロン(太線)
        col = QtGui.QColor(C["text"]) if self.isEnabled() else QtGui.QColor(C["textFaint"])
        pen = QtGui.QPen(col, 2.2)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(QtCore.Qt.NoBrush)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        w, h = 4.5, 2.6
        path = QtGui.QPainterPath()
        if self._collapsed:      # 右向き ">"
            path.moveTo(cx - h, cy - w)
            path.lineTo(cx + h, cy)
            path.lineTo(cx - h, cy + w)
        else:                    # 下向き "v"
            path.moveTo(cx - w, cy - h)
            path.lineTo(cx, cy + h)
            path.lineTo(cx + w, cy - h)
        p.drawPath(path)
        p.end()


class CollapsibleCard(Card):
    u"""
    見出し行に折り畳みシェブロンと任意のヘッダウィジェット(一括スイッチ等)を持つカード。
    frameLayout のように見出しクリックで中身(body 以下)を畳める。
    """

    collapsedChanged = QtCore.Signal(bool)

    def __init__(self, title, parent=None):
        super(CollapsibleCard, self).__init__(u"", parent)   # タイトルは自前の行で描く
        self._collapsed = False

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self._chevron = ChevronButton()
        self._chevron.clicked.connect(self.toggleCollapsed)
        head.addWidget(self._chevron)

        head.addWidget(TitleMark(), 0, QtCore.Qt.AlignVCenter)
        self._title = make_title_label(title)
        self._title.setCursor(QtCore.Qt.PointingHandCursor)
        self._title.mousePressEvent = lambda e: self.toggleCollapsed()
        head.addWidget(self._title)
        # 畳んだときに現在値の要約を薄く出す(CollapsibleSection と同じ役割。v1.8.1)
        self._summary = ElidedLabel(u"")
        self._summary.setObjectName("subSummary")
        self._summary.setCursor(QtCore.Qt.PointingHandCursor)
        self._summary.mousePressEvent = lambda e: self.toggleCollapsed()
        head.addWidget(self._summary, 1)
        self._headerSlot = head
        self.body.addLayout(head)

        # 畳む対象は content の中だけ
        self._content = QtWidgets.QWidget()
        self._content.setObjectName("collapsibleContent")
        self._contentLay = QtWidgets.QVBoxLayout(self._content)
        self._contentLay.setContentsMargins(0, 0, 0, 0)
        self._contentLay.setSpacing(10)
        self.body.addWidget(self._content)
        self._updateChevron()

    def setHeaderWidget(self, w):
        self._headerSlot.addWidget(w)
        return w

    def setSummary(self, text):
        self._summary.setText(text or u"")

    # Card 互換: addWidget / addLayout は畳める領域へ
    def addWidget(self, w):
        self._contentLay.addWidget(w)
        return w

    def addLayout(self, l):
        self._contentLay.addLayout(l)
        return l

    def isCollapsed(self):
        return self._collapsed

    def setCollapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._content.setVisible(not collapsed)
        self._updateChevron()
        self.collapsedChanged.emit(collapsed)

    def toggleCollapsed(self):
        self.setCollapsed(not self._collapsed)

    def _updateChevron(self):
        self._chevron.setCollapsed(self._collapsed)


class SubSection(QtWidgets.QFrame):
    u"""カードの中にネストして置く小見出し付きの区画。addWidget / addLayout で中身を足す。"""

    def __init__(self, title, parent=None):
        super(SubSection, self).__init__(parent)
        self.setObjectName("subsection")
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 8, 10, 10)
        outer.setSpacing(8)
        if title:
            outer.addWidget(make_title_label(title, "subTitle"))
        self.body = outer

    def addWidget(self, w):
        self.body.addWidget(w)
        return w

    def addLayout(self, l):
        self.body.addLayout(l)
        return l


class ElidedLabel(QtWidgets.QLabel):
    u"""幅が足りないときは末尾を … で省略するラベル(横幅を要求しない)。"""

    def __init__(self, text=u"", parent=None):
        super(ElidedLabel, self).__init__(text, parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)

    def minimumSizeHint(self):
        return QtCore.QSize(0, super(ElidedLabel, self).minimumSizeHint().height())

    def paintEvent(self, e):
        p = QtGui.QPainter(self)
        fm = self.fontMetrics()
        text = fm.elidedText(self.text(), QtCore.Qt.ElideRight, self.width())
        p.setPen(self.palette().color(QtGui.QPalette.WindowText))
        p.drawText(self.rect(), int(self.alignment()) | QtCore.Qt.AlignVCenter, text)
        p.end()


class CollapsibleSection(SubSection):
    u"""
    折り畳めるサブセクション(frameLayout 相当)。見出し行 = [chevron][TITLE][summary ......]。
    畳んだときは見出しの右に現在値の要約(setSummary)を薄く出せる。
    """

    collapsedChanged = QtCore.Signal(bool)

    def __init__(self, title, parent=None):
        super(CollapsibleSection, self).__init__(u"", parent)
        self._collapsed = False

        head = QtWidgets.QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(8)
        self._chevron = ChevronButton()
        self._chevron.clicked.connect(self.toggleCollapsed)
        head.addWidget(self._chevron)
        self._title = make_title_label(title, "subTitle")
        self._title.setCursor(QtCore.Qt.PointingHandCursor)
        self._title.mousePressEvent = lambda e: self.toggleCollapsed()
        head.addWidget(self._title)
        self._summary = ElidedLabel(u"")
        self._summary.setObjectName("subSummary")
        self._summary.setCursor(QtCore.Qt.PointingHandCursor)
        self._summary.mousePressEvent = lambda e: self.toggleCollapsed()
        head.addWidget(self._summary, 1)
        self.body.addLayout(head)

        self._content = QtWidgets.QWidget()
        self._contentLay = QtWidgets.QVBoxLayout(self._content)
        self._contentLay.setContentsMargins(0, 2, 0, 0)
        self._contentLay.setSpacing(8)
        self.body.addWidget(self._content)
        self._chevron.setCollapsed(False)

    def setSummary(self, text):
        self._summary.setText(text or u"")

    def addWidget(self, w):
        self._contentLay.addWidget(w)
        return w

    def addLayout(self, l):
        self._contentLay.addLayout(l)
        return l

    def isCollapsed(self):
        return self._collapsed

    def setCollapsed(self, collapsed):
        collapsed = bool(collapsed)
        if collapsed == self._collapsed:
            return
        self._collapsed = collapsed
        self._content.setVisible(not collapsed)
        self._chevron.setCollapsed(collapsed)
        self.collapsedChanged.emit(collapsed)

    def toggleCollapsed(self):
        self.setCollapsed(not self._collapsed)


class SegmentedControl(QtWidgets.QWidget):
    u"""[ A ][ B ][ C ] 形式の排他ボタン群(Pill)。"""

    changed = QtCore.Signal(str)

    def __init__(self, items, parent=None):
        u"""items : [(key, label), ...]"""
        super(SegmentedControl, self).__init__(parent)
        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._buttons = {}
        self._group = QtWidgets.QButtonGroup(self)
        self._group.setExclusive(True)

        last = len(items) - 1
        for i, (key, label) in enumerate(items):
            b = QtWidgets.QPushButton(label)
            b.setCheckable(True)
            b.setCursor(QtCore.Qt.PointingHandCursor)
            b.setProperty("seg", "true")
            if i == 0:
                b.setObjectName("segFirst")
            elif i == last:
                b.setObjectName("segLast")
            else:
                b.setObjectName("segMid")
            self._group.addButton(b, i)
            self._buttons[key] = b
            lay.addWidget(b, 1)
            b.clicked.connect(lambda _=False, k=key: self.changed.emit(k))

    def setCurrent(self, key, emit=False):
        b = self._buttons.get(key)
        if b is None:
            return
        b.blockSignals(True)
        b.setChecked(True)
        b.blockSignals(False)
        if emit:
            self.changed.emit(key)

    def current(self):
        for key, b in self._buttons.items():
            if b.isChecked():
                return key
        return None
