"""Privacy Guard MCP サーバーエントリポイント.

FastMCP stdioトランスポートで起動するMCPサーバー。
個人情報・機密情報マスキングツール群を提供する。

起動方法:
    python privacy_guard_mcp/server.py

または pyproject.toml の scripts から:
    privacy-guard-mcp

実装ツール（全7ツール）:
    Phase 2: pg_mask_text
    Phase 3: pg_read_file, pg_read_excel, pg_read_pdf, pg_gws_read
    Phase 4: pg_check_rules, pg_session_info
"""

import logging
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP

# .env の読み込み（プロジェクトルートの .env）
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")

# ロギング設定
_log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,  # MCPはstdioを使うためログはstderrへ
)
logger = logging.getLogger(__name__)

# フェイルクローズ設定確認
_fail_close = os.environ.get("FAIL_CLOSE", "true").lower() != "false"
if not _fail_close:
    logger.warning(
        "FAIL_CLOSE=false が設定されています。本番環境では必ず true にしてください。"
    )

# 設定ファイル読み込み（失敗時はstrictモード相当で続行）
_config = {}
try:
    import yaml
    _config_path = _project_root / "privacy_guard_mcp" / "config" / "settings.yaml"
    if _config_path.exists():
        with open(_config_path, "r", encoding="utf-8") as f:
            _config = yaml.safe_load(f) or {}
        logger.info("設定ファイル読み込み完了")
    else:
        logger.warning(f"設定ファイルが見つかりません: {_config_path}。デフォルト設定で続行します。")
except Exception as e:
    logger.warning(
        f"設定ファイルの読み込みに失敗しました: {e}。strictモード相当（フェイルクローズ有効）で続行します。"
    )

# FastMCP インスタンス生成
mcp = FastMCP(
    name="privacy-guard-mcp",
    instructions=(
        "個人情報・機密情報を自動マスキングするMCPサーバー。\n"
        "利用可能なツール:\n"
        "- pg_mask_text: テキストをマスキング\n"
        "- pg_read_file: テキスト/CSV/Markdownファイルを読み取ってマスキング\n"
        "- pg_read_excel: Excelファイルを読み取ってマスキング\n"
        "- pg_read_pdf: PDFファイルを読み取ってマスキング\n"
        "- pg_gws_read: Google Workspace（Sheets/Docs）を読み取ってマスキング\n"
        "- pg_check_rules: マスキングルール設定を確認\n"
        "- pg_session_info: セッション情報の確認（スタブ実装）"
    ),
)

# ============================================================
# ツール登録
# ============================================================

# Phase 2: pg_mask_text
from privacy_guard_mcp.masking.tools import register_masking_tools
register_masking_tools(mcp)

# Phase 3-4: ファイル読み取り + ルール確認 + セッション情報
from privacy_guard_mcp.masking.engine import MaskingEngine, MaskingError
from privacy_guard_mcp.masking.session import MaskingSession
from privacy_guard_mcp.readers.local import LocalFileReader, ReaderError
from privacy_guard_mcp.readers.gws import GWSReader, GWSReaderError

_reader = LocalFileReader()
_gws_reader = GWSReader()
_masking_engine = MaskingEngine(fail_close=True)

# 統計カウンター（セクション9.4: 統計ログ出力）
_stats = {
    "total_calls": 0,
    "total_masked_entities": 0,
    "errors": 0,
    "start_time": time.time(),
}


def _build_response(
    status: str,
    content: str = "",
    masking_summary: dict = None,
    warnings: list = None,
    session_id: str = "",
    **kwargs,
) -> dict:
    """標準レスポンスを生成する（仕様書セクション4.2準拠）.

    Args:
        status: "ok" | "error" | "warning"
        content: マスキング済みテキスト内容
        masking_summary: マスキング統計情報
        warnings: 警告メッセージリスト
        session_id: セッションID
        **kwargs: 追加フィールド

    Returns:
        JSON シリアライズ可能な辞書
    """
    return {
        "status": status,
        "data": content,
        "masking_summary": masking_summary or {},
        "warnings": warnings or [],
        "session_id": session_id,
        **kwargs,
    }


