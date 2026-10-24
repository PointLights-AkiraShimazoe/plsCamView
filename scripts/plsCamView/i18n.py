# -*- coding: utf-8 -*-
u"""
plsCamView.i18n
===============
UI 表示言語「システム / 日本語 / English」(v1.8.1)。plsCamView 単体で完結する小さな辞書方式で、
翻訳フレームワークや外部ファイルは使わない。

仕様(本人指示 2026-10-20):
  言語設定   : settings の "language" = "system"(既定) / "ja" / "en"。保存され、次回起動で復元。
  system 判定: 1) maya.cmds.about(uiLanguage=True) (例 "ja_JP" / "en_US")
               2) 取れなければ QtCore.QLocale.system().name()
               判定した言語タグが "ja" で始まれば日本語、それ以外はすべて English(未対応ロケールの
               fallback は English)。
  tr(text)   : ソース上の文字列そのものをキーに辞書を引く。**キーが無ければ原文をそのまま返す**
               (欠落で例外にしない)。ja 表示では EN_TO_JA、en 表示では JA_TO_EN を使う。
               ソースは日本語と英語が混在しているため、両方向の辞書を持つ。
  翻訳対象   : メニュー / ラベル / tooltip / ダイアログ / ユーザー向けエラー文(warning・
               例外メッセージ・進行ダイアログ)。ツールボックスの全カードと CameraBar・
               Playblast / 複数書き出し / フックのユーザー向けメッセージを含む(継続63)。
  翻訳しない : 製品名(plsCamView 等)・材質名・カメラ名・パネル名・パス・数値・ユーザー入力・
               ログ用の識別子。これらは tr() を通さない(呼び出し側の契約)。
               Script Editor の工程ログ(_log / _info / print)と diagnose の診断出力、
               Settings 要約の値表記(MP4 / 1920×1080 / scene / CRF 等)は値のため対象外。
               折り畳みカードの要約(mask/frame・off・ガイド名)は**ユーザー表示なので翻訳対象**
               (数値・px・% は原表記のまま。継続65 監督指摘で追加)。
               "Playblast" / "CRF" / "FPS" / "MP4" は Maya の機能名・技術用語として両言語で同表記。
               "Force Playblast Target" / "From Render Settings" は**設定ラベルとして和訳**し、
               Maya 標準項目との対応説明(原名)は tooltip に保持する(継続65 監督指摘)。
  反映の時点 : ダイアログ・警告・新しく作る UI は即時。既に開いているウィンドウの文言は
               次に開き直したときに適用(言語を変えた際にその旨を表示する)。Maya の再起動は不要。
"""
from __future__ import absolute_import

try:
    from maya import cmds
except Exception:                                  # Maya 外(テスト)
    cmds = None

LANGS = ("system", "ja", "en")

_current = "system"        # settings から set_language() で復元される
_resolved_cache = None


def _system_lang():
    u"""システム言語を 'ja' か 'en' に解決する(仕様はモジュール docstring)。"""
    tag = ""
    if cmds is not None:
        try:
            tag = str(cmds.about(uiLanguage=True) or "")
        except Exception:
            tag = ""
    if not tag:
        try:
            from .qt import QtCore
            tag = str(QtCore.QLocale.system().name() or "")
        except Exception:
            tag = ""
    return "ja" if tag.lower().startswith("ja") else "en"


def set_language(code):
    u"""'system' / 'ja' / 'en' を設定(不明値は 'system' 扱い)。戻り値は実際に使う言語 'ja'/'en'。"""
    global _current, _resolved_cache
    _current = code if code in LANGS else "system"
    _resolved_cache = None
    return resolved()


def current():
    u"""設定値('system'/'ja'/'en')。"""
    return _current


def resolved():
    u"""表示に使う言語('ja' か 'en')。"""
    global _resolved_cache
    if _resolved_cache is None:
        _resolved_cache = _system_lang() if _current == "system" else _current
    return _resolved_cache


