"""マスキングセッション管理モジュール.

セッション内のマスキングマップを管理し、同一エンティティに同一マスクIDを付与する。
マスキングマップはインスタンス変数（揮発メモリ）のみで管理し、
ディスクへの書き出しは絶対に行わない。
"""

import hashlib
import uuid
from typing import Dict, Tuple


class MaskingSession:
    """マスキングセッション.

    セッション内でのマスキングIDの一貫性を保証する。
    同じカテゴリ・同じ値には常に同じマスクIDを返す。

    セキュリティ要件:
    - マスキングマップはインスタンス変数のみ（揮発メモリ）
    - ディスク書き出しメソッドは提供しない
    - SHA-256ハッシュで元データを保持しない
    """

    def __init__(self) -> None:
        """セッションを初期化する."""
        # key: (entity_type, sha256_hash) -> mask_id
        self._masking_map: Dict[Tuple[str, str], str] = {}
        # カテゴリごとのカウンタ
        self._counters: Dict[str, int] = {}
        # セッションID（MCP レスポンスの session_id フィールド用）
        self.session_id: str = str(uuid.uuid4())

    def get_or_create_mask_id(self, entity_type: str, raw_value: str) -> str:
        """マスクIDを取得または生成する.

        同一カテゴリ・同一値には同一マスクIDを返す（セッション内一貫性）。
        元データはSHA-256ハッシュに変換してキーとして保持する。

        Args:
            entity_type: エンティティカテゴリ（例: "MASKED_NAME", "MASKED_PHONE"）
            raw_value: マスク対象の元テキスト

        Returns:
            マスクID文字列（例: "[MASKED_NAME_001]"）

        Raises:
            ValueError: entity_typeまたはraw_valueが空の場合
        """
        if not entity_type:
            raise ValueError("entity_type は空にできません")
        if not raw_value:
            raise ValueError("raw_value は空にできません")

        # 元データをSHA-256ハッシュ化（元テキストを保持しない）
        sha256_hash = hashlib.sha256(raw_value.encode("utf-8")).hexdigest()
        map_key = (entity_type, sha256_hash)

        if map_key not in self._masking_map:
            # 新しいエンティティ: カウンタをインクリメントしてIDを生成
            current_count = self._counters.get(entity_type, 0) + 1
            self._counters[entity_type] = current_count
            mask_id = f"[{entity_type}_{current_count:03d}]"
            self._masking_map[map_key] = mask_id

        return self._masking_map[map_key]

    def get_entity_count(self, entity_type: str) -> int:
        """カテゴリごとのマスク済みエンティティ数を返す.

        Args:
            entity_type: エンティティカテゴリ

        Returns:
            マスク済みエンティティ数
        """
        return self._counters.get(entity_type, 0)

    def total_masked_count(self) -> int:
        """セッション内の総マスク数を返す."""
        return len(self._masking_map)

    def category_counts(self) -> Dict[str, int]:
        """カテゴリ別マスク数を返す.

        Returns:
            {カテゴリ名: 件数} の辞書
        """
        return dict(self._counters)

    # ========================================
    # 禁止操作: ディスク書き出しメソッドは提供しない
    # ========================================
    # to_file(), save(), export(), serialize() 等は意図的に未実装
    # セッション終了時にインスタンスが破棄されることでデータが揮発する
