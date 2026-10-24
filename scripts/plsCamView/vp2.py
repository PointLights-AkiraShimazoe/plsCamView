# -*- coding: utf-8 -*-
u"""
plsCamView.vp2
==============
Viewport 2.0 のレンダー設定(hardwareRenderingGlobals)へのアクセス。

    Screen-space Ambient Occlusion : ssaoEnable / ssaoAmount / ssaoRadius /
                                     ssaoFilterRadius / ssaoSamples
    Anti-aliasing                  : multiSampleEnable / multiSampleCount /
                                     lineAAEnable

【重要】これらは Maya 全体で共有されるグローバル設定であり、
ビューポート個別の設定ではない。ここで変更すると Maya の全ビューポートに
反映される(Maya の Renderer > Viewport 2.0 の設定画面と同じもの)。
"""
from __future__ import absolute_import

try:
    from maya import cmds
except Exception:
    cmds = None

from .i18n import tr

NODE = "hardwareRenderingGlobals"

# UI 名 -> アトリビュート名
ATTR = {
    "ssaoEnable":       "ssaoEnable",
    "ssaoAmount":       "ssaoAmount",
    "ssaoRadius":       "ssaoRadius",
    "ssaoFilterRadius": "ssaoFilterRadius",
    "ssaoSamples":      "ssaoSamples",
    "aaEnable":         "multiSampleEnable",
    "aaSampleCount":    "multiSampleCount",
    "lineAAEnable":     "lineAAEnable",
}

# multiSampleCount / ssaoSamples の選択肢
AA_SAMPLE_CHOICES = [2, 4, 8, 16]
SSAO_SAMPLE_CHOICES = [8, 16, 32]


# --------------------------------------------------------------------------
def _plug(key):
    attr = ATTR.get(key, key)
    return "{}.{}".format(NODE, attr)


def has(key):
    u"""そのアトリビュートが現在の Maya に存在するか。"""
    if cmds is None:
        return False
    try:
        return bool(cmds.objExists(_plug(key)))
    except Exception:
        return False


def get(key, default=None):
    if not has(key):
        return default
    try:
        return cmds.getAttr(_plug(key))
    except Exception:
        return default


def set_(key, value):
    u"""値を設定。存在しない/失敗した場合は False を返すだけで例外は投げない。"""
    if not has(key):
        return False
    try:
        cmds.setAttr(_plug(key), value)
        return True
    except Exception as e:
        try:
            cmds.warning(u"[plsCamView] " + tr(u"{} の設定に失敗: {}").format(_plug(key), e))
        except Exception:
            pass
        return False


# --------------------------------------------------------------------------
def read_all():
    u"""現在の VP2 設定を dict で取得(設定ファイルのキー名で返す)。"""
    out = {}
    for key in ATTR:
        v = get(key)
        if v is not None:
            out[key] = v
    return out


_MASTER_GATED = ("ssaoEnable", "aaEnable", "lineAAEnable")


def apply_all(data):
    u"""設定 dict(settings.py のキー名)を VP2 に適用する。
    effectsMaster が False のときは SSAO / AA / 線 AA を OFF として適用する(個別の値は dict に残る)。"""
    master = bool(data.get("effectsMaster", True))
    order = ["ssaoEnable", "ssaoAmount", "ssaoRadius", "ssaoFilterRadius",
             "ssaoSamples", "aaEnable", "aaSampleCount", "lineAAEnable"]
    changed = False
    for key in order:
        if key in data:
            v = data[key]
            if not master and key in _MASTER_GATED:
                v = False
            # 値が同じなら setAttr しない(setAttr のたびに VP2 が再評価されて重い)
            cur = get(key)
            if cur is not None and _same(cur, v):
                continue
            if set_(key, v):
                changed = True
    return changed


def _same(a, b):
    try:
        if isinstance(a, bool) or isinstance(b, bool):
            return bool(a) == bool(b)
        return abs(float(a) - float(b)) < 1e-6
    except Exception:
        return a == b


def refresh_viewport():
    if cmds is None:
        return
    try:
        cmds.refresh(force=True)
    except Exception:
        pass
