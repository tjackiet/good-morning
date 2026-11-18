# good-morning

暗号資産投資の判断に役立つ「モーニングレター」を自動生成する CLI ツールです。
株式・債券・為替・コモディティ・暗号資産の数値、今後30日の予定、主要ニュースを集約し、
Markdown のレポートと、グラフ入りのビジュアルレポート（HTML）として出力します。メイン銘柄は BTC です。

> 開発中です（定時実行の設定が未完了）。進み具合は [CLAUDE.md](CLAUDE.md) のフェーズ表を参照してください。

## 特徴

- 数値はすべて API から機械的に取得し、LLM（Claude）は要約・まとめの文章だけを担当します。Claude の文章に出てくる数値は、元データと機械的に照合します
- 一部のデータ取得に失敗しても、該当欄を「取得失敗」と表示してレポート全体は出力します
- 銘柄・フィード・キーワード・イベント・判定基準は YAML で変更できます
- 時刻はすべて JST で表示し、データごとの基準時刻（NY終値／取得時点）を明記します
- ビジュアルレポートはライト・ダークの両方に対応し、上がり・下がりは色だけでなく ▲▼ と +/− でも示します
- Discord には、判定・3行の要約・BTC の価格と、レポートへのリンクを通知します（設定で画像のカードも添付できます）

## データ取得元

| 対象 | 取得元 |
|---|---|
| 株・指数・為替・金利・商品・セクターETF | [yfinance](https://github.com/ranaroussi/yfinance) |
| 暗号資産 | [bitbank-lab-mcp](https://www.npmjs.com/package/bitbank-lab-mcp)（公開データのみ） |
| 経済指標の発表予定日 | [FRED API](https://fred.stlouisfed.org/docs/api/fred/) |
| FOMC・日銀会合 | 公式日程を `config/events.yaml` に転記 |
| ニュース | 各社の RSS |

## セットアップ

前提: Python 3.11 以上、Node.js（`npx` で MCP サーバーを起動するため）

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cp .env.example .env                                     # API キーを記入
cp config/watchlist.example.yaml config/watchlist.yaml   # 銘柄を編集
```

画像のカードを Discord に添付したいときは、`config/notify.yaml` の `attach_card` を `true` にし、
`.venv/bin/pip install -e ".[dev,card]"` と `.venv/bin/python -m playwright install chromium` も実行してください。

`.env` と `config/watchlist.yaml` は `.gitignore` 済みです。`watchlist.yaml` がない場合は
見本（`watchlist.example.yaml`）を読み込み、警告を出します。

## 使い方

```bash
# モーニングレターを生成して outputs/ に保存
.venv/bin/good-morning run

# Notion にも書き出す（任意。.env に NOTION_PAGE_ID が必要）
.venv/bin/good-morning run --publish

# Discord に通知する（任意。.env に DISCORD_WEBHOOK_URL が必要。同じ日は1回だけ）
.venv/bin/good-morning run --publish --notify

# 通知の文面を確かめるだけ（送らない）
.venv/bin/good-morning run --notify-preview

# 保存済みのレポートの通知を後から送る（リンクは --link か .env の REPORT_URL）
.venv/bin/good-morning notify --link https://example.com/report

# 保存済みのデータからビジュアルレポートの HTML を作り直す
.venv/bin/good-morning render

# RSS 記事の通過/除外の理由を確認
.venv/bin/good-morning collect-cmd --explain
```

`run` で `outputs/` に保存されるもの:

| ファイル | 内容 |
|---|---|
| `YYYY-MM-DD.md` | Markdown のレポート（本体） |
| `YYYY-MM-DD.json` | ビジュアルレポートの元データ（計算済みの数値と文章） |
| `YYYY-MM-DD.html` | ビジュアルレポート（ブラウザで開ける） |
| `YYYY-MM-DD-artifact.html` | 同じレポートの claude.ai アーティファクト用 |
| `YYYY-MM-DD-card.png` | Discord に添付する画像のカード（`config/notify.yaml` で `attach_card: true` のときだけ） |

ログは `logs/YYYY-MM-DD.log` に出力されます。

## 開発

```bash
.venv/bin/pytest -q
.venv/bin/ruff check src tests scripts
```

テストはネットワークに依存せず、実データから作った固定データ（`tests/fixtures/`）で行います。

## 謝辞

RSS 収集・記事選定・要約の仕組みは、自作の [aion](https://github.com/tjackiet/aion)（AI 分野のニュース収集ツール）を元にしています。
aion は以下の記事を参考に作成しました。

- [AI系の情報収集手法を紹介（ビジネス・開発・研究）【2025年版】](https://zenn.dev/mkj/articles/1357a7ea2970c4)（小川 雄太郎さん）

## 免責

本ツールが生成するレポートは情報提供を目的としたもので、投資助言ではありません。
投資判断はご自身の責任で行ってください。

## ライセンス

MIT
