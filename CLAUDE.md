# CLAUDE.md

暗号資産投資向けのモーニングレターを自動生成する CLI。毎朝 `good-morning run` を1回実行すると
（定時実行は JST 6:45、米国市場の引け後）、マーケット数値・今後30日の予定・主要ニュースを集約した
Markdown が `outputs/YYYY-MM-DD.md` に出力される。あわせて、同じ内容のビジュアルレポート（HTML。
claude.ai の非公開アーティファクトに載せる）も作り、Discord にはそのリンクを送る。メイン銘柄は BTC。

- 元の指示書（全文）: [docs/ClaudeCode指示書_モーニングレター.md](docs/ClaudeCode指示書_モーニングレター.md)
- ベース: 自作ツール aion（https://github.com/tjackiet/aion）。git 履歴は引き継がず、ファイルを出発点にした

## 大原則（必ず守る）

1. **数値は API から機械的に取得し、LLM に数値を作らせない。** Claude API の役割は要約・判定理由・まとめの文章だけ。LLM に渡すのは計算済みの数値に限る。
2. **株・指数・ETF の騰落率は、日足 `history(interval="1d")` の終値から計算する。** `info` の `currentPrice` 系は使わない（JST 7:00 は米国の時間外取引中で、時間外の値が混ざるため）。
3. **一部の取得に失敗しても、レポート全体は止めない。** 該当欄は「取得失敗」と表示し、ログに理由を残す（`good_morning/sections.py` の `build_section` が担う）。
4. **設定は YAML に寄せる。** 銘柄・フィード・キーワード・イベント・判定の区切りの値は、コードを触らずに変えられるようにする。
5. **テストはネットワークに依存させない。** 実データから作った固定データ（`tests/fixtures/`）でテストする。
6. **時刻はすべて JST で表示する。** データごとの基準時刻（NY終値／取得時点）をヘッダーに明記する（`Section.basis` に入れるとヘッダーに載る）。

## 公開リポジトリなので守ること

- `config/watchlist.yaml`、`outputs/`、`logs/`、`.env` は `.gitignore` 済み。コミットするのは `config/watchlist.example.yaml` と `.env.example` だけ。
- `watchlist.yaml` がないときは example を読み込んで警告を出す（`good_morning/watchlist.py`）。
- ページIDや Webhook URL などをコードに直書きしない（環境変数で渡す）。

## 進め方

フェーズごとに `claude/phase-N-...` ブランチで作業し、PR を作る。各フェーズの最後に
**テストを通す → 実データで1回動かす → 出力のサンプルを見せる** を行ってから止まり、ユーザーの確認を待つ。

| フェーズ | 内容 | 状態 |
|---|---|---|
| 0 | リポジトリの準備（aion の複製、AI専用部分の整理、CLAUDE.md） | 済 |
| 1 | yfinance でマーケット一覧・セクター・株式ウォッチリストの表 | 済 |
| 2 | bitbank-lab-mcp で BTC の詳細（判定ルール含む）と暗号資産ウォッチリスト | 済 |
| 3 | 今後の予定（決算・FRED・events.yaml） | 済 |
| 4 | ニュース（RSS とキーワードの差し替え、要約プロンプトの変更） | 済 |
| 5 | Claude による「今朝のまとめ」「暗号資産への示唆」、全体の結合、Discord 通知 | 済 |
| 5.5 | ビジュアルレポート（アーティファクト）と Discord の画像カード、終値の未反映への対応 | 済 |
| 6 | Claude アプリの定時タスクで毎日 JST 6:45 に実行（自宅の iMac。launchd から変更） | |

## レポートの骨子

`good_morning/sections.py` の `SECTION_SPECS` がこの順に並んでいる。フェーズごとに `builder` を埋める（未設定は「未実装」と表示）。

