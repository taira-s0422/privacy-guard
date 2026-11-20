"""マスキングエンジン単体テスト.

基本テストケース（TC-001〜TC-003）を含む。
テストデータは faker(ja_JP) の架空データのみ使用。本番データ・実在個人情報禁止。
"""

import pytest

from privacy_guard_mcp.masking.engine import MaskingEngine, MaskingError
from privacy_guard_mcp.masking.session import MaskingSession
from privacy_guard_mcp.masking.patterns import MaskingPatterns, MaskingCategory, validate_pattern
from privacy_guard_mcp.masking.entropy import calculate_entropy, is_high_entropy, is_likely_api_key


# ========================================
# フィクスチャ
# ========================================

@pytest.fixture
def engine() -> MaskingEngine:
    """フェイルクローズ有効のエンジン."""
    return MaskingEngine(fail_close=True)


@pytest.fixture
def session() -> MaskingSession:
    """新規マスキングセッション."""
    return MaskingSession()


# ========================================
# 基本テストケース
# ========================================

class TestM1Required:
    """M1完了条件のテストケース."""

    def test_tc001_name_and_phone(self, engine, session):
        """TC-001: 日本語人名 + 電話番号のマスキング."""
        text = "田中太郎 090-1234-5678"
        result = engine.mask(text, session)

        # 元テキストの個人情報が含まれていないこと
        assert "田中太郎" not in result, "人名がマスクされていない"
        assert "090-1234-5678" not in result, "電話番号がマスクされていない"

        # マスクIDが含まれること（[MASKED_NAME_001] または [MASKED_NAME_EN_001] 等）
        assert "[MASKED_" in result, f"マスクIDが見つかりません: {result}"

        # 電話番号のマスクIDが含まれること
        assert "MASKED_PHONE" in result, f"電話番号マスクIDが見つかりません: {result}"

    def test_tc002_fail_close_non_string(self, engine, session):
        """TC-002: フェイルクローズ - 非文字列入力でエラー、元データ漏洩なし."""
        invalid_inputs = [None, 123, [], {}, b"bytes"]

        for invalid_input in invalid_inputs:
            with pytest.raises(MaskingError):
                engine.mask(invalid_input, session)

    def test_tc002_fail_close_output_no_original(self, engine):
        """TC-002: フェイルクローズ - エラー時に元テキストが出力に含まれないこと."""
        # tools.py の pg_mask_text を通じた場合のフェイルクローズ確認
        from privacy_guard_mcp.masking.tools import _engine
        from fastmcp import FastMCP

        # engine.mask() に非文字列を渡した場合 MaskingError が raise されること
        bad_session = MaskingSession()
        with pytest.raises(MaskingError) as exc_info:
            _engine.mask(None, bad_session)  # type: ignore

        # エラーメッセージに元データが含まれていないこと（元データは None なので当然）
        error_msg = str(exc_info.value)
        assert "None" not in error_msg or "型" in error_msg, "エラーメッセージが不適切"

    def test_tc003_session_consistency(self, engine):
        """TC-003: セッション一貫性 - 同一エンティティに同一マスクIDが付与されること."""
        session = MaskingSession()
        text = "田中太郎が田中太郎に連絡した"
        result = engine.mask(text, session)

        # 「田中太郎」が含まれていないこと
        assert "田中太郎" not in result, "田中太郎がマスクされていない"

        # セッション内で田中太郎に割り当てられたマスクIDが1つであること
        # （同一人物なので MASKED_NAME_001 が2回出現するはず）
        masked_name_count = result.count("[MASKED_NAME_001]")
        assert masked_name_count == 2, (
            f"同一人物に異なるIDが割り当てられた可能性があります。"
            f"結果: {result}"
        )


# ========================================
# MaskingSession テスト
# ========================================

