# -*- coding: utf-8 -*-
u"""
plsCamView
==========
Maya のメインウィンドウから分離した、ツールボックス付きカメラビュー。

使い方
------
    import plsCamView
    plsCamView.show()

    plsCamView.restart()         # コードを更新したとき(Maya 再起動は不要)
    plsCamView.reset_settings()  # 設定を初期化して開き直す
    plsCamView.playblast_mp4()   # このビューを MP4 に書き出す(ツールボックスの設定を使用)

パッケージを他のパッケージの配下に置いた場合は、その位置に合わせて
import してください(例: `from mytools.anim import plsCamView`)。
モジュール名は実行時に動的解決しているので、どこに置いても動きます。

【注意】`importlib.reload(plsCamView)` では ui / viewport などのサブモジュールが
古いままになります。コードを更新したら restart() を使ってください。
restart() はパッケージ自身も含めて sys.modules から破棄し、親パッケージが
保持している古いモジュール参照も消してから読み直します。

インストール
------------
同梱の plsCamView_install.py を Maya のビューポートへドラッグ&ドロップし、[Install] を
押してください。手動で入れる場合は、このフォルダごと Maya の scripts パス上に
置くだけで動きます。
"""
from __future__ import absolute_import

__version__ = "0.9.0"

_instance = None


def _restore_language():
    u"""保存済みの UI 言語を show の入口で復元する(v1.8.2)。
    ビュー領域のプレースホルダ(「すべてのビューがポップアウト中です」)はツールボックス生成
    (そこでも set_language する)より前に作られるため、ここで読まないと初回 show だけ
    保存済みの ja/en が反映されず system のままになる(1.8.1 の既知事項の修正)。
    settings が読めない場合は現状維持(既定 system)。表示用の状態だけで、失敗しても show を止めない。"""
    try:
        from . import settings as _st
        from . import i18n as _i18n
        _i18n.set_language(str((_st.load() or {}).get("language", "system")))
    except Exception:
        pass


def _disk_version():
    u"""ディスク上(インストール先)の __init__.py の __version__。読めなければ None。
    import 済みのこの値(__version__)はディスクを更新しても変わらないため、
    show() の入口で両者を比べて更新の取りこぼしを検出する(継続84)。"""
    import io
    import os
    import re
    try:
        p = os.path.splitext(os.path.abspath(__file__))[0] + ".py"
        with io.open(p, "r", encoding="utf-8") as f:
            m = re.search(r'__version__\s*=\s*[\'"]([^\'"]+)[\'"]', f.read())
        return m.group(1) if m else None
    except Exception:
        return None


# --------------------------------------------------------------------------
def show():
    u"""ウィンドウを表示(既に開いていれば前面へ)。
    インストールでディスクが新しくなっていれば restart() で読み直してから開く
    (import キャッシュのせいで「更新したのに変わらない」を防ぐ。版が同じなら何もしない)。"""
    global _instance
    disk = _disk_version()
    if disk and disk != __version__:
        print(u"[plsCamView] 更新を検出: ロード中 v{} → ディスク v{}。読み直します。".format(
            __version__, disk))
        return restart()     # 新モジュールの show() が開く(版が揃うので再帰しない)
    _restore_language()      # プレースホルダ等はツールボックス生成前に作られるため、先に復元する
    from . import ui

    print(u"[plsCamView] v{} ({})".format(__version__, __name__))

    if _instance is not None:
        try:
            if _instance.exists():
                _instance.show()
                return _instance
        except Exception:
            pass
        try:
            _instance.close()
        except Exception:
            pass
        _instance = None

    _instance = ui.PlsCamViewWindow()
    return _instance


def close():
    u"""ウィンドウを閉じる。"""
    global _instance
    if _instance is not None:
        try:
            _instance.close()
        except Exception:
            pass
    _instance = None
    try:
        from . import ui
        ui.cleanup_stale_ui()
    except Exception:
        pass


def instance():
    return _instance


def playblast_mp4(**overrides):
    u"""
    開いている plsCamView のビューを、ツールボックスの MP4 設定で書き出す。
    キーワード引数で上書きできる(output_path / width / height / fps / crf /
    preset / quality / show_ornaments / off_screen / optimize_viewport /
    keep_frames / open_after / ffmpeg_path / start_frame / end_frame)。

        import plsCamView
        plsCamView.playblast_mp4(output_path="D:/out/shot01.mp4")

    Returns: (ok, message, output_path)
    """
    win = _instance
    if win is None or not win.exists():
        win = show()
    return win.do_playblast_mp4(**overrides)


def _clear_instance():
    u"""ui 側の終了処理から呼ばれる内部関数。"""
    global _instance
    _instance = None


def version():
    return __version__


# --------------------------------------------------------------------------
def reset_settings():
    u"""保存済み設定を削除して開き直す。"""
    from . import settings as st
    close()
    st.reset()
    return show()


def _teardown():
    u"""ウィンドウ・MEL フック・残骸 UI をすべて片付ける。"""
    try:
        from . import playblast_hook as _pbh
        _pbh.uninstall()
    except Exception:
        pass
    try:
        close()
    except Exception as e:
        print(u"[plsCamView] close 時のエラー(無視): {}".format(e))
    try:
        from . import ui as _ui
        _ui.cleanup_stale_ui()
    except Exception:
        pass


def _purge_modules():
    u"""
    このパッケージを sys.modules から取り除く。

    親パッケージがある場合、それは属性として古いモジュールオブジェクトを
    持っている。sys.modules を消すだけでは `from <parent> import plsCamView` が
    その古い属性を返してしまうため、親の属性も併せて削除する。
    """
    import sys

    pkg = __name__
    if "." in pkg:
        parent_name, child = pkg.rsplit(".", 1)
        parent = sys.modules.get(parent_name)
        if parent is not None and hasattr(parent, child):
            try:
                delattr(parent, child)
            except Exception:
                pass

    removed = []
    for name in list(sys.modules.keys()):
        if name == pkg or name.startswith(pkg + "."):
            del sys.modules[name]
            removed.append(name)
    return removed


def restart():
    u"""
    Maya を再起動せずに、ディスク上の最新コードで開き直す。

        import plsCamView
        plsCamView.restart()

    パッケージ自身(__init__.py)も含めて完全に読み直すので、
    どのファイルを更新した場合でもこれ 1 つで反映される。
    """
    import importlib

    _teardown()
    removed = _purge_modules()
    print(u"[plsCamView] restart: {} 個のモジュールを破棄して読み直します。".format(
        len(removed)))

    mod = importlib.import_module(__name__)
    return mod.show()


def reload_all():
    u"""
    コード更新後の入れ替え(restart() の別名)。
    以前はサブモジュールのみを破棄していたが、__init__.py の変更が
    反映されないため restart() と同じ動作に統一した。
    """
    return restart()