0. ヘッダー: 日付、データ基準時刻（NY終値／BTCは取得時点／先物は取得時点の値／週足・月足は形成中）
1. 今朝のまとめ: 「リスクオン／リスクオフ／様子見」の3段階判定と3行の要約（Claude。根拠の数値を必ず挙げる）
2. マーケット一覧（終値・前日比・前日比%）: BTC/JPY（bitbank、24時間の変化率）、米10年債 `^TNX`（%表示、前日比は bp）、ドル円 `JPY=X`、`^DJI` `^GSPC` `^IXIC`、`CL=F` `GC=F`。任意（初期値オン）: `^VIX` `DX-Y.NYB` `ES=F` `NQ=F` `YM=F`
3. セクター別騰落率: SPDR 11セクター（XLK XLF XLE XLV XLY XLP XLI XLB XLU XLRE XLC）を騰落率順に（Markdown の表、グラフ不要）
4. BTCの詳細: 日足・週足・月足 × 一目（雲との位置・三役）、移動平均の並び（25/75/200本）、BBのσ位置、RSI(14)、MACD、判定。日足RSIの直近7日の推移と Claude の2〜3行のまとめ
5. 暗号資産ウォッチリスト（5銘柄）: 価格、24時間の変化率、対BTCの強弱（BTCの変化率との差）
6. 株式ウォッチリスト（米国株10銘柄）: 終値、前日比、騰落率順
7. 今後の予定: 7日以内は日時（JST）・内容・重要度（高中低）・予想値（取れれば）。8〜30日は1行ずつ。決算はウォッチリストと `related` の企業
8. 主要ニュース（3〜5本）: 見出し、2〜3行の要約、暗号資産への示唆、出典リンク
9. 暗号資産への示唆: 強気材料、弱気材料、まとめ1〜2行
- フッター: 投資助言ではない旨、データの出典（`Section.sources` を集めて表示）

### BTC の判定ルール（区切りの値はすべて `config/scoring.yaml` で変更可能にする）

- 5要素（雲との位置、三役、移動平均の並び、RSI、MACD）を強気+1・弱気−1・中立0で点数化。合計 +2以上「強気」、−2以下「弱気」、それ以外「中立」
- RSI: 30以下 売られすぎ／30〜45 弱め／45〜55 中立／55〜70 強め／70以上 買われすぎ

## データ取得元

| 対象 | 取得元 | 注意 |
|---|---|---|
| 株・指数・為替・金利・商品・セクターETF | yfinance | 非公式ライブラリ。取得処理は1か所にまとめ、差し替えやすくする |
| 暗号資産 | bitbank-lab-mcp（MCP Python SDK、stdio。`npx -y bitbank-lab-mcp@0.8.0`） | 公開データのみ。APIキー不要。private 系ツールは使わない |
| 経済指標の発表予定日 | FRED API `fred/releases/dates`（`include_release_dates_with_no_data=true`） | `FRED_API_KEY` |
| FOMC・日銀会合 | `config/events.yaml` に公式日程を年1回手で転記 | FOMC 議事要旨は会合の約3週間後。日付も書く |
| 決算日 | yfinance `Ticker.calendar` / `get_earnings_dates()` | 確定／推定を区別する |
| ニュース | RSS（aion の仕組み） | |

### yfinance の扱い（フェーズ1で実装・検証済み）

- yfinance に触れるのは `collector/market_data.py` だけ。外へは pandas の型を出さず `DailySeries` を返す。差し替えるときはこのファイルだけを直す。
- `config/markets.yaml` の `basis` で銘柄ごとに基準を決める。
  - `close`（NY終値）: 確定した日足だけを使う。**`^TNX` と `^VIX` は NY の取引開始前から当日の形成中の足が出る**（2026-11-17 に実データで確認）ため、NY の 16:00 + 30分（`us_market_close`）より前の当日の足、それより先の日付の足は捨てる（`markets/quotes.py` の `complete_bars`）。
  - `live`（取得時点の値）: 為替・先物・ドルインデックス。最新の足をそのまま使い、表で名前に ※ を付ける。
- `^TNX` は % の値そのもの（例 5.121）で返る。前日比は ×100 で bp。前日比%は出さない（「—」）。
- 祝日などで終値の日付が他の銘柄とずれた行には「（11/13 終値）」を添える。ヘッダーの基準日は、終値の銘柄で最も多い日付。
- 1銘柄の失敗はその行だけ「取得失敗」。全銘柄が失敗したらセクションごと「取得失敗」。
- **個別株・ETF は、NY の引け後しばらく最新日の行が「終値 NaN」で返る**（2026-11-18 の JST 10 時台に実データで確認。指数は出ていた）。そのまま捨てると前の日の値が黙って出るので、`DailySeries.empty_close_dates` に日付を残し、確定した日（`is_settled_day`）の終値が空なら `Quote.missing_close` を立てる。
  - `markets.yaml` の `missing_close_retry`（既定 2回・20秒おき）で、その銘柄だけ取り直す（`markets/builders.py` の `fetch_quotes`）。
  - それでも出なければ前の営業日の終値と前日比を出し、行に「（11/16 終値・11/17 は未反映）」と添える。表の全行がそうなら、行ごとではなく表の下に1行だけ注記する（`tables.py` の `uniform_stale` / `stale_note`）。Claude に渡すデータにも「未反映」と書く（`synthesis/facts.py`）。
  - 60分足などで補うのは公式の終値ではないので採らない（大原則2）。6:45 の定時実行でどのくらい起きるかは未確認。