def tr(text):
    u"""表示文字列の翻訳。キーが無ければ原文のまま返す。None はそのまま。"""
    if not text:
        return text
    lang = resolved()
    if lang == "ja":
        return EN_TO_JA.get(text, text)
    return JA_TO_EN.get(text, text)


# --------------------------------------------------------------------------
#  辞書(ソース文字列そのものがキー。v1.8.1 継続63 で全ユーザー表示へ拡大:
#  全カード / CameraBar / ダイアログ / ユーザー向けエラー。
#  対象外の線引きはモジュール docstring を参照)
# --------------------------------------------------------------------------

# 英語キー → 日本語(ソースが英語表記の箇所)
EN_TO_JA = {
    u"Language": u"言語",
    u"System": u"システム",
    u"Mask color": u"マスク色",
    u"Mask opacity": u"マスク不透明度",
    u"Frame color": u"枠線の色",
    u"Frame width": u"枠線の太さ",
    u"Inner gates": u"内側ゲート",
    u"Dashed": u"破線",
    u"Guides": u"ガイド",
    u"Gate": u"ゲート",
    u"Mask / Frame": u"マスク / 枠線",
    u"Ratio": u"比率",
    u"Fit to": u"合わせる枠",
    u"Opacity": u"不透明度",
    u"Width": u"太さ",
    u"Enable": u"有効",
    u"Views": u"ビュー",
    u"Show": u"表示",
    u"Shadow": u"シャドウ",
    u"Shadows": u"シャドウ",
    u"Effects": u"エフェクト",
    u"Settings": u"設定",
    u"Playblast": u"Playblast",                        # Maya の機能名(同形)
    u"Force Playblast Target": u"Playblast 対象を固定",    # 原名は tooltip に保持
    u"From Render Settings": u"レンダー設定の解像度",       # 原名との対応は tooltip に保持
    u"mask {:.2f} / frame {:.1f}px": u"マスク {:.2f} / 枠 {:.1f}px",
    u"off": u"オフ",
    u"Screen-space Ambient Occlusion": u"SSAO(画面空間の環境遮蔽)",
    u"Anti-aliasing": u"アンチエイリアス",
    u"Enable Anti-aliasing": u"アンチエイリアスを有効化",
    u"Line Anti-aliasing": u"線のアンチエイリアス",
    u"Sample count": u"サンプル数",
    u"Samples": u"サンプル数",
    u"Amount": u"強さ",
    u"Radius": u"半径",
    u"Filter Radius": u"フィルタ半径",
    u"All": u"すべて",
    u"None": u"なし",
    u"Polygon": u"ポリゴン",
    u"Color": u"色",
    u"Multi": u"複数",
}

