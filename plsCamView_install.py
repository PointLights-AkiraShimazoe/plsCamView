# -*- coding: utf-8 -*-
u"""
plsCamView installer
====================
このファイルを Maya のビューポートへドラッグ & ドロップすると
インストーラの UI が開きます。[Install] を押すと

    <Maya userAppDir>/modules/plsCamView/      … 本体
    <Maya userAppDir>/modules/plsCamView.mod   … モジュール定義

が作成され、その場で使えるようになります(Maya の再起動は不要)。
アンインストールは上記 2 つを削除するだけです。

    起動:  import plsCamView
           plsCamView.show()
"""
from __future__ import absolute_import

import os
import shutil
import sys
import tempfile

from maya import cmds

TOOL_NAME = "plsCamView"
WINDOW = "plsCamViewInstallerWin"


# --------------------------------------------------------------------------
def _source_dir():
    u"""この plsCamView_install.py が置かれているフォルダ。"""
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except NameError:
        return os.getcwd()


def _read_version(src_dir):
    init_py = os.path.join(src_dir, "scripts", TOOL_NAME, "__init__.py")
    try:
        with open(init_py, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("__version__"):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return "0.0.0"


def _modules_dir():
    base = cmds.internalVar(userAppDir=True).replace("\\", "/")
    return os.path.join(base, "modules").replace("\\", "/")


def _install_paths():
    mod_dir = _modules_dir()
    return (os.path.join(mod_dir, TOOL_NAME).replace("\\", "/"),
            os.path.join(mod_dir, TOOL_NAME + ".mod").replace("\\", "/"))


# --------------------------------------------------------------------------
def install(create_shelf_button=True):
    u"""モジュールとして導入する。成功したら導入先パスを返す。"""
    src_dir = _source_dir()
    src_scripts = os.path.join(src_dir, "scripts")
    src_icons = os.path.join(src_dir, "icons")

    if not os.path.isdir(os.path.join(src_scripts, TOOL_NAME)):
        cmds.error(u"[{0}] scripts/{0} が見つかりません。zip を展開してから "
                   u"plsCamView_install.py をドラッグ & ドロップしてください。".format(TOOL_NAME))
        return None

    version = _read_version(src_dir)
    dest_dir, mod_file = _install_paths()

    # コピーが完了するまで旧版を保持し、公開失敗時は退避した旧版へ戻す。
    staging = None
    old_moved = new_installed = keep_backup = False
    try:
        os.makedirs(os.path.dirname(dest_dir), exist_ok=True)
        staging = tempfile.mkdtemp(prefix=".plsCamView-install-",
                                   dir=os.path.dirname(dest_dir))
        payload = os.path.join(staging, "new")
        backup = os.path.join(staging, "previous")
        pending_mod = os.path.join(staging, "plsCamView.mod")
        os.makedirs(os.path.join(payload, "scripts"))
        shutil.copytree(os.path.join(src_scripts, TOOL_NAME),
                        os.path.join(payload, "scripts", TOOL_NAME),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if os.path.isdir(src_icons):
            shutil.copytree(src_icons, os.path.join(payload, "icons"),
                            ignore=shutil.ignore_patterns("__pycache__"))
        # 配布物に ffmpeg が無いときだけ、既存導入先の利用者配置 ffmpeg を新しい payload へ
        # 引き継ぐ(公開 zip は bin/ffmpeg.exe を同梱しないため、更新で MP4 機能を失わせない。0.9.0)。
        # 配布物に ffmpeg が有る場合は従来どおり配布物の内容をそのまま使う。
        # 旧版からは読むだけ(コピー)なので、公開失敗時の復元(退避した旧版へ戻す)に影響しない。
        payload_bin = os.path.join(payload, "scripts", TOOL_NAME, "bin")
        dest_bin = os.path.join(dest_dir, "scripts", TOOL_NAME, "bin")
        for ff_name in ("ffmpeg.exe", "ffmpeg"):
            new_ff = os.path.join(payload_bin, ff_name)
            old_ff = os.path.join(dest_bin, ff_name)
            if not os.path.isfile(new_ff) and os.path.isfile(old_ff):
                os.makedirs(payload_bin, exist_ok=True)
                shutil.copy2(old_ff, new_ff)
        for extra in ("README.md", "LICENSE"):
            p = os.path.join(src_dir, extra)
            if os.path.isfile(p):
                shutil.copy2(p, os.path.join(payload, extra))
        with open(pending_mod, "w", encoding="utf-8") as f:
            f.write("+ {name} {ver} {path}\n".format(
                name=TOOL_NAME, ver=version, path=dest_dir))
            f.write("scripts: scripts\n")
            f.write("icons: icons\n")
        if os.path.isdir(dest_dir):
            os.rename(dest_dir, backup)
            old_moved = True
        os.rename(payload, dest_dir)
        new_installed = True
        os.replace(pending_mod, mod_file)
    except Exception as e:
        try:
            if new_installed:
                shutil.rmtree(dest_dir)
            if old_moved:
                os.rename(backup, dest_dir)
        except Exception as restore_error:
            keep_backup = True
            cmds.error(u"[{}] 導入失敗: {}。復元失敗: {}。退避先を保持: {}".format(
                TOOL_NAME, e, restore_error, staging))
            return None
        cmds.error(u"[{}] 導入に失敗しました（旧版・モジュール定義は保持）: {}".format(
            TOOL_NAME, e))
        return None
    finally:
        if staging and not keep_backup:
            shutil.rmtree(staging, ignore_errors=True)

    # --- 再起動なしで使えるようにする -------------------------------------
    scripts_path = os.path.join(dest_dir, "scripts").replace("\\", "/")
    # 既に入っていても先頭へ移す(展開元などが前にあると、下の purge 後の import が
    # 導入先でない方を拾う)。import plsCamView の __file__ を導入先に保証する(0.9.1 レビュー対応)。
    _norm = os.path.normpath(scripts_path).lower()
    sys.path[:] = [p for p in sys.path if os.path.normpath(p or ".").lower() != _norm]
    sys.path.insert(0, scripts_path)
    for name in [m for m in list(sys.modules) if m == TOOL_NAME or
                 m.startswith(TOOL_NAME + ".")]:
        del sys.modules[name]

    if create_shelf_button:
        try:
            import importlib
            shelf = importlib.import_module(TOOL_NAME + ".shelf")
            shelf.install()
        except Exception as e:
            cmds.warning(u"[{}] シェルフボタンの作成に失敗しました: {}".format(
                TOOL_NAME, e))

    print(u"[{}] v{} をインストールしました: {}".format(TOOL_NAME, version, dest_dir))
    return dest_dir


def uninstall():
    u"""導入したファイルを削除する。"""
    dest_dir, mod_file = _install_paths()
    for name in [m for m in list(sys.modules) if m == TOOL_NAME or
                 m.startswith(TOOL_NAME + ".")]:
        del sys.modules[name]
    try:
        if os.path.isdir(dest_dir):
            shutil.rmtree(dest_dir, ignore_errors=True)
        if os.path.isfile(mod_file):
            os.remove(mod_file)
        print(u"[{}] アンインストールしました。".format(TOOL_NAME))
        return True
    except Exception as e:
        cmds.warning(u"[{}] アンインストールに失敗しました: {}".format(TOOL_NAME, e))
        return False


# --------------------------------------------------------------------------
#  UI (0.9.1: CamView 本体と同じ見た目の Qt ダイアログ。qt/style は同梱パッケージから
#  読むので未インストールの単独 D&D でも使える。使えない環境は従来の cmds UI へ戻る)
# --------------------------------------------------------------------------
_BUNDLE_PKG = "plsCamViewInstallerBundle"


def _qt_modules():
    u"""installer の隣(scripts/plsCamView)の qt / style を、通常名とは別名のパッケージ
    (plsCamViewInstallerBundle)としてファイルパスから直接読み込む(0.9.1 レビュー対応)。
    - 旧版の plsCamView が既にロードされていても、同梱版のスタイルを確実に使う
    - sys.path を変更しない(インストール後の import 解決を展開元へ向けない)
    - ロード済みの plsCamView / 生きている UI には触れない(purge / reload しない)
    失敗したら None(従来の cmds UI へ)。"""
    try:
        import importlib.util
        import types as _types
        pkg_dir = os.path.join(_source_dir(), "scripts", TOOL_NAME)
        if not os.path.isdir(pkg_dir):
            return None
        pkg = sys.modules.get(_BUNDLE_PKG)
        if pkg is None or getattr(pkg, "__path__", [None])[0] != pkg_dir:
            pkg = _types.ModuleType(_BUNDLE_PKG)
            pkg.__path__ = [pkg_dir]
            sys.modules[_BUNDLE_PKG] = pkg
            sys.modules.pop(_BUNDLE_PKG + ".qt", None)
            sys.modules.pop(_BUNDLE_PKG + ".style", None)

        def _load(name):
            full = _BUNDLE_PKG + "." + name
            if full in sys.modules:
                return sys.modules[full]
            spec = importlib.util.spec_from_file_location(
                full, os.path.join(pkg_dir, name + ".py"))
            mod = importlib.util.module_from_spec(spec)
            sys.modules[full] = mod
            try:
                spec.loader.exec_module(mod)
            except Exception:
                sys.modules.pop(full, None)
                raise
            return mod

        qt = _load("qt")          # style の from .qt import より先に読む
        style = _load("style")
        return qt, style
    except Exception:
        return None


def _maya_main_window(qt):
    try:
        import maya.OpenMayaUI as omui
        ptr = omui.MQtUtil.mainWindow()
        if ptr:
            return qt.wrapInstance(int(ptr), qt.QtWidgets.QWidget)
    except Exception:
        pass
    return None


_qt_dialog = None


def build_installer_dialog(qt, style, parent=None):
    u"""Qt 版インストーラの見た目を組み立てて返す(テスト・offscreen 画像用に分離)。
    install / rollback / ffmpeg 引き継ぎの処理は install() のまま変更しない。"""
    QtCore, QtWidgets = qt.QtCore, qt.QtWidgets
    src_dir = _source_dir()
    version = _read_version(src_dir)
    dest_dir, _mod = _install_paths()

    dlg = QtWidgets.QDialog(parent)
    dlg.setWindowTitle(u"plsCamView インストーラ")
    dlg.setObjectName("plsRoot")
    # 保存済みの UI 倍率があれば installer にも適用(無ければ既定。読取のみ)
    try:
        from maya import cmds as _cmds
        import io as _io
        import json as _json
        _pref = _cmds.internalVar(userPrefDir=True)
        with _io.open(os.path.join(_pref, "plsCamView", "settings.json"), "r", encoding="utf-8") as _f:
            style.set_ui_scale((_json.load(_f) or {}).get("uiScale", style.UI_SCALE_DEFAULT))
    except Exception:
        try:
            style.set_ui_scale(style.UI_SCALE_DEFAULT)
        except Exception:
            pass
    dlg.setStyleSheet(style.stylesheet())
    try:
        dlg.setWindowFlag(QtCore.Qt.WindowContextHelpButtonHint, False)
    except Exception:
        pass
    dlg.setFixedWidth(style.px(420))
    outer = QtWidgets.QVBoxLayout(dlg)
    outer.setContentsMargins(12, 12, 12, 12)
    outer.setSpacing(10)

    card = style.Card(u"plsCamView  v{}".format(version))
    card.setToolTip(u"Maya のメインウィンドウから分離した、ツールボックス付きカメラビュー。\n"
                    u"インストールはこの Maya のユーザー環境だけに入ります(再起動不要)。")

    dest_lab = QtWidgets.QLabel(u"導入先")
    dest_lab.setObjectName("fieldLabel")
    dest_path = QtWidgets.QLabel(dest_dir)
    dest_path.setObjectName("note")
    dest_path.setWordWrap(True)
    dest_path.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
    dest_path.setToolTip(u"モジュールとして作成: {0}\nモジュール定義: {0}.mod\n"
                         u"アンインストールはこの 2 つを削除するだけです。".format(dest_dir))
    card.body.addWidget(dest_lab)
    card.body.addWidget(dest_path)

    shelf = style.ToggleSwitch(u"シェルフボタン")
    shelf.setChecked(True)
    shelf.setToolTip(u"現在のシェルフに起動ボタンを追加します。\n"
                     u"同じ起動コマンドのボタンが既にあれば更新します。")
    card.body.addWidget(shelf)
    outer.addWidget(card)

    row = QtWidgets.QHBoxLayout()
    row.setSpacing(8)
    row.addStretch(1)
    ok = QtWidgets.QPushButton(u"インストール")
    ok.setObjectName("primary")
    ok.setDefault(True)
    ok.setToolTip(u"更新のときは新版のコピー完了後に旧版を退避し、失敗したら旧版へ自動で戻します。\n"
                  u"配布物に ffmpeg が無い場合、既存の bin/ffmpeg.exe は引き継がれます。")
    close = QtWidgets.QPushButton(u"閉じる")
    close.setToolTip(u"何もせずに閉じます。")
    row.addWidget(ok)
    row.addWidget(close)
    outer.addLayout(row)

    dlg._shelf = shelf
    dlg._ok = ok
    dlg._close = close
    dlg._dest = dest_path
    return dlg


def _show_installer_qt(qt, style):
    QtWidgets = qt.QtWidgets
    global _qt_dialog
    try:
        if _qt_dialog is not None:
            _qt_dialog.close()
            _qt_dialog.deleteLater()
    except Exception:
        pass
    dlg = build_installer_dialog(qt, style, _maya_main_window(qt))
    _qt_dialog = dlg

    def _on_install():
        dest = install(create_shelf_button=dlg._shelf.isChecked())
        if not dest:
            return
        dlg.close()
        try:
            import importlib
            importlib.import_module(TOOL_NAME).show()
        except Exception as e:
            cmds.warning(u"[{}] 起動に失敗しました: {}".format(TOOL_NAME, e))

    dlg._ok.clicked.connect(_on_install)
    dlg._close.clicked.connect(dlg.close)
    dlg.show()
    dlg.raise_()
    return dlg


def _do_install(*_):
    dest = install(create_shelf_button=cmds.checkBox(
        "plsCamViewShelfChk", q=True, value=True))
    if not dest:
        return
    if cmds.window(WINDOW, exists=True):
        cmds.deleteUI(WINDOW, window=True)
    try:
        import importlib
        importlib.import_module(TOOL_NAME).show()
    except Exception as e:
        cmds.warning(u"[{}] 起動に失敗しました: {}".format(TOOL_NAME, e))


def _do_cancel(*_):
    if cmds.window(WINDOW, exists=True):
        cmds.deleteUI(WINDOW, window=True)


def show_installer():
    u"""インストーラ UI。CamView 本体のスタイル(Qt)を優先し、使えなければ cmds UI(従来)。"""
    mods = _qt_modules()
    if mods is not None:
        try:
            return _show_installer_qt(*mods)
        except Exception as e:
            try:
                cmds.warning(u"[{}] Qt インストーラを開けませんでした({})。従来 UI で開きます。".format(
                    TOOL_NAME, e))
            except Exception:
                pass
    return _show_installer_cmds()


def _show_installer_cmds():
    src_dir = _source_dir()
    version = _read_version(src_dir)
    dest_dir, _mod = _install_paths()

    if cmds.window(WINDOW, exists=True):
        cmds.deleteUI(WINDOW, window=True)

    cmds.window(WINDOW, title=u"plsCamView Installer", widthHeight=(460, 240),
                sizeable=False)
    form = cmds.columnLayout(adjustableColumn=True, rowSpacing=8,
                             columnOffset=("both", 16))
    cmds.separator(height=8, style="none")
    cmds.text(label=u"plsCamView  v{}".format(version), align="left",
              font="boldLabelFont")
    cmds.text(label=u"Maya のメインウィンドウから分離した、"
                    u"ツールボックス付きカメラビュー。", align="left")
    cmds.separator(height=8, style="in")
    cmds.text(label=u"インストール先", align="left")
    cmds.text(label=dest_dir, align="left", font="smallPlainLabelFont")
    cmds.separator(height=4, style="none")
    cmds.checkBox("plsCamViewShelfChk", label=u"現在のシェルフに起動ボタンを追加する",
                  value=True)
    cmds.separator(height=8, style="none")
    row = cmds.rowLayout(numberOfColumns=2, columnWidth2=(215, 215),
                         columnAlign2=("center", "center"), parent=form)
    cmds.button(label=u"Install", height=32, command=_do_install)
    cmds.button(label=u"Cancel", height=32, command=_do_cancel)
    cmds.setParent(form)
    cmds.separator(height=8, style="none")
    cmds.showWindow(WINDOW)


def onMayaDroppedPythonFile(*args, **kwargs):
    u"""Maya のビューポートへ D&D されたときに呼ばれる。"""
    show_installer()


if __name__ == "__main__":
    show_installer()