### 今後の予定（フェーズ3で実装）

- 3つの取得元（events.yaml・FRED・決算）は独立して扱い、どれかが失敗しても残りで表を作る。失敗はセクション末尾に「⚠ 取得できませんでした」と書き、理由はログへ。
- **FOMC・日銀**: `events.yaml` に公式ページから転記（年1回）。FOMC 議事要旨は「政策決定の3週間後」（公式ページの記載）で計算した日付を `estimated: true` にしている。FOMC の声明は 14:00（米東部）＝日本時間 4:00（冬）／3:00（夏）。日銀の結果発表は時刻未定なので時刻なし（その日の最後に並ぶ）。
- **FRED**: `fred/releases/dates`（`include_release_dates_with_no_data=true`、昇順、1000件ずつページ送りし、期間を過ぎたら止める）。返るのは日付だけなので、時刻（米東部）と重要度は `events.yaml` の `fred.releases` で決め、`release_name` の完全一致で拾う。2026-11-18 に実データで確認し、8指標すべて名前が一致した（30日でおよそ900件の発表予定が返る）。テストは実データ（`tests/fixtures/fred/release_dates_20261118_0858.json`）。
- **FRED の API キーを漏らさない**: httpx の例外メッセージは URL（＝キー）を含むので使わず、例外の型名を原因までたどって残す（例 `ConnectError ← SSLCertVerificationError`）。`raise ... from None` でトレースバックにも残さない。httpx のログは WARNING 以上にしてあるので、リクエストの URL もログに出ない。
- **決算日**: yfinance の `info`（決算日に関わる項目だけ。価格には使わない）と `get_earnings_dates()` を使う。実データで確かめた `info` の意味: `isEarningsDateEstimate=False` かつ未来 → 確定、`True` → 推定、`False` かつ過去 → 前回の決算（次回は `get_earnings_dates()` の未発表の行から推定）。EPS 予想は `get_earnings_dates()` の日付が近い行から。`Ticker.calendar` は古い日付を返すことがあった（HOOD）ので使わない。related の関連企業は `shortName`（会社名）で表示する。
- 決算日の取得は1銘柄2回の通信（info と get_earnings_dates）。見本のウォッチリスト（関連企業込み8銘柄）で約10秒。
- **直近の決算**（2026-11-18 に追加）: 米国企業の多くは引け後すぐ（日本時間 6:00 ごろ）に決算を出すので、6:45 のレポートでは「今後の予定」から消えてしまう。そこで、過去24時間（`events.yaml` の `earnings.recent_hours`）に発表予定の時刻を過ぎた決算を、セクションの先頭に EPS の実績・予想・予想比で出す（`events.py` の `recent_earnings_result`）。数値は同じ `get_earnings_dates()` の行から取るので通信は増えない。予想比は `(実績 - 予想) / |予想|`。
  - 発表後の `get_earnings_dates()` には実績が入る（NVDA: 予想 2.47 → 実績 2.68。2026-11-18 11:15 に確認、`tests/fixtures/yfinance/earnings_20261118_1115.json`）。発表直後に取得元へ入るまでの時間は未確認なので、まだなければ「未反映」と出す。推定の日付（`isEarningsDateEstimate=True`）は実際に発表したか分からないので使わない。
  - 取れるのは EPS だけ（売上高はない）。Claude に渡すデータ・ビジュアルレポート・画像のカードにも載せる。

### 主要ニュース（フェーズ4で実装）

