# CLAUDE.md

暗号資産投資向けのモーニングレターを自動生成する CLI。毎朝 JST 7:00 以降に `good-morning run` を
1回実行すると、マーケット数値・今後30日の予定・主要ニュースを集約した Markdown が
`outputs/YYYY-MM-DD.md` に出力される。メイン銘柄は BTC。

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
| 3 | 今後の予定（決算・FRED・events.yaml） | 済（FRED は実データ未確認） |
| 4 | ニュース（RSS とキーワードの差し替え、要約プロンプトの変更） | 済（要約は実データ未確認） |
| 5 | Claude による「今朝のまとめ」「暗号資産への示唆」、全体の結合、Discord 通知 | |
| 6 | launchd で毎日 JST 7:15 に定時実行 | |

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

### 今後の予定（フェーズ3で実装）

- 3つの取得元（events.yaml・FRED・決算）は独立して扱い、どれかが失敗しても残りで表を作る。失敗はセクション末尾に「⚠ 取得できませんでした」と書き、理由はログへ。
- **FOMC・日銀**: `events.yaml` に公式ページから転記（年1回）。FOMC 議事要旨は「政策決定の3週間後」（公式ページの記載）で計算した日付を `estimated: true` にしている。FOMC の声明は 14:00（米東部）＝日本時間 4:00（冬）／3:00（夏）。日銀の結果発表は時刻未定なので時刻なし（その日の最後に並ぶ）。
- **FRED**: `fred/releases/dates`（`include_release_dates_with_no_data=true`、昇順、1000件ずつページ送りし、期間を過ぎたら止める）。返るのは日付だけなので、時刻（米東部）と重要度は `events.yaml` の `fred.releases` で決め、`release_name` の完全一致で拾う。**`FRED_API_KEY` が未設定のため、実データでの確認がまだ**。テストは合成データ（`tests/fixtures/fred/release_dates_synthetic.json`）。キーを入れたら `scripts/capture_schedule_fixture.py` で実データを保存し、`release_name` が一致するかを確かめて置き換える。
- **FRED の API キーを漏らさない**: httpx の例外メッセージは URL（＝キー）を含むので使わず、例外の型名を原因までたどって残す（例 `ConnectError ← SSLCertVerificationError`）。`raise ... from None` でトレースバックにも残さない。httpx のログは WARNING 以上にしてあるので、リクエストの URL もログに出ない。
- **決算日**: yfinance の `info`（決算日に関わる項目だけ。価格には使わない）と `get_earnings_dates()` を使う。実データで確かめた `info` の意味: `isEarningsDateEstimate=False` かつ未来 → 確定、`True` → 推定、`False` かつ過去 → 前回の決算（次回は `get_earnings_dates()` の未発表の行から推定）。EPS 予想は `get_earnings_dates()` の日付が近い行から。`Ticker.calendar` は古い日付を返すことがあった（HOOD）ので使わない。related の関連企業は `shortName`（会社名）で表示する。
- 決算日の取得は1銘柄2回の通信（info と get_earnings_dates）。見本のウォッチリスト（関連企業込み8銘柄）で約10秒。

### 主要ニュース（フェーズ4で実装）

