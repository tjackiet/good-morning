# good-morning

暗号資産投資の判断に役立つ「モーニングレター」を自動生成する CLI ツールです。
株式・債券・為替・コモディティ・暗号資産の数値、今後30日の予定、主要ニュースを集約し、
Markdown のレポートとして出力します。メイン銘柄は BTC です。

> 開発中です。進み具合は [CLAUDE.md](CLAUDE.md) のフェーズ表を参照してください。

## 特徴

- 数値はすべて API から機械的に取得し、LLM（Claude）は要約・まとめの文章だけを担当します
- 一部のデータ取得に失敗しても、該当欄を「取得失敗」と表示してレポート全体は出力します
- 銘柄・フィード・キーワード・イベント・判定基準は YAML で変更できます
- 時刻はすべて JST で表示し、データごとの基準時刻（NY終値／取得時点）を明記します

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

`.env` と `config/watchlist.yaml` は `.gitignore` 済みです。`watchlist.yaml` がない場合は
見本（`watchlist.example.yaml`）を読み込み、警告を出します。

## 使い方

```bash
# モーニングレターを生成して outputs/YYYY-MM-DD.md に保存
.venv/bin/good-morning run

# Notion にも書き出す（任意。.env に NOTION_PAGE_ID が必要）
.venv/bin/good-morning run --publish

# RSS 記事の通過/除外の理由を確認
.venv/bin/good-morning collect-cmd --explain
```

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
