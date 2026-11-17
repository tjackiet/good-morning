"""時刻の扱い（表示はすべて JST）"""

from datetime import datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")


def now_jst() -> datetime:
    return datetime.now(JST)


def format_jst(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """任意のタイムゾーン付き日時を JST に変換して文字列にする（表示用）"""
    if dt.tzinfo is None:
        raise ValueError("タイムゾーンのない日時は JST に変換できません")
    return dt.astimezone(JST).strftime(fmt) + " JST"
