# -*- coding: utf-8 -*-
u"""試験・診断用: offscreen Qt に実フォントを読ませ、フォントが解決できない環境を合格にしない。

背景(2026-10-24 Windows での実行): Qt 6.11 の offscreen プラットフォームは Windows でフォント DB が空になり
(QFontInfo.family() が空・pixelSize -1)、文字幅が偽のメトリクスになる。その状態で幅の試験を通す/落とすと
本体を誤った値に合わせてしまうため、試験・診断だけで以下を行う(本体コード・ユーザー環境は変更しない):

1. QApplication 生成前に prepare(): 既定で QT_QPA_PLATFORM=offscreen。Windows では QT_QPA_FONTDIR が
   未指定なら <WINDIR>/Fonts を指す(読み取りのみ。外部取得なし)。
2. QApplication 生成後に load_and_verify(app): Windows では標準 UI フォント(Segoe UI / Yu Gothic UI 系 /
   Meiryo / Consolas)を QFontDatabase.addApplicationFont で明示ロードし、実際に解決できたかを確認する。
   解決できなければ FontEnvError(試験は失敗扱い。skip にしない)。
"""
from __future__ import print_function
import os
import sys

_WIN_FONT_FILES = (
    "segoeui.ttf", "segoeuib.ttf", "segoeuisl.ttf",
    "YuGothR.ttc", "YuGothM.ttc", "YuGothB.ttc",
    "meiryo.ttc", "meiryob.ttc",
    "consola.ttf", "consolab.ttf",
    "msgothic.ttc",
)
# Windows で解決できなければならない UI フォント(製品の FONT_FAMILY が実際に当たる候補)
_WIN_REQUIRED_LATIN = ("Segoe UI",)
_WIN_REQUIRED_JA = ("Yu Gothic UI", "Meiryo UI", "Yu Gothic", "Meiryo")


class FontEnvError(RuntimeError):
    pass


def _win_font_dir():
    d = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    return d if os.path.isdir(d) else None


def prepare():
    u"""QApplication 生成前に呼ぶ。環境変数だけを設定する(このプロセス内のみ)。"""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if os.name == "nt" and not os.environ.get("QT_QPA_FONTDIR"):
        d = _win_font_dir()
        if d:
            os.environ["QT_QPA_FONTDIR"] = d


def _families(QtGui):
    db = QtGui.QFontDatabase
    try:
        return set(db.families())          # PySide6(静的メソッド)
    except TypeError:
        return set(db().families())        # PySide2(インスタンスメソッド)


def load_and_verify(QtGui, QtWidgets=None):
    u"""QApplication 生成後に呼ぶ。読み込んだフォントと解決結果を dict で返す。無効環境は FontEnvError。"""
    info = {"platform": QtGui.QGuiApplication.platformName(), "fontdir": os.environ.get("QT_QPA_FONTDIR"),
            "loaded": [], "failed": []}
    if os.name == "nt":
        d = _win_font_dir()
        if d is None:
            raise FontEnvError(u"Windows のフォントフォルダが見つかりません(WINDIR/Fonts)")
        for name in _WIN_FONT_FILES:
            p = os.path.join(d, name)
            if not os.path.isfile(p):
                continue
            fid = QtGui.QFontDatabase.addApplicationFont(p)
            fams = list(QtGui.QFontDatabase.applicationFontFamilies(fid)) if fid >= 0 else []
            (info["loaded"] if fid >= 0 else info["failed"]).append([name, fams])
    fams = _families(QtGui)
    info["families_count"] = len(fams)

    def _resolved(name):
        f = QtGui.QFont(name)
        f.setPixelSize(14)
        fi = QtGui.QFontInfo(f)
        fm = QtGui.QFontMetrics(f)
        return {"req": name, "resolved": fi.family(), "px": fi.pixelSize(),
                "w_latin": fm.horizontalAdvance(u"Wg"), "w_ja": fm.horizontalAdvance(u"日本語")}

    if os.name == "nt":
        latin = [n for n in _WIN_REQUIRED_LATIN if n in fams]
        ja = [n for n in _WIN_REQUIRED_JA if n in fams]
        info["latin"] = latin
        info["ja"] = ja
        if not latin or not ja:
            raise FontEnvError(u"Windows 標準 UI フォントを解決できません(Segoe UI={} / 日本語={})。"
                               u"偽メトリクスでの幅試験は無効".format(latin, ja))
        probe = [_resolved(latin[0]), _resolved(ja[0])]
    else:
        probe = [_resolved(QtWidgets.QApplication.font().family() if QtWidgets else "sans-serif")]
    info["probe"] = probe
    for p in probe:
        if not p["resolved"] or p["px"] <= 0 or p["w_latin"] <= 0:
            raise FontEnvError(u"フォントが解決できない(偽メトリクス)環境: {}".format(p))
    return info


def font_env_summary(info):
    return u"platform={} fontdir={} families={} probe={}".format(
        info.get("platform"), info.get("fontdir"), info.get("families_count"),
        [(p["req"], p["resolved"], p["px"]) for p in info.get("probe", [])])
