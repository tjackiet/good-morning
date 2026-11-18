"""Claude の出力に含まれる数値が、渡したデータにあるかを照合する（大原則1の機械的な確認）

符号・3桁区切り・末尾の 0 の違いは同じ数値とみなす（"+1.04%" と "1.04"、"10,350,000" と
"10350000"）。データにない数値（計算した値・単位を換算した値・作った値）を見つけるのが目的。
"""

import re
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _canonical(token: str) -> str | None:
    try:
        value = Decimal(token.replace(",", ""))
    except InvalidOperation:
        return None
    normalized = value.normalize()
    # Decimal("100").normalize() は 1E+2 になるので、指数表記を避けて文字列にする
    return format(normalized, "f")


def numbers_in(text: str) -> set[str]:
    """文章に含まれる数値を正規化した文字列の集合で返す"""
    found = set()
    for match in _NUMBER.finditer(text):
        canonical = _canonical(match.group())
        if canonical is not None:
            found.add(canonical)
    return found


def unknown_numbers(output: str, facts: str) -> list[str]:
    """output に出てくるが facts にない数値（出てきた順・重複なし）"""
    allowed = numbers_in(facts)
    unknown: list[str] = []
    for match in _NUMBER.finditer(output):
        canonical = _canonical(match.group())
        if canonical is not None and canonical not in allowed and match.group() not in unknown:
            unknown.append(match.group())
    return unknown
