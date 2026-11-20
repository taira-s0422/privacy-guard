"""readers モジュール単体テスト + ツール統合テスト.

テストデータは架空データのみ使用。本番データ・実在個人情報禁止。

テストカテゴリ:
- TestEncodingDetect: エンコーディング自動判別
- TestLocalFileReader: ローカルファイル読み取り（正常系・異常系）
- TestLocalFileReaderFailClose: フェイルクローズ動作
- TestMaskingSession: session_id・category_counts 追加機能
- TestServerTools: サーバーツール統合テスト（pg_read_file, pg_check_rules, pg_session_info）
- TestGWSReader: GWSReader 初期化・コマンド不在時の挙動
"""

import os
import pytest
from pathlib import Path

# テストデータディレクトリ
TEST_DATA_DIR = Path(__file__).parent / "test_data"
SAMPLE_TXT = str(TEST_DATA_DIR / "sample.txt")
SAMPLE_CSV = str(TEST_DATA_DIR / "sample.csv")


# ============================================================
# TestEncodingDetect
# ============================================================

class TestEncodingDetect:
    """エンコーディング自動判別のテスト."""

    def test_detect_utf8(self):
        """UTF-8 テキストを正しく判別する."""
        from privacy_guard_mcp.readers.encoding_detect import detect_encoding
        raw = "こんにちは世界".encode("utf-8")
        enc = detect_encoding(raw)
        assert enc.lower().replace("-", "").replace("_", "") in ("utf8", "utf8sig")

    def test_detect_empty_returns_utf8(self):
        """空バイト列はデフォルト utf-8 を返す."""
        from privacy_guard_mcp.readers.encoding_detect import detect_encoding
        assert detect_encoding(b"") == "utf-8"

    def test_decode_bytes_utf8(self):
        """UTF-8バイト列を正しくデコードする."""
        from privacy_guard_mcp.readers.encoding_detect import decode_bytes
        raw = "テストデータ".encode("utf-8")
        result = decode_bytes(raw, encoding="utf-8")
        assert "テストデータ" in result

    def test_decode_bytes_auto_detect(self):
        """エンコーディング未指定時は自動判別でデコードする."""
        from privacy_guard_mcp.readers.encoding_detect import decode_bytes
        raw = "Hello World".encode("ascii")
        result = decode_bytes(raw)
        assert "Hello World" in result

    def test_decode_bytes_empty(self):
        """空バイト列は空文字列を返す."""
        from privacy_guard_mcp.readers.encoding_detect import decode_bytes
        assert decode_bytes(b"") == ""


# ============================================================
# TestLocalFileReader - 正常系
# ============================================================

class TestLocalFileReader:
    """LocalFileReader の正常系テスト."""

    def test_read_text_file(self):
        """テキストファイルを正しく読み取る."""
        from privacy_guard_mcp.readers.local import LocalFileReader
        reader = LocalFileReader()
        result = reader.read_text(SAMPLE_TXT)

        assert result["file_type"] == "text"
        assert "テスト用" in result["content"]
        assert result["has_images"] is False
        assert result["page_count"] == -1
        assert result["sheet_names"] == []
        assert result["file_size_bytes"] > 0

    def test_read_csv_file(self):
        """CSVファイルをタブ区切りテキストとして読み取る."""
        from privacy_guard_mcp.readers.local import LocalFileReader
        reader = LocalFileReader()
        result = reader.read_csv(SAMPLE_CSV)

        assert result["file_type"] == "csv"
        assert "\t" in result["content"]  # タブ区切りに変換されている
        assert result["has_images"] is False

    def test_read_auto_dispatch_txt(self):
        """read() メソッドが拡張子で自動ディスパッチする（.txt）."""
        from privacy_guard_mcp.readers.local import LocalFileReader
        reader = LocalFileReader()
        result = reader.read(SAMPLE_TXT)
        assert result["file_type"] == "text"
        assert len(result["content"]) > 0

    def test_read_auto_dispatch_csv(self):
        """read() メソッドが拡張子で自動ディスパッチする（.csv）."""
        from privacy_guard_mcp.readers.local import LocalFileReader
        reader = LocalFileReader()
        result = reader.read(SAMPLE_CSV)
        assert result["file_type"] == "csv"

    def test_no_write_methods(self):
        """書き込みメソッドが存在しないことを確認する（元データ不変原則）."""
        from privacy_guard_mcp.readers.local import LocalFileReader
        reader = LocalFileReader()
        forbidden_methods = ["save", "write", "export", "to_file", "write_back"]
        for method in forbidden_methods:
            assert not hasattr(reader, method), (
                f"書き込みメソッド '{method}' が存在してはいけません（元データ不変原則）"
            )


# ============================================================
# TestLocalFileReaderFailClose - 異常系・フェイルクローズ
# ============================================================

