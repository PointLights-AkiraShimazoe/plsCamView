# Changelog

## 0.9.1 — 2026-11-10

主な変更 / Changes:

- **Playblast カードを整理**: 上から Force Playblast Target / Multi / Time Range / 出力先 / SETTINGS / 撮影オプション /
  完了後に開く・PNG を残す / 実行。スイッチを切り替えても部品の位置や行の数は変わりません
  - Multi を ON にすると右に 合成・個別保持 が出ます（個別保持は合成 ON のときだけ押せます）
  - Time Range: シーン範囲 OFF で同じ行の 開始 → 終了 を入力（ON の間はシーンの範囲を表示して押せない状態）
  - 形式・解像度・FPS・品質（CRF・プリセット）は畳める SETTINGS に。畳んでいるときは見出しに現在値の要約
  - 解像度・FPS の欄は隠さず、レンダー設定 / シーン ON の間はその値を表示して押せない状態に（OFF で指定値に戻る）
  - 装飾 (HUD)・オフスクリーン・ビューポート最適化は畳める「撮影オプション」に
  - CRF・プリセット・PNG を残す は MP4 のときだけ表示（形式を切り替えても高さは変わりません）
  - 実行ボタンは形式に関係なく「Playblast 実行」
- ツールボックスを上下に置いたとき、Playblast カードは右側で縦にスクロールし、部品が潰れません
- **Effects の調整プリセット**（値と ON/OFF に名前を付けて保存・切替・更新・保存値へ戻す）
- カメラ一覧の **＋ New** で新しいカメラを作り、そのビューだけを切り替え
- 内側ゲートの塗りの色が重なって混ざる問題を修正（各帯に指定色が 1 回だけ乗る）
- ゲート / ガイドの位置合わせを修正（ウィンドウの移動・ドック幅の変更・ワークスペース内のパネル移動のあと）
- 単独 / Multi の Playblast が失敗することがある問題、Show（Polygon / 標準）が一部のビューにしか効かない問題、
  入力欄の文字が欠ける問題を修正
- 数値欄・スライダー・プルダウンは、クリックするまでマウスホイールで値が変わらないように（スクロール中の誤操作防止）
- UI 倍率（75/85/100/115/125%・既定 85%）。最上部の ⚙ から選択・保存し、開き直しで反映
- Language（UI 言語）を最上部のレイアウト切替アイコンと同じ行の右端へ移動
- インストーラの画面を CamView 本体と同じ見た目に刷新（更新時の旧版退避と ffmpeg の引き継ぎは従来どおり）
- 使い方ガイド（日英）を更新

既知の制限 / Known limitations:

- ゲート / ガイドは画面確認用のオーバーレイで、Playblast には写りません
- 100% 以上の UI 倍率や狭いドックでは、ツールボックスに横スクロールが出ることがあります
- MEL から直接 playblast を呼ぶツールは Force Playblast Target の対象外です。MP4 出力は Windows で検証しています

## 0.9.0 — 2026-10-24（初回公開版 / first public release）

開発版 1.8.3 の内容をそのまま初回公開版 0.9.0 として整理したものです（機能の削減はありません）。
This is the first public release; it repackages internal build 1.8.3 without removing features.

主な機能 / Highlights:

- Maya のメインウィンドウから分離したカメラビュー（Tear Off Copy と同じメニュー・アイコンバー）
- 最大 4 ビュー（横並び / 縦並び / グリッド、各ビューのポップアウトと復帰）
- ビューごとのカメラ切り替え、カメラ一覧の自動更新
- Gate: レゾリューションゲートのオーバーレイ（マスク・枠・内側ゲート×3、線/塗り/破線）
- Guides: 構図ガイド（三分割 / 黄金・白銀の比率グリッド / アーマチュア / 中心、Fit to・色・太さ・不透明度）
- Effects（SSAO / Anti-aliasing / Line AA の一括 ON/OFF と個別調整）、Shadow、Show プリセット
- Force Playblast Target（Maya 標準・Python ツールの Playblast をこのビューへ固定、OFF で完全復元）
- Playblast 出力: Maya 標準 / MP4（H.264、同梱しない ffmpeg を bin/ に配置）、ビューポート最適化
- 複数カメラ出力（Multi）: 順次撮影、位置・比率を保った合成（`_Multi.mp4`）、個別保持、上書き防止
- UI 言語: 日本語 / English / システム追従
- 更新に安全なインストーラ（新版コピー完了後に旧版退避、失敗時は旧版へ復元。
  配布物に ffmpeg が無い更新では、利用者が置いた `bin/ffmpeg.exe` を自動で引き継ぐ）
- すべての状態の自動保存・復元（settings.json）

既知の制限 / Known limitations:

- Gate / Guides は画面確認用のオーバーレイで、Playblast には写りません
- MEL から `playblast` / `getPanel` を直接呼ぶツールは Force Playblast Target の対象外です
- MP4 出力は Windows で検証済み（他 OS は `bin/ffmpeg` を配置）
