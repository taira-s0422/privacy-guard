"""Google Workspace ファイル読み取りモジュール.

gwscli (gws コマンド) を subprocess 経由で呼び出し、
Google Sheets / Docs / Drive のファイルを読み取る。

設計原則:
- 元データ不変: 読み取りのみ実施。GWSへの書き込みは行わない
- フェイルクローズ: 読み取り失敗時は GWSReaderError を raise
- タイムアウト制御: デフォルト30秒でサブプロセスをタイムアウト
"""

import json
import logging
import os
import subprocess
import shutil
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# gwscli / gog コマンドのパス
# 環境変数 PRIVACY_GUARD_GWS_COMMAND / PRIVACY_GUARD_GOG_COMMAND で上書き可能
# （.env.example 参照）
_GWS_COMMAND = os.environ.get(
    "PRIVACY_GUARD_GWS_COMMAND",
    shutil.which("gws") or "gws",  # フォールバック: PATH から探す
)
_GOG_COMMAND = os.environ.get(
    "PRIVACY_GUARD_GOG_COMMAND",
    shutil.which("gog") or "gog",  # フォールバック: PATH から探す
)

# デフォルトタイムアウト（秒）
_DEFAULT_TIMEOUT_SECONDS = 30


class GWSReaderError(Exception):
    """Google Workspace読み取りエラー.

    フェイルクローズ原則: このエラーが発生した場合、呼び出し元はデータを遮断する。
    """

    pass