- **フィード**（2026-11-17 に全 URL を実際に取得して確認）: CoinDesk・CoinPost・The Block（暗号資産。キーワードフィルタ免除）、Bloomberg Markets / Economics（マクロ）、FRB 金融政策（免除）・日銀 新着・SEC プレスリリース（公的機関）。**除外**: Cointelegraph 日本語版（410 Gone）、ロイター（公開 RSS なし）。**保留**: 日経マーケット（公式 RSS なし。第三者の assets.wor.jp 経由で `enabled: false`。ユーザーの判断待ち）。
- **`ignore_keywords`**: 配信元の名前は全記事に含まれるため数えない（SEC の「SEC」で 25/25 件、日銀の「日銀」で統計の公表まで素通しになっていた）。
- **英語の複数形**: 英語の語は s / es にもマッチする（`ETF` → `ETFs`）。aion の単語境界だけだと英語のフィードで取りこぼすため。
- **配分**: `feeds.yaml` の `categories.*.quota`（暗号資産2・マクロ2・公的機関1）の合計5本が既定。足りないカテゴリの枠はスコア順で埋める。カテゴリの重み（`keywords.yaml` の `weight`）とあわせて YAML で調整できる。
- **要約**: Claude Sonnet 5 は既定で thinking が有効なので、応答の先頭が thinking ブロックのことがある。`content[0].text` を決め打ちせず text ブロックだけを使う。thinking も `max_tokens` に含まれるため 4000 にした（aion の 1024 では切れうる）。プロンプトで「記事にない数値を作らない」と指示（大原則1）。
- **API キーがないとき**: 要約できない旨を書き、配信元の概要（RSS の description から HTML タグを除いて140字）を載せる。
- 2026-11-18 に実データで要約を確認。入力についての言及（「詳細は記載されていません」）と単位の換算（$2.35 billion → 23億5000万ドル）が出たため、プロンプトで禁止した（数値は記事の表記のまま）。
- モデル `claude-sonnet-5` は有効な ID（前の世代。指示書の「aion と同じ」に従った）。同じ価格の後継 `claude-sonnet-5-5` もあるので、変えるかはユーザーの判断。
- 全フィードが失敗したら、記事0件と区別してセクションを「取得失敗」にする（`fetch_all_feeds` が例外を投げる）。
- **ウォッチリストの企業の記事**（2026-11-18 に追加）: `watchlist.yaml` の `stocks[].keywords` に書いた会社名（日本語・英語）を「ウォッチリストの企業」カテゴリのキーワードに足す（重みは `keywords.yaml` の `watchlist.weight`）。「Strategy」のような一般的な語は書かない。
  - 会社名と決算の語（`watchlist.earnings_words`）が両方出る記事を「決算の記事」とし、`earnings_bonus` を足したうえで、5本のうち `earnings_slots`（既定1）本を優先して回す（`ranking.py` の `select_for_summary` の `priority`）。加点だけだと BTC・FRB の記事（20点前後）に負けた（2026-11-18 の NVIDIA の決算で、決算の記事は 18.6点）。
  - 決算の語だけでは記事を通さない（ウォッチリスト外の企業の決算で枠が埋まらないように）。`collect-cmd --explain` では「（決算の記事）」と表示する。
  - キーワードは読み込み時に watchlist.yaml（なければ見本）から作る。テストは見本のウォッチリストが前提（手元に watchlist.yaml があると、記事選定のベースラインなどの数値が変わる）。

### 今朝のまとめ・暗号資産への示唆（フェーズ5で実装）

- 作る順番: 数値のセクション（stage="data"）を先に作り、Claude のセクション（stage="synthesis"）を後に作る。表示は骨子の順のまま。BTCの詳細の末尾に Claude の2〜3行のまとめを後から足す（`sections.py` の `build_sections`）。
- Claude の呼び出しは1回で、「今朝のまとめ（判定＋3行）」「BTC のまとめ」「強気材料・弱気材料・まとめ」をまとめて作る（`synthesis/claude.py`）。出力の形は `output_config.format`（json_schema）で固定し、pydantic でも検査する。
- **Claude に渡すのは計算済みの数値だけ**（`synthesis/facts.py`）。レポートの表と同じ表記の文字列にして並べる。新しい計算はしない。
- **数値の照合**（`synthesis/numbers.py`）: 出力に出てきた数値が渡したデータにあるかを機械的に確かめる（符号・3桁区切り・末尾の0は同じとみなす）。ない数値があれば、その数値を伝えて1回だけ作り直させる。それでも残れば「⚠ 次の数値は元データで確認できませんでした」と表示する。**限界**: 数字の並びで照合するので、「5万ドル台」の「5」のように、別の場所に同じ数字がある換算は見逃す。
- 失敗（キーがない・形が違う など）は2つのセクションとも「取得失敗」。Claude は1回の実行で1度だけ呼ぶ（失敗も覚えておく）。
- **前の営業日の終値に日付を添える**（2026-11-18 に追加）: 最新日の終値が取得元に未反映の銘柄は、データに「11/16 終値。11/17 の終値は取得元に未反映」と書き（セクターも）、プロンプトで日付を添えるよう指示している。それでも Claude が落とした（「NVDA-4.12%と大幅下落」）ので、3行の要約・強気材料・弱気材料・まとめの各文を機械的に確かめ、未反映の銘柄の数値（終値・前日比%）があるのに日付がない文の末尾に「（NVDA は 11/16 終値）」を足す（`synthesis/stale.py`）。呼び直しはしない。数字の並びで見るので、同じ数字が別の場所にあると日付を添えすぎることがある。
- 実データ（2026-11-18）で1回の実行は約60秒（Claude の呼び出しが計6回: 記事5本＋まとめ1回）。

### 通知（フェーズ5で実装）

