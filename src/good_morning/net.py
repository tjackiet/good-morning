"""HTTP 通信の共通設定

証明書の検証には OS の証明書ストア（macOS のキーチェーン）を使う（truststore）。
会社のネットワークでは、セキュリティ機器（Fortinet など）が HTTPS を検査して証明書を
社内の CA で署名し直すことがある（2026-11-18 に CoinPost・The Block・FRB などで確認）。
社内の CA は OS には登録されているが、httpx が標準で使う certifi の証明書の束には入っていない
ため、certifi だと「CERTIFICATE_VERIFY_FAILED」で失敗する。検証を切るのではなく、OS の
証明書ストアで検証する。
"""

import functools
import ssl

import truststore

# npx で起動する MCP サーバー（Node.js）にも OS の証明書ストアを使わせる（Node 22.15 / 23.8 以降）。
# Node も標準では独自の証明書の束を使うため、会社のネットワークでは mcp.notion.com への接続が
# 「unable to verify the first certificate」で失敗した（2026-11-18）。
# MCP SDK は env を既定の環境変数（HOME・PATH など）に足して子プロセスに渡すので、API キーなどは渡らない。
NODE_SYSTEM_CA_ENV = {"NODE_OPTIONS": "--use-system-ca"}


@functools.cache
def ssl_context() -> ssl.SSLContext:
    """OS の証明書ストアで検証する SSLContext（httpx の verify= に渡す）"""
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
