# -*- coding: utf-8 -*-
"""
plsCamView.settings
===================
ツールの状態(カメラ / SSAO / AA / Show / ドック位置 / ウィンドウジオメトリ など)を
JSON で永続化する。

保存先:
    <Maya userPrefDir>/plsCamView/settings.json
    例) C:/Users/<user>/Documents/maya/2026/prefs/plsCamView/settings.json

ユーザープリファレンス配下に置くため、ツールフォルダ自体は読み取り専用の
共有ドライブに置いても動作する。
"""
from __future__ import absolute_import

import json
import os

try:
    from maya import cmds
except Exception:                                   # Maya 外(構文チェック等)
    cmds = None

from .i18n import tr

# --------------------------------------------------------------------------
_APP_NAME = "plsCamView"
_FILE_NAME = "settings.json"

# 既定値。ここに無いキーは load() で自動的に補完される。
DEFAULTS = {
    # --- ウィンドウ -------------------------------------------------------
    "windowSize": [1280, 800],     # cmds.window の widthHeight
    "windowTopLeft": None,         # cmds.window の topLeftCorner [top, left]
    "dockArea": "right",           # ツールボックスの位置 left / right / top / bottom
    "toolboxPercent": 26,          # ツールボックス側のペイン比率(%)
    "toolboxPercentH": None,      # 上下配置のときの高さ比率(None = 初回に中身の高さから決める)

    # --- カメラ / ビュー --------------------------------------------------
    "camera": "persp",             # (互換) Playblast 対象ビューのカメラ
    "showStartupCameras": True,    # persp/top/front/side をリストに含めるか
    # ビュー一覧(最大 4)。各要素: {"camera": str, "poppedOut": bool,
    #                              "windowSize": [w, h], "windowTopLeft": [top, left]}
    # 空なら "camera" から 1 ビューを作る。
    "views": [],
    "viewLayout": "horizontal",    # ドック中のビューの配置: horizontal / vertical / grid
    "playblastViews": None,       # Noneは旧playblastViewを引き継ぐ
    "playblastMulti": False,
    "playblastCombine": False,
    "playblastKeepIndividuals": True,
    "playblastView": 0,            # Playblast の対象ビュー(index)

    # --- Effects master -----------------------------------------------------
    "effectsMaster": True,         # False で SSAO / AA / 線 AA を一括 OFF(個別設定は保持)
    "effectsCollapsed": False,     # Effects カード(SSAO / AA)を畳んでいるか

    # --- Screen-space Ambient Occlusion ----------------------------------
    "ssaoEnable": False,
    "ssaoAmount": 1.0,
    "ssaoRadius": 16,
    "ssaoFilterRadius": 16,
    "ssaoSamples": 16,

    # --- Anti-aliasing ----------------------------------------------------
    "aaEnable": False,             # multiSampleEnable
    "aaSampleCount": 8,            # multiSampleCount
    "lineAAEnable": False,         # lineAAEnable (線のスムージング)

    # --- Shadow -----------------------------------------------------------
    "shadows": False,              # modelEditor -shadows (Lighting > Shadows)

    # --- Show -------------------------------------------------------------
    "showPreset": "all",           # all / none / polygon
    "showJoints": False,
    "showNurbsCurves": False,

    # --- Playblast --------------------------------------------------------
    "forcePlayblastTarget": False,
    # "direct": 常に editorPanelName を明示してツール側で playblast を実行する(既定)
    # "auto"  : フォーカス移動が効いていれば Maya 標準の処理に任せる
    "playblastMode": "direct",
    # auto モードでフォーカス移動が効かなかったとき、ツール側で実行するか
    "playblastFallback": True,
    # Force Playblast Target が ON の間、Python の getPanel(withFocus=True) が
    # このビューを返すようにするか。外部ツールが「アクティブビューを取得して
    # 設定変更 → playblast」する場合、これが OFF だと設定変更だけ別ビューに向かう。
    "forceActivePanel": True,
    # 切り分け用の詳細ログを Script Editor に出すか
    "playblastVerbose": False,

    # --- Playblast 出力(ツール内の [Playblast 実行] ボタン) --------------
    # "maya": Maya 標準の Playblast 設定で実行 / "mp4": ffmpeg で MP4 に書き出す
    "outputMode": "maya",
    "playblastSettingsCollapsed": True,   # Playblast カードの Settings を畳んでいるか(既定: 畳む)
    "mp4Width": 1920,
    "mp4Height": 1080,
    "mp4Fps": 30.0,
    "mp4UseSceneFps": True,        # ON ならシーンの時間単位から fps を決める
    "mp4Crf": 18,                  # H.264 品質(0-51、低いほど高画質)
    "mp4Preset": "slow",           # x264 プリセット
    "mp4Quality": 100,             # playblast の quality(1-100)
    "mp4FfmpegPath": "",           # 空 = 自動解決(同梱 bin → PATH → 既知の場所)
    "mp4ShowOrnaments": False,     # showOrnaments
    "mp4OffScreen": False,         # offScreen
    # ---- Gate / 構図ガイド(オーバーレイ、1.8.0) ----
    "gateEnabled": False,
    "gateMaskColor": [0.0, 0.0, 0.0],
    "gateMaskOpacity": 0.6,
    "gateLineColor": [1.0, 1.0, 1.0],
    "gateLineWidth": 1.0,
    "innerGateEnabled": [False, False, False],   # ゲートごとの ON/OFF
    "innerGatePercent": [90.0, 80.0, 70.0],
    "innerGateColor": [[1.0, 0.85, 0.2], [0.3, 0.9, 1.0], [1.0, 0.45, 0.6]],
    "innerGateOpacity": [0.3, 0.3, 0.3],   # 塗りの不透明度
    "innerGateStroke": [True, True, True], # 線(1px)
    "innerGateFill": [False, False, False], # 塗り(内側ゲートの外側)
    "innerGateDashed": True,
    "gateMaskCollapsed": False,    # Gate カード内サブセクションの折り畳み
    "innerGatesCollapsed": False,
    "guidesCollapsed": False,
    "guidesEnabled": True,         # 構図ガイド全体の ON/OFF
    "guideThirds": False,
    "guideGrid": False,
    "guideArmature": False,
    "guideCenter": False,
    "guideRatio": 0,               # 0 黄金 φ / 1 白銀 √2
    "guideFit": 0,                 # 0 ゲート / 1..3 内側ゲート N / 4 ビュー全体
    "guideThirdsColor": [0.3, 0.5, 1.0],
    "guideGridColor": [1.0, 0.25, 0.25],
    "guideArmatureColor": [1.0, 0.9, 0.2],
    "guideOpacity": 0.8,
    "guideWidth": 1.0,
    "mp4FromRenderSettings": False, # 幅/高さをレンダー設定に合わせ、ゲート範囲ぴったりで書き出す(1.8.0)
    "mp4OptimizeViewport": True,   # 画角固定 / Polygon のみ / Use All Lights / SSAO 等
    "mp4KeepFrames": False,        # 中間 PNG 連番を残す
    "mp4OpenAfter": True,          # 完了後に MP4 を開く
    "mp4OutputPath": "",           # 空 = <project>/movies/<scene>_<camera>.mp4

    # --- その他 -----------------------------------------------------------
    "language": "system",          # UI 言語: system / ja / en (v1.8.1。仕様は i18n.py)
    "applyVp2OnStartup": True,     # 起動時に SSAO/AA を復元適用するか
    # ビューを既存パネルの複製(modelPanel -copy)として作るか。
    # メニュー/ツールセットに不具合が出る場合は false にすると新規作成になる。
    "useCopyPanel": True,
}


