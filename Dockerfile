# Privacy Guard MCP - Docker イメージ
# Python 3.12 ベース（pyproject.toml の requires-python = ">=3.11" 準拠）

FROM python:3.12-slim

# ビルド引数
ARG DEBIAN_FRONTEND=noninteractive

# 作業ディレクトリ
WORKDIR /app

# 依存パッケージのインストール（レイヤーキャッシュ活用）
COPY requirements.txt pyproject.toml ./
# setuptools を先にアップグレードしてから依存をインストール
RUN pip install --no-cache-dir --upgrade pip setuptools && \
    pip install --no-cache-dir -r requirements.txt

# ソースコードのコピー
COPY privacy_guard_mcp/ ./privacy_guard_mcp/
COPY tests/ ./tests/

# パッケージをインストール（editable モード）
RUN pip install --no-cache-dir -e ".[dev]"

# テスト実行時のデフォルトコマンド
CMD ["pytest", "tests/", "-v", "--tb=short"]