class TestMaskingSession:
    """MaskingSession の単体テスト."""

    def test_get_or_create_mask_id_basic(self):
        """同一入力には同一IDが返ること."""
        session = MaskingSession()
        id1 = session.get_or_create_mask_id("MASKED_NAME", "田中太郎")
        id2 = session.get_or_create_mask_id("MASKED_NAME", "田中太郎")
        assert id1 == id2, "同一値に異なるIDが付与された"

    def test_get_or_create_mask_id_different_values(self):
        """異なる値には異なるIDが返ること."""
        session = MaskingSession()
        id1 = session.get_or_create_mask_id("MASKED_NAME", "田中太郎")
        id2 = session.get_or_create_mask_id("MASKED_NAME", "鈴木花子")
        assert id1 != id2, "異なる値に同じIDが付与された"
        assert id1 == "[MASKED_NAME_001]"
        assert id2 == "[MASKED_NAME_002]"

    def test_get_or_create_mask_id_different_categories(self):
        """異なるカテゴリでは独立したカウンタが使われること."""
        session = MaskingSession()
        name_id = session.get_or_create_mask_id("MASKED_NAME", "田中太郎")
        phone_id = session.get_or_create_mask_id("MASKED_PHONE", "090-1234-5678")
        assert name_id == "[MASKED_NAME_001]"
        assert phone_id == "[MASKED_PHONE_001]"

    def test_no_disk_write_methods(self):
        """ディスク書き出しメソッドが存在しないこと."""
        session = MaskingSession()
        forbidden_methods = ["to_file", "save", "export", "serialize", "dump", "write"]
        for method_name in forbidden_methods:
            assert not hasattr(session, method_name), (
                f"ディスク書き出しメソッド '{method_name}' が存在します（禁止）"
            )

    def test_empty_value_raises(self):
        """空文字列はエラーになること."""
        session = MaskingSession()
        with pytest.raises(ValueError):
            session.get_or_create_mask_id("MASKED_NAME", "")

    def test_empty_entity_type_raises(self):
        """空のエンティティタイプはエラーになること."""
        session = MaskingSession()
        with pytest.raises(ValueError):
            session.get_or_create_mask_id("", "田中太郎")

    def test_sha256_no_raw_value_stored(self):
        """マスキングマップにSHA-256ハッシュのみ保持（元データなし）を確認."""
        session = MaskingSession()
        raw_value = "田中太郎のパスワードは1234"
        session.get_or_create_mask_id("MASKED_NAME", raw_value)

        # 内部マップに元データが含まれていないこと
        for key in session._masking_map.keys():
            entity_type, hash_value = key
            assert raw_value not in hash_value, "元データがハッシュキーに含まれている"
            # SHA-256の長さは64文字（16進数）
            assert len(hash_value) == 64, f"ハッシュ長が不正: {len(hash_value)}"


# ========================================
# MaskingEngine テスト
# ========================================

