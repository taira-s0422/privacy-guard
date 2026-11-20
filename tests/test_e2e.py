"""E2Eテスト - 全7ツールの正常系・異常系・フェイルクローズ検証.

仕様書セクション9.7準拠。
ダミーデータ（tests/test_data/dummy/）を使用して全7ツールを検証する。

テスト対象ツール:
    1. pg_mask_text      - テキストマスキング
    2. pg_read_file      - テキスト/CSV/Markdownファイル読み取り
    3. pg_read_excel     - Excelファイル読み取り
    4. pg_read_pdf       - PDFファイル読み取り
    5. pg_gws_read       - Google Workspace読み取り（コマンド不在時の安全動作確認）
    6. pg_check_rules    - マスキングルール確認
    7. pg_session_info   - セッション情報確認

E2Eテスト実行前にダミーデータを生成すること:
    python tests/generate_dummy_data.py

または Docker Compose で自動生成:
    docker compose -f docker-compose.test.yml run --rm e2e
"""

import os
import pytest
from pathlib import Path

from tests.generate_dummy_data import main as generate_dummy_data

# ダミーデータディレクトリ
DUMMY_DIR = Path(__file__).parent / "test_data" / "dummy"


@pytest.fixture(scope="module", autouse=True)
def ensure_dummy_data():
    """テスト前にダミーデータが存在することを確認する（なければ生成）."""
    if not DUMMY_DIR.exists() or not list(DUMMY_DIR.glob("dummy_*.csv")):
        print(f"\n[E2E] ダミーデータが見つかりません。生成します: {DUMMY_DIR}")
        generate_dummy_data(str(DUMMY_DIR))
    else:
        print(f"\n[E2E] 既存ダミーデータを使用: {DUMMY_DIR}")


# ============================================================
# ツール1: pg_mask_text E2E
# ============================================================

class TestE2EPgMaskText:
    """pg_mask_text E2Eテスト."""

    def test_normal_name_and_phone(self):
        """正常系: 人名・電話番号を含むテキストがマスクされること."""
        from privacy_guard_mcp.masking.engine import MaskingEngine
        from privacy_guard_mcp.masking.session import MaskingSession

        engine = MaskingEngine(fail_close=True)
        session = MaskingSession()

        text = "田中太郎 090-1234-5678 tanaka@example.com"
        result = engine.mask(text, session)

        assert "田中太郎" not in result, "人名がマスクされていない"
        assert "090-1234-5678" not in result, "電話番号がマスクされていない"
        assert "tanaka@example.com" not in result, "メールがマスクされていない"
        assert "MASKED_" in result, "マスクIDが付与されていない"

    def test_fail_close_non_string(self):
        """異常系: 非文字列入力でフェイルクローズ（MaskingError）が発生すること."""
        from privacy_guard_mcp.masking.engine import MaskingEngine, MaskingError
        from privacy_guard_mcp.masking.session import MaskingSession

        engine = MaskingEngine(fail_close=True)
        session = MaskingSession()

        for invalid in [None, 123, [], {}]:
            with pytest.raises(MaskingError):
                engine.mask(invalid, session)

    def test_original_text_immutable(self):
        """元データ不変: マスキング後も元テキストが変化しないこと."""
        from privacy_guard_mcp.masking.engine import MaskingEngine
        from privacy_guard_mcp.masking.session import MaskingSession

        engine = MaskingEngine(fail_close=True)
        original = "鈴木花子 03-1234-5678"
        original_id = id(original)
        engine.mask(original, MaskingSession())

        # 文字列オブジェクトは変更されていない
        assert original == "鈴木花子 03-1234-5678", "元テキストが変更された（イミュータブル違反）"

    def test_session_consistency(self):
        """セッション一貫性: 同一エンティティに同一マスクIDが付与されること."""
        from privacy_guard_mcp.masking.engine import MaskingEngine
        from privacy_guard_mcp.masking.session import MaskingSession

        engine = MaskingEngine(fail_close=True)
        session = MaskingSession()

        text = "山本誠が山本誠に連絡した"
        result = engine.mask(text, session)

        assert "山本誠" not in result
        # 同一人物なので同じマスクIDが使われているはず（_001 が2回出現）
        name_ids = [part for part in result.split() if "MASKED_NAME" in part]
        # マスクIDの登場回数確認（同じIDが複数回）
        if "[MASKED_NAME_001]" in result:
            assert result.count("[MASKED_NAME_001]") == 2, (
                f"セッション一貫性違反: {result}"
            )


# ============================================================
# ツール2: pg_read_file E2E
# ============================================================