class TestLocalFileReaderFailClose:
    """LocalFileReader のフェイルクローズ動作テスト."""

    def test_file_not_found_raises_reader_error(self):
        """存在しないファイルは ReaderError を raise する."""
        from privacy_guard_mcp.readers.local import LocalFileReader, ReaderError
        reader = LocalFileReader()
        with pytest.raises(ReaderError, match="ファイルが見つかりません"):
            reader.read_text("/tmp/privacy_guard_mcp_nonexistent_file_xyz.txt")

    def test_empty_path_raises_reader_error(self):
        """空のパスは ReaderError を raise する."""
        from privacy_guard_mcp.readers.local import LocalFileReader, ReaderError
        reader = LocalFileReader()
        with pytest.raises(ReaderError):
            reader.read_text("")

    def test_directory_path_raises_reader_error(self):
        """ディレクトリパスは ReaderError を raise する."""
        from privacy_guard_mcp.readers.local import LocalFileReader, ReaderError
        reader = LocalFileReader()
        with pytest.raises(ReaderError):
            reader.read_text(str(TEST_DATA_DIR))

    def test_max_size_exceeded_raises_reader_error(self, tmp_path):
        """最大サイズ超過は ReaderError を raise する."""
        from privacy_guard_mcp.readers.local import LocalFileReader, ReaderError
        # 10バイト以上のファイルを用意して、上限を5バイトに設定
        large_file = tmp_path / "large.txt"
        large_file.write_bytes(b"A" * 100)
        reader = LocalFileReader(max_size_bytes=5)
        with pytest.raises(ReaderError, match="ファイルサイズ超過"):
            reader.read_text(str(large_file))

    def test_excel_not_found_raises_reader_error(self):
        """存在しないExcelファイルは ReaderError を raise する."""
        from privacy_guard_mcp.readers.local import LocalFileReader, ReaderError
        reader = LocalFileReader()
        with pytest.raises(ReaderError):
            reader.read_excel("/tmp/privacy_guard_nonexistent.xlsx")

    def test_pdf_not_found_raises_reader_error(self):
        """存在しないPDFファイルは ReaderError を raise する."""
        from privacy_guard_mcp.readers.local import LocalFileReader, ReaderError
        reader = LocalFileReader()
        with pytest.raises(ReaderError):
            reader.read_pdf("/tmp/privacy_guard_nonexistent.pdf")


# ============================================================
# TestMaskingSessionExtended - session_id・category_counts
# ============================================================

class TestMaskingSessionExtended:
    """MaskingSession の追加機能テスト."""

    def test_session_id_is_set(self):
        """session_id が UUID 形式で設定されている."""
        import re
        from privacy_guard_mcp.masking.session import MaskingSession
        session = MaskingSession()
        assert hasattr(session, "session_id")
        assert isinstance(session.session_id, str)
        # UUID v4 形式の簡易チェック
        uuid_pattern = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            re.IGNORECASE,
        )
        assert uuid_pattern.match(session.session_id), f"UUID形式でない: {session.session_id}"

    def test_different_sessions_have_different_ids(self):
        """異なるセッションは異なる session_id を持つ."""
        from privacy_guard_mcp.masking.session import MaskingSession
        s1 = MaskingSession()
        s2 = MaskingSession()
        assert s1.session_id != s2.session_id

    def test_category_counts_empty_initially(self):
        """初期状態では category_counts は空辞書を返す."""
        from privacy_guard_mcp.masking.session import MaskingSession
        session = MaskingSession()
        assert session.category_counts() == {}

    def test_category_counts_after_masking(self):
        """マスキング後に category_counts が正しく更新される."""
        from privacy_guard_mcp.masking.session import MaskingSession
        session = MaskingSession()
        session.get_or_create_mask_id("MASKED_NAME", "テスト太郎")
        session.get_or_create_mask_id("MASKED_NAME", "テスト花子")
        session.get_or_create_mask_id("MASKED_EMAIL", "test@example.com")
        counts = session.category_counts()
        assert counts.get("MASKED_NAME") == 2
        assert counts.get("MASKED_EMAIL") == 1


# ============================================================
# TestServerTools - サーバーツール統合テスト
# ============================================================