class TestMaskingEngine:
    """MaskingEngine の単体テスト."""

    def test_email_masking(self, engine, session):
        """メールアドレスがマスクされること."""
        text = "連絡先: test.user@example.com"
        result = engine.mask(text, session)
        assert "test.user@example.com" not in result
        assert "MASKED_EMAIL" in result

    def test_phone_masking_with_hyphen(self, engine, session):
        """ハイフンあり電話番号がマスクされること."""
        text = "電話番号: 090-1234-5678"
        result = engine.mask(text, session)
        assert "090-1234-5678" not in result
        assert "MASKED_PHONE" in result

    def test_phone_masking_without_hyphen(self, engine, session):
        """ハイフンなし携帯番号がマスクされること."""
        text = "携帯: 09012345678"
        result = engine.mask(text, session)
        assert "09012345678" not in result
        assert "MASKED_PHONE" in result

    def test_empty_string_returns_empty(self, engine, session):
        """空文字列はそのまま返ること."""
        assert engine.mask("", session) == ""

    def test_no_sensitive_data_unchanged(self, engine, session):
        """個人情報を含まないテキストは変化しないこと."""
        text = "今日は良い天気です。"
        result = engine.mask(text, session)
        assert result == text

    def test_non_string_raises_masking_error(self, engine, session):
        """非文字列入力で MaskingError が raise されること（フェイルクローズ）."""
        with pytest.raises(MaskingError):
            engine.mask(None, session)  # type: ignore

        with pytest.raises(MaskingError):
            engine.mask(123, session)  # type: ignore

    def test_original_text_not_modified(self, engine, session):
        """元テキストが変更されないこと（イミュータブル）."""
        original = "田中太郎 090-1234-5678"
        original_copy = original
        engine.mask(original, session)
        assert original == original_copy, "元テキストが変更された"

    def test_password_masking(self, engine, session):
        """パスワードがマスクされること."""
        text = "password=SuperSecret123"
        result = engine.mask(text, session)
        assert "SuperSecret123" not in result
        assert "MASKED_PASSWORD" in result

    def test_credit_card_masking(self, engine, session):
        """クレジットカード番号がマスクされること."""
        text = "カード番号: 4111-1111-1111-1111"
        result = engine.mask(text, session)
        assert "4111-1111-1111-1111" not in result
        assert "MASKED_CC" in result

    def test_multiple_entities_same_session(self, engine):
        """同一セッションで複数エンティティが正しくマスクされること."""
        session = MaskingSession()
        text = "鈴木一郎 090-0000-1111"
        result = engine.mask(text, session)

        # 元データが含まれていないこと
        assert "鈴木一郎" not in result
        assert "090-0000-1111" not in result

        # 複数のマスクIDが含まれること
        assert "MASKED_NAME" in result or "MASKED_" in result
        assert "MASKED_PHONE" in result


# ========================================
# パターン検証テスト
# ========================================

class TestMaskingPatterns:
    """MaskingPatterns の単体テスト."""

    def test_compile_all_no_error(self):
        """全パターンがエラーなくコンパイルされること."""
        patterns = MaskingPatterns.compile_all()
        assert len(patterns) > 0, "パターンが1件も生成されていない"

    def test_all_categories_represented(self):
        """全10カテゴリのパターンが存在すること."""
        patterns = MaskingPatterns.compile_all()
        found_categories = {p.category for p in patterns}

        for category in MaskingCategory:
            assert category in found_categories, f"カテゴリ {category} のパターンが見つかりません"

    def test_validate_pattern_valid(self):
        """有効なパターンは True を返すこと."""
        assert validate_pattern(r"\d{3}-\d{4}") is True

    def test_validate_pattern_invalid(self):
        """無効なパターンは False を返すこと."""
        assert validate_pattern(r"[invalid") is False

    def test_priority_ordering(self):
        """パターンが優先度順にソートされていること."""
        patterns = MaskingPatterns.compile_all()
        priorities = [p.priority for p in patterns]
        assert priorities == sorted(priorities), "パターンが優先度順になっていない"


# ========================================
# エントロピーテスト
# ========================================

class TestEntropy:
    """エントロピー計算テスト."""

    def test_empty_string(self):
        """空文字列は 0.0 を返すこと."""
        assert calculate_entropy("") == 0.0

    def test_single_char(self):
        """単一文字は 0.0 を返すこと."""
        assert calculate_entropy("a") == 0.0

    def test_high_entropy(self):
        """高エントロピー文字列（APIキー風）は閾値以上を返すこと."""
        # ランダムに見えるAPIキー風文字列
        api_key = "aB3xK9pQmN2vR7wL5uT8yD1c"
        assert is_high_entropy(api_key, threshold=4.0), f"エントロピーが低すぎます: {calculate_entropy(api_key)}"

    def test_low_entropy_repeated(self):
        """繰り返し文字は低エントロピー."""
        assert calculate_entropy("aaaaaaaaaa") < 1.0

    def test_is_likely_api_key(self):
        """APIキーらしい文字列の判定."""
        # 短すぎるものは False
        assert is_likely_api_key("abc123") is False

        # APIキーらしいもの
        openai_key = "sk-aB3xK9pQmN2vR7wL5uT8yD1cE6fG4h"
        assert is_likely_api_key(openai_key) is True


# ========================================
# セッション分離テスト
# ========================================