class TestE2EPgReadFile:
    """pg_read_file E2Eテスト."""

    def test_normal_txt(self):
        """正常系: テキストファイルを読み取りマスキングすること."""
        from privacy_guard_mcp import server
        # server モジュールからツール関数を直接呼び出し
        result = server.pg_read_file(str(DUMMY_DIR / "dummy_email.txt"))

        assert result["status"] == "ok", f"ステータスが ok ではない: {result}"
        assert result["data"], "マスキング済みデータが空"
        # メールアドレスが残っていないこと（@ が含まれないかチェック）
        # ただし masking_summary に含まれる場合もあるため data のみ確認
        assert "@" not in result["data"] or "MASKED_EMAIL" in result["data"], (
            "メールアドレスがマスクされていない可能性"
        )

    def test_normal_csv(self):
        """正常系: CSVファイルを読み取りマスキングすること."""
        from privacy_guard_mcp import server

        result = server.pg_read_file(str(DUMMY_DIR / "dummy_employees.csv"))
        assert result["status"] == "ok", f"CSVステータスエラー: {result}"
        assert result["data"], "CSVデータが空"

    def test_fail_close_not_found(self):
        """フェイルクローズ: 存在しないファイルはエラーレスポンスを返すこと（元データ漏洩なし）."""
        from privacy_guard_mcp import server

        result = server.pg_read_file("/nonexistent/path/file.txt")
        assert result["status"] == "error", "存在しないファイルでエラーにならない"
        assert result["data"] == "", "エラー時にデータが返却されている（元データ漏洩リスク）"
        assert result["warnings"], "エラー時にwarningsが空"

    def test_masking_summary_populated(self):
        """正常系: マスキングサマリーが正しく返ること."""
        from privacy_guard_mcp import server

        result = server.pg_read_file(str(DUMMY_DIR / "dummy_email.txt"))
        assert "masking_summary" in result
        assert "total_entities" in result["masking_summary"]
        assert result["masking_summary"]["total_entities"] >= 0


# ============================================================
# ツール3: pg_read_excel E2E
# ============================================================

class TestE2EPgReadExcel:
    """pg_read_excel E2Eテスト."""

    def test_normal_xlsx(self):
        """正常系: Excelファイルを読み取りマスキングすること."""
        from privacy_guard_mcp import server

        xlsx_path = DUMMY_DIR / "dummy_clients.xlsx"
        if not xlsx_path.exists():
            pytest.skip("dummy_clients.xlsx が見つかりません")

        result = server.pg_read_excel(str(xlsx_path))
        assert result["status"] == "ok", f"Excelステータスエラー: {result}"
        assert result["data"], "Excelデータが空"
        assert "sheet_names" in result

    def test_fail_close_not_found(self):
        """フェイルクローズ: 存在しないExcelはエラーレスポンスを返すこと."""
        from privacy_guard_mcp import server

        result = server.pg_read_excel("/nonexistent/file.xlsx")
        assert result["status"] == "error"
        assert result["data"] == ""

    def test_fail_close_wrong_format(self):
        """フェイルクローズ: 拡張子不一致（txtをxlsxとして読む）はエラー."""
        from privacy_guard_mcp import server

        # txtファイルをexcelとして読ませる
        result = server.pg_read_excel(str(DUMMY_DIR / "dummy_email.txt"))
        assert result["status"] == "error", "不正ファイルでエラーにならない"


# ============================================================
# ツール4: pg_read_pdf E2E
# ============================================================

class TestE2EPgReadPdf:
    """pg_read_pdf E2Eテスト."""

    def test_normal_pdf(self):
        """正常系: PDFファイルを読み取ること（テキスト抽出可能な場合）."""
        from privacy_guard_mcp import server

        pdf_path = DUMMY_DIR / "dummy_mixed.pdf"
        if not pdf_path.exists():
            pytest.skip("dummy_mixed.pdf が見つかりません")

        result = server.pg_read_pdf(str(pdf_path))
        # スキャンPDF等でテキストが空の場合もあるが、エラーにはならないこと
        assert result["status"] in ("ok", "warning"), f"PDFステータス異常: {result}"
        assert result["data"] is not None, "PDFデータがNone"

    def test_fail_close_not_found(self):
        """フェイルクローズ: 存在しないPDFはエラーレスポンスを返すこと."""
        from privacy_guard_mcp import server

        result = server.pg_read_pdf("/nonexistent/file.pdf")
        assert result["status"] == "error"
        assert result["data"] == ""


# ============================================================
# ツール5: pg_gws_read E2E（コマンド不在時の安全動作確認）
# ============================================================

class TestE2EPgGwsRead:
    """pg_gws_read E2Eテスト.

    実際のGoogle Workspaceへの接続は行わない。
    コマンド（gws/gog）が存在しない場合・不正な resource_type の
    フェイルクローズ動作を確認する。
    """

    def test_fail_close_invalid_resource_type(self):
        """フェイルクローズ: 不正なresource_typeはエラーを返すこと."""
        from privacy_guard_mcp import server

        result = server.pg_gws_read(
            resource_type="invalid_type",
            resource_id="dummy_id",
        )
        assert result["status"] == "error"
        assert result["data"] == ""
        assert any("INVALID_RESOURCE_TYPE" in w for w in result["warnings"])

    def test_fail_close_command_not_found(self):
        """フェイルクローズ: gwsコマンドが見つからない場合はエラーを返すこと."""
        from privacy_guard_mcp import server
        import os

        # 環境変数でコマンドを存在しないパスに上書き
        original_gws = os.environ.get("PRIVACY_GUARD_GWS_COMMAND")
        original_gog = os.environ.get("PRIVACY_GUARD_GOG_COMMAND")
        try:
            os.environ["PRIVACY_GUARD_GWS_COMMAND"] = "/nonexistent/gws"
            os.environ["PRIVACY_GUARD_GOG_COMMAND"] = "/nonexistent/gog"

            # 新規GWSReaderを生成してテスト（環境変数を反映）
            from privacy_guard_mcp.readers.gws import GWSReader, GWSReaderError
            reader = GWSReader()
            with pytest.raises(GWSReaderError):
                reader.read_spreadsheet("dummy_id")
        finally:
            # 環境変数を元に戻す
            if original_gws is not None:
                os.environ["PRIVACY_GUARD_GWS_COMMAND"] = original_gws
            else:
                os.environ.pop("PRIVACY_GUARD_GWS_COMMAND", None)
            if original_gog is not None:
                os.environ["PRIVACY_GUARD_GOG_COMMAND"] = original_gog
            else:
                os.environ.pop("PRIVACY_GUARD_GOG_COMMAND", None)