def _mask_content(content: str) -> tuple[str, dict, str]:
    """テキストをマスキングし、マスキング済みテキスト・サマリー・セッションIDを返す.

    Args:
        content: マスキング対象テキスト

    Returns:
        (masked_text, masking_summary, session_id)

    Raises:
        MaskingError: マスキング失敗時（フェイルクローズ）
    """
    session = MaskingSession()
    masked = _masking_engine.mask(content, session)
    summary = {
        "total_entities": session.total_masked_count(),
        "categories": session.category_counts(),
    }
    return masked, summary, session.session_id


@mcp.tool()
def pg_read_file(file_path: str) -> dict:
    """テキスト/CSV/Markdownファイルを読み取り、マスキングして返す.

    対応形式: .txt, .md, .markdown, .csv, .log, .json, .yaml, .yml 等
    注意: .csv は read_text() でテキストとして処理する（CSVタブ変換なし）。
          CSV構造を保持したタブ区切り変換が必要な場合は read() 経由で直接読み取ること。
    フェイルクローズ: 読み取り・マスキング失敗時はエラーレスポンスを返す（元データ返却禁止）

    Args:
        file_path: 読み取るファイルの絶対パス

    Returns:
        仕様書セクション4.2準拠のJSONレスポンス
    """
    _stats["total_calls"] += 1
    warnings = []

    try:
        result = _reader.read_text(file_path)

        if result.get("has_images"):
            warnings.append("ファイルに画像が含まれています。画像内のテキストはマスキング対象外です。")

        masked, summary, session_id = _mask_content(result["content"])
        _stats["total_masked_entities"] += summary["total_entities"]
        _log_stats()

        return _build_response(
            status="ok",
            content=masked,
            masking_summary=summary,
            warnings=warnings,
            session_id=session_id,
            file_type=result.get("file_type", "text"),
            encoding=result.get("encoding", "utf-8"),
            file_size_bytes=result.get("file_size_bytes", 0),
        )

    except ReaderError as e:
        _stats["errors"] += 1
        logger.error(f"pg_read_file - 読み取りエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=[f"[READ_ERROR] ファイル読み取りに失敗しました: {e}"],
        )
    except MaskingError as e:
        _stats["errors"] += 1
        logger.error(f"pg_read_file - マスキングエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=["[MASKING_ERROR] マスキング処理に失敗しました。データへのアクセスを遮断しました。"],
        )
    except Exception as e:
        _stats["errors"] += 1
        logger.error(f"pg_read_file - 予期しないエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=["[ERROR] 予期しないエラーが発生しました。データへのアクセスを遮断しました。"],
        )


@mcp.tool()
def pg_read_excel(file_path: str, sheet_name: str = "") -> dict:
    """Excelファイルを読み取り、マスキングして返す.

    対応形式: .xlsx, .xlsm（openpyxl使用）
    画像含有の場合はwarningを付与する。
    フェイルクローズ: 読み取り・マスキング失敗時はエラーレスポンスを返す（元データ返却禁止）

    Args:
        file_path: 読み取るExcelファイルの絶対パス
        sheet_name: 読み取るシート名（空文字の場合は全シート）

    Returns:
        仕様書セクション4.2準拠のJSONレスポンス
    """
    _stats["total_calls"] += 1
    warnings = []

    try:
        result = _reader.read_excel(
            file_path,
            sheet_name=sheet_name if sheet_name else None,
        )

        if result.get("has_images"):
            warnings.append(
                "Excelファイルに画像が含まれています。画像内のテキストはマスキング対象外です。"
            )

        masked, summary, session_id = _mask_content(result["content"])
        _stats["total_masked_entities"] += summary["total_entities"]
        _log_stats()

        return _build_response(
            status="ok",
            content=masked,
            masking_summary=summary,
            warnings=warnings,
            session_id=session_id,
            file_type="excel",
            sheet_names=result.get("sheet_names", []),
            has_images=result.get("has_images", False),
            file_size_bytes=result.get("file_size_bytes", 0),
        )

    except ReaderError as e:
        _stats["errors"] += 1
        logger.error(f"pg_read_excel - 読み取りエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=[f"[READ_ERROR] Excelファイル読み取りに失敗しました: {e}"],
        )
    except MaskingError as e:
        _stats["errors"] += 1
        logger.error(f"pg_read_excel - マスキングエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=["[MASKING_ERROR] マスキング処理に失敗しました。データへのアクセスを遮断しました。"],
        )
    except Exception as e:
        _stats["errors"] += 1
        logger.error(f"pg_read_excel - 予期しないエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=["[ERROR] 予期しないエラーが発生しました。データへのアクセスを遮断しました。"],
        )