- `good-morning run --notify` で Discord に送る（`notify/`）。`--notify-preview` は文面の表示だけ、`--force-notify` は同じ日の再送。同じ日は1回だけ（`outputs/.notified/YYYY-MM-DD.discord` に記録）。
- `good-morning notify [日付] --link URL` は、保存済みの JSON とカードから後で送る（定時タスクでアーティファクトを公開してから送るため）。`--preview`・`--force` は run と同じ意味。
- 文面は保存した JSON（ビューモデル）から作る。画像のカードを添付するときは、題名・判定・取得失敗のセクション・リンクだけ（通知のプレビューで判定が見えるように）。添付しないときは、判定・3行の要約・BTC の価格と日足の判定も載せる。画像は multipart（`payload_json` と `files[0]`）で送る。
- リンクの優先順: `run` は Notion に書き出せたらそのページ → `.env` の `REPORT_URL`（アーティファクト）→ 保存先のパス。`notify` は `--link` → `REPORT_URL` → 保存先のパス。
- 送り方は「未決事項」の Discord の方針どおり（User-Agent、`allowed_mentions: {"parse": []}`、`?wait=true`、429 は `retry_after` 秒待って1回だけ再送、理由に URL を入れない、例外を投げない）。flags（4 = プレビューなし、4096 = 無音）は Discord の公式ドキュメントで確認済み（2026-11-18）。設定は `config/notify.yaml`。
- Notion: `run --publish` で書き出し、応答からページの URL を取り出して通知のリンクにする（`publisher/notion_mcp.py` の `extract_page_url`）。応答は JSON（`{"pages": [{"id", "url", "properties"}]}`）で、URL は `https://app.notion.com/p/<id>?pvs=204` の形（2026-11-18 に実際に書き出して確認）。許可は aion のときの `~/.mcp-auth` がそのまま使えた（ブラウザは開かなかった）。

### ビジュアルレポートと画像のカード（フェーズ5.5で実装）

- 朝に文字だけでは読む気にならない、というユーザーの要望で追加。`run` のたびに次を `outputs/` に保存する（どれかが失敗しても Markdown は保存済みなので止めない）。
  - `YYYY-MM-DD.json`: ビューモデル（`visual/viewmodel.py` の `build_view`）。レポートの表と同じ表記の文字列だけを持ち、HTML とカードはここから描く。新しい計算はしない（大原則1）。古い形の JSON は `render.py` の `upgrade_view` で補う。
  - `YYYY-MM-DD.html`: 単体で開ける HTML。`YYYY-MM-DD-artifact.html`: アーティファクト用（claude.ai が doctype・html・head・body を付けるので書かない。`render_html(view, standalone=False)`）。
  - `YYYY-MM-DD-card.png`: Discord に添付する画像のカード（幅 420px・3倍・ダーク固定）。`notify.yaml` の `attach_card: true` のときだけ作る（既定は作らない）。Playwright の Chromium で撮る（`visual/card.py`）。入っていない・起動できないときは画像なしで続ける。
- テンプレートは Jinja2（`visual/templates/`、自動エスケープ）。リンクは http(s) だけ（`safe_url`）。グラフ（RSI の推移・騰落率の横棒）は外部ライブラリなしの SVG と CSS。`good-morning render [日付]` で JSON から HTML を描き直せる。
- **色**: 上がり＝ティールの緑 `#179889`、下がり＝赤 `#cb5b51`。ユーザーのローソク足の色 `#429488` を基準に、鮮やかさだけを上げた（そのままでは彩度が足りず、元の赤 `#e66767` はダークで色覚の違いの見分けが足りなかった）。dataviz の検証スクリプトでライト・ダークとも合格（色覚の違いでの差 ΔE 9.0）。文字は同じ色合いの濃い版／明るい版（コントラスト 4.5:1 以上）。色だけに頼らず、必ず ▲▼ と +/− を添える。RSI の線は上下の意味を持たないので別の青。
- **アーティファクトは非公開**（ユーザーの希望。一般公開はしない）。本人が claude.ai にサインインしているときだけ開ける（2026-11-18 に未ログインのブラウザで「サインインしてください」になることを確認）。毎朝同じ URL に上書きし、URL は `.env` の `REPORT_URL` に入れて通知のリンクにする。別の会話（定時タスク）から上書きするときは、Artifact ツールでその URL を一度 read してから `url` を付けて publish する。
- **Discord には画像を添付せず、リンクと文章だけを送る**（2026-11-18 にユーザーと決めた。`attach_card: false`）。理由: アーティファクトは非公開でも本人なら開ける／添付しないほうが文章に3行の要約と BTC を載せられ、スマホの通知でそのまま読める／画像はチャンネルにいる人なら誰でも見られる／iMac に Chromium（約100MB）が要らず、毎朝の失敗の種が減る。カードの仕組みは残してあり、`true` にすれば戻せる。