# --------------------------------------------------------------------------
def config_dir():
    """設定ファイルを置くディレクトリ(無ければ作成)。"""
    base = None
    if cmds is not None:
        try:
            base = cmds.internalVar(userPrefDir=True)
        except Exception:
            base = None
    if not base:
        base = os.path.join(os.path.expanduser("~"), ".maya")
    d = os.path.join(base.replace("\\", "/"), _APP_NAME)
    try:
        if not os.path.isdir(d):
            os.makedirs(d)
    except Exception:
        pass
    return d


def config_path():
    return os.path.join(config_dir(), _FILE_NAME).replace("\\", "/")


# --------------------------------------------------------------------------
def load():
    """設定を dict で返す。欠損キーは DEFAULTS で補完。"""
    data = dict(DEFAULTS)
    path = config_path()
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                saved = json.load(f)
            if isinstance(saved, dict):
                for k, v in saved.items():
                    data[k] = v
        except Exception as e:
            _warn(u"設定の読み込みに失敗しました({}): {}".format(path, e))
    return data


def save(data):
    """設定 dict を保存。失敗しても例外は投げない(警告のみ)。"""
    path = config_path()
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
        return True
    except Exception as e:
        _warn(tr(u"設定の保存に失敗しました({}): {}").format(path, e))
        return False


def reset():
    """設定ファイルを削除して初期化。"""
    path = config_path()
    try:
        if os.path.isfile(path):
            os.remove(path)
        return True
    except Exception as e:
        _warn(tr(u"設定の初期化に失敗しました: {}").format(e))
        return False


# --------------------------------------------------------------------------
def _warn(msg):
    text = u"[plsCamView] {}".format(msg)
    if cmds is not None:
        try:
            cmds.warning(text)
            return
        except Exception:
            pass
    print(text)
