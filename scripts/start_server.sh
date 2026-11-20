#!/usr/bin/env bash
# Privacy Guard MCP サーバー起動スクリプト
# 使用方法: ./scripts/start_server.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# venv の確認と activate（Python 3.12環境 .venv-312 を優先使用）
VENV_DIR="${PROJECT_ROOT}/.venv-312"
if [[ ! -d "${VENV_DIR}" ]]; then
    echo "[ERROR] venv が見つかりません: ${VENV_DIR}" >&2
    echo "以下のコマンドで初期化してください:" >&2
    echo "  cd ${PROJECT_ROOT} && /opt/homebrew/bin/python3.12 -m venv .venv-312 && source .venv-312/bin/activate && pip install -e .[dev]" >&2
    exit 1
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"

# プロジェクトルートに移動
cd "${PROJECT_ROOT}"

echo "[INFO] Privacy Guard MCP サーバーを起動します（Python 3.12環境）..." >&2
exec python privacy_guard_mcp/server.py
