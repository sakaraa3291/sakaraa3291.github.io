# 騎手・調教師の成績集計と運用

2026年11月25日に Windows 補助PCで `8d20bfc43d18cf1f7f9eeb17d1d458b54da99184` を基準に実装。基準マスターは2021年1月2日～2026年11月23日の42,160レース、494,234行。中央は20,447レース・281,342行、地方は21,713レース・212,892行。地方の保存は2026年8月2日までで、払戻の保存と週次の結果取得は中央のみ。中央ラベルには既存の交流レースも含まれる。地方の出馬表更新は別処理。

## ChatGPT から調べる

対象の GitHub リビジョンをチェックアウトできる Codex または Python 実行環境で下記を実行し、JSON の `results` と `coverage` だけをチャットに渡す。`automation/state` 下の既存マスターと払戻、あれば `people_observations.csv.gz` が入力。`people-summary.json` は週次の上位集計とコース別件数の入口。任意条件は CLI が計算する。CLI は標準ライブラリで実行でき、データは Python が逐次処理する。

```powershell
python -X utf8 automation/people.py lookup --role jockey --name 'ルメール'
python -X utf8 automation/people.py query --group jockey --where 'jockey_id=05339' --where 'venue=東京' --where 'surface=芝' --by distance --period 1y --limit 8
python -X utf8 automation/people.py query --group trainer --by venue --by distance --by surface --period 6m
python -X utf8 automation/people.py query --group pair --where 'venue=東京' --where 'distance=1600' --by popularity --period 1m
python -X utf8 automation/people.py query --group jockey --where 'prior_style=逃げ' --where 'prior_style=先行' --by gate --by distance --from 2024-01-01 --before 2026-11-23 --as-observed --prior-form
```

`--where` は異なる項目間で AND、同じ項目内では OR。項目は `year`、`organization`、`venue`、`distance`、`surface`、`course`、`course_variant`、`going`、`class`、`popularity`、`gate`、`style`、`jockey_id`、`trainer_id`、`horse_id`、`jockey_affiliation`、`trainer_affiliation`、`prior_style`。`course` は `東京|芝|1600` のような基本条件。`course_variant` は結果ページから読み取れた `右`・`左外` などの表記。開催時点の走路が分からない場合は空欄。`lookup` で複数IDが出た場合は、本人と確認できるIDで絞る。

`--from` と `--to` は両端を含む。`--period all/1y/6m/1m` はデータ締め日または指定終了日を基準にする。`--before` は対象開催日全体を除外する。`--as-observed` を指定すると、対象開催日以後に取得した補完資料も除外する。既存マスターの訂正履歴まで当時の状態で再現する場合は、対象日より前に保存された Git リビジョンを入力に使う。`manifest_through` はマスターの締め日で、`observed_range_by_organization` に期間内の実収録範囲が出る。

## 数え方

- 取消・除外の明示行は騎乗数と賭け数から除く。中止・失格は出走と着外に含める。着順が空欄でもタイムや通過順がある行は出走に数える。いずれの証拠もない行は出走未確定として別計上する。勝率・連対率・複勝率の母数には着順が判定できた行と明示の中止・失格を含める。
- 回収率は、払戻表が検証できた出走に1頭100円ずつ投じたときの実払戻額。表があるレースの不的中は0円。券種ごとに母数と欠損数を表示し、母数0は `null`。同着および少頭数時も払戻表の馬番を使用する。
- 実走脚質はマスターの分類。序盤位置は通過順位が2点以上ある平地レースの最初の観測点で、通過点の数と頭数で正規化できた母数も表示する。`prior_style` は前日以前の同じ馬の直近5走までの有効脚質の最頻値。最多同数なら空欄。前後半3Fはレースの値。人気・枠・馬の過去成績で条件をそろえ、母数を確認してから隊列やペースに使う。
- IDは netkeiba の文字列を変更せず保持する。NAR公式の人・馬IDとは別体系で、同名照合や先頭ゼロの削除で連結しない。出馬表の予定騎手・予定調教師は実走成績の根拠から除外する。レース結果を照合できた保存済み過去走と確定オッズだけを補完に使う。騎手表示名の別表記は同じIDでまとめる。取得元・取得日時・証拠種別は補完行に付く。

## 保存、週次更新、復旧