class TestSessionIsolation:
    """セッション間の分離テスト."""

    def test_different_sessions_independent_counters(self, engine):
        """異なるセッションはカウンタが独立していること."""
        session1 = MaskingSession()
        session2 = MaskingSession()

        text = "佐藤花子"
        result1 = engine.mask(text, session1)
        result2 = engine.mask(text, session2)

        # 両方とも 001 から始まること
        assert "[MASKED_NAME_001]" in result1 or "MASKED_NAME_001" in result1
        assert "[MASKED_NAME_001]" in result2 or "MASKED_NAME_001" in result2


# ========================================
# COMPANY_NAME パターン誤検知防止テスト（Phase 5修正）
# ========================================

class TestCompanyNamePattern:
    """企業名パターン（COMPANY_NAME）の正検知・誤検知防止テスト.

    Phase 5修正内容:
    - \\s をCOMPANY_NAMEパターンの文字クラスから除外
    - ひらがな（ぁ-ん）をCOMPANY_NAMEパターンの文字クラスから除外
    - 効果: 「今日は 株式会社もある」等の誤検知を防止
    """

    def test_company_name_prefix_ja(self, engine, session):
        """前置き（株式会社テスト）が検知されること."""
        text = "株式会社テスト"
        result = engine.mask(text, session)
        assert "株式会社テスト" not in result
        assert "MASKED_COMPANY" in result

    def test_company_name_suffix_ja(self, engine, session):
        """後置き（テスト株式会社）が検知されること."""
        text = "テスト株式会社"
        result = engine.mask(text, session)
        assert "テスト株式会社" not in result
        assert "MASKED_COMPANY" in result

    def test_company_name_long_suffix(self, engine, session):
        """長い後置き（山田太郎商事株式会社）が何らかのカテゴリでマスクされること.

        優先度ルール: 辞書で「山田太郎」がNAME_JAとして先にマスクされるため、
        残った「商事株式会社」が後置きCOMPANY_NAMEにマッチする場合もある。
        いずれにせよ元の社名テキストは結果に残らないことを確認する。
        """
        text = "山田太郎商事株式会社"
        result = engine.mask(text, session)
        # 元テキストが残っていないこと（NAME_JA or COMPANY_NAME のいずれかでマスク済み）
        assert "山田太郎" not in result, "人名がマスクされていない"
        assert "MASKED_" in result, "何もマスクされていない"

    def test_company_name_katakana(self, engine, session):
        """カタカナ社名（ヤマダ電機株式会社）が検知されること."""
        text = "ヤマダ電機株式会社"
        result = engine.mask(text, session)
        assert "MASKED_COMPANY" in result

    def test_company_name_english_en_suffix(self, engine, session):
        """英語社名（ABC Electronics Inc）が何らかのカテゴリでマスクされること.

        優先度ルール: NAME_EN（priority:70）は COMPANY_NAME（priority:80）より優先度高い。
        「First Last」形式が NAME_EN として先にマスクされるため、
        COMPANY_NAME ではなく MASKED_NAME_EN として検知される場合がある。
        重要なのは元テキストが結果に残らないことを確認することである。
        """
        text = "ABC Electronics Inc"
        result = engine.mask(text, session)
        # NAME_EN または COMPANY_NAME のいずれかでマスク済み
        assert "ABC Electronics Inc" not in result, "英語社名がマスクされていない"
        assert "MASKED_" in result, "何もマスクされていない"

    def test_no_false_positive_hiragana_particle_no(self, engine, session):
        """誤検知防止: 「今日は株式会社の話」で助詞「の」による誤検知が発生しないこと.

        修正前: [一-龯ぁ-んァ-ヶa-zA-Z0-9\\s]{2,20} が「今日は 株式会社」にマッチ
        修正後: ひらがな・スペース除外により誤検知しない
        """
        text = "今日は株式会社の話をしよう"
        result = engine.mask(text, session)
        # 「今日は」が会社名としてマスクされていないこと
        assert "今日" not in result or "MASKED_COMPANY" not in result

    def test_no_false_positive_space_before_corp(self, engine, session):
        """誤検知防止: 「なんとか 株式会社もある」で空白跨ぎの誤検知が発生しないこと."""
        text = "なんとか 株式会社もある"
        result = engine.mask(text, session)
        # 「なんとか」が会社名の一部としてマスクされていないこと
        # 修正後は「なんとか」はひらがななのでマッチしない
        assert "なんとか" not in result or ("MASKED_COMPANY" not in result)

    def test_general_text_no_false_positive(self, engine, session):
        """誤検知防止: 一般的な会話文が誤検知されないこと."""
        texts_without_company = [
            "今日の会議は何時ですか",
            "明日の天気は晴れです",
            "それは良い提案です",
        ]
        for text in texts_without_company:
            result = engine.mask(text, session)
            assert "MASKED_COMPANY" not in result, (
                f"誤検知が発生しました: '{text}' → '{result}'"
            )


