# -*- coding: utf-8 -*-
u"""
plsCamView.views
================
複数ビュー(最大 4)の管理。

    ViewSlot   … 1 ビュー = [カメラバー(Qt)] + [modelPanel(Maya)] を Maya の formLayout に収めたもの。
                 メインウィンドウのビュー領域(paneLayout)に「ドック」されるか、
                 独立した cmds.window に「ポップアウト」されるかのどちらかの状態を取る。
    CameraBar  … 各ビューの上に付くバー。[● PLAYBLAST(対象)] [< 📷 カメラ名 >] [View N / ↗ ポップアウト / ⭲ 再ドッキング]

レイアウト(ドック中のビューにのみ適用):
    horizontal … 横並び   (Maya の paneLayout では vertical2/3/4 = 縦の仕切りで左右に分割)
    vertical   … 縦並び   (horizontal2/3/4)
    grid       … グリッド (2: 横並び / 3: top3 / 4: quad)

ポップアウト / 再ドッキングは modelPanel を「複製して作り直す」方式。
modelPanel は作成後に親を変えられない(-parent は create 専用)ので、
`modelPanel -copy` で表示設定ごと新しい親に作り直し、古い方を消す。
Qt のカメラバーは同じウィジェットを新しいホストへ付け替えて使い回す。
"""
from __future__ import absolute_import

from .qt import QtCore, QtGui, QtWidgets, attach_widget, to_qwidget
from . import viewport as vp
from . import style
from .i18n import tr

try:
    from maya import cmds
except Exception:
    cmds = None

MAX_VIEWS = 4
BAR_HEIGHT = 34

LAYOUT_KEYS = ("horizontal", "vertical", "grid")

# (ドック中のビュー数, レイアウト) -> paneLayout の configuration
_CONFIGS = {
    (1, "horizontal"): "single",  (1, "vertical"): "single",    (1, "grid"): "single",
    (2, "horizontal"): "vertical2", (2, "vertical"): "horizontal2", (2, "grid"): "vertical2",
    (3, "horizontal"): "vertical3", (3, "vertical"): "horizontal3", (3, "grid"): "top3",
    (4, "horizontal"): "vertical4", (4, "vertical"): "horizontal4", (4, "grid"): "quad",
}


def pane_configuration(count, layout):
    if count <= 0:
        return "single"
    count = min(count, MAX_VIEWS)
    if layout not in LAYOUT_KEYS:
        layout = "horizontal"
    return _CONFIGS[(count, layout)]


# ==========================================================================
#  レイアウトアイコン(コード描画)
# ==========================================================================
def make_layout_icon(kind, size=30, active=False):
    ratio = 2
    pm = QtGui.QPixmap(size * ratio, size * ratio)
    pm.setDevicePixelRatio(float(ratio))
    pm.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)

    if active:
        frame_col = QtGui.QColor(216, 236, 248, 217)
        cell_col = QtGui.QColor(186, 214, 247, 150)
    else:
        frame_col = QtGui.QColor(157, 167, 186, 178)
        cell_col = QtGui.QColor(199, 211, 234, 70)

    m = 4.0
    rect = QtCore.QRectF(m, m + 1.5, size - m * 2, size - (m + 1.5) * 2)
    gap = 2.0
    cells = []
    if kind == "horizontal":
        w = (rect.width() - gap) / 2.0
        cells = [QtCore.QRectF(rect.x(), rect.y(), w, rect.height()),
                 QtCore.QRectF(rect.x() + w + gap, rect.y(), w, rect.height())]
    elif kind == "vertical":
        h = (rect.height() - gap) / 2.0
        cells = [QtCore.QRectF(rect.x(), rect.y(), rect.width(), h),
                 QtCore.QRectF(rect.x(), rect.y() + h + gap, rect.width(), h)]
    else:
        w = (rect.width() - gap) / 2.0
        h = (rect.height() - gap) / 2.0
        cells = [QtCore.QRectF(rect.x(), rect.y(), w, h),
                 QtCore.QRectF(rect.x() + w + gap, rect.y(), w, h),
                 QtCore.QRectF(rect.x(), rect.y() + h + gap, w, h),
                 QtCore.QRectF(rect.x() + w + gap, rect.y() + h + gap, w, h)]

    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(cell_col)
    for c in cells:
        p.drawRoundedRect(c, 2.0, 2.0)
    p.setBrush(QtCore.Qt.NoBrush)
    p.setPen(QtGui.QPen(frame_col, 1.2))
    p.drawRoundedRect(rect, 3.5, 3.5)
    p.end()
    return pm


