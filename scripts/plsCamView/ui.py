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




def _field_label(text, width=80):
    lab = QtWidgets.QLabel(text)
    lab.setObjectName("fieldLabel")
    lab.setMinimumWidth(width)
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
        self.setFixedSize(40, 20)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.clicked.connect(self._pick)
        self._refresh()

    def _refresh(self):
        r, g, b = [int(max(0.0, min(1.0, c)) * 255) for c in self._rgb]
        self.setStyleSheet(u"#plsColorButton{{background:rgb({},{},{});border:1px solid #666;border-radius:3px;"
                           u"padding:0px;min-height:0px;min-width:0px;}}".format(r, g, b))

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
        self.setFixedSize(24, 20)
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(tooltip)
        self.setStyleSheet(u"QToolButton{border:1px solid #555;border-radius:3px;background:#2a2d33;}"
                           u"QToolButton:checked{border:1px solid #8ab4ff;background:#3a4252;}")

    def paintEvent(self, event):
        super(IconToggle, self).paintEvent(event)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        on = self.isChecked()
        col = QtGui.QColor(230, 230, 230) if on else QtGui.QColor(130, 130, 130)
        r = QtCore.QRectF(6.5, 4.5, 11, 11)
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
        lay.setSpacing(8)

        self.label = _field_label(label)

        if decimals:
            self.field = QtWidgets.QDoubleSpinBox()
            self.field.setDecimals(decimals)
            self.field.setSingleStep(0.01)
            self.field.setMinimum(self._min)
            self.field.setMaximum(self._max)
        else:
            self.field = QtWidgets.QSpinBox()
            self.field.setMinimum(int(self._min))
            self.field.setMaximum(int(self._max))
        self.field.setFixedWidth(64)
        self.field.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        self.field.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)

        self.slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider.setMinimumWidth(56)
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
        self._grid.setContentsMargins(0, 2, 0, 2)
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(8)

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
            b.setIconSize(QtCore.QSize(30, 30))
            b.setFixedSize(40, 36)
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
class ToolBox(QtWidgets.QWidget):

    def __init__(self, owner, parent=None):
        super(ToolBox, self).__init__(parent)
        self.setObjectName("plsRoot")
        self.owner = owner
        self._building = True
        self._horizontal = False
        # 言語はカードを作る前に復元する(v1.8.1。既定 system。仕様は i18n.py)
        i18n.set_language(str((owner.data or {}).get("language", "system")))
        self.setStyleSheet(style.stylesheet())

        # 縦: [scroll(全カード)]   上下配置: [scroll(他カード)] [Playblast カード(固定・常に見える)]
        self._outer = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom, self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(8)
        # Maya のホスト(formLayout)へ最小サイズを要求しない。ホストより大きい最小値を返すと、
        # ホストの QLayout と _HostFitter(geometry 合わせ)が互いに上書きし合って Maya が固まる
        self._outer.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        # 最小サイズは明示値だけ(幅 300 / 高さ 1)。Qt は明示値があれば minimumSizeHint を見ないので
        # 中身の最小サイズが Maya 側へ伝わらない。sizePolicy は通常のまま(Ignored にすると paneLayout の
        # 初期配分で幅 0 扱いになり、保存した比率が効かないことがある)
        self.setMinimumSize(300, 1)

        self._scroll = QtWidgets.QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self._outer.addWidget(self._scroll, 1)

        body = QtWidgets.QWidget()
        body.setObjectName("plsRoot")
        self._scroll.setWidget(body)
        self._body = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom, body)
        self._body.setContentsMargins(8, 8, 8, 8)
        self._body.setSpacing(8)

        self.dockPicker = DockPicker()
        self.dockPicker.changed.connect(self._on_dock_changed)

        self._cards = [
            self.dockPicker,
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
            self._body.addWidget(w)
        self._body.addLayout(self._build_language_row())
        self._body.addStretch(1)

        self._building = False

    def _build_language_row(self):
        u"""UI 言語の選択(v1.8.1 本人指示)。選択は保存され、文言は次に開いたときに適用。
        ダイアログ・警告は即時に新しい言語になる。識別子・名前・パスは翻訳しない。"""
        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(8, 0, 8, 0)
        row.setSpacing(8)
        row.addWidget(_field_label(tr(u"Language"), 60))
        self.languageCombo = style.ComboBox()
        for code, label in (("system", tr(u"System")), ("ja", u"日本語"), ("en", u"English")):
            self.languageCombo.addItem(label, code)
        self.languageCombo.setToolTip(tr(u"UI の表示言語。システム = Maya / OS の言語に従う"))
        current = str((self.owner.data or {}).get("language", "system"))
        idx = self.languageCombo.findData(current)
        self.languageCombo.setCurrentIndex(idx if idx >= 0 else 0)
        self.languageCombo.currentIndexChanged.connect(self._on_language)
        row.addWidget(self.languageCombo)
        self._languageNote = _note(u"")
        self._languageNote.setVisible(False)
        row.addWidget(self._languageNote, 1)
        row.addStretch(1)
        return row

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
        self._scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAsNeeded if horizontal else QtCore.Qt.ScrollBarAlwaysOff)
        self.setMinimumSize(1 if horizontal else 300, 1)
        self._reflow(horizontal)
        self._horizontal = horizontal

        # Playblast カードは上下配置ではスクロール領域の外(右端)に固定して、常に押せるようにする
        self._body.removeWidget(self._pbCard)
        self._outer.removeWidget(self._pbCard)
        self.dockPicker.setCompact(horizontal)
        if horizontal:
            self._outer.setDirection(QtWidgets.QBoxLayout.LeftToRight)
            self._outer.setContentsMargins(0, 8, 8, 8)
            self._outer.addWidget(self._pbCard, 0, QtCore.Qt.AlignTop)
            # 高さを抑えるため、入ったときは畳んでおく(必要なら開けばペインが広がる)
            self._effectsCard.setCollapsed(True)
            self.pbSettings.setCollapsed(True)
        else:
            self._outer.setDirection(QtWidgets.QBoxLayout.TopToBottom)
            self._outer.setContentsMargins(0, 0, 0, 0)
            self._body.insertWidget(self._body.count() - 1, self._pbCard)   # stretch の手前

    def is_horizontal(self):
        return bool(getattr(self, "_horizontal", False))

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
            # [ 1 2 3 4  ⟳            ]
            # [配置(横並び)   標準カメラ ]
            g.addWidget(self._countRow, 0, 0, 1, 2)
            g.addWidget(self._layoutBox, 1, 0, QtCore.Qt.AlignLeft)
            g.addWidget(self.startupCamChk, 1, 1, QtCore.Qt.AlignRight)
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
        main, flow = self._pbMainCol, self._pbFlow
        main.removeWidget(self.pbSettings)
        flow.removeWidget(self.pbSettings)
        self._mp4Flow.setDirection(QtWidgets.QBoxLayout.LeftToRight if horizontal
                                   else QtWidgets.QBoxLayout.TopToBottom)
        if horizontal:
            # [Force / 完了後に開く / 実行] | [Settings(畳めば見出しだけ)]
            flow.setDirection(QtWidgets.QBoxLayout.LeftToRight)
            flow.addWidget(self.pbSettings, 1, QtCore.Qt.AlignTop)
            self._mp4Flow.setAlignment(self._mp4Toggles, QtCore.Qt.AlignTop)
        else:
            # Force / Settings / 完了後に開く / 実行(縦)
            flow.setDirection(QtWidgets.QBoxLayout.TopToBottom)
            main.insertWidget(1, self.pbSettings)
            self._mp4Flow.setAlignment(self._mp4Toggles, QtCore.Qt.Alignment())

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
        self.viewCountSeg.setMinimumWidth(184)
        self.viewCountSeg.changed.connect(self._on_view_count)

        # 配置(横並び / 縦並び / グリッド)。上下配置のときは縦に積む(_reflow_views)
        self._layoutBox = QtWidgets.QWidget()
        row = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight, self._layoutBox)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
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
            b.setIconSize(QtCore.QSize(30, 30))
            b.setFixedSize(40, 36)
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
        row.setSpacing(8)
        row.addWidget(self.viewCountSeg, 1)
        self.camRefreshBtn = QtWidgets.QToolButton()
        self.camRefreshBtn.setObjectName("dockBtn")
        self.camRefreshBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.camRefreshBtn.setIcon(style.camera_refresh_icon())
        self.camRefreshBtn.setIconSize(QtCore.QSize(30, 30))
        self.camRefreshBtn.setFixedSize(40, 36)
        self.camRefreshBtn.setToolTip(tr(u"カメラ一覧を読み直す(カメラを追加・削除したとき)"))
        self.camRefreshBtn.clicked.connect(lambda: self.owner.refresh_cameras())
        row.addWidget(self.camRefreshBtn)

        self._viewsGrid = QtWidgets.QGridLayout()
        self._viewsGrid.setContentsMargins(0, 0, 0, 0)
        self._viewsGrid.setHorizontalSpacing(8)
        self._viewsGrid.setVerticalSpacing(10)
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
        self._effectsFlow.setSpacing(10)
        self._effectsFlow.addWidget(self._build_ssao())
        self._effectsFlow.addWidget(self._build_aa())
        card.addLayout(self._effectsFlow)
        card.collapsedChanged.connect(self._on_effects_collapsed)
        self._effectsCard = card
        return card

    def _on_effects_collapsed(self, collapsed):
        if self._building:
            return
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
        row.setSpacing(8)
        self._ssaoSamplesLabel = _field_label(tr(u"Samples"))
        self.ssaoSamples = style.ComboBox()
        for v in vp2.SSAO_SAMPLE_CHOICES:
            self.ssaoSamples.addItem(str(v), v)
        self.ssaoSamples.setFixedWidth(76)
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
        row.setSpacing(8)
        self._aaSamplesLabel = _field_label(tr(u"Sample count"))
        self.aaSamples = style.ComboBox()
        for v in vp2.AA_SAMPLE_CHOICES:
            self.aaSamples.addItem(str(v), v)
        self.aaSamples.setFixedWidth(76)
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
        row.setSpacing(12)
        for c in (self.jointChk, self.curveChk):
            c.toggled.connect(self._on_show)
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

    def _on_show(self, *_):
        u"""Joint / NurbsCurve のスイッチ。該当フラグだけを切り替える。"""
        if self._building:
            return
        d = self.owner.data
        d["showJoints"] = self.jointChk.isChecked()
        d["showNurbsCurves"] = self.curveChk.isChecked()
        self.owner.apply_show_extras()

    def set_show_switches(self, joints, curves):
        u"""modelEditor の実値をスイッチに反映する(シグナルは飛ばさない)。"""
        self._building = True
        try:
            self.jointChk.setChecked(bool(joints))
            self.curveChk.setChecked(bool(curves))
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
            row.setSpacing(8)
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
            pct.label.setMinimumWidth(48)
            pct.field.setSuffix(u" %")
            pct.field.setFixedWidth(72)
            st_ = IconToggle("stroke", tr(u"線(1px、Dashed で破線)"))
            fl = IconToggle("fill", tr(u"塗り: このゲートの外側(レゾリューションゲート内)を色で覆う"))
            col = ColorButton(_defcol[k])
            op = QtWidgets.QDoubleSpinBox()
            op.setDecimals(2)
            op.setRange(0.0, 1.0)
            op.setSingleStep(0.05)
            op.setFixedWidth(64)
            op.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            op.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            op.setToolTip(tr(u"塗りの不透明度"))
            st_.toggled.connect(self._on_gate)
            fl.toggled.connect(self._on_gate)
            col.colorChanged.connect(self._on_gate)
            op.valueChanged.connect(self._on_gate)
            r1 = QtWidgets.QHBoxLayout()
            r1.setSpacing(6)
            r1.addWidget(en)
            r1.addWidget(pct, 1)
            r1.addWidget(st_)
            r1.addWidget(fl)
            r1.addWidget(col)
            r1.addWidget(op)
            sec2.addLayout(r1)
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
        row.setSpacing(8)
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
        (本人指示。Gate を畳んでも Guides に届く)。設定キー・描画の意味は従来のまま。"""
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
        self.guideRatio.setFixedWidth(110)
        self.guideThirdsColor = ColorButton((0.3, 0.5, 1.0))
        self.guideGridColor = ColorButton((1.0, 0.25, 0.25))
        self.guideArmatureColor = ColorButton((1.0, 0.9, 0.2))
        # 1 行目: [三分割 ■][比率グリッド ■][アーマチュア ■][中心]   2 行目: [Ratio][Fit to]   以下 Opacity / Width
        # 2 列のグリッド(1 行に 4 つ並べるとツールボックスの最小幅を超えて右端が見切れる)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        grid.setContentsMargins(0, 0, 0, 0)
        cells = ((self.guideThirds, self.guideThirdsColor), (self.guideGrid, self.guideGridColor),
                 (self.guideArmature, self.guideArmatureColor), (self.guideCenter, None))
        for i, (tgl, btn) in enumerate(cells):
            cell = QtWidgets.QHBoxLayout()
            cell.setSpacing(6)
            cell.addWidget(tgl)
            if btn is not None:
                cell.addWidget(btn)
                btn.colorChanged.connect(self._on_guide)
            cell.addStretch(1)
            grid.addLayout(cell, i // 2, i % 2)
            tgl.toggled.connect(self._on_guide)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        card.addLayout(grid)
        self.guideRatio.currentIndexChanged.connect(self._on_guide)
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(_field_label(tr(u"Ratio"), 48))
        row.addWidget(self.guideRatio)
        row.addSpacing(8)
        row.addWidget(_field_label(tr(u"Fit to"), 44))
        self.guideFit = style.ComboBox()
        for v, label in ((0, tr(u"レゾリューションゲート")), (1, tr(u"内側ゲート 1")), (2, tr(u"内側ゲート 2")),
                         (3, tr(u"内側ゲート 3")), (4, tr(u"ビュー全体"))):
            self.guideFit.addItem(label, v)
        self.guideFit.setFixedWidth(170)
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
        # 縦: [Force][Settings][完了後に開く][実行]  横(上下配置): [main 列] | [Settings]
        self._pbFlow = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom)
        self._pbFlow.setContentsMargins(0, 0, 0, 0)
        self._pbFlow.setSpacing(10)
        card.addLayout(self._pbFlow)
        self._pbMain = QtWidgets.QWidget()
        self._pbMainCol = QtWidgets.QVBoxLayout(self._pbMain)
        self._pbMainCol.setContentsMargins(0, 0, 0, 0)
        self._pbMainCol.setSpacing(10)
        self._pbFlow.addWidget(self._pbMain)

        self.forceChk = style.ToggleSwitch(tr(u"Force Playblast Target"))
        self.forceChk.setToolTip(
            tr(u"Force Playblast Target: ON の間、このビューがアクティブでなくても\n"
               u"Maya 標準/外部のPlayblastは最後に追加した対象1つ。複数出力はこのツールの実行ボタン。"))
        self.forceChk.toggled.connect(self._on_force)
        self._pbMainCol.addWidget(self.forceChk)

        multi_row = QtWidgets.QHBoxLayout()
        self.multiEnabled = style.ToggleSwitch(tr(u"Multi"))
        self.multiEnabled.setToolTip(tr(u"ONで複数の対象を選択。OFFでは最後に選択した対象1つに戻します。"))
        multi_row.addWidget(self.multiEnabled)
        self.multiEnabled.toggled.connect(self._on_multi_option)
        self.multiCombine = style.ToggleSwitch(tr(u"合成"))
        self.multiCombine.setToolTip(tr(u"選択した複数ビューの位置・比率で動画を合成（_Multi.mp4）。画像は引き伸ばしません。"))
        self.multiKeep = style.ToggleSwitch(tr(u"個別保持"))
        self.multiKeep.setToolTip(tr(u"合成と一緒に各カメラの出力も保存。合成OFFなら常に個別保存。失敗時は途中出力を保全。"))
        multi_row.addWidget(self.multiCombine)
        multi_row.addWidget(self.multiKeep)
        multi_row.addStretch(1)
        self._pbMainCol.addLayout(multi_row)
        self.multiCombine.toggled.connect(self._on_multi_option)
        self.multiKeep.toggled.connect(self._on_multi_option)

        # 状態表示は持たない(Script Editor に出す)。互換のため文字列だけ保持する。
        self._forceStateText = u""
        self._targetText = u""

        # ---- 設定(折り畳み。決めたら基本は閉じておく想定) --------------------
        self.pbSettings = style.CollapsibleSection(tr(u"Settings"))
        self.pbSettings.collapsedChanged.connect(self._on_pb_settings_collapsed)
        self._pbMainCol.addWidget(self.pbSettings)

        # ---- 出力形式 -----------------------------------------------------
        self.outputSeg = style.SegmentedControl(
            [("maya", tr(u"Maya 標準")), ("mp4", u"MP4")])
        self.outputSeg.changed.connect(self._on_output_mode)
        self.pbSettings.addWidget(self.outputSeg)

        # ---- 書き出し設定(両モード共通。CRF / プリセット / PNG は MP4 のみ) --
        self.mp4Box = QtWidgets.QWidget()
        self._mp4Flow = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.TopToBottom, self.mp4Box)
        self._mp4Flow.setContentsMargins(0, 0, 0, 0)
        self._mp4Flow.setSpacing(10)
        self._mp4Grid = QtWidgets.QWidget()
        self._mp4Flow.addWidget(self._mp4Grid)
        grid = QtWidgets.QGridLayout(self._mp4Grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        def _lab(text):
            lab = QtWidgets.QLabel(text)
            lab.setObjectName("fieldLabel")
            lab.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            return lab

        def _narrow(w):
            w.setMinimumWidth(60)
            w.setSizePolicy(QtWidgets.QSizePolicy.Expanding,
                            QtWidgets.QSizePolicy.Fixed)
            w.setButtonSymbols(QtWidgets.QAbstractSpinBox.NoButtons)
            w.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            return w

        r = 0
        self.mp4Width = _narrow(QtWidgets.QSpinBox())
        self.mp4Width.setRange(16, 16384)
        self.mp4Height = _narrow(QtWidgets.QSpinBox())
        self.mp4Height.setRange(16, 16384)
        grid.addWidget(_lab(tr(u"幅")), r, 0)
        grid.addWidget(self.mp4Width, r, 1)
        grid.addWidget(_lab(tr(u"高さ")), r, 2)
        grid.addWidget(self.mp4Height, r, 3)

        r += 1
        self.mp4Fps = _narrow(QtWidgets.QDoubleSpinBox())
        self.mp4Fps.setRange(1.0, 240.0)
        self.mp4Fps.setDecimals(2)
        self.mp4UseSceneFps = style.ToggleSwitch(tr(u"シーン"))
        self.mp4UseSceneFps.setToolTip(tr(u"ON: シーンの時間単位から FPS を決める"))
        grid.addWidget(_lab(u"FPS"), r, 0)
        grid.addWidget(self.mp4Fps, r, 1)
        grid.addWidget(self.mp4UseSceneFps, r, 2, 1, 2)

        r += 1
        self.mp4Quality = _narrow(QtWidgets.QSpinBox())
        self.mp4Quality.setRange(1, 100)
        self.mp4Quality.setToolTip(tr(u"playblast の quality(1-100)"))
        self.mp4Crf = _narrow(QtWidgets.QSpinBox())
        self.mp4Crf.setRange(0, 51)
        self.mp4Crf.setToolTip(tr(u"H.264 品質(0-51)。低いほど高画質。18-23 推奨(MP4 のみ)"))
        self._crfLabel = _lab(u"CRF")
        grid.addWidget(_lab(tr(u"品質")), r, 0)
        grid.addWidget(self.mp4Quality, r, 1)
        grid.addWidget(self._crfLabel, r, 2)
        grid.addWidget(self.mp4Crf, r, 3)

        r += 1
        self.mp4Preset = style.ComboBox()
        for name in mp4blast.PRESETS:
            self.mp4Preset.addItem(name)
        self.mp4Preset.setToolTip(tr(u"x264 プリセット。遅いほど同じ CRF で小さくなる(MP4 のみ)"))
        self.mp4Preset.setSizeAdjustPolicy(
            QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.mp4Preset.setMinimumContentsLength(6)
        self._presetLabel = _lab(tr(u"プリセット"))
        grid.addWidget(self._presetLabel, r, 0, 1, 2)
        grid.addWidget(self.mp4Preset, r, 2, 1, 2)

        r += 1
        self.mp4Output = QtWidgets.QLineEdit()
        self.mp4Output.setPlaceholderText(tr(u"自動"))
        self.mp4Output.setToolTip(tr(u"出力先。空なら <プロジェクト>/movies/<シーン>_<カメラ>"))
        self.mp4OutputBtn = QtWidgets.QPushButton(u"…")
        self.mp4OutputBtn.setFixedWidth(40)
        self.mp4OutputBtn.setStyleSheet("padding: 6px 2px;")
        self.mp4OutputBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.mp4OutputBtn.setToolTip(tr(u"出力先を選択"))
        self.mp4OutputBtn.clicked.connect(self._browse_output)
        outRow = QtWidgets.QHBoxLayout()
        outRow.setSpacing(6)
        outRow.addWidget(self.mp4Output, 1)
        outRow.addWidget(self.mp4OutputBtn)
        grid.addWidget(_lab(tr(u"出力先")), r, 0)
        grid.addLayout(outRow, r, 1, 1, 3)

        # トグル群(上下配置では数値グリッドの右に並ぶ)
        self._mp4Toggles = QtWidgets.QWidget()
        tog = QtWidgets.QVBoxLayout(self._mp4Toggles)
        tog.setContentsMargins(0, 0, 0, 0)
        tog.setSpacing(8)
        self.mp4FromRender = style.ToggleSwitch(tr(u"From Render Settings"))
        self.mp4FromRender.setToolTip(
            tr(u"Maya 標準 Playblast の「Display size: From Render Settings」と同じ。\n"
               u"幅/高さをレンダー設定の解像度にし、オーバースキャン 1.0・パン/ズーム無効で書き出す\n"
               u"= レゾリューションゲート(最終描画範囲)ぴったりの動画。幅/高さの欄は無視される。"))
        tog.addWidget(self.mp4FromRender)
        self.mp4Ornaments = style.ToggleSwitch(tr(u"装飾 (HUD)"))
        self.mp4Ornaments.setToolTip(tr(u"showOrnaments: HUD やカメラ名などを写す"))
        tog.addWidget(self.mp4Ornaments)
        self.mp4OffScreen = style.ToggleSwitch(tr(u"オフスクリーン"))
        self.mp4OffScreen.setToolTip(tr(u"offScreen: 他ウィンドウの重なりに影響されない"))
        tog.addWidget(self.mp4OffScreen)
        self.mp4Optimize = style.ToggleSwitch(tr(u"ビューポート最適化"))
        self.mp4Optimize.setToolTip(
            tr(u"書き出し中のみ、画角をレンダー枠に固定 / Polygon のみ表示 /\n"
               u"Use All Lights / SSAO・線 AA・MSAA を ON にし、完了後に元へ戻します。"))
        tog.addWidget(self.mp4Optimize)
        self.mp4KeepFrames = style.ToggleSwitch(tr(u"PNG を残す"))
        self.mp4KeepFrames.setToolTip(tr(u"中間の PNG 連番(一時フォルダ)を削除しない(MP4 のみ)"))
        tog.addWidget(self.mp4KeepFrames)
        self._mp4Flow.addWidget(self._mp4Toggles)

        self.pbSettings.addWidget(self.mp4Box)

        # ---- 常に見えるもの: 完了後に開く ------------------------------------
        self.mp4OpenAfter = style.ToggleSwitch(tr(u"完了後に開く"))
        self._pbMainCol.addWidget(self.mp4OpenAfter)

        # ---- 実行ボタン ---------------------------------------------------
        self.pbBtn = QtWidgets.QPushButton(tr(u"Playblast 実行"))
        self.pbBtn.setObjectName("primary")
        self.pbBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.pbBtn.clicked.connect(lambda: self.owner.do_playblast(False))
        self._pbMainCol.addWidget(self.pbBtn)
        self._pbMainCol.addStretch(1)
        # オプションボックスのボタンは UI から外してある(Maya 標準の形式・圧縮は Maya の設定に従う)

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

        return card

    def _on_pb_settings_collapsed(self, collapsed):
        if self._building:
            return
        self.owner.data["playblastSettingsCollapsed"] = bool(collapsed)
        self.owner.save_settings()
        self._after_collapse_change()

    def _update_pb_summary(self):
        u"""Settings を畳んだときに見出しの右へ出す要約(形式 / 解像度 / FPS)。"""
        try:
            mode = self.outputSeg.current() or "maya"
            fps = u"scene" if self.mp4UseSceneFps.isChecked() else u"{:g}".format(self.mp4Fps.value())
            if self.mp4FromRender.isChecked():
                size = u"Render Settings"
                try:
                    size = u"{}×{} (RS)".format(*mp4blast.render_settings_size())
                except Exception:
                    pass
            else:
                size = u"{}×{}".format(self.mp4Width.value(), self.mp4Height.value())
            text = u"{}  {}  {} fps".format(u"MP4" if mode == "mp4" else u"Maya", size, fps)
            if mode == "mp4":
                text += u"  CRF {}".format(self.mp4Crf.value())
            self.pbSettings.setSummary(text)
        except Exception:
            pass

    def _on_multi_option(self, *_):
        multi = self.multiEnabled.isChecked()
        self.multiCombine.setVisible(multi)
        self.multiKeep.setVisible(multi and self.multiCombine.isChecked())
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
        self.pbBtn.setText(tr(u"MP4 に書き出し") if is_mp4 else tr(u"Playblast 実行"))

    def _update_mp4_enabled(self, *_):
        on = not self.mp4UseSceneFps.isChecked()
        self.mp4Fps.setEnabled(on)
        rs = not self.mp4FromRender.isChecked()
        self.mp4Width.setEnabled(rs)
        self.mp4Height.setEnabled(rs)

    def mp4_options(self):
        u"""UI の値を mp4blast.run() のキーワード引数にして返す。"""
        return dict(
            width=self.mp4Width.value(),
            height=self.mp4Height.value(),
            fps=None if self.mp4UseSceneFps.isChecked() else self.mp4Fps.value(),
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
        )

    def _on_mp4_option(self, *_):
        self._update_pb_summary()
        if self._building:
            return
        d = self.owner.data
        d["mp4Width"] = self.mp4Width.value()
        d["mp4Height"] = self.mp4Height.value()
        d["mp4Fps"] = self.mp4Fps.value()
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

            self.effectsMaster.setChecked(bool(data.get("effectsMaster", True)))
            self._effectsCard.setCollapsed(bool(data.get("effectsCollapsed", False)))
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

            self.showSeg.setCurrent(data.get("showPreset", "all"))
            self.jointChk.setChecked(bool(data.get("showJoints", False)))
            self.curveChk.setChecked(bool(data.get("showNurbsCurves", False)))

            self.forceChk.setChecked(bool(data.get("forcePlayblastTarget", False)))

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
        finally:
            self._building = False
        self._update_pb_summary()
        self._update_mp4_enabled()
        self._update_gate_enabled()
        self._update_ssao_enabled()
        on = self.aaEnable.isChecked()
        self.aaSamples.setEnabled(on)
        self._aaSamplesLabel.setEnabled(on)
        self._update_effects_master()

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
            v.bar.set_cameras([v.bar.combo.itemText(i) for i in range(v.bar.combo.count())], cam)
            self.data["camera"] = cam
            self.apply_view_settings(v)
            if save:
                self.save_settings()

    # ------------------------------------------------------------------
    #  ViewManager からの通知
    # ------------------------------------------------------------------
    def apply_view_settings(self, view):
        u"""1 つのビューに Show / Shadow / ゲートオーバーレイを適用する(ビュー作成・カメラ切替時)。"""
        vpt = view.viewport if view is not None else None
        if vpt is None or not hasattr(vpt, "apply_show"):
            return
        d = self.data
        try:
            vpt.apply_show(d.get("showPreset", "all"),
                           {"showJoints": d.get("showJoints", False),
                            "showNurbsCurves": d.get("showNurbsCurves", False)})
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
    def apply_show(self, save=True):
        u"""プリセット -> 追加スイッチ の順に適用する(起動時の状態復元用)。"""
        d = self.data
        extras = {"showJoints": d.get("showJoints", False),
                  "showNurbsCurves": d.get("showNurbsCurves", False)}
        for vpt in self.views.each_viewport():
            vpt.apply_show(d.get("showPreset", "all"), extras)
        if save:
            self.save_settings()

    def apply_show_preset(self, key, save=True):
        u"""
        プリセットのみを適用する。
        プリセットは Joint / NurbsCurve スイッチより優先されるため、
        適用後は modelEditor の実値をスイッチへ反映する。
        """
        for vpt in self.views.each_viewport():
            vpt.apply_show(key, None)
        ref = self.viewport
        joints = ref.get_show_flag("joints") if ref else None
        curves = ref.get_show_flag("nurbsCurves") if ref else None
        if joints is None:
            joints = (key == "all")
        if curves is None:
            curves = (key == "all")
        self.data["showJoints"] = bool(joints)
        self.data["showNurbsCurves"] = bool(curves)
        self.toolbox.set_show_switches(joints, curves)
        if save:
            self.save_settings()

    def apply_show_extras(self, save=True):
        u"""Joint / NurbsCurve のスイッチだけを反映する(プリセットは触らない)。"""
        d = self.data
        extras = {"showJoints": d.get("showJoints", False),
                  "showNurbsCurves": d.get("showNurbsCurves", False)}
        for vpt in self.views.each_viewport():
            vpt.apply_show_extras(extras)
        if save:
            self.save_settings()

    def apply_shadows(self, save=True):
        for vpt in self.views.each_viewport():
            vpt.set_shadows(self.data.get("shadows", False))
        if save:
            self.save_settings()

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

    def _on_scene_changed(self, *_):
        if self._closing or not self.exists():
            return
        try:
            self.refresh_cameras()
            self.apply_show(save=False)
            self.apply_shadows(save=False)
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
