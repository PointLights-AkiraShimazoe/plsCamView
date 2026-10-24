# -*- coding: utf-8 -*-
u"""
plsCamView.qt
=============
PySide6 / PySide2 の差異を吸収する共通モジュール。
Maya 2025 以降は PySide6、2024 以前は PySide2。
"""
from __future__ import absolute_import

QT_BINDING = None

try:
    from PySide6 import QtCore, QtGui, QtWidgets          # noqa: F401
    from shiboken6 import wrapInstance, getCppPointer     # noqa: F401
    QT_BINDING = "PySide6"
except Exception:                                          # Maya 2025 以前
    from PySide2 import QtCore, QtGui, QtWidgets          # noqa: F401
    from shiboken2 import wrapInstance, getCppPointer     # noqa: F401
    QT_BINDING = "PySide2"

try:
    import maya.OpenMayaUI as omui
except Exception:
    omui = None


def _long(ptr):
    return int(ptr)


def maya_main_window():
    u"""Maya メインウィンドウを QWidget として返す。"""
    if omui is None:
        return None
    try:
        ptr = omui.MQtUtil.mainWindow()
        if ptr:
            return wrapInstance(_long(ptr), QtWidgets.QWidget)
    except Exception:
        pass
    return None


def to_qwidget(maya_ui_name):
    u"""
    Maya の UI 名(コントロール/レイアウト)を QWidget として返す。
    短縮名で見つからない場合はフルパス名でも試す。
    """
    if omui is None or not maya_ui_name:
        return None

    names = [maya_ui_name]
    try:
        from maya import cmds
        full = cmds.control(maya_ui_name, q=True, fullPathName=True)
        if full and full not in names:
            names.append(full)
    except Exception:
        pass

    for name in names:
        for finder in ("findControl", "findLayout", "findWindow"):
            try:
                fn = getattr(omui.MQtUtil, finder, None)
                if fn is None:
                    continue
                ptr = fn(name)
                if ptr:
                    return wrapInstance(_long(ptr), QtWidgets.QWidget)
            except Exception:
                continue
    return None


def attach_widget(maya_layout_name, widget):
    u"""
    Maya のレイアウト配下に Qt ウィジェットを貼り付ける。

    Maya のレイアウト(formLayout など)は内部に独自の QLayout を持っていることが
    あり、そこへ新しく QVBoxLayout を setLayout しようとすると Qt に無視されて
    ウィジェットがサイズ 0 のまま表示されない。
    そのため
        1. 既存の QLayout があればそれを使う / 無ければ作る
        2. どちらの場合も、親のリサイズに追従して geometry を合わせる保険を掛ける
    という手順を踏む。

    戻り値: (host QWidget, resize フィルタ) / 失敗時は (None, None)
    """
    host = to_qwidget(maya_layout_name)
    if host is None or widget is None:
        return None, None

    lay = host.layout()
    if lay is None:
        lay = QtWidgets.QVBoxLayout(host)
    try:
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
    except Exception:
        pass
    try:
        lay.addWidget(widget)
    except Exception:
        widget.setParent(host)

    if widget.parent() is not host:
        widget.setParent(host)

    fitter = _HostFitter(host, widget)
    host.installEventFilter(fitter)
    widget.setGeometry(0, 0, max(1, host.width()), max(1, host.height()))
    widget.show()
    return host, fitter


class _HostFitter(QtCore.QObject):
    u"""親(Maya レイアウト)のサイズにウィジェットを追従させる保険。"""

    def __init__(self, host, child):
        super(_HostFitter, self).__init__(host)
        self._host = host
        self._child = child

    def fit(self):
        u"""今の親サイズに合わせる(表示直後などに明示的に呼ぶ)。"""
        try:
            h, c = self._host, self._child
            c.setGeometry(0, 0, max(1, h.width()), max(1, h.height()))
            if not c.isVisible():
                c.show()
        except Exception:
            pass

    def eventFilter(self, obj, event):
        try:
            if event.type() in (QtCore.QEvent.Resize,
                                QtCore.QEvent.Show,
                                QtCore.QEvent.LayoutRequest):
                h, c = self._host, self._child
                if c.width() != h.width() or c.height() != h.height():
                    c.setGeometry(0, 0, max(1, h.width()), max(1, h.height()))
        except Exception:
            pass
        return False