def layout_icon(kind):
    icon = QtGui.QIcon()
    icon.addPixmap(make_layout_icon(kind, active=False), QtGui.QIcon.Normal, QtGui.QIcon.Off)
    icon.addPixmap(make_layout_icon(kind, active=True), QtGui.QIcon.Normal, QtGui.QIcon.On)
    icon.addPixmap(make_layout_icon(kind, active=True), QtGui.QIcon.Active, QtGui.QIcon.On)
    return icon


# ==========================================================================
#  カメラバー
# ==========================================================================
class CameraCombo(style.ComboBox):
    u"""カメラ選択用の大きめコンボ。[📷] カメラ名(中央) [▾] を自前描画する。"""

    def __init__(self, parent=None):
        super(CameraCombo, self).__init__(parent)
        self.setObjectName("camCombo")
        self._icon = style.make_camera_pixmap(18)
        self._hover = False
        self.setMinimumWidth(0)
        self.setMaximumWidth(320)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)
        self.setFixedHeight(26)
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self._prefWidth = 180
        f = self.font()
        f.setPixelSize(15)
        f.setBold(True)
        self.setFont(f)

    def setPreferredWidth(self, w):
        self._prefWidth = int(w)
        self.updateGeometry()

    def sizeHint(self):
        return QtCore.QSize(self._prefWidth, 26)

    def minimumSizeHint(self):
        return QtCore.QSize(0, 26)

    def enterEvent(self, e):
        self._hover = True
        self.update()
        super(CameraCombo, self).enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False
        self.update()
        super(CameraCombo, self).leaveEvent(e)

    def paintEvent(self, event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QtGui.QPen(style._qc(186, 215, 247, 0.30 if self._hover else 0.18), 1.0))
        p.setBrush(style._qc(186, 214, 247, 0.16 if self._hover else 0.10))
        p.drawRoundedRect(r, 13, 13)

        # カメラアイコン(左)
        ih = self._icon.height() / self._icon.devicePixelRatio()
        p.drawPixmap(QtCore.QPointF(10, (self.height() - ih) / 2.0), self._icon)

        # 名前(中央)
        name = self.currentText().split("|")[-1] or tr(u"(カメラなし)")
        text_rect = QtCore.QRectF(30, 0, self.width() - 30 - 26, self.height())
        p.setPen(QtGui.QColor(style.C["textHi"] if self.isEnabled() else style.C["textFaint"]))
        p.setFont(self.font())
        fm = QtGui.QFontMetrics(self.font())
        name = fm.elidedText(name, QtCore.Qt.ElideMiddle, int(text_rect.width()))
        p.drawText(text_rect, QtCore.Qt.AlignCenter, name)

        # ▾(右)
        w, h = 9.0, 5.0
        cx = self.width() - 15.0
        cy = self.height() / 2.0 + 0.5
        path = QtGui.QPainterPath()
        path.moveTo(cx - w / 2.0, cy - h / 2.0)
        path.lineTo(cx + w / 2.0, cy - h / 2.0)
        path.lineTo(cx, cy + h / 2.0)
        path.closeSubpath()
        p.fillPath(path, QtGui.QColor(style.C["text"]))
        p.end()