@mcp.tool()
def pg_read_pdf(file_path: str) -> dict:
    """PDFファイルを読み取り、マスキングして返す.

    スキャンPDF（画像のみ）はテキストが空になる場合がある。has_images=True で通知する。
    フェイルクローズ: 読み取り・マスキング失敗時はエラーレスポンスを返す（元データ返却禁止）

    Args:
        file_path: 読み取るPDFファイルの絶対パス

    Returns:
        仕様書セクション4.2準拠のJSONレスポンス
    """
    _stats["total_calls"] += 1
    warnings = []

    try:
        result = _reader.read_pdf(file_path)

        if result.get("has_images"):
            warnings.append(
                "PDFに画像が含まれています。画像内のテキスト（スキャンPDF等）はマスキング対象外です。"
            )

        masked, summary, session_id = _mask_content(result["content"])
        _stats["total_masked_entities"] += summary["total_entities"]
        _log_stats()

        return _build_response(
            status="ok",
            content=masked,
            masking_summary=summary,
            warnings=warnings,
            session_id=session_id,
            file_type="pdf",
            page_count=result.get("page_count", -1),
            has_images=result.get("has_images", False),
            file_size_bytes=result.get("file_size_bytes", 0),
        )

    except ReaderError as e:
        _stats["errors"] += 1
        logger.error(f"pg_read_pdf - 読み取りエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=[f"[READ_ERROR] PDFファイル読み取りに失敗しました: {e}"],
        )
    except MaskingError as e:
        _stats["errors"] += 1
        logger.error(f"pg_read_pdf - マスキングエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=["[MASKING_ERROR] マスキング処理に失敗しました。データへのアクセスを遮断しました。"],
        )
    except Exception as e:
        _stats["errors"] += 1
        logger.error(f"pg_read_pdf - 予期しないエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=["[ERROR] 予期しないエラーが発生しました。データへのアクセスを遮断しました。"],
        )


@mcp.tool()
def pg_gws_read(
    resource_type: str,
    resource_id: str,
    sheet_name: str = "",
    range_notation: str = "",
) -> dict:
    """Google Workspace（Sheets/Docs/Drive）を読み取り、マスキングして返す.

    gwscli (gws) / gog コマンドを subprocess 経由で呼び出す。
    フェイルクローズ: 読み取り・マスキング失敗時はエラーレスポンスを返す（元データ返却禁止）

    Args:
        resource_type: "sheets" | "docs" | "drive"
        resource_id: SpreadsheetID / DocumentID / DriveFileID
        sheet_name: シート名（sheetsの場合のみ有効）
        range_notation: A1記法の範囲（sheetsの場合のみ有効、例: "A1:Z100"）

    Returns:
        仕様書セクション4.2準拠のJSONレスポンス
    """
    _stats["total_calls"] += 1

    try:
        if resource_type == "sheets":
            result = _gws_reader.read_spreadsheet(
                spreadsheet_id=resource_id,
                sheet_name=sheet_name if sheet_name else None,
                range_notation=range_notation if range_notation else None,
            )
        elif resource_type == "docs":
            result = _gws_reader.read_document(document_id=resource_id)
        elif resource_type == "drive":
            result = _gws_reader.read_drive_file(file_id=resource_id)
        else:
            return _build_response(
                status="error",
                content="",
                warnings=[
                    f"[INVALID_RESOURCE_TYPE] 未対応のresource_type: '{resource_type}'. "
                    "対応: 'sheets', 'docs', 'drive'"
                ],
            )

        masked, summary, session_id = _mask_content(result["content"])
        _stats["total_masked_entities"] += summary["total_entities"]
        _log_stats()

        return _build_response(
            status="ok",
            content=masked,
            masking_summary=summary,
            warnings=[],
            session_id=session_id,
            source=result.get("source", resource_type),
            resource_type=resource_type,
            resource_id=resource_id,
        )

    except GWSReaderError as e:
        _stats["errors"] += 1
        logger.error(f"pg_gws_read - GWS読み取りエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=[f"[GWS_ERROR] Google Workspace読み取りに失敗しました: {e}"],
        )
    except MaskingError as e:
        _stats["errors"] += 1
        logger.error(f"pg_gws_read - マスキングエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=["[MASKING_ERROR] マスキング処理に失敗しました。データへのアクセスを遮断しました。"],
        )
    except Exception as e:
        _stats["errors"] += 1
        logger.error(f"pg_gws_read - 予期しないエラー（フェイルクローズ）: {e}")
        return _build_response(
            status="error",
            content="",
            warnings=["[ERROR] 予期しないエラーが発生しました。データへのアクセスを遮断しました。"],
        )


