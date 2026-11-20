#!/usr/bin/env bash
# Privacy Guard MCP - セッション監査スクリプト
# 仕様書セクション9.5準拠
#
# 用途:
#   - MCPサーバーのセッション設計（メモリ管理）を静的監査する
#   - ディスク書き出しメソッドが存在しないことを確認する
#   - フェイルクローズ設定が有効であることを確認する
#   - 実行ログから異常を検知する（オプション）
#
# 使い方:
#   ./scripts/audit_session.sh
#   ./scripts/audit_session.sh --log-file /path/to/server.log
#   ./scripts/audit_session.sh --strict  # 1件でも警告があれば失敗
#
# 戻り値:
#   0: 監査通過（クリティカルな問題なし）
#   1: 監査失敗（フェイルクローズ無効 / ディスク書き出しメソッド検出等）

set -euo pipefail

# ============================================================
# 設定
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PYTHON="${PYTHON:-python3}"
LOG_FILE=""
STRICT_MODE=false
AUDIT_PASSED=true
WARNINGS=0
ERRORS=0

# カラー出力
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RESET='\033[0m'

# ============================================================
# ユーティリティ関数
# ============================================================
log_info() {
    echo -e "${BLUE}[INFO]${RESET} $*"
}

log_ok() {
    echo -e "${GREEN}[OK]${RESET}   $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${RESET} $*"
    WARNINGS=$((WARNINGS + 1))
    if [ "$STRICT_MODE" = true ]; then
        AUDIT_PASSED=false
    fi
}

log_error() {
    echo -e "${RED}[ERROR]${RESET} $*"
    ERRORS=$((ERRORS + 1))
    AUDIT_PASSED=false
}

# ============================================================
# 引数解析
# ============================================================
while [[ $# -gt 0 ]]; do
    case "$1" in
        --log-file)
            LOG_FILE="$2"
            shift 2
            ;;
        --strict)
            STRICT_MODE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--log-file <path>] [--strict]"
            echo "  --log-file <path>  : サーバーログファイルを監査対象に追加"
            echo "  --strict           : 警告でも失敗扱い"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ============================================================
# 監査開始
# ============================================================
echo ""
echo "================================================================"
echo "  Privacy Guard MCP - セッション監査"
echo "  プロジェクトルート: ${PROJECT_ROOT}"
echo "  実行日時: $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================================"
echo ""

# ============================================================
# 1. Python 環境チェック
# ============================================================
log_info "チェック 1/6: Python 環境"

if ! command -v "${PYTHON}" &>/dev/null; then
    log_error "Python コマンドが見つかりません: ${PYTHON}"
else
    PYTHON_VERSION=$("${PYTHON}" --version 2>&1)
    log_ok "Python: ${PYTHON_VERSION}"
fi

# venv の確認
VENV_DIRS=(".venv-312" ".venv")
ACTIVE_VENV=""
for venv in "${VENV_DIRS[@]}"; do
    if [ -d "${PROJECT_ROOT}/${venv}" ]; then
        ACTIVE_VENV="${PROJECT_ROOT}/${venv}"
        log_ok "仮想環境: ${venv}"
        break
    fi
done
if [ -z "$ACTIVE_VENV" ]; then
    log_warn "仮想環境が見つかりません (.venv-312 / .venv)"
fi

# ============================================================
# 2. ディスク書き出しメソッド検出（静的解析）
# ============================================================
log_info "チェック 2/6: ディスク書き出しメソッド禁止確認（静的解析）"

FORBIDDEN_METHODS=("to_file" "save_to_disk" "export_session" "dump_session" "write_session")
SESSION_FILE="${PROJECT_ROOT}/privacy_guard_mcp/masking/session.py"

if [ ! -f "${SESSION_FILE}" ]; then
    log_error "session.py が見つかりません: ${SESSION_FILE}"
else
    FOUND_FORBIDDEN=false
    for method in "${FORBIDDEN_METHODS[@]}"; do
        if grep -q "def ${method}" "${SESSION_FILE}"; then
            log_error "禁止メソッド '${method}' が session.py に存在します（設計原則違反）"
            FOUND_FORBIDDEN=true
        fi
    done
    if [ "$FOUND_FORBIDDEN" = false ]; then
        log_ok "ディスク書き出しメソッドなし（session.py 検査完了）"
    fi
fi

# ============================================================
# 3. フェイルクローズ設定確認（静的解析）
# ============================================================
log_info "チェック 3/6: フェイルクローズ設定確認"

SERVER_FILE="${PROJECT_ROOT}/privacy_guard_mcp/server.py"
if grep -q "fail_close=True" "${SERVER_FILE}"; then
    log_ok "server.py: MaskingEngine(fail_close=True) 確認"
else
    log_error "server.py: fail_close=True が見つかりません（フェイルクローズ無効化リスク）"
fi

# .env.example に FAIL_CLOSE が存在するか
ENV_EXAMPLE="${PROJECT_ROOT}/.env.example"
if [ -f "${ENV_EXAMPLE}" ] && grep -q "FAIL_CLOSE" "${ENV_EXAMPLE}"; then
    log_ok ".env.example: FAIL_CLOSE 変数定義あり"
