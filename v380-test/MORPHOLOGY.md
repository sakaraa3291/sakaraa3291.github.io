# v3.8.0 コース形態（テスト版）

確認日: 2026-10-06。対象はこのディレクトリのみ。本番への昇格は別作業。

JRA公式主・うましる/競馬ラボ補助照合。今回の実装では、依頼の距離整理を
JRA現行距離表と照合し、以下10場の公式平面図を目視して独自ベクターを作成した。
公式画像をアプリに同梱・転載していない。

| 場 | JRA公式（平面図・距離表） | 主な形状 |
|---|---|---|
| 東京 | https://www.jra.go.jp/facilities/race/tokyo/course/index.html | 長い直線、左右で異なる曲線 |
| 中山 | https://www.jra.go.jp/facilities/race/nakayama/course/index.html | 外回りの張り出しと斜めの向正面 |
| 京都 | https://www.jra.go.jp/facilities/race/kyoto/course/index.html | 傾いた向正面、3角分岐・4角合流 |
| 阪神 | https://www.jra.go.jp/facilities/race/hanshin/course/index.html | 外回りの長い向正面と大きい3〜4角 |
| 中京 | https://www.jra.go.jp/facilities/race/chukyo/course/index.html | 傾いた向正面と非対称の曲線 |
| 新潟 | https://www.jra.go.jp/facilities/race/niigata/course/index.html | 外回りの長い直線と拡大した左側、1000m直線 |
| 福島 | https://www.jra.go.jp/facilities/race/fukushima/course/index.html | 左右の曲線形状の違い |
| 札幌 | https://www.jra.go.jp/facilities/race/sapporo/course/index.html | 短い直線と大きな曲線の比率 |
| 函館 | https://www.jra.go.jp/facilities/race/hakodate/course/index.html | 札幌より長細い周回 |
| 小倉 | https://www.jra.go.jp/facilities/race/kokura/course/index.html | 横長の周回と丸い曲線 |

補助資料: https://umasiru.com/archives/category/racecourse 、
https://www.keibalab.jp/yosou/coursedata/ 。今回全補助ページを再読したという意味ではなく、
ユーザーの照合済み整理を利用し、最終判定は上記公式に置いた。

## 表示と制限

- 24種類の周回ベクターと新潟1000m直線。全127距離・内外を含む133経路。
- `shape_id` でテンプレートを選び、右左回りを平面図と同じ向きで表示する。
- 曲線を同一の折れ線にサンプリングしてSVG描画と距離位置計算に使う。
  経路長/公式1周距離を一定の倍率として色帯と距離点を配置する。
  実地の座標・区間形状を距離精度で再現するものではない。
- ゴールは公式直線距離に基づき配置。コーナー番号は形状の目安であり距離アンカーではない。
- 発走用引込線・芝スタートは省略。「開始※」は周回上への距離換算。
- 1周超は最終1周の色帯・距離点のみ。中山2500mは内回りで発走が外側部分。
  中山・阪神3200mは外→内の単一経路とし、色帯は最終内回り1周。
  灰線は別回りの形状。外→内全行程の接続アニメーションは実装しない。
- 京都1400/1600/2000、阪神1400、新潟1400/2000は公式に両設定があるため両図を表示。
- 起伏データ・分析計算・dataset_idは変更していない。起伏の既存の推定や内外共用の制限は残る。

## 検証

- `node v380-test/morphology.test.cjs`: 4件。4 JSON構造・SHA256、代表距離、
  全距離描画・24形状・閉路長・距離倍率、端数ラップ/最終1周の連続性。
- `node --check v380-test/app.js` / `node --check v380-test/sw.js`
- `python3 v380-test/build_release.py`: SWを生成。APP_VERSION 3.8.0維持。
- Chromium: 133経路を390px幅で描画し、文字の図外はみ出し・横スクロールなし。
  SVG実測経路長と距離点の一致を確認。代表条件は1200px/390px幅で目視。
- 既存Pythonテスト: 145件合格（初回のjsonschema不足を既存依存環境で解消し、
  racecard 84件を再実行。残り61件は初回合格）。automationのファイル変更なし。
