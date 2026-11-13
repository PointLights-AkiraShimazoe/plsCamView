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

import copy
import json
import os
import unicodedata

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
    "playblastCollapsed": False,          # Playblast カード全体を畳んでいるか(既定: 開く)
    "playblastRangeScene": True,          # Time Range: ON = シーンの再生範囲 / OFF = 下の開始・終了
    "playblastStart": 1,                  # Time Range 開始フレーム(シーン範囲 OFF のとき)
    "playblastEnd": 24,                   # Time Range 終了フレーム(シーン範囲 OFF のとき)
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

    # --- 調整プリセット(FX-PRESETS。仕様は末尾の PRESET_SPEC) ---------------
    "effectPresets": {},           # {名前: {キー: 値}}
    "effectPresetSelected": "",    # 選択中の名前("" = 未選択)

    # --- その他 -----------------------------------------------------------
    "language": "system",          # UI 言語: system / ja / en (v1.8.1。仕様は i18n.py)
    "uiScale": 85,                 # UI 倍率 %(0.9.1。75/85/100/115/125。style.UI_SCALE_DEFAULT と一致させる)
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
    data = copy.deepcopy(DEFAULTS)     # 入れ子の既定値(effectPresets など)を共有しない
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


# ==========================================================================
#  調整プリセット(FX-PRESETS-20261030-01)
# ==========================================================================
#  保存先は上の設定ファイルの追加キー 2 つだけ(既存キー・既存の保存形式は変えない)。
#    PRESET_TABLE_KEY    = {名前: {キー: 値}}       … 保存済みプリセット
#    PRESET_SELECTED_KEY = 名前 / ""                 … 選択中(空 = 未選択)
#  プリセットが扱うのは PRESET_SPEC のキーだけ(利用者が Effects で調整する値と ON/OFF)。
#  カメラ / シーン / 選択 / ビュー配置 / Show / Playblast 出力先など、ここに無いキーは
#  プリセットの保存・切替・Reset のどれでも読まず、書かない。
#    "b" = bool / ("n", 下限, 上限) = 範囲内の有限の数 / ("c", 選択肢) = 選択肢の整数 / "rgb" = 0..1 の 3 要素
#  形・範囲が合わない値(破損・手書きの誤り)は「そのキーは無い」ものとして扱い、適用しない。
PRESET_TABLE_KEY = "effectPresets"
PRESET_SELECTED_KEY = "effectPresetSelected"
PRESET_NAME_MAX = 32
PRESET_DEFERRED = "deferred"     # _preset_apply_current の戻り値: 値は現在値へ入れたが、実環境(Fx プラグイン)が未ロードで未適用(設計上の「適用保留」。失敗ではない)
#  操作結果の種類(PresetOps.last_kind)と、UI に出す短語。文章(詳細)は tooltip 側へ。
PRESET_SHORT = {
    "saved": u"保存済", "updated": u"更新済", "applied": u"適用済", "reset": u"復元",
    "deferred": u"保留", "unsaved": u"未保存", "failed": u"失敗", "unrestored": u"未復帰", "unconfirmed": u"未確認", "invalid": u"不可",
}
PRESET_SPEC = (
    ("effectsMaster", "b"),
    ("ssaoEnable", "b"),
    ("ssaoAmount", ("n", 0.0, 10.0)),
    ("ssaoRadius", ("n", 0.0, 1000.0)),
    ("ssaoFilterRadius", ("n", 0.0, 100.0)),
    ("ssaoSamples", ("c", (8, 16, 32))),
    ("aaEnable", "b"),
    ("aaSampleCount", ("c", (2, 4, 8, 16))),
    ("lineAAEnable", "b"),
    ("shadows", "b"),
)
PRESET_KEYS = tuple(k for k, _ in PRESET_SPEC)
_PRESET_SPEC = dict(PRESET_SPEC)
_MISSING = object()


def _finite(x):
    return (isinstance(x, (int, float)) and not isinstance(x, bool)
            and x == x and x not in (float("inf"), float("-inf")))


