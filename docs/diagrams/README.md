# plsCamView 構造図（docs/diagrams）

plsCamView のコード構造図は [Archify](https://github.com/tt-a1i/archify) で生成しています。
JSON が編集元（正）、同名の HTML が配信物です。ノード ID とパッケージ階層ビューの構成は
版を跨いで安定させています（既存 ID は変更しない）。

| 図 | 編集元 JSON | 配信 HTML | 内容 |
|---|---|---|---|
| アーキテクチャ | diagrams/architecture.architecture.json | ../architecture.html | モジュール構成と依存 |
| 使い方の流れ | diagrams/workflow.workflow.json | ../workflow.html | 起動〜Playblast のユーザーフロー |
| 複数カメラ書き出し | diagrams/multi-playblast.workflow.json | diagrams/multi-playblast.html | Multi の処理手順 |
| 追従と終了処理 | diagrams/ui-lifecycle.workflow.json | diagrams/ui-lifecycle.html | ウィンドウ追従・終了・保存の流れ |

## 照合記録（0.9.0 / 2026-10-24）

- 対象範囲: 上記 4 図。0.9.0 でのコード変更（版表記・installer の ffmpeg 引き継ぎ）は
  図のノード・接続に影響しないことを照合済み。architecture / workflow は題字のみ
  0.9.0 へ更新（ノード・ID・レイアウト変更なし）。multi-playblast / ui-lifecycle は変更なし。
- 検証結果: architecture.architecture.json は Archify validate（--quality showcase）で
  9 チェック・errors 0・warnings 0（2026-10-24）。workflow.workflow.json は題字 1 行のみの
  差分であることをバイト照合で確認。
- パッケージ階層ビュー: 公開版はパス表示・コピーとも**リポジトリ相対パス**
  （エディタ連携リンクは無効）。
- 編集元 JSON の SHA256（2026-10-24）:
  - architecture.architecture.json `a8710ca4d5403e3035e599ef5de468d9efe81e87ef04a8a9c6744b54dce7a7ad`
  - workflow.workflow.json `f75fa23e6829720956b857e379df3a0b498f5237aa51140065e599cf8a1aa4fa`
  - multi-playblast.workflow.json `2049d67b0be76d600aa1590622a4fb9405c65698a6ba9bf4d8b757224e9de3a3`
  - ui-lifecycle.workflow.json `5edc787753c917fc4f150d91e6d5e84c9f7eb9761d23d69faa031be3230fbf37`

## 再生成手順

Archify CLI（node）で、リポジトリのルートから:

```
node <archify>/bin/archify.mjs validate architecture docs/diagrams/architecture.architecture.json --quality showcase --json
node <archify>/bin/archify.mjs deliver  architecture docs/diagrams/architecture.architecture.json docs/architecture.html --quality showcase
node <archify>/bin/archify.mjs validate workflow docs/diagrams/workflow.workflow.json --quality showcase --json
node <archify>/bin/archify.mjs deliver  workflow docs/diagrams/workflow.workflow.json docs/workflow.html --quality showcase
```

（multi-playblast / ui-lifecycle も同じ workflow コマンドで、出力先を docs/diagrams/ 直下にする。）
再生成後、公開版ではパッケージ階層ビューの root を空（相対パス表示）にすること。
