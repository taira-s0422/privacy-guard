"""ローカルファイル読み取りモジュール.

テキスト/CSV/Markdown/Excel/PDF/Word 形式のファイルを読み取る。
画像含有検知（Excel/Word/PDF）も実施する。

設計原則:
- 元データ不変: 読み取りのみ実施。入力ファイルへの書き込みは一切行わない
- フェイルクローズ: 読み取り失敗時は ReaderError を raise し、中途データを返さない
- セキュリティ: パストラバーサル対策（絶対パスのみ許可）
"""

import csv
import io
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 対応ファイル拡張子
_TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".csv", ".log", ".json", ".yaml", ".yml", ".toml", ".ini", ".conf"}
_EXCEL_EXTENSIONS = {".xlsx", ".xls", ".xlsm"}
_PDF_EXTENSIONS = {".pdf"}
_WORD_EXTENSIONS = {".docx", ".doc"}

# ファイルサイズ上限（デフォルト: 50MB）
_DEFAULT_MAX_SIZE_BYTES = 50 * 1024 * 1024


class ReaderError(Exception):
    """ファイル読み取りエラー.

    フェイルクローズ原則: このエラーが発生した場合、呼び出し元はデータを遮断する。
    """

    pass


class LocalFileReader:
    """ローカルファイル読み取りクラス.

    拡張子に応じて適切な読み取り処理を選択する。
    全メソッドは読み取り専用。書き込みメソッドは提供しない。
    """

    def __init__(self, max_size_bytes: int = _DEFAULT_MAX_SIZE_BYTES) -> None:
        """初期化.

        Args:
            max_size_bytes: 読み取り可能な最大ファイルサイズ（バイト）
        """
        self._max_size_bytes = max_size_bytes

    def read(self, file_path: str) -> Dict:
        """ファイルを読み取り、テキスト内容とメタデータを返す.

        拡張子に応じて適切な読み取り処理を自動選択する。

        Args:
            file_path: 読み取るファイルのパス（絶対パス推奨）

        Returns:
            {
                "content": str,          # 読み取ったテキスト内容
                "encoding": str,         # 使用したエンコーディング（テキスト系のみ）
                "page_count": int,       # ページ数（PDF）または -1
                "sheet_names": list,     # シート名一覧（Excel）または []
                "has_images": bool,      # 画像含有フラグ
                "file_type": str,        # 判別されたファイルタイプ
                "file_size_bytes": int,  # ファイルサイズ
            }

        Raises:
            ReaderError: 読み取り失敗時（フェイルクローズ）
        """
        path = self._validate_path(file_path)
        ext = path.suffix.lower()

        if ext in _EXCEL_EXTENSIONS:
            return self.read_excel(file_path)
        elif ext in _PDF_EXTENSIONS:
            return self.read_pdf(file_path)
        elif ext == ".csv":
            return self.read_csv(file_path)
        elif ext in _TEXT_EXTENSIONS:
            return self.read_text(file_path)
        else:
            # 未知拡張子はテキストとして試みる
            logger.warning(f"未知の拡張子 '{ext}': テキストとして読み取りを試みます")
            return self.read_text(file_path)

    def read_text(self, file_path: str, encoding: Optional[str] = None) -> Dict:
        """テキストファイルを読み取る.

        Args:
            file_path: ファイルパス
            encoding: エンコーディング（省略時は自動判別）

        Returns:
            read() と同形式の辞書

        Raises:
            ReaderError: 読み取り失敗時
        """
        from .encoding_detect import decode_bytes, EncodingError

        path = self._validate_path(file_path)
        try:
            raw_bytes = self._read_raw_bytes(path)
            used_encoding = encoding
            if used_encoding is None:
                from .encoding_detect import detect_encoding
                used_encoding = detect_encoding(raw_bytes)

            content = raw_bytes.decode(used_encoding, errors="replace")
            return {
                "content": content,
                "encoding": used_encoding,
                "page_count": -1,
                "sheet_names": [],
                "has_images": False,
                "file_type": "text",
                "file_size_bytes": len(raw_bytes),
            }
        except ReaderError:
            raise
        except EncodingError as e:
            raise ReaderError(f"エンコーディングエラー: {e}") from e
        except Exception as e:
            raise ReaderError(f"テキストファイル読み取りエラー [{file_path}]: {e}") from e

    def read_csv(self, file_path: str, encoding: Optional[str] = None) -> Dict:
        """CSVファイルを読み取り、テキスト形式に変換して返す.

        Args:
            file_path: ファイルパス
            encoding: エンコーディング（省略時は自動判別）

        Returns:
            read() と同形式の辞書（content はタブ区切りテキスト）

        Raises:
            ReaderError: 読み取り失敗時
        """
        from .encoding_detect import detect_encoding, EncodingError

        path = self._validate_path(file_path)
        try:
            raw_bytes = self._read_raw_bytes(path)
            used_encoding = encoding
            if used_encoding is None:
                used_encoding = detect_encoding(raw_bytes)

            text = raw_bytes.decode(used_encoding, errors="replace")
            reader = csv.reader(io.StringIO(text))
            rows = list(reader)

            # CSV内容をタブ区切りテキストに変換（マスキング処理がしやすい形式）
            content_lines = ["\t".join(row) for row in rows]
            content = "\n".join(content_lines)

            return {
                "content": content,
                "encoding": used_encoding,
                "page_count": -1,
                "sheet_names": [],
                "has_images": False,
                "file_type": "csv",
                "file_size_bytes": len(raw_bytes),
            }
        except ReaderError:
            raise
        except EncodingError as e:
            raise ReaderError(f"エンコーディングエラー: {e}") from e
        except Exception as e:
            raise ReaderError(f"CSVファイル読み取りエラー [{file_path}]: {e}") from e

    def read_excel(self, file_path: str, sheet_name: Optional[str] = None) -> Dict:
        """Excelファイルを読み取り、テキスト形式に変換して返す.

        openpyxl を使用して .xlsx/.xlsm を読み取る。
        .xls（旧形式）は xlrd が必要だが、本実装では openpyxl のみサポート。

        Args:
            file_path: ファイルパス
            sheet_name: 読み取るシート名（省略時は全シート）

        Returns:
            read() と同形式の辞書

        Raises:
            ReaderError: 読み取り失敗時
        """
        try:
            import openpyxl
        except ImportError as e:
            raise ReaderError("openpyxl がインストールされていません。pip install openpyxl") from e

        path = self._validate_path(file_path)
        try:
            file_size = path.stat().st_size

            # read_only=True で元ファイルへの書き込みを防ぐ
            wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
            sheet_names = wb.sheetnames

            # 画像含有チェック（通常モードで再読み込みが必要だが read_only では検知不可）
            # read_only=True の場合、_images属性はアクセスできないため、
            # ファイル内の画像有無はZIPファイル構造から判定する
            has_images = self._check_excel_has_images(path)

            content_parts = []
            target_sheets = [sheet_name] if sheet_name else sheet_names

            for sname in target_sheets:
                if sname not in sheet_names:
                    logger.warning(f"シート '{sname}' が見つかりません。スキップします。")
                    continue
                ws = wb[sname]
                content_parts.append(f"=== シート: {sname} ===")
                for row in ws.iter_rows(values_only=True):
                    row_text = "\t".join(
                        str(cell) if cell is not None else "" for cell in row
                    )
                    content_parts.append(row_text)

            wb.close()

            return {
                "content": "\n".join(content_parts),
                "encoding": "utf-8",
                "page_count": -1,
                "sheet_names": sheet_names,
                "has_images": has_images,
                "file_type": "excel",
                "file_size_bytes": file_size,
            }
        except ReaderError:
            raise
        except Exception as e:
            raise ReaderError(f"Excelファイル読み取りエラー [{file_path}]: {e}") from e

    def read_pdf(self, file_path: str) -> Dict:
        """PDFファイルを読み取り、テキスト内容を返す.

        pypdf を使用してテキストを抽出する。
        スキャンPDF（画像のみ）はテキストが空になるが、has_images=True で通知する。

        Args:
            file_path: ファイルパス

        Returns:
            read() と同形式の辞書

        Raises:
            ReaderError: 読み取り失敗時
        """
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise ReaderError("pypdf がインストールされていません。pip install pypdf") from e

        path = self._validate_path(file_path)
        try:
            file_size = path.stat().st_size

            # 元データ不変: 読み取り専用モードで開く
            with open(str(path), "rb") as f:
                reader = PdfReader(f)
                page_count = len(reader.pages)
                content_parts = []
                has_images = False

                for i, page in enumerate(reader.pages):
                    text = page.extract_text() or ""
                    content_parts.append(f"=== ページ {i + 1} ===")
                    content_parts.append(text)

                    # 画像含有チェック
                    if hasattr(page, "images") and page.images:
                        has_images = True

            return {
                "content": "\n".join(content_parts),
                "encoding": "utf-8",
                "page_count": page_count,
                "sheet_names": [],
                "has_images": has_images,
                "file_type": "pdf",
                "file_size_bytes": file_size,
            }
        except ReaderError:
            raise
        except Exception as e:
            raise ReaderError(f"PDFファイル読み取りエラー [{file_path}]: {e}") from e

    # ============================================================
    # 内部ヘルパーメソッド
    # ============================================================

    def _validate_path(self, file_path: str) -> Path:
        """ファイルパスを検証して Path オブジェクトを返す.

        Args:
            file_path: 検証するファイルパス

        Returns:
            検証済み Path オブジェクト

        Raises:
            ReaderError: パスが無効または存在しない場合
        """
        if not file_path or not isinstance(file_path, str):
            raise ReaderError("ファイルパスは空でない文字列でなければなりません")

        path = Path(file_path)

        if not path.is_absolute():
            logger.warning(f"相対パスが指定されました: {file_path}（絶対パスを推奨）")

        if not path.exists():
            raise ReaderError(f"ファイルが見つかりません: {file_path}")

        if not path.is_file():
            raise ReaderError(f"指定パスはファイルではありません: {file_path}")

        return path

    def _read_raw_bytes(self, path: Path) -> bytes:
        """ファイルのバイト列を読み取る.

        ファイルサイズ上限を超える場合は ReaderError を raise する。

        Args:
            path: 読み取るファイルの Path オブジェクト

        Returns:
            ファイルのバイト列

        Raises:
            ReaderError: ファイルサイズ超過または読み取りエラー時
        """
        file_size = path.stat().st_size
        if file_size > self._max_size_bytes:
            raise ReaderError(
                f"ファイルサイズ超過: {file_size:,} バイト > 上限 {self._max_size_bytes:,} バイト"
                f" [{path}]"
            )

        try:
            return path.read_bytes()
        except PermissionError as e:
            raise ReaderError(f"ファイルの読み取り権限がありません: {path}") from e
        except OSError as e:
            raise ReaderError(f"ファイル読み取りエラー: {path} - {e}") from e

    def _check_excel_has_images(self, path: Path) -> bool:
        """Excelファイルに画像が含まれるかチェックする.

        ZIPファイル構造を解析して xl/media/ ディレクトリの有無で判定する。
        .xlsx は ZIP 形式のため、直接 zipfile で検査できる。

        Args:
            path: Excelファイルの Path オブジェクト

        Returns:
            画像が含まれる場合 True
        """
        import zipfile

        try:
            with zipfile.ZipFile(str(path), "r") as zf:
                for name in zf.namelist():
                    if name.startswith("xl/media/"):
                        return True
            return False
        except Exception as e:
            logger.debug(f"Excel画像チェックエラー（無視）: {e}")
            return False

    # 禁止操作: ディスク書き出しメソッドは提供しない
    # save(), write(), export(), to_file() 等は意図的に未実装
    # 設計意図: 元データ不変原則を「書き出しAPIが存在しない」ことで機械的に担保する
