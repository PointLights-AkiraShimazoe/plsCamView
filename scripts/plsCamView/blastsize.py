# -*- coding: utf-8 -*-
u"""Playblast の寸法処理(Maya に依存しない純粋な部分。plsCamView / plsFxView で同一のファイル)。

背景: libx264 + yuv420p は幅・高さが偶数でないと失敗する(例 1913x1074 → "width not divisible by 2")。
Maya 標準の Playblast(形式 avi / qt / 画像)は奇数でも書けるので、MP4 化と合成だけで起きる。

方針(画像の内容は切り落とさない):
  - 要求された幅・高さは検査して整数にする(0 / 負 / NaN / 無限大は撮影の前に弾く。端数は四捨五入)
  - エンコードの寸法は「Maya が実際に書いた画像の寸法」から決める(要求値ではない)
  - 奇数なら右 / 下へ黒を 1px 足して偶数にする(pad。左上基準なので内容の位置は動かない。crop・拡縮はしない)
  - 合成(Multi)のキャンバスも同じ規則で偶数へ切り上げる(レイアウトはその偶数サイズで割り付ける)
  - 書いた動画は ffmpeg の出力から実際の寸法を読み、偶数かつ期待どおりか確かめる
"""
from __future__ import absolute_import

import math
import os
import re
import struct

MAX_SIDE = 16384


def normalize_dimension(value, label):
    u"""要求された幅 / 高さを整数にする。1 以上 MAX_SIDE 以下だけ通す(端数は四捨五入)。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(u"{} が数値ではありません: {!r}".format(label, value))
    if not math.isfinite(f):
        raise ValueError(u"{} が有限の数値ではありません: {!r}".format(label, value))
    n = int(math.floor(f + 0.5))
    if n < 1:
        raise ValueError(u"{} は 1 以上にしてください(指定値: {!r})".format(label, value))
    if n > MAX_SIDE:
        raise ValueError(u"{} は {} 以下にしてください(指定値: {!r})".format(label, MAX_SIDE, value))
    return n


def normalize_size(width, height):
    return normalize_dimension(width, u"幅"), normalize_dimension(height, u"高さ")


def _finite(value, label):
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueError(u"{} が数値ではありません: {!r}".format(label, value))
    if not math.isfinite(f):
        raise ValueError(u"{} が有限の数値ではありません: {!r}".format(label, value))
    return f


def normalize_range(start, end):
    u"""フレーム範囲を整数(四捨五入)にし、終了 < 開始は ValueError。"""
    s = int(math.floor(_finite(start, u"開始フレーム") + 0.5))
    e = int(math.floor(_finite(end, u"終了フレーム") + 0.5))
    if e < s:
        raise ValueError(u"終了フレーム({})は開始フレーム({})以上にしてください。".format(e, s))
    return s, e


def normalize_fps(fps):
    f = _finite(fps, u"FPS")
    if f <= 0 or f > 1000:
        raise ValueError(u"FPS は 0 より大きく 1000 以下にしてください(指定値: {!r})".format(fps))
    return f


def normalize_crf(crf):
    n = int(math.floor(_finite(crf, u"CRF") + 0.5))
    if n < 0 or n > 51:
        raise ValueError(u"CRF は 0〜51 にしてください(指定値: {!r})".format(crf))
    return n


def even_up(n):
    u"""偶数へ切り上げ(最小 2)。偶数はそのまま。"""
    n = int(n)
    if n < 2:
        return 2
    return n + (n % 2)


def even_size(width, height):
    return even_up(width), even_up(height)


def png_size(path):
    u"""PNG の IHDR から (幅, 高さ)。PNG でない / 壊れていれば None。"""
    try:
        with open(path, "rb") as f:
            head = f.read(24)
    except (IOError, OSError):
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        return None
    w, h = struct.unpack(">II", head[16:24])
    if w < 1 or h < 1:
        return None
    return int(w), int(h)


def sequence_size(files):
    u"""画像連番の実寸法。1 枚も無い / 読めない / 寸法が混在するときは ValueError。"""
    if not files:
        raise ValueError(u"PNG 連番が 1 枚も作成されませんでした。")
    first = None
    for p in files:
        s = png_size(p)
        if s is None:
            raise ValueError(u"画像の寸法を読めません: {}".format(p))
        if first is None:
            first = s
        elif s != first:
            raise ValueError(u"連番の画像寸法が一定ではありません: {} は {}x{}、先頭は {}x{}".format(
                os.path.basename(p), s[0], s[1], first[0], first[1]))
    return first


def pad_filter(width, height):
    u"""奇数のときだけ pad フィルタ(右 / 下に黒)。偶数なら空文字(= 現行の ffmpeg コマンドと同一)。"""
    ew, eh = even_size(width, height)
    if (ew, eh) == (width, height):
        return u""
    return u"pad={}:{}:0:0:color=black".format(ew, eh)


_VIDEO_SIZE = re.compile(r"Video:.*?[ ,](\d{1,5})x(\d{1,5})(?=[ ,\[])")


def parse_video_size(ffmpeg_info_text):
    u"""`ffmpeg -i <file>` の標準エラーから最初の映像ストリームの (幅, 高さ)。無ければ None。"""
    m = _VIDEO_SIZE.search(ffmpeg_info_text or u"")
    return (int(m.group(1)), int(m.group(2))) if m else None
