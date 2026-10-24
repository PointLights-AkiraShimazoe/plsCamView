# Changelog

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