class TestServerTools:
    """server.py の pg_read_file / pg_check_rules / pg_session_info テスト."""

    def test_pg_read_file_normal(self):
        """pg_read_file: 正常系 - テキストファイルを読み取ってマスキングする."""
        from privacy_guard_mcp import server
        result = server.pg_read_file(SAMPLE_TXT)
        assert result["status"] == "ok"
        assert isinstance(result["data"], str)
        assert "masking_summary" in result
        assert "session_id" in result
        # フェイルクローズ確認: 元テキスト（メールアドレス）がそのまま残っていない
        assert "test-user@example.com" not in result["data"]

    def test_pg_read_file_not_found(self):
        """pg_read_file: 異常系 - 存在しないファイルはエラーレスポンスを返す（元データ返却禁止）."""
        from privacy_guard_mcp import server
        result = server.pg_read_file("/tmp/privacy_guard_nonexistent_xyz.txt")
        assert result["status"] == "error"
        # フェイルクローズ: data フィールドは空
        assert result["data"] == ""
        assert len(result["warnings"]) > 0

    def test_pg_read_file_csv(self):
        """pg_read_file: CSVファイルを読み取る（auto dispatch は text として処理）."""
        from privacy_guard_mcp import server
        result = server.pg_read_file(SAMPLE_CSV)
        # CSVもテキストとして読み取れる
        assert result["status"] == "ok"
        assert "taro@example.com" not in result["data"]

    def test_pg_check_rules_returns_categories(self):
        """pg_check_rules: カテゴリ一覧を正しく返す."""
        from privacy_guard_mcp import server
        result = server.pg_check_rules()
        assert result["status"] == "ok"
        assert "rules" in result
        assert "categories" in result["rules"]
        assert len(result["rules"]["categories"]) > 0
        assert result["rules"]["pattern_count"] > 0
        assert result["rules"]["fail_close"] is True

    def test_pg_session_info_returns_stats(self):
        """pg_session_info: サーバー統計を返す（スタブ実装）."""
        from privacy_guard_mcp import server
        result = server.pg_session_info()
        assert result["status"] == "ok"
        assert "session" in result
        assert result["session"]["design"] == "per-call"
        assert "server_stats" in result["session"]
        assert "total_calls" in result["session"]["server_stats"]

    def test_pg_read_excel_not_found(self):
        """pg_read_excel: 存在しないファイルはエラーレスポンスを返す."""
        from privacy_guard_mcp import server
        result = server.pg_read_excel("/tmp/privacy_guard_nonexistent.xlsx")
        assert result["status"] == "error"
        assert result["data"] == ""

    def test_pg_read_pdf_not_found(self):
        """pg_read_pdf: 存在しないPDFはエラーレスポンスを返す."""
        from privacy_guard_mcp import server
        result = server.pg_read_pdf("/tmp/privacy_guard_nonexistent.pdf")
        assert result["status"] == "error"
        assert result["data"] == ""

    def test_pg_gws_read_invalid_resource_type(self):
        """pg_gws_read: 無効なresource_typeはエラーレスポンスを返す."""
        from privacy_guard_mcp import server
        result = server.pg_gws_read(
            resource_type="invalid_type",
            resource_id="dummy-id",
        )
        assert result["status"] == "error"
        assert "INVALID_RESOURCE_TYPE" in result["warnings"][0]

    def test_pg_gws_read_command_not_available(self):
        """pg_gws_read: gwsコマンド不在でもエラーレスポンスを返す（フェイルクローズ）."""
        from privacy_guard_mcp import server
        # 存在しないコマンドパスを使用
        from privacy_guard_mcp.readers.gws import GWSReader
        original_reader = server._gws_reader
        server._gws_reader = GWSReader(
            gws_command="/nonexistent/gws",
            gog_command="/nonexistent/gog",
        )
        try:
            result = server.pg_gws_read(
                resource_type="sheets",
                resource_id="dummy-spreadsheet-id",
            )
            assert result["status"] == "error"
            assert result["data"] == ""
        finally:
            server._gws_reader = original_reader


# ============================================================
# TestGWSReader
# ============================================================

class TestGWSReader:
    """GWSReader の初期化・コマンド不在時のテスト."""

    def test_init_default(self):
        """デフォルト初期化が正常に完了する."""
        from privacy_guard_mcp.readers.gws import GWSReader
        reader = GWSReader()
        assert reader._timeout == 30

    def test_init_custom_timeout(self):
        """カスタムタイムアウトが設定される."""
        from privacy_guard_mcp.readers.gws import GWSReader
        reader = GWSReader(timeout_seconds=60)
        assert reader._timeout == 60

    def test_command_not_found_raises_gws_reader_error(self):
        """存在しないコマンドは GWSReaderError を raise する."""
        from privacy_guard_mcp.readers.gws import GWSReader, GWSReaderError
        reader = GWSReader(gws_command="/nonexistent/gws", gog_command="/nonexistent/gog")
        with pytest.raises(GWSReaderError):
            reader.read_spreadsheet("dummy-id")

    def test_no_write_methods(self):
        """書き込みメソッドが存在しないことを確認する（元データ不変原則）."""
        from privacy_guard_mcp.readers.gws import GWSReader
        reader = GWSReader()
        forbidden_methods = ["write_spreadsheet", "update_document", "upload_file"]
        for method in forbidden_methods:
            assert not hasattr(reader, method), (
                f"書き込みメソッド '{method}' が存在してはいけません（元データ不変原則）"
            )