def preset_clean_value(key, v):
    u"""(ok, 値の複製)。形・範囲が合わない値は (False, None)。"""
    spec = _PRESET_SPEC.get(key)
    if spec == "b":
        return (True, v) if isinstance(v, bool) else (False, None)
    if spec == "rgb":
        if isinstance(v, (list, tuple)) and len(v) == 3 and all(_finite(x) and 0.0 <= x <= 1.0 for x in v):
            return True, [float(x) for x in v]
        return False, None
    if isinstance(spec, tuple) and spec[0] == "n":
        return (True, v) if _finite(v) and spec[1] <= v <= spec[2] else (False, None)
    if isinstance(spec, tuple) and spec[0] == "c":
        if _finite(v) and v == int(v) and int(v) in spec[1]:
            return True, int(v)
        return False, None
    return False, None


def preset_clean(raw):
    u"""保存済みの 1 件(生データ)から、扱える値だけの新しい dict を作る。dict でない / 扱える値が 1 つも無い場合は None。
    未知のキー・不正な値は含めない(元データには手を付けない)。"""
    if not isinstance(raw, dict):
        return None
    out = {}
    for k in PRESET_KEYS:
        if k in raw:
            ok, v = preset_clean_value(k, raw[k])
            if ok:
                out[k] = v
    return out or None


def _preset_table(data):
    t = data.get(PRESET_TABLE_KEY)
    return t if isinstance(t, dict) else {}


def preset_names(data):
    u"""使えるプリセットの名前(読めない項目は除く)。大文字小文字を無視した名前順。"""
    names = [n for n, raw in _preset_table(data).items() if isinstance(n, str) and preset_clean(raw) is not None]
    return sorted(names, key=lambda n: (n.casefold(), n))


def preset_selected(data):
    u"""選択中のプリセット名。保存名が無い / 読めないときは ""。"""
    n = data.get(PRESET_SELECTED_KEY)
    return n if isinstance(n, str) and n and n in preset_names(data) else u""


def preset_get(data, name):
    u"""保存済みの値を **複製して** 返す(呼び出し側が書き換えても保存済みは変わらない)。無ければ None。"""
    return preset_clean(_preset_table(data).get(name))