- **フィード**（2026-11-17 に全 URL を実際に取得して確認）: CoinDesk・CoinPost・The Block（暗号資産。キーワードフィルタ免除）、Bloomberg Markets / Economics（マクロ）、FRB 金融政策（免除）・日銀 新着・SEC プレスリリース（公的機関）。**除外**: Cointelegraph 日本語版（410 Gone）、ロイター（公開 RSS なし）。**保留**: 日経マーケット（公式 RSS なし。第三者の assets.wor.jp 経由で `enabled: false`。ユーザーの判断待ち）。
- **`ignore_keywords`**: 配信元の名前は全記事に含まれるため数えない（SEC の「SEC」で 25/25 件、日銀の「日銀」で統計の公表まで素通しになっていた）。
- **英語の複数形**: 英語の語は s / es にもマッチする（`ETF` → `ETFs`）。aion の単語境界だけだと英語のフィードで取りこぼすため。
- **配分**: `feeds.yaml` の `categories.*.quota`（暗号資産2・マクロ2・公的機関1）の合計5本が既定。足りないカテゴリの枠はスコア順で埋める。カテゴリの重み（`keywords.yaml` の `weight`）とあわせて YAML で調整できる。
- **要約**: Claude Sonnet 5 は既定で thinking が有効なので、応答の先頭が thinking ブロックのことがある。`content[0].text` を決め打ちせず text ブロックだけを使う。thinking も `max_tokens` に含まれるため 4000 にした（aion の 1024 では切れうる）。プロンプトで「記事にない数値を作らない」と指示（大原則1）。
- **API キーがないとき**: 要約できない旨を書き、配信元の概要（RSS の description から HTML タグを除いて140字）を載せる。**`ANTHROPIC_API_KEY` が未設定のため、要約は実データで未確認**（テストは偽のクライアント）。
- モデル `claude-sonnet-5` は有効な ID（前の世代。指示書の「aion と同じ」に従った）。同じ価格の後継 `claude-sonnet-5-5` もあるので、変えるかはユーザーの判断。
- 全フィードが失敗したら、記事0件と区別してセクションを「取得失敗」にする（`fetch_all_feeds` が例外を投げる）。

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
| `watchlist.example.yaml` | 暗号資産（main + watch 最大5）と米国株（最大10、`related` 付き）。手元で `watchlist.yaml` にコピーして使う | 済 |
| `markets.yaml` | マーケット一覧とセクターの銘柄コード、任意項目のオン・オフ、NY終値の確定時刻 | 済 |
| `scoring.yaml` | 判定ルールの区切りの値、RSI の各区分の点数、一目のずらし、移動平均の本数 | 済 |
| `events.yaml` | FOMC・日銀の日程（2026-11-17 に公式ページから転記）、FRED で拾う指標と時刻・重要度、決算の重要度、表示する期間 | 済 |
| `feeds.yaml` | 市場ニュースの RSS（暗号資産・マクロ・公的機関）、カテゴリごとの要約枠、フィードごとの `keyword_filter` / `ignore_keywords` | 済 |
| `keywords.yaml` | 市場用語（日本語＋英語）とカテゴリごとの重み（`weight`） | 済 |
| `prompts.yaml` | Claude のモデル名（`claude-sonnet-5`、aion と同じ）、`max_tokens`、記事要約のプロンプト（「要約」「暗号資産への示唆」） | 済（今朝のまとめ用はフェーズ5） |

- 暗号資産のペアは bitbank の取扱銘柄と照合し、存在しないペアは警告してスキップする（フェーズ2）。
- 上限を超えたら先頭から順に採用する（実装済み）。

## 環境変数（`.env`、見本は `.env.example`）

- `ANTHROPIC_API_KEY`: 要約・まとめ用
- `FRED_API_KEY`: 経済指標の発表予定日
- `NOTION_PAGE_ID`（任意）: Notion への書き出し先
- `DISCORD_WEBHOOK_URL`（任意）: Discord 通知（フェーズ5で実装予定）

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
    - launchd はシェルの環境変数を引き継がないので、plist の `EnvironmentVariables` に入れる（plist はリポジトリに入れない）。Mac がスリープ中は動かないので、フェーズ6で `pmset` による起動予約などを検討する。
    - URL が漏れたら、Webhook を作り直して古いものを削除する。
- **ウォッチリストの銘柄**: 見本は仮のもの。
- **任意項目**（VIX、ドルインデックス、株価指数先物）: 初期値はオン。

## コード構成

```
src/good_morning/
  main.py            CLI（typer）。run / collect-cmd / publish
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
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
.venv/bin/good-morning run                 # outputs/YYYY-MM-DD.md を生成
.venv/bin/good-morning collect-cmd --explain   # RSS の通過/除外の理由を確認
```

- テストは aion の流儀に合わせる: 実データのスナップショットを `tests/fixtures/` に置き、`monkeypatch` で取得関数を差し替える。共通の部品は `tests/conftest.py`。
- yfinance の固定データは `scripts/capture_yfinance_fixture.py` で `tests/fixtures/yfinance/` に保存する。テストでは `fake_yfinance` フィクスチャで差し替える。`conftest.py` の autouse フィクスチャが、テストから yfinance・bitbank-lab-mcp に触れたら失敗させる。
- bitbank の固定データは `scripts/capture_bitbank_fixture.py` で `tests/fixtures/bitbank/` に保存する（使う部分だけに切り詰める。1本約1MB → 全体で約170KB）。テストでは `fake_bitbank` フィクスチャで差し替える。
- 決算日・FRED の固定データは `scripts/capture_schedule_fixture.py` で保存する（FRED はキーがあるときだけ）。テストでは `fake_yfinance`（決算日も返す）と、`test_schedule_builder.py` の `fake_fred` で差し替える。autouse フィクスチャは `httpx.get` も止める。
- `tests/test_fixture_characterization.py` は「現状の挙動」を固定するベースライン（`tests/fixtures/rss/` の実フィード、2026-11-17 取得）。語彙やフィードを変えたら、意図した差分だけが出ているかを確かめて数値を更新する。有効なフィードを足したら固定データも足す（テストで確認している）。
