"""シャノンエントロピー計算モジュール.

APIキー・トークン検知の補助として、文字列のエントロピーを計算する。
高エントロピー文字列（ランダム性が高い）はAPIキー候補として扱う。
"""

import math
from collections import Counter
from typing import Optional


def calculate_entropy(text: str) -> float:
    """シャノンエントロピーを計算する.

    エントロピーが高いほど文字列がランダム（APIキーらしい）。
    一般的に英文テキストは 3.5〜4.0 bit/char 程度。
    APIキーは 4.5 bit/char 以上が多い。

    Args:
        text: エントロピーを計算する文字列

    Returns:
        エントロピー値（bit/char）。空文字列は 0.0 を返す。
    """
    if not text:
        return 0.0

    # 文字頻度をカウント
    char_counts = Counter(text)
    total = len(text)

    # シャノンエントロピー計算
    entropy = 0.0
    for count in char_counts.values():
        probability = count / total
        if probability > 0:
            entropy -= probability * math.log2(probability)

    return entropy


def is_high_entropy(text: str, threshold: float = 4.5) -> bool:
    """文字列が高エントロピー（APIキー候補）かどうか判定する.

    Args:
        text: 判定する文字列
        threshold: エントロピー閾値（デフォルト: 4.5）

    Returns:
        エントロピーが閾値以上なら True
    """
    return calculate_entropy(text) >= threshold


def is_likely_api_key(text: str) -> bool:
    """文字列がAPIキーらしいかどうか総合判定する.

    エントロピー + 長さ + 文字種の組み合わせで判定する。

    Args:
        text: 判定する文字列

    Returns:
        APIキーらしければ True
    """
    if len(text) < 16:
        return False

    entropy = calculate_entropy(text)
    if entropy < 4.0:
        return False

    # 英字と数字が混在しているか
    has_alpha = any(c.isalpha() for c in text)
    has_digit = any(c.isdigit() for c in text)

    return has_alpha and has_digit and entropy >= 4.5