- GitHub Actions の既存 `keiba-update.yml` で火曜05:23 JST、本便未完時に06:23 JSTの予備便。旧処理が取得した結果HTMLから補完項目を抜き、追加レースに紐づける。旧処理の並行実行制御と Git の通常の fast-forward を使用する。補完の検証に失敗した場合は補完候補をコミットせず、既存更新は継続する。週次の候補を作るだけの実行では push もデプロイも発生しない。
- 公開リポジトリでの追加取得と保存は、取得元の利用条件と許諾範囲を管理者が確認した上で、承認後にリポジトリ変数 `KEIBA_PEOPLE_PUBLICATION=authorized` で有効にする。その時点から `automation/state/people_observations.csv.gz` と `automation/state/people-summary.json` が既存の更新コミットに含まれる。GitHub Pages の配置対象外。過去分は権利を確認した補完ファイルを別途取り込める。
- 補完の未解決一覧は `automation/runs/current/people-pending.json`。上記の公開・取得条件を満たす場合、`KEIBA_PEOPLE_RETRY_LIMIT` を1～12に設定すると、今回の新規対象を除く直近28日間の中央の未解決レースを、同じ方法で1回だけ再試行する。初期値は0。robots 方針を読み、制限応答で中断し、試行記録を `people-retry-log.json` と `people-summary.json` に残す。多量の過去分は自動で巡回しない。
- ローカルでは `python -X utf8 automation/people.py reuse-archive --out automation/runs/archive-observations.csv.gz` で既存出馬表アーカイブの再利用結果を生成できる。`--people <ファイル>` をサブコマンドの前に指定すると、公開前の補完データを集計できる。`audit --out <監査JSON> --pending <レース単位の欠損JSON>` で毎回再監査できる。
- 取得済み結果HTMLのファイル名を `<race_id>.html` として作業フォルダに置き、`python -X utf8 automation/people_weekly.py import-results --state automation/state --input <HTMLフォルダ> --out <隔離補完CSV.gz> --report <結果JSON>` を実行する。馬ID・開催日・馬番で照合し、既存の補完ファイルへ追記する。退避した旧ファイルまたは前回正常コミットから復旧できる。途中の失敗はエラー一覧に記録し、有効な結果を再利用する。異常終了で `.lock` が残る場合は作業プロセスの終了と出力の整合性を確認してから、そのロックを取り除き再実行する。
- 地方の履歴更新を追加するには、NAR公式の結果と払戻の利用条件を確認し、既存の地方出馬表カレンダーで開催を検出する。既存マスターとの主催者・開催日・レース番号・馬番・馬IDの対応表を別途検証する。中央用の厳密検査と週次コミットを流用する場合も、地方の結果を中央と誤分類する現行コマンドには流し込まない。

## 取得元の確認先