### ネットワーク（フェーズ5で判明）

- **会社のネットワークでは Fortinet の機器が一部の HTTPS を検査し、社内の CA で証明書を署名し直す**（2026-11-18 に CoinPost・The Block・FRB・api.anthropic.com で確認）。httpx が標準で使う certifi には社内の CA がないため `CERTIFICATE_VERIFY_FAILED` になる。検証は切らず、OS の証明書ストアで検証する（`net.py` の `ssl_context()`、truststore）。RSS・FRED・Discord の通信はこれを使う。anthropic SDK（httpx2）は最初から OS の証明書ストアを使っている。
- `npx`（bitbank-lab-mcp・Notion MCP）は fnm でインストールした Node を使っている（PATH はシェルごとの一時的な場所）。定時タスクや launchd から動かすときは PATH に注意（フェーズ6）。
- Node（mcp-remote）も標準では独自の証明書の束を使うため、会社のネットワークでは mcp.notion.com で `unable to verify the first certificate` になった。npx で起動する MCP サーバーには `NODE_OPTIONS=--use-system-ca`（Node 22.15 / 23.8 以降）を渡している（`net.py` の `NODE_SYSTEM_CA_ENV`）。

### bitbank-lab-mcp の注意（検証で判明済み）

- **文章のラベルを使わない。** 同じ出力で RSI 37.0 が「中立圏」と「弱め（反発余地）」の両方で出る。判定は `structuredContent` の数値から自前の基準で行う。
- **週足・月足でも「200日」「5日前」と表示される**（実際は「本」）。数値だけを使い、単位はこちらで付ける。
- **`analyze_sma_snapshot` は月足で使えない**（200本以上必要で n/a）。月足の移動平均は `analyze_indicators(type=1month)` の値を使い、月足の200本線は「算出不可」と表示する。
- **最新の足は形成中。** 週足・月足が途中経過であることをレポートに一言入れる。
- 使うツール: BTC のテクニカルは `analyze_indicators` を日足・週足・月足で各1回、ウォッチリストの価格は `get_tickers_jpy`、取扱銘柄の確認は bitbank の取扱銘柄一覧。
- 実装前に `structuredContent` の中身を確認し、必要な数値（一目の各線、SMA 25/75/200、BBのσ位置、RSI(14) と直近7本、MACD）が取れることを確かめる。取れない項目は bitbank 公開API のローソク足から自前で計算する予備処理を検討する。`scripts/mcp_tools.py bitbank <tool>` でスキーマを見られる。

#### フェーズ2で確認・実装したこと（2026-11-17）

- `structuredContent` を読むのは LLM ではなく Python（MCP Python SDK）。MCP SDK 2.x では属性名が snake_case（`result.structured_content`、`tool.input_schema`）。pyproject は `mcp>=2.0,<3` に固定。
- 必要な数値は `analyze_indicators` の `data.indicators` と `data.normalized`（足）ですべて取れた。予備の自前計算は不要だった。BB の σ 位置は `(終値 - BB_middle) / (BB1_upper - BB_middle)` で計算（ツールの文章の値と一致）。
- **一目の `ICHIMOKU_spanA/spanB` と `ichi_series` はずらす前の値**（今の足で計算した先行スパン）。今の足の雲は `ichi_series.spanA/spanB[-1 - shift]`、遅行スパンは今の終値と `shift` 本前の終値の比較。bitbank-lab-mcp のずらしは 26 本（`chart.meta.shift` と遅行スパンの系列で確認）。日足・週足・月足とも、ツールの文章の「雲の上／下」と一致することを確認済み。
- 月足は `SMA_200` が `null`（`meta.warnings` に「データ不足」）。表では「200本は算出不可」と出し、並びは残りの線（25/75）で判定する（`moving_average.allow_partial`）。
- 足の区切りは日本時間 9:00（`isoTimeLocal`）。日足は毎日、週足は月曜、月足は1日。最新の足は形成中（`meta.provisional: true`）。
- `get_tickers_jpy` は全 JPY ペア（2026-11 時点で44ペア）を返すので、これを取扱銘柄一覧として照合に使う。`change24hPct` は小数2桁に丸められているので、変化率は `last / open` から自前で計算する。価格の表示は取引所の桁数の文字列（`last`）をそのまま3桁区切りにする。
- MCP サーバーへの接続は1回の実行で1度だけ（3つのセクションで共有）。接続に失敗したら覚えておき、再接続しない。ツールごとの失敗は、その部分だけ「取得失敗」。
- **RSI の点数の初期値は「流れに沿う」見方**（強め・買われすぎ +1、弱め・売られすぎ -1）。他の4要素と向きをそろえた。「売られすぎ＝反発の余地」と見るなら `scoring.yaml` の `rsi.scores` で変える（ユーザーに確認待ち）。

