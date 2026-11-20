"""マスキングエンジン本体.

全10カテゴリの検知・マスキングを実装する。
フェイルクローズ原則を厳守: 異常時は MaskingError を raise し、
元テキストを絶対に返さない。
"""

import re
import logging
from typing import List, Optional, Tuple

from .patterns import CompiledPattern, MaskingCategory, MaskingPatterns
from .session import MaskingSession
from .dictionary import DictionaryMatcher
from .entropy import calculate_entropy

logger = logging.getLogger(__name__)


class MaskingError(Exception):
    """マスキング処理エラー.

    フェイルクローズ原則により、このエラーが発生した場合は
    呼び出し元でデータを遮断しなければならない。
    """

    pass


class MaskingEngine:
    """マスキングエンジン.

    全10カテゴリのマスキングを実装する。
    フェイルクローズ: マスキング処理で例外が発生した場合は
    MaskingError を raise し、元テキストを返さない。

    設計原則:
    - 入力テキストは読み取り専用（上書き禁止）
    - マスキングマップは session オブジェクトで管理（揮発メモリ）
    - エラー時は必ず raise（素通し禁止）
    """

    # APIキー検知のエントロピー閾値
    ENTROPY_THRESHOLD = 4.5

    def __init__(self, fail_close: bool = True) -> None:
        """エンジンを初期化する.

        Args:
            fail_close: Trueの場合、マスキングエラー時にデータを遮断する（本番必須）
                        Falseはデバッグ専用。本番環境での使用禁止。
        """
        self._fail_close = fail_close
        self._patterns: List[CompiledPattern] = MaskingPatterns.compile_all()
        self._dictionary = DictionaryMatcher()

        if not fail_close:
            logger.warning(
                "fail_close=False はデバッグ専用です。本番環境での使用は禁止されています。"
            )

    def mask(self, text: str, session: MaskingSession) -> str:
        """テキストをマスキングする.

        元テキストは変更せず、マスキング済みの新しい文字列を返す。

        Args:
            text: マスキング対象テキスト（読み取り専用）
            session: マスキングセッション（ID一貫性管理）

        Returns:
            マスキング済みテキスト

        Raises:
            MaskingError: マスキング処理に失敗した場合（フェイルクローズ）
            TypeError: textがstr型でない場合
        """
        if not isinstance(text, str):
            raise MaskingError(
                f"マスキング対象は str 型でなければなりません。受け取った型: {type(text).__name__}"
            )

        if not text:
            return text

        try:
            masked = self._apply_masking(text, session)
            return masked
        except MaskingError:
            # MaskingError はそのまま再 raise（フェイルクローズ）
            raise
        except Exception as e:
            # 予期しない例外も MaskingError に変換してフェイルクローズ
            logger.error(f"マスキング中に予期しないエラーが発生しました: {e}")
            if self._fail_close:
                raise MaskingError(
                    f"マスキング処理に失敗しました。データを遮断します。原因: {e}"
                ) from e
            else:
                # デバッグモードのみ: エラーを記録して元テキストを返す（本番禁止）
                logger.debug("デバッグモード: マスキング失敗、元テキストを返します（本番禁止）")
                raise MaskingError(f"デバッグモードでもマスキング失敗: {e}") from e

    def _apply_masking(self, text: str, session: MaskingSession) -> str:
        """マスキングを適用する内部メソッド.

        各カテゴリを優先度順に処理し、検知された箇所をマスクIDで置換する。
        既にマスク済みの箇所（[MASKED_*]）は再処理しない。

        Args:
            text: マスキング対象テキスト
            session: マスキングセッション

        Returns:
            マスキング済みテキスト

        Raises:
            MaskingError: 処理失敗時
        """
        # マスキング済み箇所を追跡するために span リストを管理
        # (start, end, mask_id) のリスト
        masked_spans: List[Tuple[int, int, str]] = []

        # ステップ1: 辞書マッチング（日本語人名・企業名）
        self._apply_dictionary_masking(text, session, masked_spans)

        # ステップ2: 正規表現マスキング（優先度順）
        self._apply_regex_masking(text, session, masked_spans)

        # ステップ3: 重複スパンを解決して置換
        # 注意: masked_spans は優先度昇順（低値=高優先）に積まれる。
        # _build_masked_text の貪欲スパン選択は「先勝ち」方式であり、
        # これは「高優先カテゴリが勝つ」と等価。
        # 同一優先度内の処理順はパターン記述順（pattern_map の順序）に依存する。
        # パターン追加時はこの前提を維持すること。
        result = self._build_masked_text(text, masked_spans)
        return result

    def _apply_dictionary_masking(
        self,
        text: str,
        session: MaskingSession,
        masked_spans: List[Tuple[int, int, str]],
    ) -> None:
        """辞書マッチングによるマスキングを適用する.

        日本語人名・企業名を辞書から検知し masked_spans に追加する。

        Args:
            text: 対象テキスト
            session: マスキングセッション
            masked_spans: スパンリスト（追記される）
        """
        try:
            matches = self._dictionary.find_names(text)
            for match_text, start, end in matches:
                if not self._is_already_masked(start, end, masked_spans):
                    mask_id = session.get_or_create_mask_id(
                        MaskingCategory.NAME_JA.value, match_text
                    )
                    masked_spans.append((start, end, mask_id))
                    logger.debug(f"辞書マッチ: span=({start},{end}) → {mask_id}")
        except Exception as e:
            logger.warning(f"辞書マッチング中にエラー: {e}")
            # 辞書マッチングのエラーはフェイルクローズ対象（マスキング漏れを防ぐ）
            raise MaskingError(f"辞書マッチングに失敗しました: {e}") from e

    def _apply_regex_masking(
        self,
        text: str,
        session: MaskingSession,
        masked_spans: List[Tuple[int, int, str]],
    ) -> None:
        """正規表現マスキングを適用する.

        全パターンを優先度順に処理し masked_spans に追加する。

        Args:
            text: 対象テキスト
            session: マスキングセッション
            masked_spans: スパンリスト（追記される）
        """
        for compiled_pattern in self._patterns:
            try:
                for match in compiled_pattern.pattern.finditer(text):
                    start, end = match.start(), match.end()
                    matched_text = match.group(0)

                    # すでにマスク済みのスパンとの重複チェック
                    if self._is_already_masked(start, end, masked_spans):
                        continue

                    # APIキーの場合はエントロピー追加検証
                    # ただし固有プレフィックス（AKIA/sk-/pk-/rk_/ghp_/gho_/ghs_/ghr_）は
                    # それ自体が高い識別力を持つため、エントロピーチェックを免除する。
                    # （AKIAキーは英大文字+数字のみで構成されエントロピーが理論上低くなりがち）
                    if compiled_pattern.category == MaskingCategory.API_KEY:
                        # グループがある場合はグループ1を使用（キー値部分）
                        key_value = match.group(1) if match.lastindex and match.lastindex >= 1 else matched_text
                        prefixed = (
                            matched_text.startswith("AKIA")
                            or matched_text.startswith(("sk-", "pk-", "rk_"))
                            or matched_text.startswith(("ghp_", "gho_", "ghs_", "ghr_"))
                        )
                        if not prefixed:
                            entropy = calculate_entropy(key_value)
                            if entropy < self.ENTROPY_THRESHOLD:
                                logger.debug(
                                    f"APIキー候補をスキップ（低エントロピー {entropy:.2f}）: {len(key_value)} 文字"
                                )
                                continue

                    # NAME_JA / NAME_EN カテゴリは列ヘッダ・システム単語等の除外語と一致したらスキップ
                    # （例: Excelのタブ区切りで「電話番号\t住所」のような連結が
                    # 「漢字+空白+漢字」の正規表現にマッチしてしまう問題への対処、
                    #  および「localhost」「ssh」等のシステム単語が英人名と誤検知されるのを防ぐ）
                    if compiled_pattern.category in (
                        MaskingCategory.NAME_JA,
                        MaskingCategory.NAME_EN,
                    ):
                        if self._dictionary.is_name_excluded(matched_text):
                            logger.debug(
                                f"{compiled_pattern.category.value}候補をスキップ（除外語ヒット）: span=({start},{end})"
                            )
                            continue

                    # 注意: PASSWORD カテゴリは match.group(0) 全体（"password=XXX" のキーワード込み）が
                    # マスク対象になる。APIキーと異なりキーワード部分も含めてマスクする設計。
                    # 理由: パスワードは「password=」という文字列自体も情報開示リスクになるため。
                    # Phase 5 でカテゴリ別のマスク範囲（group 指定）を統一化する場合は再設計する。

                    mask_id = session.get_or_create_mask_id(
                        compiled_pattern.category.value, matched_text
                    )
                    masked_spans.append((start, end, mask_id))
                    logger.debug(
                        f"正規表現マッチ [{compiled_pattern.category.value}]: "
                        f"span=({start},{end}) → {mask_id}"
                    )

            except Exception as e:
                logger.error(
                    f"パターン適用エラー [{compiled_pattern.category.value}]: {e}"
                )
                raise MaskingError(
                    f"正規表現マスキングに失敗しました [{compiled_pattern.category.value}]: {e}"
                ) from e

    def _is_already_masked(
        self,
        start: int,
        end: int,
        masked_spans: List[Tuple[int, int, str]],
    ) -> bool:
        """指定スパンがすでにマスク済みスパンと重複しているか確認する.

        Args:
            start: チェックするスパンの開始位置
            end: チェックするスパンの終了位置
            masked_spans: 既存のマスク済みスパンリスト

        Returns:
            重複している場合 True
        """
        for m_start, m_end, _ in masked_spans:
            # 部分重複・内包・一致を全てチェック
            if not (end <= m_start or start >= m_end):
                return True
        return False

    def _build_masked_text(
        self,
        original: str,
        masked_spans: List[Tuple[int, int, str]],
    ) -> str:
        """マスク済みスパンを元にテキストを再構築する.

        重複スパンを排除し、開始位置順にソートして置換する。

        Args:
            original: 元テキスト（読み取り専用）
            masked_spans: マスク済みスパンのリスト (start, end, mask_id)

        Returns:
            マスキング済みテキスト
        """
        if not masked_spans:
            return original

        # 開始位置でソート（重複は長い方を優先）
        sorted_spans = sorted(masked_spans, key=lambda x: (x[0], -(x[1] - x[0])))

        # 重複スパンを除去（貪欲法: 早い開始位置・長いスパンを優先）
        non_overlapping: List[Tuple[int, int, str]] = []
        last_end = 0
        for start, end, mask_id in sorted_spans:
            if start >= last_end:
                non_overlapping.append((start, end, mask_id))
                last_end = end

        # テキストを再構築
        result_parts = []
        cursor = 0
        for start, end, mask_id in non_overlapping:
            result_parts.append(original[cursor:start])
            result_parts.append(mask_id)
            cursor = end
        result_parts.append(original[cursor:])

        return "".join(result_parts)