# 日本語キー → English(ソースが日本語表記の箇所)
JA_TO_EN = {
    u"言語": u"Language",
    u"システム": u"System",
    u"日本語": u"日本語",            # 言語名は原語表記のまま
    u"レゾリューションゲート(レンダー解像度の範囲)を各ビューの上に描く(オーバーレイ)":
        u"Draw the resolution gate (render-resolution region) over each view (overlay).",
    u"構図ガイド全体の ON/OFF(各系統のスイッチはそのまま保持)":
        u"Master ON/OFF for composition guides (each guide's own switch is kept).",
    u"三分割": u"Thirds",
    u"グリッド": u"Grid",
    u"比率グリッド": u"Ratio grid",
    u"アーマチュア": u"Armature",
    u"中心": u"Center",
    u"1/3・2/3 の縦横線": u"Horizontal / vertical lines at 1/3 and 2/3.",
    u"黄金比 0.382/0.618(白銀比 0.414/0.586)の縦横線":
        u"Lines at golden-ratio 0.382/0.618 (silver-ratio 0.414/0.586).",
    u"対角線 2 本 + 各隅から対角線への垂線 4 本 + 交点(目)を通る縦横 4 本。\n黄金比(または白銀比)の矩形で計算して枠に引き伸ばす(MoveSpirit と同じ)":
        u"2 diagonals + 4 perpendiculars from the corners + 4 lines through the eyes.\nComputed on a golden (or silver) rectangle and stretched to the frame (same as MoveSpirit).",
    u"黄金比 φ": u"Golden ratio φ",
    u"白銀比 √2": u"Silver ratio √2",
    u"レゾリューションゲート": u"Resolution gate",
    u"内側ゲート 1": u"Inner gate 1",
    u"内側ゲート 2": u"Inner gate 2",
    u"内側ゲート 3": u"Inner gate 3",
    u"ビュー全体": u"Whole view",
    u"ガイドを合わせる矩形。内側ゲートは Inner gates の % を使う(本数が足りなくても計算には使える)":
        u"Rectangle the guides fit to. Inner gates use the % from Inner gates (usable even when fewer gates are shown).",
    u"画面上のオーバーレイ(Playblast には写りません)":
        u"On-screen overlay (not captured in Playblast).",
    u"言語設定は次にウィンドウを開いたときに適用されます":
        u"The language setting is applied the next time the window is opened.",
    u"UI の表示言語。システム = Maya / OS の言語に従う":
        u"UI display language. System = follow the Maya / OS language.",
    u"線": u"Stroke",
    u"塗り": u"Fill",
    u"このゲートを描く": u"Draw this gate.",
    u"線(1px、Dashed で破線)": u"Stroke (1 px; dashed when Dashed is on).",
    u"塗り: このゲートの外側(レゾリューションゲート内)を色で覆う":
        u"Fill: covers the area outside this gate (inside the resolution gate) with the color.",
    u"塗りの不透明度": u"Fill opacity",

    # ---- ツールボックス(ドック / Views / Effects / Show / Shadow) ----
    u"左": u"Left",
    u"上": u"Top",
    u"下": u"Bottom",
    u"右": u"Right",
    u"ツールボックスを{}に配置": u"Dock the toolbox: {}",
    u"ビューの数": u"Number of views",
    u"横並び": u"Side by side",
    u"縦並び": u"Stacked",
    u"ビューを{}に配置": u"Arrange views: {}",
    u"標準カメラ": u"Startup cameras",
    u"persp / top / front / side をカメラ一覧に含める":
        u"Include persp / top / front / side in the camera list.",
    u"カメラ一覧を読み直す(カメラを追加・削除したとき)":
        u"Reload the camera list (after adding or removing cameras).",
    u"OFF で SSAO・アンチエイリアス・線 AA をまとめて切る(個別の設定は保持)":
        u"OFF disables SSAO, anti-aliasing and line AA together (individual settings are kept).",
    u"ビューポートの Lighting > Shadows と同じ設定です。":
        u"Same as the viewport's Lighting > Shadows.",

    # ---- Playblast カード ----
    u"Force Playblast Target: ON の間、このビューがアクティブでなくても\nMaya 標準/外部のPlayblastは最後に追加した対象1つ。複数出力はこのツールの実行ボタン。":
        u"Force Playblast Target: while ON, Maya standard / external playblasts go to the last added target\neven when this view is not active. Use this tool's run button for multiple outputs.",
    u"ONで複数の対象を選択。OFFでは最後に選択した対象1つに戻します。":
        u"ON: select multiple targets. OFF: back to the single last-selected target.",
    u"合成": u"Combine",
    u"選択した複数ビューの位置・比率で動画を合成（_Multi.mp4）。画像は引き伸ばしません。":
        u"Compose one video from the selected views' layout (_Multi.mp4). Images are not stretched.",
    u"個別保持": u"Keep each",
    u"合成と一緒に各カメラの出力も保存。合成OFFなら常に個別保存。失敗時は途中出力を保全。":
        u"Also keep each camera's output with the combined one. Always kept when Combine is OFF. Partial outputs are preserved on failure.",
    u"Maya 標準": u"Maya native",
    u"幅": u"Width",
    u"高さ": u"Height",
    u"品質": u"Quality",
    u"プリセット": u"Preset",
    u"出力先": u"Output",
    u"シーン": u"Scene",
    u"ON: シーンの時間単位から FPS を決める": u"ON: derive FPS from the scene's time unit.",
    u"playblast の quality(1-100)": u"playblast quality (1-100).",
    u"H.264 品質(0-51)。低いほど高画質。18-23 推奨(MP4 のみ)":
        u"H.264 quality (0-51). Lower = better quality. 18-23 recommended (MP4 only).",
    u"x264 プリセット。遅いほど同じ CRF で小さくなる(MP4 のみ)":
        u"x264 preset. Slower = smaller files at the same CRF (MP4 only).",
    u"自動": u"Auto",
    u"出力先。空なら <プロジェクト>/movies/<シーン>_<カメラ>":
        u"Output path. Empty = <project>/movies/<scene>_<camera>.",
    u"出力先を選択": u"Choose the output path",
    u"Maya 標準 Playblast の「Display size: From Render Settings」と同じ。\n幅/高さをレンダー設定の解像度にし、オーバースキャン 1.0・パン/ズーム無効で書き出す\n= レゾリューションゲート(最終描画範囲)ぴったりの動画。幅/高さの欄は無視される。":
        u"Same as Maya's playblast \"Display size: From Render Settings\".\nUses the render-settings resolution with overscan 1.0 and pan/zoom disabled\n= a video that matches the resolution gate exactly. The width/height fields are ignored.",
    u"装飾 (HUD)": u"Ornaments (HUD)",
    u"showOrnaments: HUD やカメラ名などを写す": u"showOrnaments: capture HUD, camera name, etc.",
    u"オフスクリーン": u"Off screen",
    u"offScreen: 他ウィンドウの重なりに影響されない":
        u"offScreen: not affected by overlapping windows.",
    u"ビューポート最適化": u"Optimize viewport",
    u"書き出し中のみ、画角をレンダー枠に固定 / Polygon のみ表示 /\nUse All Lights / SSAO・線 AA・MSAA を ON にし、完了後に元へ戻します。":
        u"Only while exporting: lock the view to the render frame, show polygons only,\nuse all lights and enable SSAO / line AA / MSAA, then restore everything afterwards.",
    u"PNG を残す": u"Keep PNG frames",
    u"中間の PNG 連番(一時フォルダ)を削除しない(MP4 のみ)":
        u"Do not delete the intermediate PNG sequence (temp folder) (MP4 only).",
    u"完了後に開く": u"Open when done",
    u"Playblast 実行": u"Run Playblast",
    u"MP4 に書き出し": u"Export MP4",
    u"MP4 の出力先": u"MP4 output path",
    u"書き出し中です。": u"An export is already running.",
    u"対象パネルがありません。": u"No target panel.",
    u"準備中": u"Preparing",
    u"取消": u"Cancel",
    u"複数カメラ Playblast": u"Multi-camera Playblast",

    # ---- ウィンドウ / ビュー操作(views.py・ui.py の警告) ----
    u"plsCamView は Maya 上でのみ動作します。": u"plsCamView only runs inside Maya.",
    u"ツールボックスの生成に失敗しました(Maya レイアウト {} を QWidget として取得できません)。":
        u"Failed to build the toolbox (Maya layout {} could not be wrapped as a QWidget).",
    u"ツールボックス位置の変更に失敗: {}": u"Failed to change the toolbox position: {}",
    u"ゲートの適用に失敗: {}": u"Failed to apply the gate: {}",
    u"(カメラなし)": u"(no camera)",
    u"Playblast 対象を追加・解除（複数選択）\n紫 = 選択中。最後の1つは解除しません。":
        u"Add / remove this view as a Playblast target (multi-select).\nPurple = selected. The last one cannot be removed.",
    u"前のカメラ": u"Previous camera",
    u"このビューのカメラを切り替える": u"Switch this view's camera",
    u"次のカメラ": u"Next camera",
    u"Playblast 対象から解除（最後の1つは保持）":
        u"Remove from the Playblast targets (the last one is kept)",
    u"Playblast 対象へ追加（複数選択）": u"Add to the Playblast targets (multi-select)",
    u"Playblast 対象（1つ選択）": u"Playblast target (single)",
    u"このビューをPlayblast対象にする": u"Make this view the Playblast target",
    u"メインウィンドウへ戻す(再ドッキング)": u"Return to the main window (re-dock)",
    u"別ウィンドウに出す(ポップアウト)": u"Move to a separate window (pop out)",
    u"ビュー {} のレイアウトに失敗: {}": u"Failed to lay out view {}: {}",
    u"ビュー {} のカメラバーを配置できませんでした。": u"Could not place the camera bar for view {}.",
    u"ビュー {} の再ドッキングに失敗: {}": u"Failed to re-dock view {}: {}",
    u"すべてのビューがポップアウト中です": u"All views are popped out",
    u"ビューの配置に失敗: {}": u"Failed to arrange the views: {}",
    u"対象カメラがありません。": u"No target camera.",
    u"カメラを一意に識別できません: {}": u"The camera name is not unique: {}",
    u"カメラの親を識別できません: {}": u"Cannot resolve the camera's parent: {}",
    u"対象ビューを表示してから合成してください。": u"Show the target views before combining.",
    u"カメラ切替に失敗: {}": u"Failed to switch the camera: {}",
    u"Show プリセット適用に失敗: {}": u"Failed to apply the Show preset: {}",
    u"Shadow の切替に失敗: {}": u"Failed to toggle shadows: {}",
    u"{} の設定に失敗: {}": u"Failed to set {}: {}",
    u"ゲートオーバーレイを作れませんでした: {}": u"Could not create the gate overlay: {}",
    u"設定の保存に失敗しました({}): {}": u"Failed to save the settings ({}): {}",
    u"設定の初期化に失敗しました: {}": u"Failed to reset the settings: {}",
    u"シェルフを特定できませんでした。": u"Could not determine the shelf.",
    u"PLS CamView: 分離カメラビューを開く": u"PLS CamView: open the detached camera view",
    u"PLS CamView: 最新コードを読み直して開く(Maya 再起動不要)":
        u"PLS CamView: reload the latest code and open (no Maya restart needed)",

    # ---- Playblast / MP4 の結果・エラー(mp4blast.py) ----
    u"出力フォルダを作成できません: {} ({})": u"Cannot create the output folder: {} ({})",
    u"読み取り専用を解除できません: {} ({})": u"Cannot clear the read-only flag: {} ({})",
    u"出力ファイルが読み取り専用です(チェックアウト漏れ?): {}":
        u"The output file is read-only (not checked out?): {}",
    u"出力ファイルを開けません(他アプリで使用中?): {} ({})":
        u"Cannot open the output file (in use by another app?): {} ({})",
    u"出力フォルダに書き込めません: {} ({})": u"Cannot write to the output folder: {} ({})",
    u"Maya 外では実行できません。": u"This can only run inside Maya.",
    u"対象パネルが見つかりません。": u"Target panel not found.",
    u"同梱の ffmpeg が見つかりません: {} に ffmpeg.exe を置いてください。":
        u"Bundled ffmpeg not found: place ffmpeg.exe at {}.",
    u"ffmpeg が失敗しました(Script Editor を確認)。": u"ffmpeg failed (see the Script Editor).",
    u"完了: {}": u"Done: {}",
    u"失敗: {}": u"Failed: {}",

    # ---- 複数書き出し(multiblast.py) ----
    u"同名カメラにnamespaceがありません: {}": u"Same-named cameras without a namespace: {}",
    u"カメラの出力名を決められません: {}": u"Cannot derive an output name for the camera: {}",
    u"namespaceを使っても出力名が重複します。対象またはnamespaceを変更してください。":
        u"Output names still collide even with namespaces. Change the targets or namespaces.",
    u"合成サイズは2以上の偶数にしてください。": u"The combined size must be even numbers of 2 or more.",
    u"ビューの表示配置を取得できません。ウィンドウを表示してください。":
        u"Cannot read the views' on-screen layout. Show the window first.",
    u"合成対象のビューが重なっています。重ならない位置へ移動してください。":
        u"The views to combine overlap. Move them so they do not overlap.",
    u"合成サイズに対して小さすぎるビューがあります。": u"A view is too small for the combined size.",
    u"画像連番として認識できません: {}": u"Not recognized as an image sequence: {}",
    u"撮影した画像連番に欠落があります。": u"The captured image sequence has missing frames.",
    u"画像連番の形式が混在しています。": u"The image-sequence formats are mixed.",
    u"合成中": u"Combining",
    u"合成を取り消しました。": u"Combining was cancelled.",
    u"合成に失敗: {}": u"Combining failed: {}",
    u"複数書き出しには2つ以上の対象が必要です。": u"Multi-export needs two or more targets.",
    u"カメラ名Multiは合成名と重なります。対象名を変更してください。":
        u"A camera named 'Multi' collides with the combined output name. Rename the target.",
    u"出力先はフォルダーではなくファイル名まで指定してください。":
        u"Specify the output as a file name, not a folder.",
    u"出力が既に存在します。別の出力名を指定してください: {}":
        u"The output already exists. Use a different name: {}",
    u"FPSは正の数にしてください。": u"FPS must be a positive number.",
    u"複数書き出しの範囲は整数フレームの開始≦終了にしてください。":
        u"The multi-export range must be integer frames with start <= end.",
    u"動画合成にはffmpegが必要です: {}": u"Combining videos requires ffmpeg: {}",
    u"対象ビューが見つかりません: {}": u"Target view not found: {}",
    u"撮影 {}/{}: {}": u"Capturing {}/{}: {}",
    u"書き出しを取り消しました。": u"Export was cancelled.",
    u"出力がありません。": u"No output was produced.",
    u"合成動画が作成されませんでした。": u"The combined video was not created.",
    u"完了 {}件: {}": u"Done ({} files): {}",
    u"\n途中の動画・画像を保全: {}": u"\nPartial videos/images preserved at: {}",
    u"\n出力済み: {}": u"\nAlready exported: {}",

    # ---- Force Playblast Target(playblast_hook.py の警告) ----
    u"Playblast の実行に失敗: {}": u"Failed to run the playblast: {}",
    u"Playblast のターゲット情報が失われています。Force Playblast Target を OFF→ON し直してください。":
        u"The Playblast target info was lost. Turn Force Playblast Target OFF and ON again.",
    u"対象パネルが見つかりません: {}": u"Target panel not found: {}",
    u"Playblast のターゲットを強制できませんでした。ツールの [Playblast 実行] ボタンをご利用ください。":
        u"Could not force the Playblast target. Use the tool's [Run Playblast] button.",
    u"performPlayblast.mel が見つからないため、標準 Playblast のフックを行えませんでした。ツール内の [Playblast 実行] ボタンをご利用ください。":
        u"performPlayblast.mel was not found, so the standard Playblast could not be hooked. Use the tool's [Run Playblast] button.",
    u"performPlayblast の退避に失敗したため、標準 Playblast のフックを行えませんでした。ツール内の [Playblast 実行] ボタンをご利用ください。":
        u"Failed to back up performPlayblast, so the standard Playblast could not be hooked. Use the tool's [Run Playblast] button.",
    u"Playblast フックの導入に失敗: {}": u"Failed to install the Playblast hook: {}",
    u"先行ツールのPlayblastフック復元に失敗: {}":
        u"Failed to restore a previous tool's Playblast hook: {}",
    u"Playblast フックの解除に失敗: {}": u"Failed to remove the Playblast hook: {}",
    u"Playblast の対象パネルが見つかりません。": u"No target panel for Playblast.",
    u"Playblast オプションの表示に失敗: {}": u"Failed to open the Playblast options: {}",
}