def preset_same(a, b):
    u"""プリセットの値同士 / 現在値との比較(数値は 1e-6 の誤差を許す。bool は bool として比べる)。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (list, tuple)) or isinstance(b, (list, tuple)):
        try:
            return len(a) == len(b) and all(preset_same(x, y) for x, y in zip(a, b))
        except Exception:
            return False
    if _finite(a) and _finite(b):
        return abs(float(a) - float(b)) < 1e-6
    return a == b


def preset_is_dirty(data, name):
    u"""選択中プリセットの保存値と現在値が違うか。名前が無い / 読めない(= 比べる相手が無い)ときは False。"""
    vals = preset_get(data, name) if name else None
    if vals is None:
        return False
    for k, v in vals.items():
        if k not in data or not preset_same(data[k], v):
            return True
    return False


def preset_snapshot(data):
    u"""現在値のうち PRESET_KEYS の分を、複製して返す。形・範囲が合わない値は含めない。"""
    out = {}
    for k in PRESET_KEYS:
        if k in data:
            ok, v = preset_clean_value(k, data[k])
            if ok:
                out[k] = v
    return out


def preset_check_name(data, name):
    u"""(正規化した名前, "") または (None, 理由)。前後の空白は除く。重複は大文字小文字を無視して判定(読めない項目の名前も含む)。"""
    if not isinstance(name, str):
        return None, tr(u"名前が空です")
    nm = name.strip()
    if not nm:
        return None, tr(u"名前が空です")
    if len(nm) > PRESET_NAME_MAX:
        return None, tr(u"名前は {} 文字以内にしてください").format(PRESET_NAME_MAX)
    if any(unicodedata.category(c) in ("Cc", "Cf", "Cs", "Co") for c in nm):
        return None, tr(u"使えない文字が含まれています")
    low = nm.casefold()
    for n in _preset_table(data):
        if isinstance(n, str) and n.casefold() == low:
            return None, tr(u"同じ名前があります")
    return nm, u""


class PresetOps(object):
    u"""プリセットの作成・更新・切替・Reset。owner は data(設定 dict)/ _collect() / save_settings() /
    _preset_apply_current()(現在値を実際に適用して成否を返す)を持つ。UI は持たない(UI は ToolBox 側)。
    すべて (成否, 利用者に見せる短い文) を返す。"""

    def __init__(self, owner):
        self.owner = owner
        self.last_kind = u""        # 直前の操作の結果の種類(PRESET_SHORT のキー / "ok")。成否(bool)だけでは区別できない状態を UI へ渡す

    def _ret(self, ok, kind, text):
        self.last_kind = kind
        return ok, text

    @property
    def data(self):
        return self.owner.data

    # -- 照会 --------------------------------------------------------------
    def names(self):
        return preset_names(self.data)

    def selected(self):
        return preset_selected(self.data)

    def is_dirty(self):
        return preset_is_dirty(self.data, self.selected())

    # -- 内部 --------------------------------------------------------------
    def _state(self):
        d = self.data
        # 欠落(キーが無い旧設定)は _MISSING のまま持つ。deepcopy すると sentinel 自体が複製されて「欠落」を判別できなくなる
        return tuple(_MISSING if k not in d else copy.deepcopy(d[k]) for k in (PRESET_TABLE_KEY, PRESET_SELECTED_KEY))

    def _restore_state(self, state):
        d = self.data
        for key, v in zip((PRESET_TABLE_KEY, PRESET_SELECTED_KEY), state):
            if v is _MISSING:
                d.pop(key, None)
            else:
                d[key] = v

    def _persist(self):
        try:
            return bool(save(self.owner._collect()))
        except Exception as e:
            _warn(tr(u"設定の保存に失敗しました: {}").format(e))
            return False

    def _writable_snapshot(self):
        values = preset_snapshot(self.data)
        if len(values) != len(PRESET_KEYS):
            return None
        return values

    # -- 作成 / 更新(保存) --------------------------------------------------
    def save_new(self, name):
        u"""現在値を **新しい** プリセットとして保存し、それを選択する。同名は作らない(更新は update_selected)。"""
        d = self.data
        if PRESET_TABLE_KEY in d and not isinstance(d[PRESET_TABLE_KEY], dict):
            # 壊れた既存テーブル({} へ作り直すと元のデータを失う)。そのまま残して保存を拒否する(キーが無い旧設定は通常どおり作る)
            return self._ret(False, "invalid", tr(u"保存済みプリセットの形式が不正なため保存できません(元のデータは変更していません)"))
        nm, why = preset_check_name(d, name)
        if nm is None:
            return self._ret(False, "invalid", why)
        values = self._writable_snapshot()
        if values is None:
            return self._ret(False, "invalid", tr(u"現在の値に不正な項目があるため保存できません"))
        before = self._state()
        table = d.get(PRESET_TABLE_KEY)
        if table is None:
            table = d[PRESET_TABLE_KEY] = {}
        table[nm] = values
        d[PRESET_SELECTED_KEY] = nm
        if not self._persist():
            self._restore_state(before)
            return self._ret(False, "failed", tr(u"保存に失敗しました。プリセットは変更していません"))
        return self._ret(True, "saved", tr(u"「{}」を保存しました").format(nm))

    def update_selected(self):
        u"""選択中のプリセットを現在値で **上書き** する(新規は作らない)。保存値の未知キーは残す。"""
        d = self.data
        sel = self.selected()
        if not sel:
            return self._ret(False, "invalid", tr(u"更新するプリセットを選んでください"))
        values = self._writable_snapshot()
        if values is None:
            return self._ret(False, "invalid", tr(u"現在の値に不正な項目があるため保存できません"))
        before = self._state()
        table = d[PRESET_TABLE_KEY]
        entry = dict(table[sel]) if isinstance(table.get(sel), dict) else {}
        entry.update(values)
        table[sel] = entry
        if not self._persist():
            self._restore_state(before)
            return self._ret(False, "failed", tr(u"保存に失敗しました。プリセットは変更していません"))
        return self._ret(True, "updated", tr(u"「{}」を更新しました").format(sel))

    # -- 切替 / Reset(保存済みを現在値へ。保存済みは変えない) -------------------
    def select(self, name):
        u"""name のプリセットを適用して選択する。name が "" なら選択を外すだけ(値は変えない)。
        適用に失敗したら元の値へ戻し、選択も変えない。成功の保存は **その場で** 行い、失敗は「未保存」として区別して返す
        (遅延保存に任せて成否を捨てない)。"""
        d = self.data
        if not name:
            d[PRESET_SELECTED_KEY] = u""
            if not self._persist():
                return self._ret(False, "unsaved", tr(u"選択は外しましたが、設定を保存できませんでした(再起動後は元の選択に戻る可能性があります)"))
            return self._ret(True, "ok", u"")
        if name not in self.names():
            return self._ret(False, "invalid", tr(u"プリセットを読めません"))
        return self._apply(name, "applied", tr(u"「{}」を適用しました"))

    def reset(self):
        u"""選択中のプリセットの保存値へ戻す。未選択 / 保存値と同じなら何もしない。"""
        sel = self.selected()
        if not sel:
            return self._ret(False, "invalid", tr(u"プリセットが選ばれていません"))
        if not self.is_dirty():
            return self._ret(True, "ok", u"")
        return self._apply(sel, "reset", tr(u"「{}」の保存値へ戻しました"))

    def _apply(self, name, kind, done_text):
        d = self.data
        vals = preset_get(d, name)                      # 複製。保存済みとは別のオブジェクト
        if vals is None:
            return self._ret(False, "invalid", tr(u"プリセットを読めません"))
        backup = {k: copy.deepcopy(d[k]) for k in vals if k in d}
        absent = [k for k in vals if k not in d]
        for k, v in vals.items():
            d[k] = v
        res = False
        try:
            res = self.owner._preset_apply_current()
        except Exception as e:
            _warn(tr(u"プリセットの適用に失敗しました: {}").format(e))
        if not res:
            for k, v in backup.items():                 # 設定(メモリ)の復帰: ここは必ず行う
                d[k] = v
            for k in absent:
                d.pop(k, None)
            env = False                                 # 実環境の復帰: 戻した値を再適用して確かめる(これも失敗しうる)
            try:
                env = self.owner._preset_apply_current()
            except Exception as e:
                _warn(tr(u"プリセットの適用に失敗しました: {}").format(e))
            if env == PRESET_DEFERRED:                   # 保留(プラグイン未ロード / ロード状態不明)= Maya へ再適用できていない。復帰済みとは言わない
                return self._ret(False, "unconfirmed", tr(u"「{}」を適用できませんでした。設定の値は元に戻しましたが、Maya 側が元に戻ったかは確認できていません(プラグイン未ロードなど)").format(name))
            if env:
                return self._ret(False, "failed", tr(u"「{}」を適用できませんでした。元の値に戻しました").format(name))
            return self._ret(False, "unrestored", tr(u"「{}」を適用できず、Maya 側を元の値へ戻せませんでした(設定の値は元に戻しました。表示が元と違う可能性があります)").format(name))
        deferred = (res == PRESET_DEFERRED)
        d[PRESET_SELECTED_KEY] = name
        if not self._persist():                          # 選択と保存の成否を区別する(適用はできている)
            if deferred:
                return self._ret(False, "unsaved", tr(u"「{}」の値を設定しましたが、設定を保存できませんでした(Maya へは未適用。再起動後は戻る可能性があります)").format(name))
            return self._ret(False, "unsaved", tr(u"「{}」を適用しましたが、設定を保存できませんでした(再起動後は戻る可能性があります)").format(name))
        if deferred:
            return self._ret(True, "deferred", tr(u"「{}」の値を設定しました。Maya へは未適用です(プラグイン未ロード。ロード後に反映されます)").format(name))
        return self._ret(True, kind, done_text.format(name))
