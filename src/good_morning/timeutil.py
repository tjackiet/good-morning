"""時刻の扱い（表示はすべて JST）"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS_JA = "月火水木金土日"


def now_jst() -> datetime:
    return datetime.now(JST)


def format_jst(dt: datetime, fmt: str = "%Y-%m-%d %H:%M") -> str:
    """任意のタイムゾーン付き日時を JST に変換して文字列にする（表示用）"""
    if dt.tzinfo is None:
        raise ValueError("タイムゾーンのない日時は JST に変換できません")
    return dt.astimezone(JST).strftime(fmt) + " JST"


def weekday_ja(d: date) -> str:
    return WEEKDAYS_JA[d.weekday()]


def format_month_day(d: date) -> str:
    """11/16（月） の形式"""
    return f"{d.month}/{d.day}（{weekday_ja(d)}）"