- netkeiba の公開結果に騎手・調教師IDと着順等がある。私的利用の範囲を超える公開は規約の第14条、通信制限はサポート案内を参照する。 [利用規約](https://www.netkeiba.com/info/kiyaku.html) · [スクレイピングについて](https://support.keiba.netkeiba.com/hc/ja/articles/39720493823129)
- JRA 公式は中央の結果と払戻の突合元。 [過去のレース成績](https://www.jra.go.jp/faq/pop02/1_6.html) · [利用条件](https://www.jra.go.jp/use/) · [払戻ルール](https://www.jra.go.jp/kouza/baken/)
- NAR 公式は地方の結果・払戻と人物IDの候補。レース情報の商用利用と改変した転載を制限している。 [レース情報の利用条件](https://www.keiba.go.jp/qa.html) · [競走成績と払戻](https://www.keiba.go.jp/beginner/step6.html)

## 2026年11月25日の隔離検証と引き継ぎ

- `automation/runs/weekly-real/people-candidate/` に補完証拠12,798行と週次集計の実データ候補を保存。内訳は保存済み過去走5,693行、確定オッズ7,089行、福島の実レース1件16頭。原本への欠損補完は騎手名5,709、調教師名・ID・所属・枠番・コース表記各16、人気と単勝オッズ各7,090。騎手IDの新規補完は0。
- 取消・除外は117行が明示され、5,617行は出走自体が未確定。出走確認済みの中央280,011行・地方208,489行に限定すると、騎手IDの残存欠損114、騎手名30,891、調教師ID488,484、調教師名36,584、人気と単勝オッズ各29,515。同一騎手IDで既存の表示名を返せる出走は、騎手名欠損のうち別途30,776行。行に記録された当時の氏名は未確認。
- 東京芝1600mの騎手ID `05339` を2025-11-24～2026-11-23で照合。47騎乗19勝、勝率40.43%、単勝実払戻4,370円・回収率92.98%、複勝実払戻3,830円・回収率81.49%。原本CSVを pandas で独立再集計し一致。
- 本番投入の前に、補完元の利用・保存許諾を確認し、中央・地方の歴史的未取得範囲を埋める。先に `people-pending.json` と保存済みHTMLを照合し、再取得対象を減らす。既存 GitHub Actions の本番起動はマージ後に検証する。最新版の監査・テスト証跡は作業クローンの `automation/runs/` に保存。

## 公式データを使うWindows補助PCの週次運用

Windows補助PC内では、作業クローンの `automation/runs/` に中央と地方の参照用データを保存できる。`people_local_weekly.py` は中央・地方を独立に実行し、検証が通過した版の `current.json` を切り替える。実行結果は `automation/runs/private-weekly.json`。

- 中央は公開GitHubの `main` を読み取り、コミットに固定したマスターと払戻のハッシュを照合する。既存の欠損があるJRAの開催だけ、公式の成績表PDFを取り込む。開催・開催日・レース番号・馬番・馬名が一致した行を使う。オッズが全部揃ったレースに限り、単勝払戻表の人気との一致を確認して同値のないオッズから人気順を補完する。調教師IDはJRA名鑑の同じ氏名・所属が一意で、引退日との矛盾がないものを `jra:` 形式で付ける。PDFから得た氏名に所属がない場合は、同じ馬の対象日前の成績で氏名・所属を照合する。 [JRA公式成績表](https://www.jra.go.jp/datafile/seiseki/report/) · [JRAの騎手・調教師データ](https://www.jra.go.jp/datafile/meikan/)
- 地方はNAR公式月次ZIPの出馬表、レース一覧、払戻金を利用する。2026年3月以降の別配布ファイルでは単勝確定オッズを照合する。両種類とも公式説明書FAQの専用機能を使い、ファイルごとに同一JST日内の再取得を防止する。既存ZIPのハッシュが一致して対象日までを覆っていれば再使用する。単勝・複勝は公式払戻を使う。公式CSVには人物・馬のIDがなく、既存結果と同一レース・馬番・馬名・着順、または保存済み公式の同一馬の確定情報と照合できた場合にIDを付ける。名称と所属で確認する場合は `jockey-label`、`trainer-label`、`pair-label` を明示して使う。 [NAR公式ダウンロード説明書](https://www.keiba.go.jp/pdf/manual/data_pdf_manual.pdf) · [NAR公式利用規約](https://www.keiba.go.jp/terms.html)
- 取得元の条件に沿って両データは補助PC内の `automation/runs/` に置く。公開リポジトリやGitHub Actionsの公開成果物へのデータ追加は許諾確認後に有効にする。GitHub側の本便は火曜05:23 JST、予備便は06:23 JST。Windows側の `KeibaPeopleOfficialWeekly` は両便の後の火曜07:23 JSTに実行する。復旧時はこのタスクの状態を確認し、保存済みの正常版の `current.json` を選び直せる。

```powershell
.\.venv\Scripts\python.exe -X utf8 automation/people_local_weekly.py --runs automation/runs
.\.venv\Scripts\python.exe -X utf8 automation/people.py --state automation/runs/jra-official/state query --group trainer --where 'trainer_id=jra:001020' --period 1y
.\.venv\Scripts\python.exe -X utf8 automation/people.py --state automation/runs/nar-official/state query --group trainer-label --where 'trainer_label=荒山勝' --where 'trainer_affiliation=大井' --where 'venue=大井' --period 1y
```

中央・地方それぞれの版の `people-summary.json` に競馬場・馬場・距離別の週次集計がある。中央版の `coverage.json` と `pending.json`、地方版の `manifest.json` から収録日、欠損数、取得元を確認できる。中央の `--as-observed` は補完資料の取得日時を確認する。地方について当時取得済みの状態まで再現する場合は対象日以前に保存された版を選ぶ。期間内の履歴は `--before` で対象開催日前日までに制限する。