else
    log_warn ".env.example: FAIL_CLOSE 変数定義が見つかりません"
fi

# ============================================================
# 4. セキュリティ: .env が Git トラック対象でないことを確認
# ============================================================
log_info "チェック 4/6: .env セキュリティ確認"

cd "${PROJECT_ROOT}"
if git status --porcelain ".env" 2>/dev/null | grep -q "^?? .env$\|^ M .env$\|^A  .env$"; then
    log_warn ".env ファイルが Git の管理対象になっている可能性があります"
elif git ls-files --error-unmatch ".env" &>/dev/null 2>&1; then
    log_error ".env が Git でトラックされています（認証情報漏洩リスク）"
else
    log_ok ".env は Git 管理外（untracked または gitignore）"
fi

if [ -f "${PROJECT_ROOT}/.gitignore" ] && grep -q "^\.env$\|^\.env\.\*" "${PROJECT_ROOT}/.gitignore"; then
    log_ok ".gitignore: .env の除外設定あり"
else
    log_warn ".gitignore に .env の除外設定が見つかりません"
fi

# ============================================================
# 5. Python による動的チェック（MaskingSession インスタンス検査）
# ============================================================
log_info "チェック 5/6: MaskingSession 動的検査"

if [ -n "$ACTIVE_VENV" ]; then
    PYTHON_BIN="${ACTIVE_VENV}/bin/python3"
else
    PYTHON_BIN="${PYTHON}"
fi

DYNAMIC_CHECK_RESULT=$("${PYTHON_BIN}" - << 'PYTHON_SCRIPT' 2>&1
import sys
sys.path.insert(0, '.')
try:
    from privacy_guard_mcp.masking.session import MaskingSession
    session = MaskingSession()

    # 禁止メソッドチェック
    forbidden = ["to_file", "save", "export", "serialize", "dump", "write"]
    found = [m for m in forbidden if hasattr(session, m)]

    if found:
        print(f"FAIL: 禁止メソッドが存在: {found}")
        sys.exit(1)
    else:
        print("OK: 禁止メソッドなし")

    # セッションIDが生成されること
    assert session.session_id, "session_id が空"
    print(f"OK: session_id 生成確認 (例: {session.session_id[:8]}...)")

    # SHA-256ハッシュ確認
    mask_id = session.get_or_create_mask_id("MASKED_NAME", "テスト太郎")
    for key in session._masking_map.keys():
        entity_type, hash_val = key
        assert "テスト太郎" not in hash_val, "元データがハッシュキーに含まれている"
        assert len(hash_val) == 64, f"ハッシュ長が不正: {len(hash_val)}"
    print("OK: SHA-256ハッシュのみ保持（元データなし）")

    sys.exit(0)
except Exception as e:
    print(f"FAIL: {e}")
    sys.exit(1)
PYTHON_SCRIPT
)

DYNAMIC_EXIT=$?
if [ $DYNAMIC_EXIT -eq 0 ]; then
    echo "${DYNAMIC_CHECK_RESULT}" | while IFS= read -r line; do
        log_ok "${line}"
    done
else
    echo "${DYNAMIC_CHECK_RESULT}" | while IFS= read -r line; do
        log_error "${line}"
    done
fi

# ============================================================
# 6. ログファイル監査（オプション）
# ============================================================
log_info "チェック 6/6: ログファイル監査"

if [ -z "$LOG_FILE" ]; then
    log_info "  ログファイル未指定（スキップ）。--log-file で指定可能"
elif [ ! -f "$LOG_FILE" ]; then
    log_warn "指定されたログファイルが見つかりません: ${LOG_FILE}"
else
    # エラーパターンを検索
    ERROR_COUNT=$(grep -c "\[ERROR\]\|\[CRITICAL\]\|MaskingError\|FAIL_CLOSE" "${LOG_FILE}" 2>/dev/null || echo 0)
    if [ "$ERROR_COUNT" -gt 0 ]; then
        log_warn "ログに ${ERROR_COUNT} 件のエラー/フェイルクローズ発動を検出"
        grep "\[ERROR\]\|\[CRITICAL\]\|MaskingError\|FAIL_CLOSE" "${LOG_FILE}" | head -5
    else
        log_ok "ログにエラーなし: ${LOG_FILE}"
    fi
fi

# ============================================================
# 監査結果サマリー
# ============================================================
echo ""
echo "================================================================"
echo "  監査結果サマリー"
echo "================================================================"
echo "  エラー: ${ERRORS} 件"
echo "  警告:   ${WARNINGS} 件"
echo "  モード: $([ "$STRICT_MODE" = true ] && echo 'STRICT（警告も失敗扱い）' || echo 'NORMAL')"
echo ""

if [ "$AUDIT_PASSED" = true ]; then
    echo -e "  ${GREEN}AUDIT PASSED${RESET} - クリティカルな問題は検出されませんでした"
    echo ""
    exit 0
else
    echo -e "  ${RED}AUDIT FAILED${RESET} - 問題が検出されました。上記のエラーを確認してください"
    echo ""
    exit 1
fi