# ============================================================
# ツール6: pg_check_rules E2E
# ============================================================

class TestE2EPgCheckRules:
    """pg_check_rules E2Eテスト."""

    def test_normal_returns_categories(self):
        """正常系: 全10カテゴリが返ること."""
        from privacy_guard_mcp import server

        result = server.pg_check_rules()
        assert result["status"] == "ok"
        assert "rules" in result

        categories = result["rules"]["categories"]
        expected_categories = [
            "MASKED_ADDRESS", "MASKED_API_KEY", "MASKED_CC",
            "MASKED_COMPANY", "MASKED_EMAIL", "MASKED_MY_NUMBER",
            "MASKED_NAME", "MASKED_NAME_EN", "MASKED_PHONE", "MASKED_PASSWORD",
        ]
        for cat in expected_categories:
            assert cat in categories, f"カテゴリ {cat} が見つからない"

    def test_fail_close_flag(self):
        """正常系: fail_close フラグが返ること."""
        from privacy_guard_mcp import server

        result = server.pg_check_rules()
        assert "fail_close" in result["rules"]
        assert result["rules"]["fail_close"] is True, "fail_close が True ではない"

    def test_pattern_count_reasonable(self):
        """正常系: パターン数が妥当な範囲（10件以上）であること."""
        from privacy_guard_mcp import server

        result = server.pg_check_rules()
        pattern_count = result["rules"]["pattern_count"]
        assert pattern_count >= 10, f"パターン数が少なすぎる: {pattern_count}"


# ============================================================
# ツール7: pg_session_info E2E
# ============================================================

class TestE2EPgSessionInfo:
    """pg_session_info E2Eテスト."""

    def test_normal_returns_design(self):
        """正常系: セッション設計（per-call）が返ること."""
        from privacy_guard_mcp import server

        result = server.pg_session_info()
        assert result["status"] == "ok"
        assert "session" in result
        assert result["session"]["design"] == "per-call", (
            f"セッション設計が per-call ではない: {result['session']['design']}"
        )

    def test_server_stats_returned(self):
        """正常系: サーバー稼働統計が返ること."""
        from privacy_guard_mcp import server

        result = server.pg_session_info()
        stats = result["session"]["server_stats"]

        assert "total_calls" in stats
        assert "total_masked_entities" in stats
        assert "errors" in stats
        assert "uptime_seconds" in stats

        assert stats["total_calls"] >= 0
        assert stats["errors"] >= 0
        assert stats["uptime_seconds"] >= 0


# ============================================================
# フェイルクローズ総合テスト
# ============================================================

class TestE2EFailClose:
    """フェイルクローズの総合検証."""

    def test_masking_error_never_returns_raw_data(self):
        """フェイルクローズ: エラー発生時に元データが絶対に返らないこと."""
        from privacy_guard_mcp import server

        # 不正ファイルパスを渡した場合
        result = server.pg_read_file("/dev/null/nonexistent")
        assert result["data"] == "", "エラー時に data が空ではない（元データ漏洩リスク）"

    def test_excel_fail_close_empty_data(self):
        """フェイルクローズ: Excel読み取り失敗時に data が空であること."""
        from privacy_guard_mcp import server

        result = server.pg_read_excel("/nonexistent/file.xlsx")
        assert result["data"] == "", "Excelエラー時に data が空ではない"

    def test_pdf_fail_close_empty_data(self):
        """フェイルクローズ: PDF読み取り失敗時に data が空であること."""
        from privacy_guard_mcp import server

        result = server.pg_read_pdf("/nonexistent/file.pdf")
        assert result["data"] == "", "PDFエラー時に data が空ではない"

    def test_no_disk_write_on_session(self):
        """設計確認: MaskingSession にディスク書き出しメソッドがないこと."""
        from privacy_guard_mcp.masking.session import MaskingSession

        session = MaskingSession()
        forbidden_methods = ["to_file", "save", "export", "serialize", "dump", "write"]
        for method_name in forbidden_methods:
            assert not hasattr(session, method_name), (
                f"禁止メソッド '{method_name}' が存在する（設計原則違反）"
            )
