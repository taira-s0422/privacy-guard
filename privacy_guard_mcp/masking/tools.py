"""pg_mask_text MCPツール実装.

FastMCP の @mcp.tool デコレータを使用して pg_mask_text ツールを登録する。
エラー時は元テキストを漏洩せず、エラーメッセージのみを返す（フェイルクローズ）。
"""

import logging
from typing import TYPE_CHECKING

from .engine import MaskingEngine, MaskingError
from .session import MaskingSession

if TYPE_CHECKING:
    from fastmcp import FastMCP

logger = logging.getLogger(__name__)

# エンジンはモジュールレベルで1インスタンス（fail_close=True固定）
_engine = MaskingEngine(fail_close=True)


def register_masking_tools(mcp: "FastMCP") -> None:
    """マスキングツールをMCPサーバーに登録する.

    Args:
        mcp: FastMCP インスタンス
    """

    @mcp.tool()
    def pg_mask_text(text: str) -> str:
        """テキスト内の個人情報・機密情報をマスキングする.

        個人名・電話番号・メールアドレス・住所・マイナンバー・
        APIキー・パスワード・クレジットカード番号・企業名を検知し、
        [MASKED_XXX_NNN] 形式のIDに置換して返す。

        セッション内で同一エンティティには同一のマスクIDが付与される。

        Args:
            text: マスキング対象のテキスト

        Returns:
            マスキング済みテキスト。エラー時はエラーメッセージを返す（元テキストは返さない）
        """
        if not isinstance(text, str):
            return "[ERROR] 入力は文字列でなければなりません"

        if not text.strip():
            return text

        # セッション設計: 現仕様では呼び出しごとに新規セッションを生成する（A案を採用）。
        # セッション内一貫性（同一エンティティ→同一マスクID）は1回の pg_mask_text 呼び出し内で保証。
        # 複数呼び出し間のセッション永続化は Phase 5 で pg_session_info 実装時に再設計する。
        session = MaskingSession()

        try:
            result = _engine.mask(text, session)
            masked_count = session.total_masked_count()
            logger.info(f"マスキング完了: {masked_count} 件のエンティティを検知")
            return result

        except MaskingError as e:
            # フェイルクローズ: エラーメッセージのみ返す（元テキスト漏洩禁止）
            logger.error(f"マスキングエラー（フェイルクローズ）: {e}")
            return f"[MASKING_ERROR] データの安全なマスキングに失敗しました。データへのアクセスを遮断しました。"

        except Exception as e:
            # 予期しない例外も元テキストを返さない
            logger.error(f"予期しないエラー（フェイルクローズ）: {e}")
            return f"[MASKING_ERROR] 予期しないエラーが発生しました。データへのアクセスを遮断しました。"
