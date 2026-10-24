# -*- coding: utf-8 -*-
u"""
plsCamView.shelf
================
シェルフに plsCamView のボタンを追加するヘルパー。

    from plsCamView import shelf
    shelf.install()        # 通常起動ボタン
    shelf.install_dev()    # 押すたびに最新コードを読み直して開くボタン

ボタンに埋め込むコマンドは、このパッケージの実際の置き場所から自動生成する
(他パッケージの配下に置いた場合でも、単体で置いた場合でもそのまま動く)。
"""
from __future__ import absolute_import

import os

from .i18n import tr

try:
    from maya import cmds
    from maya import mel
except Exception:
    cmds = None
    mel = None

BUTTON_LABEL = "CamView"

# このモジュールの親パッケージ(例: plsCamView)
PACKAGE = __name__.rsplit(".", 1)[0]


def command_text():
    u"""通常起動。既に読み込まれていればそのまま使う。"""
    return (
        "import importlib\n"
        "importlib.import_module('{pkg}').show()\n"
    ).format(pkg=PACKAGE)


def dev_command_text():
    u"""
    押すたびにディスク上の最新コードで開き直す(Maya 再起動不要)。
    パッケージが読み込まれていない場合も動くよう、素の import から書いている。
    """
    return (
        "import importlib, sys\n"
        "_pkg = '{pkg}'\n"
        "_mod = sys.modules.get(_pkg)\n"
        "if _mod is not None and hasattr(_mod, 'restart'):\n"
        "    _mod.restart()\n"
        "else:\n"
        "    importlib.import_module(_pkg).show()\n"
    ).format(pkg=PACKAGE)


def _current_shelf():
    try:
        top = mel.eval("$tmp = $gShelfTopLevel;")
        return cmds.tabLayout(top, q=True, selectTab=True)
    except Exception:
        return None


def _add(label, overlay, command, annotation, shelf_name=None):
    if cmds is None:
        return None
    shelf_name = shelf_name or _current_shelf()
    if not shelf_name:
        cmds.warning(u"[plsCamView] " + tr(u"シェルフを特定できませんでした。"))
        return None
    # 再導入では、このパッケージの同じ起動ボタンだけを修復する。
    existing = None
    for child in cmds.shelfLayout(shelf_name, q=True, childArray=True) or []:
        try:
            if (cmds.shelfButton(child, q=True, label=True) == label and
                    cmds.shelfButton(child, q=True, sourceType=True) == "python" and
                    cmds.shelfButton(child, q=True, command=True).strip() == command.strip()):
                existing = child
                break
        except RuntimeError:
            continue

    icon = os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "icons", "plsCamView_shelf.png"))
    kwargs = dict(
        label=label,
        annotation=annotation,
        imageOverlayLabel=overlay,
        command=command,
        sourceType="python",
        style="iconOnly",
        width=32,
        height=32,
        flexibleWidthType=1,
        image=icon.replace("\\", "/") if os.path.isfile(icon) else "menuIconPanels.png",
    )
    args = (existing,) if existing else ()
    if existing:
        kwargs["edit"] = True
    else:
        kwargs["parent"] = shelf_name
    try:
        btn = cmds.shelfButton(*args, **kwargs)
    except Exception:
        kwargs["image"] = "menuIconPanels.png"
        btn = cmds.shelfButton(*args, **kwargs)
    print(u"[plsCamView] シェルフ '{}' のボタンを設定しました。(package={})".format(
        shelf_name, PACKAGE))
    return btn


def install(shelf_name=None):
    u"""通常起動ボタンを作成し、同じボタンがあれば更新する。"""
    return _add(BUTTON_LABEL, "CamV", command_text(),
                tr(u"PLS CamView: 分離カメラビューを開く"), shelf_name)


def install_dev(shelf_name=None):
    u"""
    更新反映つき起動ボタンを追加する。
    押すたびに最新コードを読み直して開くので、コード更新時の確認が速い。
    """
    return _add(BUTTON_LABEL, "CamR", dev_command_text(),
                tr(u"PLS CamView: 最新コードを読み直して開く(Maya 再起動不要)"),
                shelf_name)