## 設定ファイル（`config/`）

| ファイル | 内容 | 状態 |
|---|---|---|
| `watchlist.example.yaml` | 暗号資産（main + watch 最大5）と米国株（最大10、`related`・ニュースで拾う会社名 `keywords` 付き）。手元で `watchlist.yaml` にコピーして使う | 済 |
| `markets.yaml` | マーケット一覧とセクターの銘柄コード、任意項目のオン・オフ、NY終値の確定時刻、終値が未反映のときの取り直し | 済 |
| `scoring.yaml` | 判定ルールの区切りの値、RSI の各区分の点数、一目のずらし、移動平均の本数 | 済 |
| `events.yaml` | FOMC・日銀の日程（2026-11-17 に公式ページから転記）、FRED で拾う指標と時刻・重要度、決算の重要度と直近の決算を出す期間、表示する期間 | 済 |
| `feeds.yaml` | 市場ニュースの RSS（暗号資産・マクロ・公的機関）、カテゴリごとの要約枠、フィードごとの `keyword_filter` / `ignore_keywords` | 済 |
| `keywords.yaml` | 市場用語（日本語＋英語）とカテゴリごとの重み（`weight`）、ウォッチリストの企業の重みと決算の記事の扱い（`watchlist`） | 済 |
| `prompts.yaml` | Claude のモデル名（`claude-sonnet-5`、aion と同じ）、`max_tokens`、記事要約のプロンプト、今朝のまとめ（synthesis）のプロンプト | 済 |
| `notify.yaml` | Discord 通知の設定（画像のカードの添付・プレビューなし・無音・429 の再送） | 済 |

- 暗号資産のペアは bitbank の取扱銘柄と照合し、存在しないペアは警告してスキップする（フェーズ2）。
- 上限を超えたら先頭から順に採用する（実装済み）。

## 環境変数（`.env`、見本は `.env.example`）

- `ANTHROPIC_API_KEY`: 要約・まとめ用
- `FRED_API_KEY`: 経済指標の発表予定日
- `NOTION_PAGE_ID`（任意）: Notion への書き出し先
- `DISCORD_WEBHOOK_URL`（任意）: Discord 通知（`run --notify` / `notify`）
- `REPORT_URL`（任意）: 毎朝上書きするアーティファクトの URL。通知のリンクになる（秘密ではないが、本人しか開けない）

## 未決事項（初期値で進め、変えやすくしておく）

- **出力先**: ローカルの Markdown が本体。Notion への書き出しは aion の機能を残してオプション（`run --publish`）。
- **Discord 通知**（ユーザー要望）: Webhook で、判定と3行要約と、スマホで開けるリンク（Notion ページを想定）を送る。フェーズ5で実装。Notion 連携は `mcp-remote` のブラウザ認証に依存するため、launchd での無人実行に耐えるか（公式APIのトークンに替えるか）をフェーズ5で検証する。
  - ユーザーが別プロジェクトで使っている構成を元にした方針:
    - 送るのは `{"content": ...}` が中心（1通・2000字未満）。リンクは `[11/18 のモーニングレター](URL)` の形。
    - **`User-Agent` を必ず付ける**（例 `good-morning/0.1`）。付けないと Discord の手前の Cloudflare に 403（error 1010）で弾かれる。
    - `allowed_mentions: {"parse": []}` を既定にして、題名などに紛れた `@everyone` で鳴らないようにする。無音は `flags: 4096`、リンクプレビューを消すのは `flags: 4`（併用は 4100）。`?wait=true` で送れたかを確かめられる。※ flags 等は使う前に Discord の公式ドキュメントで確認する。
    - URL は環境変数 `DISCORD_WEBHOOK_URL` からだけ読む。未設定なら「送らない」とログに残すだけ。ログやエラー理由に URL を入れない。
    - 送信は失敗しても例外を投げず、理由を返して記録する（HTTP は状態コード、それ以外は例外の型名と、URL を含まない原因の種類＝証明書・名前解決など）。すべての例外を捕まえる。タイムアウト10秒。レポートの保存が済んでから送る。
    - 1日1回なので、`429` のときは `retry_after` 秒待って1回だけ再送してよい。二重投稿しないよう、その日の分を送ったことをファイルに記録する。
    - launchd はシェルの環境変数を引き継がないので、plist の `EnvironmentVariables` に入れる（plist はリポジトリに入れない）。Mac がスリープ中は動かないので、フェーズ6で `pmset` による起動予約などを検討する。※ フェーズ6は launchd ではなく Claude アプリの定時タスクにした（自宅の iMac、6:45）。`.env` はプログラムが自分で読むので、環境変数の受け渡しは不要。
    - URL が漏れたら、Webhook を作り直して古いものを削除する。
