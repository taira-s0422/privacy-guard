"""マスキングパターン定義モジュール.

10カテゴリの検知パターン（正規表現）を定義する。
仕様書セクション9.2準拠。

【設計方針】
- 正規表現は誤検知を最小化するため、文脈依存パターンを優先する
- 日本語個人名は辞書マッチング（dictionary.py）が主体。正規表現は補助のみ
- 住所パターンは都道府県名を正確に `(?:A|B)` 形式で OR 接続する
  （文字クラス [...] 内の | はリテラルの縦棒であり OR 演算子ではない）
- COMPANY_NAME パターンは `\\s` を文字クラスに含めない（Phase 5修正）
  理由: `[一-龯ぁ-んァ-ヶa-zA-Z0-9\\s]` の \\s が「今日は 株式会社」のような
  一般文章中の空白を越えて誤検知を引き起こす。ひらがな・スペースを除外することで
  助詞（の・を・に・は・が・も 等）での誤検知を防ぐ。
  英語社名パターンも同様に `\\s` を除外（Phase 5最終修正）：
  `[a-zA-Z\\s]` → `[a-zA-Z]` とすることで「The quick brown Corp」等の英文センテンスへの
  誤検知を防止する。
"""

import re
from dataclasses import dataclass
from enum import Enum
from typing import List, Pattern


class MaskingCategory(str, Enum):
    """マスキングカテゴリ定義."""

    NAME_JA = "MASKED_NAME"
    NAME_EN = "MASKED_NAME_EN"
    EMAIL = "MASKED_EMAIL"
    PHONE_JP = "MASKED_PHONE"
    ADDRESS_JP = "MASKED_ADDRESS"
    MY_NUMBER = "MASKED_MY_NUMBER"
    API_KEY = "MASKED_API_KEY"
    PASSWORD = "MASKED_PASSWORD"
    CREDIT_CARD = "MASKED_CC"
    COMPANY_NAME = "MASKED_COMPANY"


@dataclass
class CompiledPattern:
    """コンパイル済みパターン."""

    category: MaskingCategory
    pattern: Pattern[str]
    description: str
    priority: int = 50  # 数値が小さいほど優先度高


