"""データモデル定義"""

from datetime import datetime

from pydantic import BaseModel, Field


class Article(BaseModel):
    """記事データモデル"""

    title: str = Field(..., description="記事タイトル")
    url: str = Field(..., description="記事URL")
    source: str = Field(..., description="情報源名")
    category: str = Field(..., description="カテゴリ（feeds.yaml の categories のキー。例 crypto/macro/official）")
    published: datetime | None = Field(None, description="公開日時")
    summary: str | None = Field(None, description="記事概要（RSSから取得）")
    content: str | None = Field(None, description="記事本文")

    # LLM生成フィールド（数値は記事にあるものだけを使わせる。大原則1）
    ai_summary: str | None = Field(None, description="AI生成要約")
    crypto_implication: str | None = Field(None, description="暗号資産への示唆")

    # 選定ロジックの可視化用フィールド（--explain で利用）
    matched_keywords: list[str] = Field(default_factory=list, description="マッチしたキーワード")
    excluded_reason: str | None = Field(None, description="選定から除外された理由（通過時はNone）")
    score: float = Field(0.0, description="選定スコア（大きいほど優先。good_morning.selector.scoring 参照）")


class FeedConfig(BaseModel):
    """RSSフィード設定"""

    name: str
    url: str
    category: str
    enabled: bool = True
    # フィード自体が対象分野に限定されている場合は False にする。
    # その情報源はキーワードフィルタを適用せず全件通過させる（日付フィルタは適用される）。
    keyword_filter: bool = True
    # このフィードでは数えないキーワード。配信元の名前そのもの（SEC のプレスリリースの「SEC」、
    # 日銀の新着情報の「日銀」）は全記事に含まれ、フィルタの意味がなくなるため。
    ignore_keywords: list[str] = Field(default_factory=list)


class FeedCategory(BaseModel):
    """フィードのカテゴリ（表示名と要約枠の配分）"""

    label: str
    quota: int = 1


class FeedsConfig(BaseModel):
    """フィード設定ファイル全体"""

    categories: dict[str, FeedCategory] = Field(default_factory=dict)
    feeds: list[FeedConfig]
