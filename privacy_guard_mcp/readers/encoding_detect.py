"""エンコーディング自動判別モジュール.

chardet による自動判別を主体とし、失敗時は UTF-8 → Shift-JIS → EUC-JP の
フォールバックチェーンでデコードを試みる。

設計原則:
- 元データ不変: バイト列を読み取るのみ。ファイルへの書き込みは行わない
- フェイルクローズ: 全フォールバックを試みてもデコード失敗の場合は EncodingError を raise
"""

import logging
from typing import Optional, Tuple

import chardet

logger = logging.getLogger(__name__)

# フォールバックチェーン（chardet判別失敗時の試行順序）
_FALLBACK_ENCODINGS = ["utf-8", "shift_jis", "euc_jp", "cp932", "latin-1"]


class EncodingError(Exception):
    """エンコーディング判別・デコードエラー."""

    pass


def detect_encoding(raw_bytes: bytes) -> str:
    """バイト列のエンコーディングを自動判別する.

    chardet による判別を試み、信頼度が低い場合はフォールバックチェーンを使用する。

    Args:
        raw_bytes: エンコーディング判別対象のバイト列

    Returns:
        判別されたエンコーディング名（例: "utf-8", "shift_jis"）

    Raises:
        EncodingError: エンコーディングを判別できなかった場合
    """
    if not raw_bytes:
        return "utf-8"

    # chardet による自動判別
    result = chardet.detect(raw_bytes)
    encoding = result.get("encoding")
    confidence = result.get("confidence", 0.0)

    if encoding and confidence >= 0.7:
        logger.debug(f"chardet判別成功: {encoding} (confidence={confidence:.2f})")
        return encoding

    # 信頼度が低い場合はフォールバック
    logger.debug(
        f"chardet信頼度低 ({confidence:.2f}): フォールバックチェーンを試行"
    )
    for enc in _FALLBACK_ENCODINGS:
        try:
            raw_bytes.decode(enc)
            logger.debug(f"フォールバック成功: {enc}")
            return enc
        except (UnicodeDecodeError, LookupError):
            continue

    raise EncodingError(
        f"エンコーディングを判別できませんでした。試行: {_FALLBACK_ENCODINGS}"
    )


def decode_bytes(raw_bytes: bytes, encoding: Optional[str] = None) -> str:
    """バイト列を文字列にデコードする.

    encoding が未指定の場合は detect_encoding() で自動判別する。

    Args:
        raw_bytes: デコード対象のバイト列
        encoding: エンコーディング名（省略時は自動判別）

    Returns:
        デコードされた文字列

    Raises:
        EncodingError: デコードに失敗した場合
    """
    if not raw_bytes:
        return ""

    if encoding is None:
        encoding = detect_encoding(raw_bytes)

    try:
        return raw_bytes.decode(encoding, errors="strict")
    except (UnicodeDecodeError, LookupError) as e:
        # 指定エンコーディングで失敗した場合、フォールバックを試みる
        logger.warning(f"指定エンコーディング({encoding})でデコード失敗: {e}")
        for enc in _FALLBACK_ENCODINGS:
            if enc == encoding:
                continue
            try:
                text = raw_bytes.decode(enc, errors="strict")
                logger.debug(f"フォールバックデコード成功: {enc}")
                return text
            except (UnicodeDecodeError, LookupError):
                continue

        raise EncodingError(
            f"全エンコーディングでデコードに失敗しました。試行: {[encoding] + _FALLBACK_ENCODINGS}"
        ) from e
