# -*- coding: utf-8 -*-
"""FX-PRESETS-20261030-01: 調整プリセット(Effects の値と ON/OFF の名前付き保存・切替・Reset)の試験。Cam / Fx 共通(PKG_DIR で対象パッケージを選ぶ)。

実 Maya / GPU は使わない。test_show_views.py の StubCmds / FakeWin(実物の ToolBox)の上に、実物の settings.PresetOps・実物の Window メソッド
(Cam: _preset_apply_current / apply_shadows / vp2、Fx: apply_effects / _preset_apply_current)を載せ、設定ファイルは実際に一時フォルダへ書いて読み直す。
VP2 のアトリビュート(Cam)と plsFxView プラグイン(Fx)は記録・失敗注入できる小さなスタブ。
これは「コード経路」の確認であり、実 Maya での描画・プラグインの実適用・マウス操作の証明ではない。

使い方: PKG_DIR=<scripts/パッケージ> python3 -I tests/test_presets.py
"""
import copy
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import test_show_views as T            # noqa: E402  (PKG_DIR を読んでパッケージを読み込む)
from test_show_views import (StubCmds, FakeWin, viewsmod, vpmod, ui, i18n, app, qt, settings, IS_FX, WindowCls, PKG_DIR)   # noqa: E402

import importlib                       # noqa: E402
vp2mod = importlib.import_module(T.PACKAGE + ".vp2")
S = settings
KEYS = S.PRESET_KEYS
DEF = S.DEFAULTS

# プリセットが決して触れてはならない状態(カメラ / ビュー配置 / Show / Playblast 出力先 / ゲート・ガイド / 言語 / ウィンドウなど)
UNRELATED = {
    "camera": "camX", "views": [{"camera": "camX", "poppedOut": False}], "viewLayout": "grid", "playblastViews": [1, 2],
    "playblastMulti": True, "playblastView": 1, "showPreset": "polygon", "showJoints": True, "showNurbsCurves": True,
    "forcePlayblastTarget": True, "playblastMode": "auto", "outputMode": "mp4", "mp4OutputPath": "X:/out/keep.mp4",
    "mp4Width": 1234, "mp4Crf": 23, "playblastStart": 7, "playblastEnd": 99, "language": "en", "uiScale": 115,
    "dockArea": "left", "toolboxPercent": 33, "windowSize": [900, 700], "windowTopLeft": [10, 20],
    "effectsCollapsed": True, "showStartupCameras": False, "futureUnknownKey": {"a": [1, 2, 3]},
}
if IS_FX:
    UNRELATED.update({"gateEnabled": True, "gateMaskOpacity": 0.4, "guideThirds": True, "guideOpacity": 0.33,
                      "innerGatePercent": [91.0, 82.0, 73.0], "gradeDetailCollapsed": False})
else:
    UNRELATED.update({"applyVp2OnStartup": False})


UI_HI = {} if IS_FX else {"ssaoAmount": 2.0, "ssaoRadius": 48.0, "ssaoFilterRadius": 32.0}   # Cam のスライダ範囲(Maya に問い合わせられないときの既定)


# --------------------------------------------------------------------------
#  値の作り方(全キー・形と範囲に合う、既定とも互いにも違う値)
# --------------------------------------------------------------------------
def _varied(key, which=1):
    spec = S._PRESET_SPEC[key]
    d = DEF[key]
    if spec == "b":
        return (not d) if which == 1 else bool(d)
    if spec == "rgb":
        return [0.25, 0.5, 0.75] if which == 1 else [0.9, 0.1, 0.4]
    if spec[0] == "c":
        others = [c for c in spec[1] if c != d]
        if which == 1:
            return others[0]
        return others[-1] if len(others) > 1 else d          # 選択肢が 2 つだけのキーは、2 つ目の値を既定へ戻す
    lo, hi = spec[1], spec[2]
    hi = min(hi, UI_HI.get(key, hi))                  # UI(スライダ)の上限を超えない値にする(実操作の試験でも使うため)
    for frac in ((0.37, 0.61) if which == 1 else (0.83, 0.19)):
        v = lo + (hi - lo) * frac
        if isinstance(d, int) and not isinstance(d, bool):
            v = int(round(v))
        else:
            v = round(v, 3)
        if abs(v - d) > 1e-3 and lo <= v <= hi:
            return v
    raise AssertionError(key)


def varied_all(which=1):
    return {k: _varied(k, which) for k in KEYS}


def table_of(win):
    return copy.deepcopy(win.data.get(S.PRESET_TABLE_KEY))


# --------------------------------------------------------------------------
#  スタブ
# --------------------------------------------------------------------------
class Vp2Stub(object):
    u"""Cam: hardwareRenderingGlobals のアトリビュート(読み戻せる。書込みを無視 / 失敗 / 存在しないを注入できる)。"""

    def __init__(self):
        self.vals = {"ssaoEnable": False, "ssaoAmount": 1.0, "ssaoRadius": 16, "ssaoFilterRadius": 16, "ssaoSamples": 16,
                     "multiSampleEnable": False, "multiSampleCount": 8, "lineAAEnable": False}
        self.locked = set()
        self.raises = set()
        self.missing = set()
        self.warnings = []
        self.writes = []

    def _name(self, plug):
        return plug.split(".", 1)[1]

    def objExists(self, plug):
        return self._name(plug) in self.vals and self._name(plug) not in self.missing

    def getAttr(self, plug):
        return self.vals[self._name(plug)]

    def setAttr(self, plug, v):
        n = self._name(plug)
        self.writes.append((n, v))
        if n in self.raises:
            raise RuntimeError("setAttr failed: " + n)
        if n not in self.locked:
            self.vals[n] = v

    def warning(self, msg):
        self.warnings.append(msg)

    def refresh(self, **kw):
        pass

    def attributeQuery(self, *a, **k):
        raise RuntimeError("no range")


class FakeVP(object):
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def set_shadows(self, on):
        self.calls.append(bool(on))
        return self.ok


class FxPlugin(object):
    u"""Fx: pkg.is_loaded / set_params / grade_supported / grade_flags の差し替え先。呼出し引数を記録し、失敗を注入できる。"""

    def __init__(self):
        self.loaded = True
        self.fail = False
        self.fail_first = 0          # 最初の N 回の呼出しだけ失敗させる(その後は成功 = 戻した値の再適用が通る)
        self.calls = []

    def is_loaded(self):
        return self.loaded

    def set_params(self, **kw):
        self.calls.append(dict(kw))
        if self.fail or self.fail_first > 0:
            self.fail_first = max(0, self.fail_first - 1)
            raise RuntimeError("plugin rejected")
        return True

    def grade_supported(self):
        return True

    def grade_flags(self, d):
        return {"gradeExposure": float(d.get("gradeExposure", 0.0)), "gradeEnabled": bool(d.get("gradeEnabled", False)),
                "gradeFilter": tuple(d.get("gradeFilter", (1, 1, 1)))}


class PresetWin(FakeWin):
    u"""FakeWin に、実物の PresetOps と、実物の Window メソッド(プリセット適用 / 同期 / Effects 適用 / Shadow 適用)を載せる。"""
    _gateSuppressed = False

    def __init__(self, data=None):
        FakeWin.__init__(self, data or {})
        self.data = copy.deepcopy(self.data)          # FakeWin は DEFAULTS を浅くコピーする。入れ子の既定値を共有しない
        self.presets = S.PresetOps(self)
        self.vps = []
        self.views = types.SimpleNamespace(each_viewport=lambda: iter(self.vps))
        self._savePending = False
        self._saveTimerArmed = True          # 実物の save_settings を使うが、300ms のタイマは張らない(ファイルは試験が明示的に書く)

    def _collect(self):
        return self.data

    def save_settings(self, *a, **k):
        self.saves += 1
        return WindowCls.save_settings(self)      # 実物(プリセット欄の同期を含む)


for _n in ("_preset_sync", "_preset_apply_current", "apply_shadows", "apply_effects"):
    if hasattr(WindowCls, _n):
        setattr(PresetWin, _n, getattr(WindowCls, _n))


class WindowWiring(unittest.TestCase):
    def test_window_creates_preset_ops_in_init(self):
        import ast
        src = (PKG_DIR / "ui.py").read_text(encoding="utf-8")
        cls = [n for n in ast.parse(src).body if isinstance(n, ast.ClassDef) and n.name == WindowCls.__name__][0]
        init = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "__init__"][0]
        hit = [n for n in ast.walk(init) if isinstance(n, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == "presets" for t in n.targets)
            and isinstance(n.value, ast.Call) and getattr(n.value.func, "attr", "") == "PresetOps"]
        self.assertEqual(len(hit), 1)
        for name in ("_preset_sync", "_preset_apply_current"):
            self.assertTrue(hasattr(WindowCls, name), name)