@mcp.tool()
def pg_check_rules() -> dict:
    """現在のマスキングルール設定を確認する.

    有効なマスキングカテゴリ・パターン数・設定ファイルパスを返す。

    Returns:
        {
            "status": "ok",
            "rules": {
                "categories": [...],       # 有効なカテゴリ一覧
                "pattern_count": int,      # 合計パターン数
                "fail_close": bool,        # フェイルクローズ設定
                "config_loaded": bool,     # 設定ファイル読み込み成功フラグ
            }
        }
    """
    _stats["total_calls"] += 1

    try:
        from privacy_guard_mcp.masking.patterns import MaskingPatterns, MaskingCategory

        patterns = MaskingPatterns.compile_all()
        categories = list({p.category.value for p in patterns})
        categories.sort()

        return {
            "status": "ok",
            "rules": {
                "categories": categories,
                "pattern_count": len(patterns),
                "fail_close": _fail_close,
                "config_loaded": bool(_config),
                "config_keys": list(_config.keys()) if _config else [],
            },
            "warnings": [],
        }

    except Exception as e:
        _stats["errors"] += 1
        logger.error(f"pg_check_rules エラー: {e}")
        return {
            "status": "error",
            "rules": {},
            "warnings": [f"[ERROR] ルール確認中にエラーが発生しました: {e}"],
        }


@mcp.tool()
def pg_session_info() -> dict:
    """セッション情報を返す（Phase 5スタブ実装）.

    Phase 5 でセッション永続化・セッションID引数化を実装予定。
    現在は各 pg_mask_text / pg_read_* 呼び出しで独立したセッションを生成する（A案）。
    このツールはサーバーレベルの統計情報のみを返す。

    Returns:
        {
            "status": "ok",
            "session": {
                "design": "per-call",      # セッション設計（A案: 呼び出しごとに新規生成）
                "note": "Phase 5 で再設計予定",
                "server_stats": {...},     # サーバー稼働統計
            }
        }
    """
    _stats["total_calls"] += 1

    uptime_seconds = int(time.time() - _stats["start_time"])

    return {
        "status": "ok",
        "session": {
            "design": "per-call",
            "note": (
                "Phase 5 (pg_session_info 実装) でセッション永続化 or セッションID引数化を再設計する。"
                "A案（呼び出しごとに新規セッション生成）を採用。"
            ),
            "server_stats": {
                "total_calls": _stats["total_calls"],
                "total_masked_entities": _stats["total_masked_entities"],
                "errors": _stats["errors"],
                "uptime_seconds": uptime_seconds,
            },
        },
        "warnings": [],
    }


def _log_stats() -> None:
    """統計ログを出力する（セクション9.4準拠）."""
    if _stats["total_calls"] % 10 == 0:  # 10回ごとに定期ログ
        logger.info(
            f"[統計] 累計呼び出し: {_stats['total_calls']}, "
            f"マスキング件数: {_stats['total_masked_entities']}, "
            f"エラー: {_stats['errors']}"
        )


logger.info("Privacy Guard MCP サーバー初期化完了（全7ツール登録）")
logger.info(f"フェイルクローズモード: {_fail_close}")


if __name__ == "__main__":
    logger.info("Privacy Guard MCP サーバーを起動します（stdio transport）")
    mcp.run()