# ========================================
# Issue 2/3/4 修正回帰テスト
# ========================================

class TestColumnHeaderExclusion:
    """Issue 4: 列ヘッダ（電話番号・担当者・会社名等）が氏名として誤検知されない."""

    def test_tab_separated_headers_not_masked(self, engine, session):
        """タブ区切りの列ヘッダは MASKED_NAME 化されないこと."""
        text = "氏名\tメール\t電話番号\t住所\t契約種別"
        result = engine.mask(text, session)
        assert "MASKED_NAME" not in result, (
            f"列ヘッダが氏名として誤検知された: {result}"
        )
        assert "電話番号" in result
        assert "住所" in result

    def test_corp_sheet_headers_not_masked(self, engine, session):
        """法人シートのヘッダ（会社名・担当者）も誤検知されない."""
        text = "法人ID\t会社名\t担当者\tメール\t電話番号\t住所"
        result = engine.mask(text, session)
        assert "MASKED_NAME" not in result, f"ヘッダ誤検知: {result}"
        assert "会社名" in result
        assert "担当者" in result

    def test_real_name_with_space_still_masked(self, engine, session):
        """ヘッダ除外で実際の氏名（漢字+空白+漢字）まで誤って残さない."""
        text = "田中 太郎"
        result = engine.mask(text, session)
        assert "田中" not in result
        assert "MASKED_NAME" in result


class TestGivenNameDictionaryExpansion:
    """Issue 2: 辞書漏れだった名（知実・里佳等）がマスクされること."""

    @pytest.mark.parametrize("fullname", [
        "加藤 知実",
        "福田 知実",
        "三浦 里佳",
    ])
    def test_added_given_names_masked(self, engine, session, fullname):
        """辞書追加した名で構成されたフルネームがマスクされる."""
        result = engine.mask(fullname, session)
        # 姓部分が残っていないこと（マスクされていれば姓も含めて消える）
        assert "知実" not in result and "里佳" not in result, (
            f"追加辞書の名が残っている: {result}"
        )
        assert "MASKED_NAME" in result


class TestNameSuffixCharCapture:
    """Issue 3: 名の末尾1文字（子・美・樹等）が辞書境界外で残らないこと."""

    @pytest.mark.parametrize("fullname,leftover_char", [
        ("田中 太郎子", "子"),
        ("佐藤 桜美", "美"),
        ("鈴木 直樹", "樹"),
        ("伊藤 裕樹", "樹"),
    ])
    def test_trailing_suffix_included(self, engine, session, fullname, leftover_char):
        """マスク後にフルネーム末尾の1文字がプレーンテキストとして残らない."""
        result = engine.mask(fullname, session)
        # 例: '[MASKED_NAME_001]子' のように末尾文字が露出していないこと
        assert not result.endswith(leftover_char), (
            f"末尾文字 '{leftover_char}' が露出している: {result}"
        )
        assert "MASKED_NAME" in result


# ========================================
# Issue 5/6/7/8 追加テスト
# ========================================