class MaskingPatterns:
    """10カテゴリのマスキングパターン集.

    仕様書セクション9.2の正規表現パターンを管理する。
    compile_all() でパターンをコンパイルして返す。
    """

    # ========================================
    # 各カテゴリの正規表現パターン定義
    # ========================================

    # 1. 日本語個人名（辞書補助前の補完正規表現）
    # 主体は dictionary.py の辞書マッチ。正規表現は「空白区切りの漢字2語」のみに絞る
    # 単独漢字パターン（[一-龯]{2,5}）は誤検知が多いため使用しない
    NAME_JA_PATTERNS: List[str] = [
        # 「田中 太郎」など空白区切りの漢字2語
        r"[一-龯]{1,4}[\s\u3000][一-龯]{1,4}",
    ]

    # 2. 英語個人名
    # First Last 形式（大文字始まり2語以上）
    NAME_EN_PATTERNS: List[str] = [
        # 同一行内の半角スペース・タブ区切り（改行は許容しない＝行跨ぎ誤検知防止）
        r"\b[A-Z][a-z]{1,20}[ \t]+[A-Z][a-z]{1,20}(?:[ \t]+[A-Z][a-z]{1,20})?\b",
    ]

    # 3. メールアドレス
    # RFC 5321準拠（簡略版）
    EMAIL_PATTERNS: List[str] = [
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    ]

    # 4. 電話番号（日本）
    # 携帯: 090/080/070、固定: 03-xxxx-xxxx等、国際: +81
    PHONE_JP_PATTERNS: List[str] = [
        # 携帯電話（ハイフンあり）: 090-1234-5678, 080-1234-5678
        r"0[789]0[-\u2010\u2011\u2012\u2013\u2014\uff0d]?\d{4}[-\u2010\u2011\u2012\u2013\u2014\uff0d]?\d{4}",
        # 携帯電話（ハイフンなし）: 09012345678
        r"0[789]0\d{8}",
        # 固定電話（市外局番2-4桁）: 03-1234-5678, 0120-123-456
        r"0\d{1,4}[-\u2010\u2011\u2012\u2013\u2014\uff0d]\d{1,4}[-\u2010\u2011\u2012\u2013\u2014\uff0d]\d{3,4}",
        # 国際形式: +81-90-1234-5678
        r"\+81[-\s]?\d{1,4}[-\s]?\d{3,4}[-\s]?\d{3,4}",
    ]

    # 5. 住所（日本）
    # 都道府県・市区町村・番地
    # 注意: 都道府県名は (?:A|B|C) 形式を使用。[A|B|C] はリテラルの縦棒を含む文字クラスになるため誤検知が多い
    ADDRESS_JP_PATTERNS: List[str] = [
        # 都道府県始まり（非キャプチャグループで OR 接続）
        (
            r"(?:北海道|青森県|岩手県|宮城県|秋田県|山形県|福島県|茨城県|栃木県|群馬県|"
            r"埼玉県|千葉県|東京都|神奈川県|新潟県|富山県|石川県|福井県|山梨県|長野県|"
            r"岐阜県|静岡県|愛知県|三重県|滋賀県|京都府|大阪府|兵庫県|奈良県|和歌山県|"
            r"鳥取県|島根県|岡山県|広島県|山口県|徳島県|香川県|愛媛県|高知県|"
            r"福岡県|佐賀県|長崎県|熊本県|大分県|宮崎県|鹿児島県|沖縄県)"
            r"[^\s、。\n]{5,50}"
        ),
        # 番地パターン: x丁目y番z号
        r"\d{1,3}丁目\d{1,3}番(?:\d{1,3}号)?",
        # 番地パターン: x-y-z 番地
        r"\d{1,3}[-－]\d{1,3}(?:[-－]\d{1,3})?番地?",
        # 郵便番号: 〒123-4567 または 1234567
        r"〒\d{3}[-\u2010]?\d{4}",
    ]

    # 6. マイナンバー（個人番号）
    # 【設計判断】純粋12桁パターン（\b\d{12}\b）は除外。
    # 理由: 電話番号連結・金額・日付連結等あらゆる12桁数字にマッチし誤検知率が極めて高い。
    # 本MCPサーバーの用途（Claude Codeへの安全入力提供）ではFalsePositiveのコストが高く、
    # 「マイナンバー/個人番号」という文脈が明示されている場合のみ検知する方針とする。
    MY_NUMBER_PATTERNS: List[str] = [
        # マイナンバーという文字列が近傍にある12桁数字
        r"(?:マイナンバー|個人番号)[\s:：]?\d{4}[-\s]?\d{4}[-\s]?\d{4}",
    ]

    # 7. APIキー・トークン（高エントロピー文字列）
    # キーワード + 値 パターン
    API_KEY_PATTERNS: List[str] = [
        # 一般的なAPIキー変数名パターン
        r"(?:api[_\-]?key|apikey|access[_\-]?token|secret[_\-]?key|bearer|authorization|auth[_\-]?token|private[_\-]?key|client[_\-]?secret)\s*[=:\"']\s*([a-zA-Z0-9_\-./+]{20,})",
        # Bearer トークン
        r"Bearer\s+([a-zA-Z0-9_\-./+]{20,})",
        # SK-/pk_/sk_ プレフィックス（OpenAI等）
        r"\b(?:sk-|pk-|rk_)[a-zA-Z0-9_\-]{20,}\b",
        # AWS形式: AKIA始まり
        r"\bAKIA[0-9A-Z]{16}\b",
        # GitHub Token: ghp_/gho_/ghs_
        r"\b(?:ghp|gho|ghs|ghr)_[a-zA-Z0-9]{36}\b",
    ]

    # 8. パスワード
    # password= / passwd= 等のパターン
    PASSWORD_PATTERNS: List[str] = [
        r"(?:password|passwd|pass|pwd)\s*[=:\"']\s*([^\s\"']{6,})",
        r"(?:パスワード|合言葉)\s*[=:：\"']\s*([^\s\"']{4,})",
    ]

    # 9. クレジットカード番号
    # 主要ブランド（Luhn検証はengine.pyで実施）
    CREDIT_CARD_PATTERNS: List[str] = [
        # Visa: 4xxx xxxx xxxx xxxx
        r"\b4[0-9]{3}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}\b",
        # Mastercard: 5[1-5]xx
        r"\b5[1-5][0-9]{2}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}\b",
        # AMEX: 3[47]xx xxxxxx xxxxx (15桁)
        r"\b3[47][0-9]{2}[\s\-]?[0-9]{6}[\s\-]?[0-9]{5}\b",
        # JCB: 35xx
        r"\b35[0-9]{2}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}[\s\-]?[0-9]{4}\b",
    ]

    # 10. 企業名（法人形態キーワードが含まれるもの）
    # 【Phase 5修正】\\s を文字クラスから除外
    # 修正前: [一-龯ぁ-んァ-ヶa-zA-Z0-9\\s] → 助詞（の・は・が等ひらがな）や空白を含む誤検知が多発
    # 修正後: ひらがな（ぁ-ん）とスペース（\\s）を文字クラスから除外
    #   - 前置きパターン: 法人形態 + 漢字/カタカナ/英数字（スペース・ひらがな不可）
    #   - 後置きパターン: 漢字/カタカナ/英数字（スペース・ひらがな不可） + 法人形態
    # 効果: 「今日は株式会社の話」「なんとか 株式会社もある」等の誤検知を防止
    # 【Phase 5最終修正】英語社名パターンの \\s も除外
    #   - 修正前: [a-zA-Z\\s]{2,30} → 「The quick brown Corp」等の英文センテンスが企業名としてマッチ
    #   - 修正後: [a-zA-Z]{2,30} → スペースなしの英語社名のみ対象
    COMPANY_NAME_PATTERNS: List[str] = [
        # 前置き: 法人形態 + 漢字/カタカナ/英数字（ひらがな・スペースなし）
        r"(?:株式会社|有限会社|合同会社|合名会社|合資会社|一般社団法人|公益社団法人|一般財団法人|公益財団法人|特定非営利活動法人|独立行政法人|国立大学法人)[一-龯ァ-ヶa-zA-Z0-9]{2,15}",
        # 後置き: 漢字/カタカナ/英数字（ひらがな・スペースなし） + 法人形態
        r"[一-龯ァ-ヶa-zA-Z0-9]{2,20}(?:株式会社|有限会社|合同会社|Co\.,?\s*Ltd\.?|Inc\.?|Corp\.?|LLC\.?)",
        # 英語社名（Inc./Corp./LLC後置）: \\s を除去し英字のみ対象（スペース跨ぎ誤検知防止）
        r"\b[A-Z][a-zA-Z]{2,30}(?:Inc|Corp|LLC|Ltd|Co)\b\.?",
    ]

    @classmethod
    def compile_all(cls) -> List[CompiledPattern]:
        """全カテゴリのパターンをコンパイルして返す.

        Returns:
            優先度順にソートされたCompiledPatternリスト
        """
        compiled: List[CompiledPattern] = []

        pattern_map = [
            # (category, patterns, description, priority)
            (MaskingCategory.EMAIL, cls.EMAIL_PATTERNS, "メールアドレス", 20),
            (MaskingCategory.PHONE_JP, cls.PHONE_JP_PATTERNS, "電話番号（日本）", 30),
            (MaskingCategory.MY_NUMBER, cls.MY_NUMBER_PATTERNS, "マイナンバー", 15),
            (MaskingCategory.API_KEY, cls.API_KEY_PATTERNS, "APIキー・トークン", 10),
            (MaskingCategory.PASSWORD, cls.PASSWORD_PATTERNS, "パスワード", 12),
            (MaskingCategory.CREDIT_CARD, cls.CREDIT_CARD_PATTERNS, "クレジットカード番号", 18),
            (MaskingCategory.ADDRESS_JP, cls.ADDRESS_JP_PATTERNS, "住所（日本）", 40),
            (MaskingCategory.COMPANY_NAME, cls.COMPANY_NAME_PATTERNS, "企業名", 80),
            (MaskingCategory.NAME_EN, cls.NAME_EN_PATTERNS, "英語個人名", 70),
            (MaskingCategory.NAME_JA, cls.NAME_JA_PATTERNS, "日本語個人名", 90),
        ]

        # カテゴリ別の正規表現フラグ.
        # NAME_EN は大文字始まりを厳密に判定する必要があるため IGNORECASE を外す。
        # 他カテゴリ（API_KEY, PASSWORD, EMAIL等）は大文字小文字非依存で従来通り IGNORECASE を有効化。
        category_flags = {
            MaskingCategory.NAME_EN: re.UNICODE,
        }
        default_flags = re.IGNORECASE | re.UNICODE

        for category, patterns, description, priority in pattern_map:
            flags = category_flags.get(category, default_flags)
            for pat_str in patterns:
                try:
                    compiled_pat = re.compile(pat_str, flags)
                    compiled.append(
                        CompiledPattern(
                            category=category,
                            pattern=compiled_pat,
                            description=description,
                            priority=priority,
                        )
                    )
                except re.error as e:
                    raise ValueError(f"パターンコンパイルエラー [{category}]: {e}") from e

        # 優先度順にソート（低い値=高優先度）
        compiled.sort(key=lambda x: x.priority)
        return compiled


def validate_pattern(pattern_str: str) -> bool:
    """正規表現パターンの妥当性を検証する.

    Args:
        pattern_str: 検証する正規表現文字列

    Returns:
        コンパイル成功なら True
    """
    try:
        re.compile(pattern_str)
        return True
    except re.error:
        return False