class Base(unittest.TestCase):
    def setUp(self):
        self.stub = StubCmds()
        self.vp2 = Vp2Stub()
        self.plugin = FxPlugin()
        self.tmp = tempfile.mkdtemp(prefix="presettest_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._saved = {}
        for m in (vpmod, viewsmod, ui, settings):
            self._saved[m] = getattr(m, "cmds", None)
            m.cmds = self.stub
        self._saved[vp2mod] = getattr(vp2mod, "cmds", None)
        vp2mod.cmds = self.vp2
        self._saved_cfg = settings.config_dir
        settings.config_dir = lambda: self.tmp
        self._saved_pkg = {n: getattr(T.pkg, n, None) for n in ("is_loaded", "set_params", "grade_supported", "grade_flags")}
        for n in self._saved_pkg:
            setattr(T.pkg, n, getattr(self.plugin, n))
        self.addCleanup(self._restore)

    def _restore(self):
        settings.config_dir = self._saved_cfg
        for m, v in self._saved.items():
            m.cmds = v
        for n, v in self._saved_pkg.items():
            if v is None:
                if hasattr(T.pkg, n):
                    delattr(T.pkg, n)
            else:
                setattr(T.pkg, n, v)
        app.processEvents()

    # -- 構築 ----------------------------------------------------------
    def make(self, data=None, build_ui=True, fresh_load=False):
        base = settings.load() if fresh_load else {}
        d = dict(base)
        d.update(data or {})
        win = PresetWin(d)
        if fresh_load:
            win.data = settings.load()
            win.data.update(data or {})
        win.vps = [FakeVP(), FakeVP()]
        if build_ui:
            tb = ui.ToolBox(win)
            self.addCleanup(tb.deleteLater)
            win.toolbox = tb
            tb.pull(dict(settings.DEFAULTS, **win.data))
        return win

    def set_current(self, win, values):
        win.data.update(copy.deepcopy(values))

    def settings_file(self):
        with open(settings.config_path(), "r", encoding="utf-8") as f:
            return json.load(f)

    def write_settings_file(self, obj):
        with open(settings.config_path(), "w", encoding="utf-8") as f:
            if isinstance(obj, str):
                f.write(obj)
            else:
                json.dump(obj, f, ensure_ascii=False)

    def reset_hidden(self, win):
        return win.toolbox.presetResetBtn.isHidden()


# ==========================================================================
class KeySetAndNames(Base):
    def test_key_set_is_explicit_and_stays_inside_effects(self):
        self.assertEqual(len(KEYS), 39 if IS_FX else 10)
        self.assertEqual(len(set(KEYS)), len(KEYS))
        for k in KEYS:
            self.assertIn(k, DEF)
            ok, v = S.preset_clean_value(k, DEF[k])
            self.assertTrue(ok, "既定値がプリセットの形・範囲に合わない: " + k)
            self.assertTrue(S.preset_same(v, DEF[k]), k)
        forbidden = re.compile(r"^(camera|views?|viewLayout|playblast|mp4|outputMode|show|force|gate|innerGate|guide|window|dock|toolbox|"
                               r"language|uiScale|useCopyPanel|applyVp2|effectPresets|effectPresetSelected)|Collapsed$")
        for k in KEYS:
            self.assertIsNone(forbidden.search(k), "プリセットが扱ってはならないキー: " + k)

    def test_fx_keys_match_apply_path_and_grade_spec(self):
        if not IS_FX:
            self.skipTest("Fx のみ")
        src = (PKG_DIR / "ui.py").read_text(encoding="utf-8")
        body = src[src.index("    def apply_effects("):src.index("    # ---", src.index("    def apply_effects("))]
        grade = set(k for k in KEYS if k.startswith("grade"))
        self.assertEqual(grade, set(k for k in T.pkg.GRADE_DEFAULTS))      # グレードの全キー(折畳みは GRADE_DEFAULTS に無い)
        for k in KEYS:
            if k not in grade:
                self.assertIn('d.get("%s"' % k, body, "Effects の適用経路が読まないキー: " + k)

    def test_name_validation(self):
        d = {S.PRESET_TABLE_KEY: {"Look A": {"effectsMaster": True}, u"日本語": {}}}
        for bad in ("", "   ", u"\u3000\u3000", None, 5, "x" * (S.PRESET_NAME_MAX + 1), "a\x00b", "a\nb", u"a\u200bb",
                    "look a", "  LOOK A ", u"日本語"):
            nm, why = S.preset_check_name(d, bad)
            self.assertIsNone(nm, repr(bad))
            self.assertTrue(why, repr(bad))
        nm, why = S.preset_check_name(d, u"  \u3000夜景  ")
        self.assertEqual((nm, why), (u"夜景", u""))
        self.assertEqual(S.preset_check_name(d, "x" * S.PRESET_NAME_MAX)[0], "x" * S.PRESET_NAME_MAX)

    def test_clean_value_rejects_bad_shapes(self):
        k_bool = [k for k in KEYS if S._PRESET_SPEC[k] == "b"][0]
        k_num = [k for k in KEYS if isinstance(S._PRESET_SPEC[k], tuple) and S._PRESET_SPEC[k][0] == "n"][0]
        k_ch = [k for k in KEYS if isinstance(S._PRESET_SPEC[k], tuple) and S._PRESET_SPEC[k][0] == "c"][0]
        for v in (1, 0, "true", None, [True]):
            self.assertFalse(S.preset_clean_value(k_bool, v)[0], repr(v))
        for v in (True, "1", None, float("nan"), float("inf"), -1e9, 1e9, [1]):
            self.assertFalse(S.preset_clean_value(k_num, v)[0], repr(v))
        for v in (True, "2", None, 1.5, 12345, [2]):
            self.assertFalse(S.preset_clean_value(k_ch, v)[0], repr(v))
        self.assertFalse(S.preset_clean_value("noSuchKey", 1)[0])
        if IS_FX:
            for v in ([1, 1], [1, 1, 2.5], "abc", [True, 1, 1], [float("nan"), 0, 0], None):
                self.assertFalse(S.preset_clean_value("gradeFilter", v)[0], repr(v))


# ==========================================================================
class SaveAndReload(Base):
    def test_new_save_persists_and_reloads_after_restart(self):
        win = self.make()
        self.set_current(win, varied_all(1))
        ok, msg = win.presets.save_new(u"  夜景  ")
        self.assertTrue(ok, msg)
        self.assertEqual(win.presets.names(), [u"夜景"])
        self.assertEqual(win.presets.selected(), u"夜景")
        self.assertFalse(win.presets.is_dirty())
        # 再起動相当: ファイルから読み直す
        raw = self.settings_file()
        self.assertIn(S.PRESET_TABLE_KEY, raw)
        win2 = self.make(fresh_load=True)
        self.assertEqual(win2.presets.names(), [u"夜景"])
        self.assertEqual(win2.presets.selected(), u"夜景")
        for k, v in varied_all(1).items():
            self.assertTrue(S.preset_same(win2.data[k], v), k)         # 現在値も保存されている
        self.assertFalse(win2.presets.is_dirty())
        self.assertEqual(set(S.preset_get(win2.data, u"夜景")), set(KEYS))

    def test_save_keeps_existing_settings_and_unknown_keys(self):
        seed = dict(DEF)
        seed.update(UNRELATED)
        self.write_settings_file(seed)
        win = self.make(fresh_load=True)
        before = self.settings_file()
        self.set_current(win, varied_all(1))
        self.assertTrue(win.presets.save_new("A")[0])
        after = self.settings_file()
        for k, v in before.items():
            if k in KEYS or k in (S.PRESET_TABLE_KEY, S.PRESET_SELECTED_KEY):
                continue
            self.assertEqual(after[k], v, "既存キーが変わった: " + k)
        self.assertEqual(set(after) - set(before), set())               # 既存キー以外が増えていない(effectPresets 系は DEFAULTS 補完で既に在る)
        self.assertEqual(after["futureUnknownKey"], UNRELATED["futureUnknownKey"])

    def test_old_settings_file_without_preset_keys_still_loads(self):
        old = {k: v for k, v in DEF.items() if k not in (S.PRESET_TABLE_KEY, S.PRESET_SELECTED_KEY)}
        old["diffusionStrength" if IS_FX else "ssaoAmount"] = 0.5
        self.write_settings_file(old)
        d = settings.load()
        self.assertEqual(d[S.PRESET_TABLE_KEY], {})
        self.assertEqual(d[S.PRESET_SELECTED_KEY], "")
        self.assertIsNot(d[S.PRESET_TABLE_KEY], DEF[S.PRESET_TABLE_KEY])   # 既定値の入れ子を共有しない
        d[S.PRESET_TABLE_KEY]["x"] = {}
        self.assertEqual(DEF[S.PRESET_TABLE_KEY], {})
        self.assertEqual(settings.load()[S.PRESET_TABLE_KEY], {})

    def test_new_vs_update_roles(self):
        win = self.make()
        self.set_current(win, varied_all(1))
        self.assertTrue(win.presets.save_new("A")[0])
        t1 = table_of(win)
        # 同名の新規は作らない(更新は ✓)
        ok, msg = win.presets.save_new("a")
        self.assertFalse(ok)
        self.assertEqual(table_of(win), t1)
        self.assertEqual(win.presets.selected(), "A")
        # 選択中の更新は新規を作らない
        self.set_current(win, varied_all(2))
        self.assertTrue(win.presets.is_dirty())
        ok, msg = win.presets.update_selected()
        self.assertTrue(ok, msg)
        self.assertEqual(win.presets.names(), ["A"])
        self.assertFalse(win.presets.is_dirty())
        for k, v in varied_all(2).items():
            self.assertTrue(S.preset_same(S.preset_get(win.data, "A")[k], v), k)
        # 未選択では更新できない
        win.presets.select("")
        ok, msg = win.presets.update_selected()
        self.assertFalse(ok)
        self.assertEqual(win.presets.names(), ["A"])

    def test_update_only_touches_selected_preset(self):
        win = self.make()
        self.set_current(win, varied_all(1))
        win.presets.save_new("A")
        self.set_current(win, varied_all(2))
        win.presets.save_new("B")
        tb = table_of(win)["B"]
        self.assertTrue(win.presets.select("A")[0])
        self.set_current(win, {KEYS[1]: _varied(KEYS[1], 2)})
        win.presets.update_selected()
        self.assertEqual(table_of(win)["B"], tb)

    def test_save_failure_leaves_presets_unchanged(self):
        win = self.make()
        self.set_current(win, varied_all(1))
        win.presets.save_new("A")
        t_before, sel_before = table_of(win), win.data[S.PRESET_SELECTED_KEY]
        disk_before = self.settings_file()
        real_save = S.save
        for mode in ("false", "raise"):
            S.save = (lambda d: False) if mode == "false" else (lambda d: (_ for _ in ()).throw(OSError("disk full")))
            self.addCleanup(setattr, S, "save", real_save)
            self.set_current(win, varied_all(2))
            ok, msg = win.presets.save_new("B")
            self.assertFalse(ok, mode)
            self.assertEqual(table_of(win), t_before, mode)
            self.assertEqual(win.data[S.PRESET_SELECTED_KEY], sel_before, mode)
            ok, msg = win.presets.update_selected()
            self.assertFalse(ok, mode)
            self.assertEqual(table_of(win), t_before, mode)           # 保存値は古いまま
            self.assertEqual(win.presets.names(), ["A"])
        S.save = real_save
        self.assertEqual(self.settings_file(), disk_before)

    def test_missing_keys_stay_missing_after_failed_first_save_and_retry_works(self):
        # キー欠落の旧設定(load が既定を足す前の形)で最初の保存が失敗しても、欠落のまま戻る(sentinel を複製して object 型を残さない)
        T, SEL = S.PRESET_TABLE_KEY, S.PRESET_SELECTED_KEY
        for drop in ((T, SEL), (T,), (SEL,)):
            for mode in ("false", "raise"):
                win = self.make()
                for k in drop:
                    win.data.pop(k, None)
                kept = {k: copy.deepcopy(win.data[k]) for k in (T, SEL) if k not in drop}
                self.set_current(win, varied_all(1))
                real = S.save
                S.save = (lambda d: False) if mode == "false" else (lambda d: (_ for _ in ()).throw(OSError("disk full")))
                try:
                    ok, msg = win.presets.save_new("A")
                finally:
                    S.save = real
                self.assertFalse(ok, (drop, mode))
                self.assertEqual(win.presets.last_kind, "failed")
                for k in drop:
                    self.assertNotIn(k, win.data, (drop, mode))          # 欠落のまま(object 型で復帰しない)
                for k, v in kept.items():
                    self.assertEqual(win.data[k], v, (drop, mode, k))
                json.dumps(win._collect())                               # 書き出せる(TypeError にならない)
                self.assertEqual(win.presets.names(), [])
                ok, msg = win.presets.save_new("A")                      # 再試行できる(不正テーブルとして拒否されない)
                self.assertTrue(ok, (drop, mode, msg))
                self.assertEqual(win.presets.names(), ["A"])
                self.assertEqual(list(self.settings_file()[T]), ["A"])

    def test_state_keeps_missing_marker_and_copies_values(self):
        win = self.make()
        win.data.pop(S.PRESET_TABLE_KEY, None)
        win.data[S.PRESET_SELECTED_KEY] = "x"
        st = win.presets._state()
        self.assertIs(st[0], S._MISSING)                                 # 欠落は同じ marker のまま
        self.assertEqual(st[1], "x")
        win.data[S.PRESET_TABLE_KEY] = {"A": {"k": [1, 2]}}
        st = win.presets._state()
        win.data[S.PRESET_TABLE_KEY]["A"]["k"].append(3)
        self.assertEqual(st[0], {"A": {"k": [1, 2]}})                    # 値は複製(後の編集が退避へ入り込まない)

    def test_real_write_failure_keeps_existing_file(self):
        win = self.make()
        self.set_current(win, varied_all(1))
        win.presets.save_new("A")
        disk_before = self.settings_file()
        real_replace = os.replace

        def bad(*a, **k):
            raise OSError("replace failed")
        os.replace = bad
        try:
            self.set_current(win, varied_all(2))
            ok, msg = win.presets.save_new("B")
        finally:
            os.replace = real_replace
        self.assertFalse(ok)
        self.assertEqual(win.presets.names(), ["A"])
        self.assertEqual(self.settings_file(), disk_before)


# ==========================================================================
class DirtyAndReset(Base):
    def _saved_win(self, which=1, name="A"):
        win = self.make()
        self.set_current(win, varied_all(which))
        self.assertTrue(win.presets.save_new(name)[0])
        return win

    def test_dirty_for_every_key(self):
        win = self._saved_win(1)
        self.assertFalse(win.presets.is_dirty())
        for k in KEYS:
            keep = copy.deepcopy(win.data[k])
            win.data[k] = _varied(k, 2)
            self.assertTrue(win.presets.is_dirty(), "変更を検知できない: " + k)
            win.data[k] = keep
            self.assertFalse(win.presets.is_dirty(), "戻しても dirty のまま: " + k)

    def test_dirty_tolerance_and_types(self):
        win = self._saved_win(1)
        nk = [k for k in KEYS if isinstance(S._PRESET_SPEC[k], tuple) and S._PRESET_SPEC[k][0] == "n" and isinstance(DEF[k], float)][0]
        win.data[nk] += 1e-9
        self.assertFalse(win.presets.is_dirty())
        win.data[nk] += 1e-3
        self.assertTrue(win.presets.is_dirty())
        win.data[nk] = _varied(nk, 1)
        bk = [k for k in KEYS if S._PRESET_SPEC[k] == "b"][0]
        win.data[bk] = 1 if win.data[bk] else 0          # bool でない値は「違う」
        self.assertTrue(win.presets.is_dirty())

    def test_unselected_or_unreadable_never_dirty(self):
        win = self._saved_win(1)
        win.presets.select("")
        self.set_current(win, varied_all(2))
        self.assertFalse(win.presets.is_dirty())
        self.assertTrue(self.reset_hidden(win))
        ok, msg = win.presets.reset()
        self.assertFalse(ok)
        win.data[S.PRESET_SELECTED_KEY] = "nosuch"
        self.assertEqual(win.presets.selected(), "")
        self.assertFalse(win.presets.is_dirty())

    def test_reset_restores_saved_values_and_does_not_touch_saved(self):
        win = self._saved_win(1)
        saved = table_of(win)
        disk = self.settings_file()
        self.set_current(win, varied_all(2))
        win.presets._persist_calls = 0
        ok, msg = win.presets.reset()
        self.assertTrue(ok, msg)
        for k, v in varied_all(1).items():
            self.assertTrue(S.preset_same(win.data[k], v), k)
        self.assertFalse(win.presets.is_dirty())
        self.assertEqual(table_of(win), saved)                          # 保存値は変わらない
        self.assertEqual(self.settings_file(), disk)                    # Reset はファイルへ保存値を書き換えない
        self.assertEqual(win.presets.selected(), "A")

    def test_reset_noop_when_equal(self):
        win = self._saved_win(1)
        n = win.saves
        ok, msg = win.presets.reset()
        self.assertTrue(ok)
        self.assertEqual(msg, u"")
        self.assertEqual(win.saves, n)

    def test_switch_applies_values_and_selection(self):
        win = self._saved_win(1, "A")
        self.set_current(win, varied_all(2))
        win.presets.save_new("B")
        self.assertEqual(win.presets.selected(), "B")
        ok, msg = win.presets.select("A")
        self.assertTrue(ok, msg)
        for k, v in varied_all(1).items():
            self.assertTrue(S.preset_same(win.data[k], v), k)
        self.assertEqual(win.presets.selected(), "A")
        self.assertFalse(win.presets.is_dirty())
        ok, msg = win.presets.select("B")
        for k, v in varied_all(2).items():
            self.assertTrue(S.preset_same(win.data[k], v), k)

    def test_switch_discards_unsaved_edits_by_design(self):
        win = self._saved_win(1, "A")
        self.set_current(win, varied_all(2))
        win.presets.save_new("B")
        win.presets.select("A")
        k = KEYS[2]
        win.data[k] = _varied(k, 2)                       # A に未保存の編集
        win.presets.select("B")
        win.presets.select("A")
        self.assertTrue(S.preset_same(win.data[k], _varied(k, 1)))   # 未保存の編集は A の保存値に戻る(保存する前提の仕様)

    def test_unrelated_state_untouched_by_every_operation(self):
        win = self.make(UNRELATED)
        ref = copy.deepcopy({k: win.data[k] for k in UNRELATED})
        self.set_current(win, varied_all(1))
        win.presets.save_new("A")
        self.set_current(win, varied_all(2))
        win.presets.save_new("B")
        win.presets.select("A")
        self.set_current(win, {KEYS[0]: not win.data[KEYS[0]]})
        win.presets.update_selected()
        win.presets.reset()
        win.presets.select("B")
        win.presets.select("")
        for k, v in ref.items():
            self.assertEqual(win.data[k], v, "無関係な状態が変わった: " + k)
        # 実適用の経路も、プリセットのキー以外を送らない / 無関係なコマンドを呼ばない
        forbidden = ("playblast", "lookThru", "select", "camera", "file", "viewFit", "currentTime")
        for c in self.stub.calls:
            self.assertFalse(any(c.startswith(f) for f in forbidden), c)

    def test_saved_values_are_never_shared_by_reference(self):
        win = self._saved_win(1)
        raw_before = table_of(win)
        live = win.data[S.PRESET_TABLE_KEY]["A"]
        # 取り出した値を書き換えても保存済みは変わらない
        got = S.preset_get(win.data, "A")
        for v in got.values():
            if isinstance(v, list):
                v[0] = 123.0
        got[KEYS[0]] = "mutated"
        self.assertEqual(table_of(win), raw_before)
        # 切替・Reset で現在値に入る入れ子値は保存値と別オブジェクト
        win.presets.select("A")
        for k in KEYS:
            if isinstance(win.data[k], list):
                self.assertIsNot(win.data[k], live[k], k)
                win.data[k][0] = 0.123                       # 現在値を in-place 変更
        self.assertEqual(table_of(win), raw_before)
        self.assertTrue(win.presets.is_dirty() or not any(isinstance(win.data[k], list) for k in KEYS))
        win.presets.reset()
        self.assertEqual(table_of(win), raw_before)
        # 保存時も現在値の入れ子を共有しない
        for k in KEYS:
            if isinstance(win.data[k], list):
                self.assertIsNot(win.data[S.PRESET_TABLE_KEY]["A"][k], win.data[k], k)

    def test_nested_value_gradefilter_roundtrip(self):
        if not IS_FX:
            self.skipTest("Fx のみ(入れ子値は gradeFilter)")
        win = self.make()
        win.data["gradeFilter"] = [0.2, 0.4, 0.6]
        win.presets.save_new("A")
        win.data["gradeFilter"][1] = 0.9
        self.assertTrue(win.presets.is_dirty())
        win.presets.reset()
        self.assertEqual(win.data["gradeFilter"], [0.2, 0.4, 0.6])
        self.assertEqual(win.data[S.PRESET_TABLE_KEY]["A"]["gradeFilter"], [0.2, 0.4, 0.6])
        win2 = self.make(fresh_load=True)
        self.assertEqual(win2.data["gradeFilter"], [0.2, 0.4, 0.6])


# ==========================================================================
class ApplyFailure(Base):
    def _two(self):
        win = self.make()
        self.set_current(win, varied_all(1))
        win.presets.save_new("A")
        self.set_current(win, varied_all(2))
        win.presets.save_new("B")
        return win

    def _inject_failure(self, win):
        u"""実適用を失敗させる。Fx: プラグインが例外 / Cam: VP2 が書込みを無視(読み戻しが合わない)。"""
        if IS_FX:
            self.plugin.fail = True
        else:
            self.vp2.locked.update(self.vp2.vals)

    def _clear_failure(self):
        self.plugin.fail = False
        self.vp2.locked.clear()

    def test_select_failure_is_not_success_and_rolls_back(self):
        win = self._two()
        self.assertTrue(win.presets.select("A")[0])
        before = copy.deepcopy({k: win.data[k] for k in KEYS})
        n_saves = win.saves
        self._inject_failure(win)
        ok, msg = win.presets.select("B")
        self.assertFalse(ok)
        self.assertTrue(msg)
        self.assertIn(win.presets.last_kind, ("failed", "unrestored"))  # Fx は戻しの再適用も失敗し続けるので未復帰 / Cam は元の値と一致して復帰
        self.assertEqual({k: win.data[k] for k in KEYS}, before)         # 元の値へ戻している
        self.assertEqual(win.presets.selected(), "A")                    # 選択も変わらない
        self.assertEqual(win.saves, n_saves)                             # 成功扱いの保存をしない

    def test_exception_escaping_apply_current_is_failure_and_rolls_back(self):
        # 実の _preset_apply_current は自分で例外を握るが、PresetOps 側も「例外が直接飛んできた」場合に
        # 成功扱いにせず元の値へ戻すこと(防御の二重化)
        win = self._two()
        self.assertTrue(win.presets.select("A")[0])
        before = copy.deepcopy({k: win.data[k] for k in KEYS})
        n_saves = win.saves
        real = win._preset_apply_current
        calls = []

        def boom():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("apply exploded")
            return real()
        win._preset_apply_current = boom
        ok, msg = win.presets.select("B")
        self.assertFalse(ok)
        self.assertTrue(msg)
        self.assertEqual({k: win.data[k] for k in KEYS}, before)
        self.assertEqual(win.presets.selected(), "A")
        self.assertEqual(win.saves, n_saves)
        self.assertEqual(len(calls), 2)                                  # 戻した値を実環境へ再適用している

    # --- 保存の成否と適用の成否を区別する / 復帰失敗 / Fx 保留 --------------------------------
    def _save_fails(self, mode="false"):
        real = S.save
        if mode == "false":
            S.save = lambda d: False
        else:
            S.save = lambda d: (_ for _ in ()).throw(OSError("disk full"))
        self.addCleanup(setattr, S, "save", real)
        return real

    def test_select_reset_and_deselect_save_immediately(self):
        win = self._two()
        ok, msg = win.presets.select("A")
        self.assertTrue(ok, msg)
        self.assertEqual(win.presets.last_kind, "applied")
        self.assertEqual(self.settings_file()[S.PRESET_SELECTED_KEY], "A")      # 遅延保存を待たずにファイルへ入っている
        self.set_current(win, {KEYS[3]: _varied(KEYS[3], 2)})
        ok, msg = win.presets.reset()
        self.assertTrue(ok, msg)
        self.assertEqual(win.presets.last_kind, "reset")
        self.assertEqual(self.settings_file()[S.PRESET_SELECTED_KEY], "A")
        ok, msg = win.presets.select("")
        self.assertTrue(ok)
        self.assertEqual(win.presets.last_kind, "ok")
        self.assertEqual(self.settings_file()[S.PRESET_SELECTED_KEY], "")
        # 再起動(読み直し)で選択がそのまま戻る
        win.presets.select("B")
        self.assertEqual(settings.load()[S.PRESET_SELECTED_KEY], "B")

    def test_save_failure_after_select_reset_deselect_is_reported_as_unsaved(self):
        for mode in ("false", "raise"):
            win = self._two()
            win.presets.select("B")
            disk = self.settings_file()
            real = self._save_fails(mode)
            ok, msg = win.presets.select("A")                            # 適用はできたが保存できない
            self.assertFalse(ok, mode)
            self.assertEqual(win.presets.last_kind, "unsaved")
            self.assertTrue(msg)
            self.assertNotEqual(msg, ui.tr(u"「{}」を適用しました").format("A"))        # 成功文言を出さない(言語に依らず tr で比べる)
            self.assertEqual(msg, ui.tr(u"「{}」を適用しましたが、設定を保存できませんでした(再起動後は戻る可能性があります)").format("A"))
            for k, v in varied_all(1).items():
                self.assertTrue(S.preset_same(win.data[k], v), k)        # 適用した値は残る(適用成功と保存失敗は別)
            self.assertEqual(win.presets.selected(), "A")
            self.assertEqual(self.settings_file(), disk)
            self.set_current(win, {KEYS[3]: _varied(KEYS[3], 2)})
            ok, msg = win.presets.reset()
            self.assertFalse(ok)
            self.assertEqual(win.presets.last_kind, "unsaved")
            ok, msg = win.presets.select("")
            self.assertFalse(ok)
            self.assertEqual(win.presets.last_kind, "unsaved")
            self.assertEqual(win.presets.selected(), "")
            self.assertTrue(msg)
            self.assertEqual(self.settings_file(), disk)
            S.save = real
            ok, msg = win.presets.select("A")                            # 保存が直れば通常どおり成功
            self.assertTrue(ok, msg)
            self.assertEqual(win.presets.last_kind, "applied")
            self.assertEqual(self.settings_file()[S.PRESET_SELECTED_KEY], "A")

    def test_failed_apply_with_failed_restore_is_reported_as_unrestored(self):
        win = self._two()
        self.assertTrue(win.presets.select("A")[0])
        before = copy.deepcopy({k: win.data[k] for k in KEYS})
        disk = self.settings_file()
        n_saves = win.saves
        if IS_FX:
            self.plugin.fail = True                                      # 適用も、戻した値の再適用も失敗し続ける
        else:
            self.vp2.vals["ssaoRadius"] = 999                            # 環境が A とずれている状態で全属性が書けない
            self.vp2.locked.update(self.vp2.vals)
        ok, msg = win.presets.select("B")
        self.assertFalse(ok)
        self.assertEqual(win.presets.last_kind, "unrestored")
        self.assertNotEqual(msg, ui.tr(u"「{}」を適用できませんでした。元の値に戻しました").format("B"))     # 「戻した」と断定しない
        self.assertEqual(msg, ui.tr(u"「{}」を適用できず、Maya 側を元の値へ戻せませんでした(設定の値は元に戻しました。表示が元と違う可能性があります)").format("B"))
        self.assertEqual({k: win.data[k] for k in KEYS}, before)         # 設定(メモリ)の値は戻っている
        self.assertEqual(win.presets.selected(), "A")
        self.assertEqual(self.settings_file(), disk)
        self.assertEqual(win.saves, n_saves)
        win.presets.last_kind = ""
        self.set_current(win, {KEYS[3]: _varied(KEYS[3], 2)})
        ok, msg = win.presets.reset()
        self.assertFalse(ok)
        self.assertEqual(win.presets.last_kind, "unrestored")

    def test_restore_exception_and_false_are_both_unrestored(self):
        for how in ("false", "raise"):
            win = self._two()
            self.assertTrue(win.presets.select("A")[0])
            before = copy.deepcopy({k: win.data[k] for k in KEYS})
            calls = []

            def fail():
                calls.append(1)
                if how == "raise":
                    raise RuntimeError("apply exploded")
                return False
            win._preset_apply_current = fail
            ok, msg = win.presets.select("B")
            self.assertFalse(ok, how)
            self.assertEqual(win.presets.last_kind, "unrestored", how)
            self.assertEqual(len(calls), 2, how)                         # 適用と、戻した値の再適用の 2 回(どちらも結果を見ている)
            self.assertEqual({k: win.data[k] for k in KEYS}, before, how)

    def test_restore_reapply_deferred_is_unconfirmed_not_restored(self):
        # 適用 False → 戻しの再適用が「保留」(プラグイン未ロード / 状態不明)。Maya が戻ったとは言わない。設定の値・選択は維持
        for op in ("select", "reset"):
            win = self._two()
            self.assertTrue(win.presets.select("A")[0])
            if op == "reset":
                self.set_current(win, {KEYS[3]: _varied(KEYS[3], 2)})
            before = copy.deepcopy({k: win.data[k] for k in KEYS})
            disk = self.settings_file()
            n_saves = win.saves
            seq = [False, S.PRESET_DEFERRED]
            win._preset_apply_current = lambda: seq.pop(0)
            ok, msg = win.presets.select("B") if op == "select" else win.presets.reset()
            self.assertEqual(seq, [], op)                                # 適用と再適用の 2 回だけ
            self.assertFalse(ok, op)
            self.assertEqual(win.presets.last_kind, "unconfirmed", op)
            name = "B" if op == "select" else "A"
            self.assertEqual(msg, ui.tr(u"「{}」を適用できませんでした。設定の値は元に戻しましたが、Maya 側が元に戻ったかは確認できていません(プラグイン未ロードなど)").format(name))
            self.assertNotEqual(msg, ui.tr(u"「{}」を適用できませんでした。元の値に戻しました").format(name))
            self.assertEqual({k: win.data[k] for k in KEYS}, before, op)   # 値のメモリ復帰は維持
            self.assertEqual(win.presets.selected(), "A", op)              # 選択不変
            self.assertEqual(self.settings_file(), disk, op)
            self.assertEqual(win.saves, n_saves, op)

    def test_fx_real_path_failure_then_plugin_unloaded_is_unconfirmed(self):
        if not IS_FX:
            self.skipTest("Fx のみ(Cam に通常の保留経路は無い)")
        win = self._two()
        self.assertTrue(win.presets.select("A")[0])
        before = copy.deepcopy({k: win.data[k] for k in KEYS})
        orig = self.plugin.set_params

        def vanishing(**kw):
            self.plugin.loaded = False                                   # 最初の適用が失敗した直後にプラグインが外れた状況
            return orig(**kw)
        self.plugin.fail = True
        T.pkg.set_params = vanishing
        ok, msg = win.presets.select("B")
        self.assertFalse(ok)
        self.assertEqual(win.presets.last_kind, "unconfirmed")
        self.assertEqual({k: win.data[k] for k in KEYS}, before)
        self.assertEqual(win.presets.selected(), "A")

    def test_restore_success_is_still_reported_as_failed_but_restored(self):
        win = self._two()
        win.presets.select("A")
        if IS_FX:
            self.plugin.fail_first = 1
        else:
            self.vp2.locked.add("ssaoAmount")
        ok, msg = win.presets.select("B")
        self.assertFalse(ok)
        self.assertEqual(win.presets.last_kind, "failed")
        self.assertEqual(msg, ui.tr(u"「{}」を適用できませんでした。元の値に戻しました").format("B"))

    def test_fx_plugin_not_loaded_is_reported_as_deferred_not_applied(self):
        if not IS_FX:
            self.skipTest("Fx のみ(プラグイン未ロード)")
        win = self._two()
        self.plugin.loaded = False
        self.assertEqual(win._preset_apply_current(), S.PRESET_DEFERRED)    # 「適用した(True)」とは別の戻り値
        self.plugin.loaded = True
        self.assertIs(win._preset_apply_current(), True)
        self.plugin.loaded = False
        ok, msg = win.presets.select("A")
        self.assertTrue(ok, msg)                                         # 失敗ではない(設計上の保留)
        self.assertEqual(win.presets.last_kind, "deferred")
        self.assertNotEqual(msg, ui.tr(u"「{}」を適用しました").format("A"))        # 「適用しました」と言わない
        self.assertEqual(msg, ui.tr(u"「{}」の値を設定しました。Maya へは未適用です(プラグイン未ロード。ロード後に反映されます)").format("A"))
        self.assertEqual(win.presets.selected(), "A")
        self.assertEqual(self.settings_file()[S.PRESET_SELECTED_KEY], "A")
        self.set_current(win, {KEYS[3]: _varied(KEYS[3], 2)})
        ok, msg = win.presets.reset()
        self.assertTrue(ok, msg)
        self.assertEqual(win.presets.last_kind, "deferred")
        self._save_fails()
        ok, msg = win.presets.select("B")
        self.assertFalse(ok)                                             # 保留 + 保存失敗は「未保存」
        self.assertEqual(win.presets.last_kind, "unsaved")
        self.assertEqual(msg, ui.tr(u"「{}」の値を設定しましたが、設定を保存できませんでした(Maya へは未適用。再起動後は戻る可能性があります)").format("B"))

    def test_fx_unknown_load_state_is_deferred_not_applied(self):
        if not IS_FX:
            self.skipTest("Fx のみ(プラグイン未ロード)")
        win = self._two()
        calls = []

        def flaky():
            calls.append(1)
            if len(calls) >= 2:                                          # apply_effects 内の確認は通り、そのあとのロード状態の確認だけ失敗
                raise RuntimeError("cannot query")
            return True
        T.pkg.is_loaded = flaky
        self.assertEqual(win._preset_apply_current(), S.PRESET_DEFERRED)   # 確かめられないときは「適用した」と言わない

    def test_reset_failure_is_not_success_and_keeps_edits(self):
        win = self._two()
        win.presets.select("A")
        self.set_current(win, {KEYS[3]: _varied(KEYS[3], 2)})
        self.assertTrue(win._preset_apply_current())                   # 編集した値は実環境にも入っている(UI 操作と同じ)
        before = copy.deepcopy({k: win.data[k] for k in KEYS})
        saved = table_of(win)
        self._inject_failure(win)
        ok, msg = win.presets.reset()
        self.assertFalse(ok)
        self.assertEqual({k: win.data[k] for k in KEYS}, before)
        self.assertEqual(table_of(win), saved)
        self.assertTrue(win.presets.is_dirty())

    def test_failed_switch_puts_previous_values_back_into_the_environment(self):
        win = self._two()
        win.presets.select("A")
        if IS_FX:
            self.plugin.fail_first = 1                                   # 最初の適用(B)だけ失敗 → 元の値(A)の再適用は通る
            ok, msg = win.presets.select("B")
            self.assertFalse(ok)
            self.assertEqual(self.plugin.calls[-1]["diffusionStrength"], _varied("diffusionStrength", 1))
            self.assertEqual(len(self.plugin.calls) >= 2, True)
        else:
            self.vp2.locked.add("ssaoAmount")                           # 1 つだけ書けない(他の属性は B の値で書かれてしまう)
            ok, msg = win.presets.select("B")
            self.assertFalse(ok)
            self.vp2.locked.clear()
            self.assertEqual(self.vp2.vals["ssaoRadius"], _varied("ssaoRadius", 1))     # 書かれてしまった分は元の値(A)へ戻っている
            self.assertEqual(self.vp2.vals["multiSampleCount"], _varied("aaSampleCount", 1))
            self.assertEqual(self.vp2.vals["ssaoSamples"], _varied("ssaoSamples", 1))

    def test_failure_then_retry_succeeds(self):
        win = self._two()
        win.presets.select("A")
        self._inject_failure(win)
        self.assertFalse(win.presets.select("B")[0])
        self._clear_failure()
        self.assertTrue(win.presets.select("B")[0])
        self.assertEqual(win.presets.selected(), "B")

    def test_real_apply_receives_saved_values(self):
        win = self._two()
        win.presets.select("A")
        if IS_FX:
            kw = self.plugin.calls[-1]
            self.assertEqual(kw["diffusionStrength"], _varied("diffusionStrength", 1))
            self.assertEqual(kw["shadowMapSize"], _varied("shadowMapSize", 1))
            self.assertEqual(kw["hairDomSize"], _varied("hairDomSize", 1))
            self.assertEqual(bool(kw["post"]), _varied("effectsMaster", 1))
        else:
            master = _varied("effectsMaster", 1)
            self.assertEqual(self.vp2.vals["ssaoAmount"], _varied("ssaoAmount", 1))
            self.assertEqual(self.vp2.vals["multiSampleCount"], _varied("aaSampleCount", 1))
            self.assertEqual(self.vp2.vals["ssaoEnable"], bool(_varied("ssaoEnable", 1)) and master)
            self.assertEqual([c for vp in win.vps for c in vp.calls][-2:], [_varied("shadows", 1)] * 2)

    def test_cam_shadow_failure_counts_as_failure(self):
        if IS_FX:
            self.skipTest("Cam のみ")
        win = self._two()
        win.presets.select("A")
        win.vps[1].ok = False
        before = copy.deepcopy({k: win.data[k] for k in KEYS})
        ok, msg = win.presets.select("B")
        self.assertFalse(ok)
        self.assertEqual({k: win.data[k] for k in KEYS}, before)

    def test_cam_unexpected_exception_in_apply_is_failure(self):
        if IS_FX:
            self.skipTest("Cam のみ")
        win = self._two()
        win.presets.select("A")
        before = copy.deepcopy({k: win.data[k] for k in KEYS})
        real = vp2mod.apply_all

        def boom(d):
            raise RuntimeError("unexpected")
        vp2mod.apply_all = boom
        self.addCleanup(setattr, vp2mod, "apply_all", real)
        ok, msg = win.presets.select("B")
        self.assertFalse(ok)
        self.assertEqual({k: win.data[k] for k in KEYS}, before)
        self.assertEqual(win.presets.selected(), "A")

    def test_cam_master_off_gating_is_not_a_failure(self):
        if IS_FX:
            self.skipTest("Cam のみ")
        win = self.make()
        v = varied_all(1)
        v["effectsMaster"] = False
        v["ssaoEnable"] = True
        v["aaEnable"] = True
        self.set_current(win, v)
        win.presets.save_new("Off")
        self.set_current(win, varied_all(2))
        ok, msg = win.presets.select("Off")
        self.assertTrue(ok, msg)
        self.assertFalse(self.vp2.vals["ssaoEnable"])                  # master OFF では SSAO / AA は OFF として適用される(既存仕様)
        self.assertTrue(win.data["ssaoEnable"])                        # 個別の値は保持
        self.assertFalse(win.presets.is_dirty())

    def test_cam_missing_attribute_is_skipped_not_failure(self):
        if IS_FX:
            self.skipTest("Cam のみ")
        win = self._two()
        self.vp2.missing.add("lineAAEnable")
        ok, msg = win.presets.select("A")
        self.assertTrue(ok, msg)

    def test_fx_plugin_not_loaded_is_deferred_not_failure(self):
        if not IS_FX:
            self.skipTest("Fx のみ")
        win = self._two()
        self.plugin.loaded = False
        n = len(self.plugin.calls)
        ok, msg = win.presets.select("A")
        self.assertTrue(ok, msg)
        self.assertEqual(len(self.plugin.calls), n)                      # 未ロードなら何も送らない(読込み時に apply_effects が反映する既存経路)
        self.assertEqual(win.presets.selected(), "A")


# ==========================================================================
class CorruptData(Base):
    def _raw_win(self, table, selected=""):
        seed = dict(DEF)
        seed[S.PRESET_TABLE_KEY] = table
        seed[S.PRESET_SELECTED_KEY] = selected
        self.write_settings_file(seed)
        return self.make(fresh_load=True)

    def test_table_of_wrong_type_is_kept_and_new_save_refused(self):
        for bad in ([], "oops", 5, None, [1, 2], 3.5, True):
            win = self._raw_win(bad, "A")
            disk = self.settings_file()
            self.assertEqual(win.presets.names(), [], repr(bad))
            self.assertEqual(win.presets.selected(), "")
            self.set_current(win, varied_all(1))
            ok, msg = win.presets.save_new("A")
            self.assertFalse(ok, repr(bad))                              # 壊れた入れ物は作り直さない(元のデータを失う)
            self.assertTrue(msg)
            self.assertEqual(win.presets.last_kind, "invalid")
            got = win.data[S.PRESET_TABLE_KEY]
            self.assertIs(type(got), type(bad), repr(bad))
            self.assertEqual(got, bad)                                   # メモリの元データはそのまま
            self.assertEqual(win.data[S.PRESET_SELECTED_KEY], "A")       # 選択キーにも触れない
            self.assertEqual(self.settings_file(), disk)                 # ファイルは 1 バイトも書かない(拒否は保存を試みない)
            self.assertEqual(win.presets.names(), [])
            S.save(win._collect())                                       # 通常の自動保存が通っても、壊れた元データは書き戻されるだけ(失われない)
            self.assertEqual(self.settings_file()[S.PRESET_TABLE_KEY], bad)

    def test_missing_table_key_is_normal_first_save(self):
        seed = dict(DEF)
        seed.pop(S.PRESET_TABLE_KEY, None)
        seed.pop(S.PRESET_SELECTED_KEY, None)
        self.write_settings_file(seed)
        win = self.make(fresh_load=True)
        win.data.pop(S.PRESET_TABLE_KEY, None)                           # キー欠落の旧設定(load が既定の {} を足す前の形)を直接再現
        self.set_current(win, varied_all(1))
        ok, msg = win.presets.save_new("A")
        self.assertTrue(ok, msg)
        self.assertEqual(win.presets.last_kind, "saved")
        self.assertEqual(list(self.settings_file()[S.PRESET_TABLE_KEY]), ["A"])

    def test_bad_entries_are_ignored_but_kept_on_disk(self):
        good = varied_all(1)
        table = {"good": good, "str": "x", "none": None, "list": [1], "empty": {}, "junk": {"nonsense": 1}, 5: {"a": 1}}
        win = self._raw_win({k: v for k, v in table.items() if isinstance(k, str)}, "str")
        self.assertEqual(win.presets.names(), ["good"])
        self.assertEqual(win.presets.selected(), "")                     # 読めない項目は選択扱いにしない
        # 読めない項目の名前は新規に使えない(上書きして壊さない)
        for nm in ("str", "none", "list", "empty", "junk"):
            self.assertFalse(win.presets.save_new(nm)[0], nm)
        self.set_current(win, varied_all(2))
        self.assertTrue(win.presets.save_new("new")[0])
        t = win.data[S.PRESET_TABLE_KEY]
        for nm in ("str", "none", "list", "empty", "junk"):
            self.assertEqual(t[nm], table[nm], nm)                       # 読めない項目は触れずに残す

    def test_partially_invalid_entry_applies_only_valid_keys(self):
        entry = varied_all(1)
        bad_keys = [KEYS[0], KEYS[4]]
        entry[KEYS[0]] = "garbage"
        entry[KEYS[4]] = 10 ** 9
        entry["unknownFutureKey"] = {"x": 1}
        win = self._raw_win({"P": entry}, "P")
        self.assertEqual(win.presets.names(), ["P"])
        got = S.preset_get(win.data, "P")
        self.assertEqual(set(got), set(KEYS) - set(bad_keys))
        self.assertNotIn("unknownFutureKey", got)
        keep = {k: copy.deepcopy(win.data[k]) for k in bad_keys}
        self.set_current(win, varied_all(2))
        win.data.update(keep)
        ok, msg = win.presets.select("P")
        self.assertTrue(ok, msg)
        for k in bad_keys:
            self.assertEqual(win.data[k], keep[k], "不正な値は適用せず現在値のまま: " + k)
        for k in got:
            self.assertTrue(S.preset_same(win.data[k], got[k]), k)
        self.assertFalse(win.presets.is_dirty())

    def test_unknown_keys_survive_an_update(self):
        entry = varied_all(1)
        entry["unknownFutureKey"] = {"x": [1, 2]}
        entry[KEYS[0]] = "garbage"                                        # 不正値は更新で正しい値になる
        win = self._raw_win({"P": entry}, "P")
        self.set_current(win, varied_all(2))
        self.assertTrue(win.presets.update_selected()[0])
        saved = win.data[S.PRESET_TABLE_KEY]["P"]
        self.assertEqual(saved["unknownFutureKey"], {"x": [1, 2]})
        self.assertEqual(saved[KEYS[0]], _varied(KEYS[0], 2))
        self.assertEqual(set(S.preset_get(win.data, "P")), set(KEYS))

    def test_invalid_current_value_blocks_saving_instead_of_storing_garbage(self):
        win = self.make()
        win.data[KEYS[1]] = "garbage"
        ok, msg = win.presets.save_new("A")
        self.assertFalse(ok)
        self.assertEqual(win.presets.names(), [])
        self.assertFalse(os.path.exists(settings.config_path()))        # 何も書いていない

    def test_whole_file_corrupt_falls_back_to_defaults(self):
        self.write_settings_file(u"{ this is not json")
        win = self.make(fresh_load=True)
        self.assertEqual(win.presets.names(), [])
        self.set_current(win, varied_all(1))
        self.assertTrue(win.presets.save_new("A")[0])
        self.assertEqual(self.make(fresh_load=True).presets.names(), ["A"])

    def test_non_string_selected_is_ignored(self):
        for bad in (None, 5, ["A"], {"a": 1}):
            win = self._raw_win({"A": varied_all(1)}, bad)
            self.assertEqual(win.presets.selected(), "")
            self.assertFalse(win.presets.is_dirty())


# ==========================================================================
class UiFlow(Base):
    def _name_dialog(self, win, name):
        win.toolbox._ask_preset_name = lambda: name

    def test_row_parts_exist_and_are_icon_buttons(self):
        win = self.make()
        tb = win.toolbox
        for w in (tb.presetCombo, tb.presetNewBtn, tb.presetUpdateBtn, tb.presetResetBtn):
            self.assertTrue(w.toolTip())
        for b in (tb.presetNewBtn, tb.presetUpdateBtn, tb.presetResetBtn):
            self.assertIsInstance(b, qt.QtWidgets.QToolButton)
            self.assertLessEqual(len(b.text()), 1)                         # アイコン(1 文字)中心
        self.assertEqual(tb.presetCombo.count(), 1)
        self.assertFalse(tb.presetUpdateBtn.isEnabled())
        self.assertTrue(self.reset_hidden(win))

    def test_new_button_creates_selects_and_lists(self):
        win = self.make()
        tb = win.toolbox
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "Look 1")
        tb.presetNewBtn.click()
        self.assertEqual(win.presets.names(), ["Look 1"])
        self.assertEqual(tb.presetCombo.currentData(), "Look 1")
        self.assertEqual(tb.presetCombo.count(), 2)
        self.assertTrue(tb.presetUpdateBtn.isEnabled())
        self.assertTrue(self.reset_hidden(win))
        self.assertFalse(tb.presetMsg.isHidden())

    def test_status_label_is_a_short_word_with_details_in_tooltip(self):
        win = self.make()
        tb = win.toolbox
        short = lambda k: ui.tr(S.PRESET_SHORT[k])
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "Look 1")
        tb.presetNewBtn.click()
        self.assertFalse(tb.presetMsg.isHidden())
        self.assertEqual(tb.presetMsg.text(), short("saved"))            # 文章ではなく短語
        self.assertIn("Look 1", tb.presetMsg.toolTip())                  # 詳細は tooltip
        self.assertFalse(tb.presetMsg.wordWrap())
        self.assertLessEqual(len(tb.presetMsg.text()), 12)                # 短語(日本語 2〜3 文字 / 英語でも 1 語〜2 語)
        self.assertLess(len(tb.presetMsg.text()), len(tb.presetMsg.toolTip()))
        self.assertFalse(tb.presetMsg.property("error"))
        self._name_dialog(win, "  ")
        tb.presetNewBtn.click()
        self.assertEqual(tb.presetMsg.text(), short("invalid"))
        self.assertTrue(tb.presetMsg.toolTip())
        self.assertTrue(tb.presetMsg.property("error"))
        self.assertTrue(any("[%s]" % T.PACKAGE in w for w in self.stub.warnings))   # 必要な warning は残る
        win.save_settings()                                              # 次の同期で消える(常駐しない)
        self.assertTrue(tb.presetMsg.isHidden())

    def test_status_label_for_unsaved_unrestored_and_deferred(self):
        win = self.make()
        tb = win.toolbox
        short = lambda k: ui.tr(S.PRESET_SHORT[k])
        self.set_current(win, varied_all(1))
        self.assertTrue(win.presets.save_new("A")[0])
        self.set_current(win, varied_all(2))
        self.assertTrue(win.presets.save_new("B")[0])
        real = S.save
        S.save = lambda d: False
        self.addCleanup(setattr, S, "save", real)
        tb.refresh_presets()                                             # 直接 save_new した直後はコンボが古い。一覧を更新してから選ぶ(選べないと「解除」になる)
        self.assertGreaterEqual(tb.presetCombo.findData("A"), 0)
        tb.presetCombo.setCurrentIndex(tb.presetCombo.findData("A"))
        self.assertEqual(win.presets.selected(), "A")
        self.assertEqual(tb.presetMsg.text(), short("unsaved"))
        self.assertTrue(tb.presetMsg.property("error"))
        self.assertTrue(tb.presetMsg.toolTip())
        self.assertTrue(any("[%s]" % T.PACKAGE in w for w in self.stub.warnings))
        S.save = real
        if IS_FX:
            self.plugin.loaded = False
            tb.presetCombo.setCurrentIndex(tb.presetCombo.findData("B"))
            self.assertEqual(tb.presetMsg.text(), short("deferred"))
            self.assertFalse(tb.presetMsg.property("error"))
            self.plugin.loaded = True
            self.plugin.fail = True
        else:
            self.vp2.vals["ssaoRadius"] = 999
            self.vp2.locked.update(self.vp2.vals)
        other = "A" if IS_FX else "B"                                    # 選択中と違う方へ切り替える(同じ名前を選んでも何も起きない)
        self.assertNotEqual(win.presets.selected(), other)
        tb.presetCombo.setCurrentIndex(tb.presetCombo.findData(other))
        self.assertEqual(tb.presetMsg.text(), short("unrestored"))
        self.assertTrue(tb.presetMsg.property("error"))

    def test_status_label_for_unconfirmed_restore(self):
        win = self.make()
        tb = win.toolbox
        self.set_current(win, varied_all(1))
        self.assertTrue(win.presets.save_new("A")[0])
        self.set_current(win, varied_all(2))
        self.assertTrue(win.presets.save_new("B")[0])
        seq = []
        win._preset_apply_current = lambda: seq.pop(0)
        seq[:] = [False, S.PRESET_DEFERRED]
        tb.refresh_presets()
        self.assertGreaterEqual(tb.presetCombo.findData("A"), 0)
        tb.presetCombo.setCurrentIndex(tb.presetCombo.findData("A"))
        self.assertEqual(seq, [])                                        # 適用と再適用の 2 回が実際に走った
        self.assertEqual(tb.presetMsg.text(), ui.tr(S.PRESET_SHORT["unconfirmed"]))
        self.assertTrue(tb.presetMsg.property("error"))
        self.assertTrue(tb.presetMsg.toolTip())
        self.assertTrue(any("[%s]" % T.PACKAGE in w for w in self.stub.warnings))

    def test_broken_table_shows_not_allowed_and_keeps_file(self):
        seed = dict(DEF)
        seed[S.PRESET_TABLE_KEY] = [1, 2]
        self.write_settings_file(seed)
        win = self.make(fresh_load=True)
        disk = self.settings_file()
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "A")
        win.toolbox.presetNewBtn.click()
        self.assertEqual(win.toolbox.presetMsg.text(), ui.tr(S.PRESET_SHORT["invalid"]))
        self.assertEqual(win.data[S.PRESET_TABLE_KEY], [1, 2])
        self.assertEqual(self.settings_file(), disk)

    def test_cancel_and_invalid_name_change_nothing(self):
        win = self.make()
        tb = win.toolbox
        self._name_dialog(win, None)
        tb.presetNewBtn.click()
        self.assertEqual(win.presets.names(), [])
        self.assertTrue(tb.presetMsg.isHidden())                             # 取消は何も言わない(エラー扱いにしない)
        self.assertEqual(self.stub.warnings, [])
        self._name_dialog(win, "   ")
        tb.presetNewBtn.click()
        self.assertEqual(win.presets.names(), [])
        self.assertFalse(tb.presetMsg.isHidden())
        self.assertTrue(tb.presetMsg.property("error"))
        self.assertTrue(any("[%s]" % T.PACKAGE in w for w in self.stub.warnings))

    def test_reset_button_visible_only_when_selected_and_different(self):
        win = self.make()
        tb = win.toolbox
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "A")
        tb.presetNewBtn.click()
        self.assertTrue(self.reset_hidden(win))                            # 選択中・同じ値 → 非表示
        k = KEYS[3]
        win.data[k] = _varied(k, 2)
        win.save_settings()                                                 # 実ハンドラと同じ: data を書いて save_settings
        self.assertFalse(self.reset_hidden(win))                           # 違う → 表示
        win.data[k] = _varied(k, 1)
        win.save_settings()
        self.assertTrue(self.reset_hidden(win))                            # 戻した → 非表示
        win.data[k] = _varied(k, 2)
        win.save_settings()
        tb.presetCombo.setCurrentIndex(0)                                   # 未選択
        self.assertTrue(self.reset_hidden(win))
        self.assertEqual(win.presets.selected(), "")
        self.assertEqual(win.data[k], _varied(k, 2))                       # 選択を外しても値は変えない

    def test_reset_button_click_restores_values_and_ui(self):
        win = self.make()
        tb = win.toolbox
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "A")
        tb.presetNewBtn.click()
        if IS_FX:
            tb.diffStrength.field.setValue(0.9)                                   # 実ウィジェットを操作 → 実ハンドラ → apply_effects → 同期
            self.assertAlmostEqual(win.data["diffusionStrength"], 0.9, places=2)
            saved = _varied("diffusionStrength", 1)
            getter = lambda: tb.diffStrength.value()
        else:
            tb.ssaoAmount.field.setValue(1.9)
            self.assertAlmostEqual(win.data["ssaoAmount"], 1.9, places=2)
            saved = _varied("ssaoAmount", 1)
            getter = lambda: tb.ssaoAmount.value()
        self.assertFalse(self.reset_hidden(win))
        disk = copy.deepcopy(win.data[S.PRESET_TABLE_KEY])
        tb.presetResetBtn.click()
        self.assertAlmostEqual(win.data["diffusionStrength" if IS_FX else "ssaoAmount"], saved, places=3)
        self.assertAlmostEqual(getter(), saved, places=2)                  # UI も戻る
        self.assertTrue(self.reset_hidden(win))
        self.assertEqual(win.data[S.PRESET_TABLE_KEY], disk)               # 保存値は変わらない
        if IS_FX:
            self.assertAlmostEqual(self.plugin.calls[-1]["diffusionStrength"], saved, places=3)   # 適用経路にも流れた
        else:
            self.assertAlmostEqual(self.vp2.vals["ssaoAmount"], saved, places=3)

    def test_combo_switch_applies_and_failed_switch_reverts_combo(self):
        win = self.make()
        tb = win.toolbox
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "A")
        tb.presetNewBtn.click()
        self.set_current(win, varied_all(2))
        self._name_dialog(win, "B")
        tb.presetNewBtn.click()
        tb.presetCombo.setCurrentIndex(tb.presetCombo.findData("A"))
        self.assertEqual(win.presets.selected(), "A")
        self.assertTrue(S.preset_same(win.data[KEYS[0]], _varied(KEYS[0], 1)))
        if IS_FX:
            self.assertAlmostEqual(tb.diffStrength.value(), _varied("diffusionStrength", 1), places=2)
            self.plugin.fail = True
        else:
            self.assertAlmostEqual(tb.ssaoAmount.value(), _varied("ssaoAmount", 1), places=2)
            self.vp2.locked.update(self.vp2.vals)
        before = copy.deepcopy({k: win.data[k] for k in KEYS})
        tb.presetCombo.setCurrentIndex(tb.presetCombo.findData("B"))
        self.assertEqual(win.presets.selected(), "A")
        self.assertEqual(tb.presetCombo.currentData(), "A")                # コンボも元の選択へ戻る
        self.assertEqual({k: win.data[k] for k in KEYS}, before)
        self.assertTrue(tb.presetMsg.property("error"))

    def test_update_button_overwrites_selected_only(self):
        win = self.make()
        tb = win.toolbox
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "A")
        tb.presetNewBtn.click()
        k = KEYS[5]
        win.data[k] = _varied(k, 2)
        win.save_settings()
        self.assertFalse(self.reset_hidden(win))
        tb.presetUpdateBtn.click()
        self.assertEqual(win.presets.names(), ["A"])
        self.assertTrue(self.reset_hidden(win))
        self.assertTrue(S.preset_same(S.preset_get(win.data, "A")[k], _varied(k, 2)))

    def test_edit_path_updates_reset_visibility_through_real_save_settings(self):
        win = self.make()
        tb = win.toolbox
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "A")
        tb.presetNewBtn.click()
        win.data[KEYS[4]] = _varied(KEYS[4], 2)
        self.assertTrue(self.reset_hidden(win))                            # まだ誰も同期していない
        win.save_settings()                                                 # 実物の Window.save_settings(= 全ての値変更が通る)
        self.assertFalse(self.reset_hidden(win))

    def test_fx_drag_path_updates_reset_visibility(self):
        if not IS_FX:
            self.skipTest("Fx のみ(スライダのドラッグ中は save=False で適用する)")
        win = self.make()
        tb = win.toolbox
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "A")
        tb.presetNewBtn.click()
        win.data["diffusionStrength"] = 0.99
        win.apply_effects(save=False, undoable=False)
        self.assertFalse(self.reset_hidden(win))

    def test_grade_reset_is_distinct_from_preset_reset(self):
        win = self.make()
        tb = win.toolbox
        self.assertIsNot(tb.presetResetBtn, getattr(tb, "gradeReset", None))
        self.assertNotEqual(tb.presetResetBtn.toolTip(), getattr(getattr(tb, "gradeReset", None), "toolTip", lambda: "")())
        if not IS_FX:
            self.skipTest("グレードは Fx のみ")
        self.set_current(win, varied_all(1))
        win.data["effectsMaster"] = True                                    # master OFF だとグレードのカードごと無効(押せない)
        tb.pull_effects(win.data)
        self._name_dialog(win, "A")
        tb.presetNewBtn.click()
        tb.gradeReset.click()                                                # 既定値 Reset: 値を既定へ(プリセットの保存値は変えない)
        self.assertEqual(win.data["gradeExposure"], T.pkg.GRADE_DEFAULTS["gradeExposure"])
        self.assertEqual(win.data[S.PRESET_TABLE_KEY]["A"]["gradeExposure"], _varied("gradeExposure", 1))
        self.assertFalse(self.reset_hidden(win))                            # 保存値と違う → プリセット Reset が出る
        tb.presetResetBtn.click()
        self.assertTrue(S.preset_same(win.data["gradeExposure"], _varied("gradeExposure", 1)))

    def test_restart_restores_list_selection_and_dirty_state(self):
        win = self.make()
        tb = win.toolbox
        self.set_current(win, varied_all(1))
        self._name_dialog(win, "A")
        tb.presetNewBtn.click()
        win.data[KEYS[2]] = _varied(KEYS[2], 2)
        self.assertTrue(S.save(win.data))                                   # 通常の自動保存(debounce 後)に相当
        win2 = self.make(fresh_load=True)
        tb2 = win2.toolbox
        self.assertEqual(tb2.presetCombo.currentData(), "A")
        self.assertFalse(self.reset_hidden(win2))                          # 再起動後も「選択中 + 保存値と違う」なら Reset が出る
        tb2.presetResetBtn.click()
        self.assertTrue(S.preset_same(win2.data[KEYS[2]], _varied(KEYS[2], 1)))

    def test_toolbox_tolerates_owner_without_presets(self):
        w = FakeWin({})
        tb = ui.ToolBox(w)
        self.addCleanup(tb.deleteLater)
        w.toolbox = tb
        tb.pull(dict(settings.DEFAULTS))
        self.assertFalse(tb.presetCombo.isEnabled())
        tb.presetNewBtn.click()                                             # 何も起きない(例外にならない)
        tb.refresh_presets()

    def test_pull_effects_does_not_touch_other_cards(self):
        win = self.make(UNRELATED)
        tb = win.toolbox
        marker = "X:/typed/by/user.mp4"
        tb.mp4Output.setText(marker)                                         # 未確定の入力(pull されたら data の値に戻ってしまう欄)
        tb.pull_effects(win.data)
        self.assertEqual(tb.mp4Output.text(), marker)

    def test_new_strings_have_english(self):
        i18n.set_language("en")
        self.addCleanup(i18n.set_language, "ja")
        src = (PKG_DIR / "settings.py").read_text(encoding="utf-8")
        a = src.index("調整プリセット(FX-PRESETS")
        ui_src = (PKG_DIR / "ui.py").read_text(encoding="utf-8")
        b = ui_src.index("-- 調整プリセット(FX-PRESETS)")
        e = ui_src.index("    def _on_effects_collapsed(self, collapsed):")
        lits = set(re.findall(r'tr\(u"([^"]+)"\)', src[a:] + ui_src[b:e]))
        lits = set(s for s in lits if s not in (u"設定の保存に失敗しました: {}",)) | {u"設定の保存に失敗しました: {}"}
        self.assertGreater(len(lits), 15)
        for s in lits:
            self.assertIn(s, i18n.JA_TO_EN, "英語訳が無い: " + s)
            self.assertNotEqual(i18n.tr(s), s, s)


if __name__ == "__main__":
    print("PySide6 " + qt.QtCore.qVersion() if hasattr(qt.QtCore, "qVersion") else "")
    unittest.main(verbosity=2)
