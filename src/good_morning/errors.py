"""例外の扱いの共通部品"""


def cause_chain(error: BaseException, depth: int = 4) -> str:
    """例外の型名を原因までたどって並べる（メッセージは使わない）

    httpx などの例外メッセージはリクエストの URL（API キーや Webhook のトークンを含む）を
    含むことがあるので、型名だけを残す。原因の型名から、証明書・名前解決・タイムアウトなどの
    違いは分かる（例: "ConnectError ← ConnectError ← SSLCertVerificationError"）。
    """
    names = []
    current: BaseException | None = error
    while current is not None and len(names) < depth:
        names.append(type(current).__name__)
        current = current.__cause__ or current.__context__
    return " ← ".join(names)