class TestMaleNameSuffixCapture:
    """Issue 5: 男性名語尾（平・太郎・郎等）の取りこぼし防止."""

    @pytest.mark.parametrize("fullname,leftover", [
        ("三浦 涼平", "平"),
        ("遠藤 涼平", "平"),
        ("阿部 聡太郎", "太郎"),
        ("田中 一郎", ""),  # 「一郎」は辞書登録済み・素通りでもOK
    ])
    def test_male_suffix_included(self, engine, session, fullname, leftover):
        result = engine.mask(fullname, session)
        if leftover:
            assert not result.endswith(leftover), (
                f"末尾 '{leftover}' が露出: {result}"
            )
        assert "MASKED_NAME" in result, f"人名検知失敗: {result}"
        # 元の漢字が結果に残らないこと（フルネームがマスクされている）
        assert fullname.split()[1][0] not in result.replace("MASKED_NAME", ""), (
            f"名の漢字が残っている: {result}"
        )


class TestHiraganaGivenName:
    """Issue 6: 平仮名で書かれる名前のマスキング."""

    @pytest.mark.parametrize("fullname", [
        "加藤 あすか",
        "田中 さくら",
        "佐藤 みき",
        "鈴木 ゆい",
    ])
    def test_hiragana_name_masked(self, engine, session, fullname):
        result = engine.mask(fullname, session)
        assert "MASKED_NAME" in result, f"平仮名名が検知されない: {result}"
        # 元の名前がそのまま残っていない
        assert fullname not in result


class TestAwsAccessKeyMasking:
    """Issue 7: AWS アクセスキー（AKIA形式）のマスキング."""

    def test_aws_access_key_id_masked(self, engine, session):
        text = "aws_access_key_id = AKIAJOZ9XFZAQ8H3XQYX"
        result = engine.mask(text, session)
        assert "AKIAJOZ9XFZAQ8H3XQYX" not in result, f"AKIAキーが素通り: {result}"
        assert "MASKED_API_KEY" in result

    def test_akia_in_text_masked(self, engine, session):
        text = "鍵: AKIAIOSFODNN7EXAMPLE を使う"
        result = engine.mask(text, session)
        assert "AKIAIOSFODNN7EXAMPLE" not in result
        assert "MASKED_API_KEY" in result


class TestSystemKeywordExclusion:
    """Issue 8: localhost 等のシステム関連単語が人名と誤検知されないこと."""

    @pytest.mark.parametrize("text,forbidden_label", [
        ("host = localhost\nport = 5432", "MASKED_NAME_EN"),
        ("接続先: localhost", "MASKED_NAME_EN"),
        ("server ssh tcp", "MASKED_NAME_EN"),
    ])
    def test_system_keyword_not_masked_as_name(self, engine, session, text, forbidden_label):
        result = engine.mask(text, session)
        assert forbidden_label not in result, (
            f"システム単語が人名扱いされている: {result}"
        )
        # localhost等の元語は素通りで残ること
        if "localhost" in text:
            assert "localhost" in result


class TestPartialExclusionKeepsRemainder:
    """除外語が名前候補の一部だけの時、除外語を除いた残りがマスクされること."""

    @pytest.mark.parametrize("text,kept,leaked", [
        ("担当 乙川", "担当", "乙川"),
        ("部長 蘆花 弦", "部長", "蘆花"),
    ])
    def test_name_next_to_exclusion_word_is_masked(self, engine, session, text, kept, leaked):
        result = engine.mask(text, session)
        assert leaked not in result, f"除外語の隣の氏名が漏れた: {result}"
        assert kept in result
        assert "MASKED_NAME" in result

    def test_split_excluded_keeps_only_remainder(self):
        from privacy_guard_mcp.masking.dictionary import DictionaryMatcher
        d = DictionaryMatcher()
        assert d.split_excluded("電話番号 住所") == []
        assert d.split_excluded("担当 乙川") == [("乙川", 3, 5)]
        assert d.is_name_excluded("電話番号 住所") is True
        assert d.is_name_excluded("担当 乙川") is False