- **ウォッチリストの銘柄**: 見本は仮のもの。
- **任意項目**（VIX、ドルインデックス、株価指数先物）: 初期値はオン。

## コード構成

```
src/good_morning/
  main.py            CLI（typer）。run / notify / render / collect-cmd / publish
  sections.py        セクションの並びと、失敗を閉じ込める build_section
  context.py         builder が受け取る RunContext（ctx.data に計算済みの数値を置く）と戻り値
  reporter/markdown.py  ヘッダー・各セクション・フッターの描画と保存
  collector/market_data.py  yfinance で日足を取得（yfinance に触れるのはここだけ）
  markets/           markets.yaml の読み込み、前日比の計算、3つの表とセクションの builder
  collector/bitbank_mcp.py  bitbank-lab-mcp への接続（MCP に触れるのはここだけ）
  crypto/            scoring.yaml の読み込み、テクニカルの判定、BTCの詳細・暗号資産ウォッチリスト
  collector/fred.py  FRED の発表予定日の取得
  schedule/          events.yaml の読み込み、予定の組み立て（JST 変換・期間・並べ替え）、今後の予定のセクション
  news/builder.py    主要ニュースのセクション（収集→選定→要約→表示）
  synthesis/         Claude に渡すデータ（facts）、数値の照合、まとめの呼び出し、今朝のまとめ・暗号資産への示唆のセクション
  notify/            Discord 通知（文面と送信。画像のカードの添付）
  visual/            ビジュアルレポート（ビューモデル・SVG の部品・Jinja2 のテンプレート・画像のカード）
  net.py / errors.py  OS の証明書ストアで検証する SSLContext、例外の原因の型名
  watchlist.py       watchlist.yaml の読み込み（example へのフォールバック、上限の切り詰め）
  paths.py / timeutil.py / logging_setup.py   パス・JST・ログ（logs/YYYY-MM-DD.log）
  collector/rss.py   RSS 取得（aion から流用）
  selector/          絞り込み・スコアリング・ランキング（aion から流用）
  processor/summarizer.py  Claude による記事要約（「要約」と「暗号資産への示唆」）
  publisher/notion_mcp.py  Notion 書き出し（任意）
```

## 開発コマンド

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
# 画像のカードを使うとき（attach_card: true）だけ: pip install -e ".[dev,card]" と python -m playwright install chromium（約100MB）
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/good-morning run                 # outputs/ に md・json・html・アーティファクト用 html を生成
.venv/bin/good-morning render             # 保存済みの JSON から HTML を描き直す（テンプレートを直したとき）
.venv/bin/good-morning notify --preview   # 通知の文面を表示するだけ（送らない）
.venv/bin/good-morning collect-cmd --explain   # RSS の通過/除外の理由を確認
```

- ビジュアルレポートの見た目は `.claude/launch.json` の `report-preview`（outputs/ を 127.0.0.1:8765 で配る。gitignore 済み）でブラウザに出して確かめる。
- テストは aion の流儀に合わせる: 実データのスナップショットを `tests/fixtures/` に置き、`monkeypatch` で取得関数を差し替える。共通の部品は `tests/conftest.py`。
- yfinance の固定データは `scripts/capture_yfinance_fixture.py` で `tests/fixtures/yfinance/` に保存する。テストでは `fake_yfinance` フィクスチャで差し替える。`conftest.py` の autouse フィクスチャが、テストから yfinance・bitbank-lab-mcp に触れたら失敗させる。
- bitbank の固定データは `scripts/capture_bitbank_fixture.py` で `tests/fixtures/bitbank/` に保存する（使う部分だけに切り詰める。1本約1MB → 全体で約170KB）。テストでは `fake_bitbank` フィクスチャで差し替える。
- 決算日・FRED の固定データは `scripts/capture_schedule_fixture.py` で保存する（FRED はキーがあるときだけ）。テストでは `fake_yfinance`（決算日も返す）と、`test_schedule_builder.py` の `fake_fred` で差し替える。autouse フィクスチャは `httpx.get` も止める。
- `tests/test_fixture_characterization.py` は「現状の挙動」を固定するベースライン（`tests/fixtures/rss/` の実フィード、2026-11-17 取得）。語彙やフィードを変えたら、意図した差分だけが出ているかを確かめて数値を更新する。有効なフィードを足したら固定データも足す（テストで確認している）。