class GWSReader:
    """Google Workspace ファイル読み取りクラス.

    gwscli (gws) または gog コマンドを subprocess で実行して読み取りを行う。
    書き込みコマンドは提供しない（元データ不変原則）。
    """

    def __init__(
        self,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
        gws_command: str = _GWS_COMMAND,
        gog_command: str = _GOG_COMMAND,
    ) -> None:
        """初期化.

        Args:
            timeout_seconds: subprocess タイムアウト秒数
            gws_command: gwscli コマンドのパス
            gog_command: gog コマンドのパス
        """
        self._timeout = timeout_seconds
        self._gws_command = gws_command
        self._gog_command = gog_command

    def read_spreadsheet(
        self,
        spreadsheet_id: str,
        sheet_name: Optional[str] = None,
        range_notation: Optional[str] = None,
    ) -> Dict:
        """Google Spreadsheet を読み取る.

        Args:
            spreadsheet_id: スプレッドシートID（URLの /d/ 以降）
            sheet_name: シート名（省略時はデフォルトシート）
            range_notation: A1記法での範囲（例: "A1:Z100"）

        Returns:
            {
                "content": str,   # タブ区切りテキスト
                "rows": list,     # 行データのリスト（各行はリスト）
                "sheet_name": str,
                "source": "google_sheets",
            }

        Raises:
            GWSReaderError: 読み取り失敗時
        """
        self._check_gws_available()

        # 範囲指定
        range_spec = sheet_name or "Sheet1"
        if range_notation:
            range_spec = f"{range_spec}!{range_notation}"

        cmd = [
            self._gws_command,
            "sheets", "spreadsheets", "values", "get",
            "--params", json.dumps({
                "spreadsheetId": spreadsheet_id,
                "range": range_spec,
            }),
        ]

        result = self._run_command(cmd, context=f"Sheets読み取り [{spreadsheet_id}]")

        try:
            data = json.loads(result)
            rows = data.get("values", [])
            content_lines = ["\t".join(str(cell) for cell in row) for row in rows]
            return {
                "content": "\n".join(content_lines),
                "rows": rows,
                "sheet_name": sheet_name or "Sheet1",
                "source": "google_sheets",
            }
        except json.JSONDecodeError as e:
            # 出力はマスキング前のデータを含みうるため、エラー文に載せない
            raise GWSReaderError(
                f"gwscli の出力をJSONとして解析できませんでした: {e}（出力 {len(result)} 文字）"
            ) from e

    def read_document(self, document_id: str) -> Dict:
        """Google Document を読み取る.

        Args:
            document_id: ドキュメントID（URLの /d/ 以降）

        Returns:
            {
                "content": str,   # ドキュメントのテキスト内容
                "source": "google_docs",
            }

        Raises:
            GWSReaderError: 読み取り失敗時
        """
        self._check_gog_available()

        cmd = [
            self._gog_command,
            "docs", "get",
            "--doc-id", document_id,
            "--format", "text",
        ]

        content = self._run_command(cmd, context=f"Docs読み取り [{document_id}]")
        return {
            "content": content,
            "source": "google_docs",
        }

    def read_drive_file(self, file_id: str, mime_type: Optional[str] = None) -> Dict:
        """Google Drive のファイルをエクスポート・読み取る.

        Google Forms / Slides 等、テキスト変換できるファイルに対応。

        Args:
            file_id: ファイルID
            mime_type: エクスポート形式（省略時は text/plain）

        Returns:
            {
                "content": str,
                "source": "google_drive",
                "file_id": str,
            }

        Raises:
            GWSReaderError: 読み取り失敗時
        """
        self._check_gog_available()

        export_mime = mime_type or "text/plain"
        cmd = [
            self._gog_command,
            "drive", "export",
            "--file-id", file_id,
            "--mime-type", export_mime,
        ]

        content = self._run_command(cmd, context=f"Drive読み取り [{file_id}]")
        return {
            "content": content,
            "source": "google_drive",
            "file_id": file_id,
        }

    # ============================================================
    # 内部ヘルパーメソッド
    # ============================================================

    def _run_command(self, cmd: List[str], context: str = "") -> str:
        """subprocess でコマンドを実行し、stdout を返す.

        Args:
            cmd: 実行するコマンドと引数のリスト
            context: ログ出力用のコンテキスト文字列

        Returns:
            コマンドの stdout 出力（文字列）

        Raises:
            GWSReaderError: タイムアウト・実行エラー・非ゼロ終了コード時
        """
        logger.debug(f"コマンド実行: {' '.join(cmd)} [{context}]")
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                check=False,  # 終了コードは手動チェック
            )
        except subprocess.TimeoutExpired as e:
            raise GWSReaderError(
                f"コマンドタイムアウト（{self._timeout}秒）: {context}"
            ) from e
        except FileNotFoundError as e:
            raise GWSReaderError(
                f"コマンドが見つかりません: {cmd[0]} [{context}]"
            ) from e
        except Exception as e:
            raise GWSReaderError(f"コマンド実行エラー [{context}]: {e}") from e

        if result.returncode != 0:
            # stderr はマスキング前のデータを含みうるため、エラー文に載せない
            raise GWSReaderError(
                f"コマンド失敗（終了コード {result.returncode}）[{context}]\n"
                "詳細はターミナルで同じコマンドを直接実行して確認してください"
            )

        return result.stdout

    def _check_gws_available(self) -> None:
        """gwscli コマンドが利用可能か確認する.

        Raises:
            GWSReaderError: コマンドが見つからない場合
        """
        if not shutil.which(self._gws_command) and not self._command_exists(self._gws_command):
            raise GWSReaderError(
                f"gwscli コマンドが見つかりません: {self._gws_command}\n"
                "インストール: npm install -g @googleworkspace/cli"
            )

    def _check_gog_available(self) -> None:
        """gog コマンドが利用可能か確認する.

        Raises:
            GWSReaderError: コマンドが見つからない場合
        """
        if not shutil.which(self._gog_command) and not self._command_exists(self._gog_command):
            raise GWSReaderError(
                f"gog コマンドが見つかりません: {self._gog_command}\n"
                "パスを確認してください: ~/.local/bin/gog"
            )

    def _command_exists(self, command: str) -> bool:
        """コマンドが実行可能か確認する（フルパス指定の場合）.

        Args:
            command: 確認するコマンドのパス

        Returns:
            実行可能な場合 True
        """
        return os.path.isfile(command) and os.access(command, os.X_OK)

    # 禁止操作: Google Workspace への書き込みメソッドは提供しない
    # write_spreadsheet(), update_document() 等は意図的に未実装
    # 設計意図: 元データ不変原則を「書き込みAPIが存在しない」ことで機械的に担保する