class CameraBar(QtWidgets.QWidget):
    u"""
    各ビューの上に付くバー。
        左  : [● PLAYBLAST] … このビューを Playblast の対象に追加/解除する。ON のとき Void Violet
        中央: [<] [📷 カメラ名 ▾] [>] … カメラ切り替え(コンボ or 前後ボタン)
        右  : View N  [↗ / ⭲] … ポップアウト / 再ドッキング
    左右のブロックは同じ伸縮率(stretch 1)にして、カメラ名がビューの中央に来るようにしている。
    ※ バーは最小幅を Maya 側へ要求しない(SetNoConstraint)。Qt 子の最小幅が Maya の formLayout/paneLayout
      より大きいと、Maya がレイアウトを収束できずフリーズするため。ビューが狭いときは端が切れるだけにする。
    """

    cameraChanged = QtCore.Signal(str)
    targetClicked = QtCore.Signal()
    popClicked = QtCore.Signal()

    def __init__(self, parent=None):
        super(CameraBar, self).__init__(parent)
        self.setObjectName("plsRoot")
        self.setStyleSheet(style.stylesheet() + u"""
            QWidget#plsCamBar { background: %(bg)s; }
            QPushButton#targetBtn {
                background: transparent; border: 1px solid %(border)s; border-radius: 12px;
                padding: 0px 10px 0px 8px; color: %(textFaint)s; font-size: 12px; font-weight: 700;
                min-height: 0px;
            }
            QPushButton#targetBtn:hover { background: %(frost12)s; color: %(textHi)s; }
            QPushButton#targetBtn:checked {
                background: %(accentDeep)s; border: 1px solid rgba(186, 215, 247, 0.30);
                color: #ffffff;
            }
            QPushButton#targetBtn:checked:hover { background: %(accent)s; }
            QToolButton#popBtn {
                background: transparent; border: 1px solid %(border)s; border-radius: 12px;
                padding: 0px; color: %(textDim)s; font-size: 14px;
            }
            QToolButton#popBtn:hover { background: %(buttonHover)s; color: #ffffff; }
            QToolButton#camStep {
                background: transparent; border: 1px solid %(border)s; border-radius: 12px;
                padding: 0px;
            }
            QToolButton#camStep:hover { background: %(buttonHover)s; }
            QToolButton#camStep:disabled { border-color: %(borderSoft)s; }
            QLabel#viewNo { color: %(textFaint)s; font-size: 12px; font-weight: 600;
                            background: transparent; border: none; }
        """ % style.C)
        self._building = False
        self._popped = False

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(6, 3, 6, 3)
        lay.setSpacing(6)
        lay.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        self.setMinimumSize(0, 0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)

        # ---- 左: Playblast 対象 ----
        left = QtWidgets.QWidget()
        left.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        ll = QtWidgets.QHBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        ll.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        self.targetBtn = QtWidgets.QPushButton(u"\u25cf  PLAYBLAST")
        self.targetBtn.setObjectName("targetBtn")
        self.targetBtn.setCheckable(True)
        self.targetBtn.setFixedHeight(26)
        self.targetBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.targetBtn.setToolTip(tr(u"Playblast 対象を追加・解除（複数選択）\n紫 = 選択中。最後の1つは解除しません。"))
        self.targetBtn.clicked.connect(self._on_target)
        f = self.targetBtn.font()
        f.setPixelSize(12)
        f.setBold(True)
        self.targetBtn.setFont(f)
        btn_w = QtGui.QFontMetrics(f).horizontalAdvance(self.targetBtn.text()) + 30
        self.targetBtn.setFixedWidth(btn_w)
        ll.addWidget(self.targetBtn)
        ll.addStretch(1)
        left.setMinimumWidth(btn_w)   # 狭くてもボタンは残す(削られるのはカメラ名と VIEW N)
        lay.addWidget(left, 1)

        # ---- 中央: カメラ ----
        self.prevBtn = QtWidgets.QToolButton()
        self.prevBtn.setObjectName("camStep")
        self.prevBtn.setFixedSize(26, 26)
        self.prevBtn.setIcon(QtGui.QIcon(style.make_arrow_pixmap("left")))
        self.prevBtn.setIconSize(QtCore.QSize(16, 16))
        self.prevBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.prevBtn.setToolTip(tr(u"前のカメラ"))
        self.prevBtn.clicked.connect(lambda: self.step_camera(-1))
        lay.addWidget(self.prevBtn)

        self.combo = CameraCombo()
        self.combo.setToolTip(tr(u"このビューのカメラを切り替える"))
        self.combo.currentIndexChanged.connect(self._on_camera)
        lay.addWidget(self.combo)

        self.nextBtn = QtWidgets.QToolButton()
        self.nextBtn.setObjectName("camStep")
        self.nextBtn.setFixedSize(26, 26)
        self.nextBtn.setIcon(QtGui.QIcon(style.make_arrow_pixmap("right")))
        self.nextBtn.setIconSize(QtCore.QSize(16, 16))
        self.nextBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.nextBtn.setToolTip(tr(u"次のカメラ"))
        self.nextBtn.clicked.connect(lambda: self.step_camera(1))
        lay.addWidget(self.nextBtn)

        # ---- 右: View 番号 / ポップアウト ----
        right = QtWidgets.QWidget()
        right.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        rl = QtWidgets.QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        rl.setSizeConstraint(QtWidgets.QLayout.SetNoConstraint)
        self.label = style.ElidedLabel(u"VIEW 1")
        self.label.setObjectName("viewNo")
        self.label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        rl.addWidget(self.label, 1)
        self.popBtn = QtWidgets.QToolButton()
        self.popBtn.setObjectName("popBtn")
        self.popBtn.setFixedSize(26, 26)
        self.popBtn.setCursor(QtCore.Qt.PointingHandCursor)
        self.popBtn.clicked.connect(self.popClicked.emit)
        rl.addWidget(self.popBtn)
        right.setMinimumWidth(26)
        lay.addWidget(right, 1)
        self.set_popped(False)

        self.setFixedHeight(BAR_HEIGHT)

    # ------------------------------------------------------------------
    def _on_target(self, *_):
        self.targetClicked.emit()

    def _on_camera(self, *_):
        if self._building:
            return
        cam = self.combo.currentText()
        if cam:
            self.cameraChanged.emit(cam)

    def step_camera(self, delta):
        n = self.combo.count()
        if n <= 1:
            return
        self.combo.setCurrentIndex((self.combo.currentIndex() + delta) % n)

    def set_label(self, text):
        self.label.setText(text.upper())

    def set_target(self, on, multi=False):
        self.targetBtn.blockSignals(True)
        self.targetBtn.setChecked(bool(on))
        self.targetBtn.blockSignals(False)
        if multi:
            tip = (tr(u"Playblast 対象から解除（最後の1つは保持）") if on else
                   tr(u"Playblast 対象へ追加（複数選択）"))
        else:
            tip = tr(u"Playblast 対象（1つ選択）") if on else tr(u"このビューをPlayblast対象にする")
        self.targetBtn.setToolTip(tip)

    def set_popped(self, popped):
        self._popped = bool(popped)
        if self._popped:
            self.popBtn.setText(u"\u2b72")      # ⭲ (再ドッキング)
            self.popBtn.setToolTip(tr(u"メインウィンドウへ戻す(再ドッキング)"))
        else:
            self.popBtn.setText(u"\u2197")      # ↗ (ポップアウト)
            self.popBtn.setToolTip(tr(u"別ウィンドウに出す(ポップアウト)"))

    def set_cameras(self, cams, current):
        self._building = True
        try:
            self.combo.clear()
            for c in cams:
                self.combo.addItem(c)
            if current:
                i = self.combo.findText(current)
                if i >= 0:
                    self.combo.setCurrentIndex(i)
        finally:
            self._building = False
        # 名前が省略されない幅を「希望幅」にする(最小幅としては要求しない)
        try:
            fm = QtGui.QFontMetrics(self.combo.font())
            widest = max([fm.horizontalAdvance(c.split("|")[-1]) for c in cams] or [60])
            self.combo.setPreferredWidth(max(150, min(320, widest + 70)))
        except Exception:
            pass
        many = self.combo.count() > 1
        self.prevBtn.setEnabled(many)
        self.nextBtn.setEnabled(many)
        self.combo.update()

    def current_camera(self):
        return self.combo.currentText()


