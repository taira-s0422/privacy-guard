"""ファイル読み取りモジュール.

Phase 3で実装するファイルリーダー群。
元データ不変原則: 読み取りのみ実施し、入力ファイルへの書き込みは行わない。
フェイルクローズ: 読み取り失敗時は ReaderError を raise し、中途データを返さない。
"""

from .local import LocalFileReader, ReaderError
from .encoding_detect import detect_encoding
from .gws import GWSReader

__all__ = ["LocalFileReader", "ReaderError", "detect_encoding", "GWSReader"]