# ==========================================================================
#  ビュー 1 つ分
# ==========================================================================
class ViewSlot(object):
    u"""
    owner : ViewManager
    state : {"camera": str, "poppedOut": bool, "windowSize": [w,h], "windowTopLeft": [t,l] or None}
    """

    def __init__(self, owner, index, state):
        self.owner = owner
        self.index = index
        self.state = dict(state or {})
        self.viewport = None       # vp.ModelViewport
        self.slot = None           # メインのビュー領域内の formLayout(ドック中)
        self.window = None         # ポップアウト先の cmds.window(ポップアウト中)
        self.barHost = None        # カメラバーを載せる formLayout
        self.bar = CameraBar()
        self.bar.set_label(u"View {}".format(index + 1))
        self.bar.cameraChanged.connect(self._on_camera_changed)
        self.bar.targetClicked.connect(lambda: self.owner.toggle_target(self.index))
        self.bar.popClicked.connect(self._on_pop_clicked)
        self._fitter = None
        self._docking = False
        self._fit_timers = tuple(QtCore.QTimer(self.bar) for _ in range(3))
        for timer in self._fit_timers:
            timer.setSingleShot(True)
            timer.timeout.connect(self.fit_bar)

    # ------------------------------------------------------------------
    #  状態
    # ------------------------------------------------------------------
    @property
    def panel(self):
        return self.viewport.panel if self.viewport else None

    def is_popped(self):
        return self.window is not None

    def is_valid(self):
        return self.viewport is not None and self.viewport.is_valid()

    def camera(self):
        cam = self.viewport.get_camera() if self.viewport else None
        return cam or self.state.get("camera")

    # ------------------------------------------------------------------
    #  構築
    # ------------------------------------------------------------------
    def _build_in(self, parent, copy_from=None):
        u"""
        parent の中に [barHost][modelPanel] を持つ formLayout を作る。
        戻り値: slot(formLayout 名)
        """
        slot = cmds.formLayout(parent=parent)
        bar_host = cmds.formLayout(parent=slot, height=BAR_HEIGHT)
        label = u"{} {}".format(self.owner.title, self.index + 1)
        viewport = vp.ModelViewport(slot, label=label,
                                    use_copy=self.owner.use_copy_panel,
                                    copy_from=copy_from)
        ctrl = viewport.panel
        try:
            ctrl = cmds.modelPanel(viewport.panel, q=True, control=True) or viewport.panel
        except Exception:
            pass
        try:
            cmds.formLayout(slot, e=True,
                            attachForm=[(bar_host, "top", 0), (bar_host, "left", 0),
                                        (bar_host, "right", 0),
                                        (ctrl, "left", 0), (ctrl, "right", 0), (ctrl, "bottom", 0)],
                            attachNone=[(bar_host, "bottom")],
                            attachControl=[(ctrl, "top", 0, bar_host)])
        except Exception as e:
            cmds.warning(u"[plsCamView] " + tr(u"ビュー {} のレイアウトに失敗: {}").format(self.index + 1, e))

        # カメラバー(Qt)をホストへ
        try:
            self.bar.setParent(None)
        except Exception:
            pass
        host, self._fitter = attach_widget(bar_host, self.bar)
        if host is None:
            cmds.warning(u"[plsCamView] " + tr(u"ビュー {} のカメラバーを配置できませんでした。").format(self.index + 1))

        old = self.viewport
        self.viewport = viewport
        self.barHost = bar_host
        return slot, old

    def build_docked(self, parent_pane, copy_from=None):
        self.slot, old = self._build_in(parent_pane, copy_from)
        self.window = None
        self.bar.set_popped(False)
        self._after_build(old)
        return self.slot

    def build_popped(self, copy_from=None):
        size = self.state.get("windowSize") or [960, 600]
        title = u"{} {}".format(self.owner.title, self.index + 1)
        win = cmds.window(title=title, widthHeight=(int(size[0]), int(size[1])))
        outer = cmds.formLayout(parent=win)
        slot, old = self._build_in(outer, copy_from)
        try:
            cmds.formLayout(outer, e=True,
                            attachForm=[(slot, "top", 0), (slot, "left", 0),
                                        (slot, "right", 0), (slot, "bottom", 0)])
        except Exception:
            pass
        self.window = win
        self.slot = None
        self.bar.set_popped(True)
        try:
            cmds.window(win, e=True, closeCommand=self._on_window_closed)
        except Exception:
            pass
        cmds.showWindow(win)
        pos = self.state.get("windowTopLeft")
        if pos:
            try:
                cmds.window(win, e=True, topLeftCorner=(int(pos[0]), int(pos[1])))
            except Exception:
                pass
        self._after_build(old)
        self._schedule_fit()
        return win

    def _after_build(self, old_viewport):
        # 古いパネルを消す(複製後)
        if old_viewport is not None:
            try:
                self._clear_render_override(old_viewport.panel)
                old_viewport.destroy()
            except Exception:
                pass
        # カメラ・表示設定
        cam = self.state.get("camera")
        if cam:
            self.viewport.set_camera(cam)
        self.owner.apply_view_settings(self)
        self._schedule_fit()

    def _schedule_fit(self):
        # Mayaがレイアウトを確定する0/120/400msの補正は保ち、重複予約だけをまとめる。
        if not any(timer.isActive() for timer in self._fit_timers):
            for timer, delay in zip(self._fit_timers, (0, 120, 400)):
                timer.start(delay)

    def fit_bar(self):
        try:
            if self._fitter is not None:
                self._fitter.fit()
            elif self.bar.parent() is not None:
                p = self.bar.parent()
                self.bar.setGeometry(0, 0, max(1, p.width()), max(1, p.height()))
            if not self.bar.isVisible():
                self.bar.show()
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  ポップアウト / 再ドッキング
    # ------------------------------------------------------------------
    def pop_out(self):
        if self.is_popped() or cmds is None:
            return
        self.state["camera"] = self.camera()
        old_slot = self.slot
        old_panel = self.panel
        # 新しいウィンドウに複製を作ってから、古いパネルとスロットを消す
        self.viewport = _Holder(old_panel)
        self.build_popped(copy_from=old_panel)
        self._clear_render_override(old_panel)
        self._remove_layout(old_slot)
        self.state["poppedOut"] = True
        self.owner.on_view_moved(self)

    def dock(self):
        if not self.is_popped() or cmds is None or self._docking:
            return
        self._docking = True
        try:
            self._remember_window_geometry()
            self.state["camera"] = self.camera()
            old_win = self.window
            old_panel = self.panel
            self.viewport = _Holder(old_panel)
            self.build_docked(self.owner.views_pane, copy_from=old_panel)
            self._clear_render_override(old_panel)
            self._remove_window(old_win)
            self.state["poppedOut"] = False
            self.owner.on_view_moved(self)
        finally:
            self._docking = False

    def _on_pop_clicked(self):
        if self.is_popped():
            self.dock()
        else:
            self.pop_out()

    def _on_window_closed(self, *_):
        u"""ポップアウトウィンドウが閉じられた → メインへ戻す。"""
        if self._docking or self.owner.closing:
            return
        self._remember_window_geometry()
        old_panel = self.panel
        try:
            self.state["camera"] = self.camera() or self.state.get("camera")
        except Exception:
            pass
        self.window = None            # ウィンドウは Maya が消す(パネルも一緒に消える)
        self.viewport = None          # 古いパネルはこちらでは消さない
        try:
            self.build_docked(self.owner.views_pane, copy_from=old_panel)
        except Exception as e:
            cmds.warning(u"[plsCamView] " + tr(u"ビュー {} の再ドッキングに失敗: {}").format(self.index + 1, e))
        self.state["poppedOut"] = False
        self.owner.on_view_moved(self)

    def _remember_window_geometry(self):
        if not self.window:
            return
        try:
            self.state["windowSize"] = [cmds.window(self.window, q=True, width=True),
                                        cmds.window(self.window, q=True, height=True)]
            self.state["windowTopLeft"] = list(cmds.window(self.window, q=True, topLeftCorner=True))
        except Exception:
            pass

    @staticmethod
    def _clear_render_override(panel):
        u"""パネルを消す前に描画オーバーライド(plsFxView 等)を外す。
        オーバーライドが付いたままの modelPanel を deleteUI すると Maya が落ちることがある。"""
        if cmds is None or not panel:
            return
        try:
            if cmds.modelPanel(panel, exists=True) and cmds.modelEditor(panel, q=True, rendererOverrideName=True):
                cmds.modelEditor(panel, e=True, rendererOverrideName="")
        except Exception:
            pass

    def _remove_layout(self, layout):
        if not layout:
            return
        try:
            cmds.deleteUI(layout, layout=True)
        except Exception:
            try:
                cmds.deleteUI(layout)
            except Exception:
                pass

    def _remove_window(self, win):
        if not win:
            return
        try:
            if cmds.window(win, exists=True):
                cmds.deleteUI(win, window=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    def destroy(self):
        u"""このビューを完全に消す(数を減らしたとき / 終了時)。"""
        if cmds is None:
            return
        self._docking = True
        for timer in self._fit_timers:
            timer.stop()
        try:
            self._remember_window_geometry()
            self._clear_render_override(self.panel)
            try:
                self.bar.setParent(None)
                self.bar.hide()
                self.bar.deleteLater()     # 親無しの Qt ウィジェットを残すと終了時に落ちる
            except Exception:
                pass
            if self.window:
                self._remove_window(self.window)
                self.window = None
            elif self.slot:
                self._remove_layout(self.slot)
                self.slot = None
            self.viewport = None
        finally:
            self._docking = False

    def collect(self):
        self._remember_window_geometry()
        self.state["camera"] = self.camera()
        self.state["poppedOut"] = self.is_popped()
        return dict(self.state)

    # ------------------------------------------------------------------
    def _on_camera_changed(self, cam):
        if self.viewport and self.viewport.set_camera(cam):
            self.state["camera"] = cam
            self.owner.on_camera_changed(self)

    def set_cameras(self, cams):
        current = self.camera()
        if current and current not in cams:
            short = current.split("|")[-1]
            match = [c for c in cams if c.split("|")[-1] == short]
            current = match[0] if match else (cams[0] if cams else None)
        self.bar.set_cameras(cams, current)
        if current and self.viewport:
            self.viewport.set_camera(current)
            self.state["camera"] = current

    def activate(self):
        u"""このビューのウィンドウを前面に出してフォーカスを移す。"""
        try:
            if self.window and cmds.window(self.window, exists=True):
                cmds.showWindow(self.window)
            else:
                self.owner.show_main_window()
        except Exception:
            pass
        if self.viewport:
            self.viewport.focus()


class _Holder(object):
    u"""複製元パネルを一時的に保持するだけのダミー(destroy で古いパネルを消す)。"""

    def __init__(self, panel):
        self.panel = panel

    def is_valid(self):
        try:
            return bool(self.panel and cmds.modelPanel(self.panel, exists=True))
        except Exception:
            return False

    def get_camera(self):
        try:
            return cmds.modelPanel(self.panel, q=True, camera=True)
        except Exception:
            return None

    def destroy(self):
        try:
            if self.panel and cmds.modelPanel(self.panel, exists=True):
                try:
                    if cmds.modelEditor(self.panel, q=True, rendererOverrideName=True):
                        cmds.modelEditor(self.panel, e=True, rendererOverrideName="")
                except Exception:
                    pass
                cmds.deleteUI(self.panel, panel=True)
        except Exception:
            pass
        self.panel = None


# ==========================================================================
#  ビュー全体の管理
# ==========================================================================
class ViewManager(object):
    u"""
    メインウィンドウのビュー領域(paneLayout)と、各 ViewSlot を管理する。
    owner(PlsCamViewWindow) には以下を求める:
        owner.data / owner.save_settings() / owner.apply_view_settings(view)
        owner.on_views_changed() / owner.on_target_changed() / owner.show_main_window()
    """

    def __init__(self, owner, parent_layout, title=u"PLS CamView"):
        self.owner = owner
        self.title = title
        self.closing = False
        self.use_copy_panel = bool(owner.data.get("useCopyPanel", True))
        self.views = []
        self.layout = owner.data.get("viewLayout", "horizontal")
        if self.layout not in LAYOUT_KEYS:
            self.layout = "horizontal"
        self.target_index = int(owner.data.get("playblastView", 0) or 0)
        selected = owner.data.get("playblastViews")
        self.target_indices = list(selected) if isinstance(selected, list) else [self.target_index]

        self.views_pane = cmds.paneLayout(parent=parent_layout, configuration="single")
        # 全ビューがポップアウト中のときに見せるプレースホルダ
        self._placeholder = cmds.formLayout(parent=self.views_pane)
        try:
            cmds.text(parent=self._placeholder, label=tr(u"すべてのビューがポップアウト中です"),
                      align="center")
        except Exception:
            pass

    # ------------------------------------------------------------------
    #  構築 / 復元
    # ------------------------------------------------------------------
    def build_from_settings(self):
        states = self.owner.data.get("views") or []
        if not states:
            states = [{"camera": self.owner.data.get("camera", "persp"), "poppedOut": False}]
        states = states[:MAX_VIEWS]
        for i, s in enumerate(states):
            self._add_view(s)
        self._normalize_targets()
        self.relayout()
        self._update_target_marks()

    def _add_view(self, state):
        v = ViewSlot(self, len(self.views), state)
        self.views.append(v)
        if state.get("poppedOut"):
            v.build_popped()
        else:
            v.build_docked(self.views_pane)
        return v

    def set_count(self, n):
        n = max(1, min(MAX_VIEWS, int(n)))
        changed = False
        while len(self.views) < n:
            last = self.views[-1] if self.views else None
            cam = last.camera() if last else self.owner.data.get("camera", "persp")
            self._add_view({"camera": cam, "poppedOut": False})
            changed = True
        while len(self.views) > n:
            v = self.views.pop()
            v.destroy()
            changed = True
        if changed:
            self._normalize_targets()
            self.relayout()
            self.refresh_cameras()
            self._update_target_marks()
            self.owner.on_views_changed()

    def set_layout(self, key):
        if key not in LAYOUT_KEYS:
            return
        self.layout = key
        self.relayout()
        self.owner.on_views_changed()

    def count(self):
        return len(self.views)

    # ------------------------------------------------------------------
    #  レイアウト
    # ------------------------------------------------------------------
    def docked_views(self):
        return [v for v in self.views if not v.is_popped() and v.slot]

    def relayout(self):
        if cmds is None:
            return
        docked = self.docked_views()
        n = len(docked)
        conf = pane_configuration(n, self.layout)
        try:
            cmds.paneLayout(self.views_pane, e=True, configuration=conf)
            if n == 0:
                cmds.paneLayout(self.views_pane, e=True, setPane=(self._placeholder, 1))
            else:
                for i, v in enumerate(docked[:MAX_VIEWS]):
                    cmds.paneLayout(self.views_pane, e=True, setPane=(v.slot, i + 1))
            self._equalize(n, conf)
        except Exception as e:
            cmds.warning(u"[plsCamView] " + tr(u"ビューの配置に失敗: {}").format(e))
        for v in docked:
            v._schedule_fit()

    def _equalize(self, n, conf):
        if n < 2:
            return
        pct = 100.0 / n
        try:
            if conf.startswith("vertical"):
                for i in range(n):
                    cmds.paneLayout(self.views_pane, e=True, paneSize=(i + 1, pct, 100))
            elif conf.startswith("horizontal"):
                for i in range(n):
                    cmds.paneLayout(self.views_pane, e=True, paneSize=(i + 1, 100, pct))
            elif conf == "quad":
                for i in range(4):
                    cmds.paneLayout(self.views_pane, e=True, paneSize=(i + 1, 50, 50))
            elif conf == "top3":
                cmds.paneLayout(self.views_pane, e=True, paneSize=(1, 100, 50))
                cmds.paneLayout(self.views_pane, e=True, paneSize=(2, 50, 50))
                cmds.paneLayout(self.views_pane, e=True, paneSize=(3, 50, 50))
        except Exception:
            pass

    def on_view_moved(self, view):
        self.relayout()
        self._update_target_marks()
        self.owner.on_views_changed()

    # ------------------------------------------------------------------
    #  Playblast 対象
    # ------------------------------------------------------------------
    def set_target(self, index):
        if index < 0 or index >= len(self.views):
            return
        self.target_index = index
        self.target_indices = [index]
        self._update_target_marks()
        self.owner.on_target_changed()

    def _normalize_targets(self):
        self.target_indices = sorted(set(i for i in self.target_indices
                                         if isinstance(i, int) and 0 <= i < len(self.views)))
        if not self.target_indices and self.views:
            self.target_indices = [min(max(0, self.target_index), len(self.views) - 1)]
        if self.target_indices and self.target_index not in self.target_indices:
            self.target_index = self.target_indices[0]
        if not self.owner.data.get("playblastMulti", False) and self.target_indices:
            self.target_indices = [self.target_index]

    def toggle_target(self, index):
        if not self.owner.data.get("playblastMulti", False):
            self.set_target(index)
            return
        if index < 0 or index >= len(self.views):
            return
        if index in self.target_indices:
            if len(self.target_indices) > 1:
                self.target_indices.remove(index)
        else:
            self.target_indices.append(index)
            self.target_index = index
        self._normalize_targets()
        self._update_target_marks()
        self.owner.on_target_changed()

    def selected_views(self):
        self._normalize_targets()
        return [v for i, v in enumerate(self.views) if i in self.target_indices]

    def playblast_targets(self, geometry=False):
        result = []
        for view in self.selected_views():
            camera = view.camera()
            if not camera:
                raise ValueError(tr(u"対象カメラがありません。"))
            paths = cmds.ls(camera, long=True) or []
            if len(paths) != 1:
                raise ValueError(tr(u"カメラを一意に識別できません: {}").format(camera))
            camera = paths[0]
            if cmds.nodeType(camera) == "camera":
                parents = cmds.listRelatives(camera, parent=True, fullPath=True) or []
                if len(parents) != 1:
                    raise ValueError(tr(u"カメラの親を識別できません: {}").format(camera))
                camera = parents[0]
            target = {"panel": view.panel, "camera": camera}
            if geometry:
                widget = to_qwidget(view.slot or view.panel)
                if widget is None or not widget.isVisible():
                    raise ValueError(tr(u"対象ビューを表示してから合成してください。"))
                point = widget.mapToGlobal(QtCore.QPoint(0, 0))
                target["rect"] = (point.x(), point.y(), widget.width(), widget.height())
            result.append(target)
        return result

    def target_view(self):
        if not self.views:
            return None
        i = min(max(0, self.target_index), len(self.views) - 1)
        return self.views[i]

    def target_panel(self):
        v = self.target_view()
        return v.panel if v else None

    def _update_target_marks(self):
        for i, v in enumerate(self.views):
            v.bar.set_target(i in self.target_indices, bool(self.owner.data.get("playblastMulti", False)))

    # ------------------------------------------------------------------
    #  カメラ
    # ------------------------------------------------------------------
    def refresh_cameras(self):
        include = bool(self.owner.data.get("showStartupCameras", True))
        cams = vp.list_cameras(include_startup=include)
        for v in self.views:
            v.set_cameras(cams)

    def on_camera_changed(self, view):
        self.owner.apply_view_settings(view)
        self.owner.on_views_changed()

    # ------------------------------------------------------------------
    #  一括適用
    # ------------------------------------------------------------------
    def each_viewport(self):
        for v in self.views:
            if v.viewport is not None and isinstance(v.viewport, vp.ModelViewport):
                yield v.viewport

    def show_main_window(self):
        self.owner.show_main_window()

    def apply_view_settings(self, view):
        self.owner.apply_view_settings(view)

    # ------------------------------------------------------------------
    def collect(self):
        return [v.collect() for v in self.views]

    def destroy_all(self):
        self.closing = True
        for v in self.views:
            try:
                v.destroy()
            except Exception:
                pass
        self.views = []
