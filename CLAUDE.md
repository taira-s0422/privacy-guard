# Privacy Guard MCP - Claude Code向け実装ガイド

## プロジェクト概要

個人情報・機密情報を自動マスキングするMCPサーバー（Python / FastMCP / stdio transport）。
Claude Codeがファイル・Google Workspace等を読み取る際に、個人情報が含まれていてもAIに
安全に渡せるようにマスキングする。

- **Python要件**: 3.11以上（推奨: 3.12）
- **フレームワーク**: FastMCP（stdioトランスポート）

## 絶対に守ること（変更不可の設計原則）

1. **フェイルクローズ**: `MaskingError` が発生したら `raise` して処理停止。元テキストを返すことは禁止
2. **元データ不変**: 入力テキストを上書き・変更しない。新しい文字列を生成して返す
3. **メモリ管理**: `MaskingSession._masking_map` はインスタンス変数のみ。`to_file()` 等のディスク書き出しメソッドを追加禁止
4. **ハッシュ化**: 元データは SHA-256 ハッシュのみ保持（`session.py` の `get_or_create_mask_id` 参照）
5. **テストデータ**: テストは必ず `faker` (ja_JP) で生成した架空データのみ使用。実在個人情報禁止

## ディレクトリ構造

```
privacy-guard-mcp/
├── CLAUDE.md                              # このファイル
├── README.md                              # セットアップガイド
├── Dockerfile                             # Docker環境
├── docker-compose.test.yml               # テスト用Docker Compose
├── .gitignore
├── pyproject.toml                         # パッケージ定義
├── requirements.txt                       # pip依存
├── .env.example                           # 環境変数テンプレート
├── .mcp.json.example                      # MCPサーバー設定テンプレート
├── scripts/
│   ├── start_server.sh                   # 起動スクリプト
│   └── audit_session.sh                  # セッション監査スクリプト
├── privacy_guard_mcp/
│   ├── __init__.py                        # バージョン定義
│   ├── server.py                          # FastMCPエントリポイント（全7ツール登録）
│   ├── config/
│   │   ├── settings.yaml                  # デフォルト設定
│   │   ├── masking_rules.yaml             # マスキングルール
│   │   ├── exclusions.yaml                # 除外ルール
│   │   └── dictionaries/
│   │       └── names_ja.yaml             # 日本語姓名辞書
│   ├── masking/
│   │   ├── __init__.py
│   │   ├── session.py                     # マスキングセッション（揮発メモリ管理）
│   │   ├── patterns.py                   # 10カテゴリ正規表現パターン
│   │   ├── engine.py                      # マスキングエンジン（フェイルクローズ）
│   │   ├── dictionary.py                 # 辞書読み込み・人名検知
│   │   ├── entropy.py                    # シャノンエントロピー計算
│   │   └── tools.py                       # pg_mask_text MCPツール
│   └── readers/
│       ├── local.py                       # ローカルファイルリーダー
│       ├── gws.py                         # Google Workspaceリーダー
│       └── encoding_detect.py             # エンコーディング自動判別
└── tests/
    ├── test_masking.py                    # マスキングエンジン単体テスト
    ├── test_readers.py                    # リーダー・サーバーツール統合テスト
    ├── test_e2e.py                        # E2Eテスト（全7ツール）
    ├── generate_dummy_data.py             # ダミーデータ自動生成
    └── test_data/
        ├── sample.txt                     # テスト用サンプルテキスト
        ├── sample.csv                     # テスト用サンプルCSV
        └── dummy/                         # 生成済みダミーデータ（gitignore対象）
```

## 環境構築

```bash
cd privacy-guard-mcp

# Python 3.12 仮想環境（推奨）
python3.12 -m venv .venv-312
source .venv-312/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## テスト実行

```bash
source .venv-312/bin/activate

# 全テスト実行
pytest tests/ -v

# E2Eのみ
pytest tests/test_e2e.py -v

# Docker Composeテスト環境
docker compose -f docker-compose.test.yml up --build
```

## ダミーデータ生成

```bash
python tests/generate_dummy_data.py
# → tests/test_data/dummy/ に6種類のダミーファイルを生成
```

## セッション監査

```bash
./scripts/audit_session.sh
# ログファイルも監査する場合
./scripts/audit_session.sh --log-file /path/to/server.log
```

## マスキングカテゴリ（10種）

| カテゴリ | マスクラベル | 検知方法 |
|---------|------------|---------|
| 日本語個人名 | `MASKED_NAME` | 辞書 + 正規表現 |
| 英語個人名 | `MASKED_NAME_EN` | 正規表現 |
| メールアドレス | `MASKED_EMAIL` | 正規表現 |
| 電話番号（日本） | `MASKED_PHONE` | 正規表現 |
| 住所（日本） | `MASKED_ADDRESS` | 正規表現 |
| マイナンバー | `MASKED_MY_NUMBER` | 正規表現 |
| APIキー・トークン | `MASKED_API_KEY` | 正規表現 + エントロピー |
| パスワード | `MASKED_PASSWORD` | 正規表現 |
| クレジットカード番号 | `MASKED_CC` | 正規表現 |
| 企業名 | `MASKED_COMPANY` | 正規表現（ひらがな除外で誤検知修正済み） |

## Claude Codeへの登録（グローバル配置）

`~/.claude.json` の `mcpServers` に追加する:

```json
{
  "mcpServers": {
    "privacy-guard-mcp": {
      "command": "/path/to/privacy-guard-mcp/.venv-312/bin/python",
      "args": ["-m", "privacy_guard_mcp.server"],
      "cwd": "/path/to/privacy-guard-mcp"
    }
  }
}
```

`/path/to/privacy-guard-mcp` は実際のリポジトリのパスに置き換える。

## Google Workspace連携（オプション）

`pg_gws_read` ツールを使うには、`gws`（gwscli）または `gog` コマンドが必要:

- `gws`: `npm install -g @googleworkspace/cli`
- `gog`: 配布元のインストール方法に従う

コマンドのパスは `.env` の `PRIVACY_GUARD_GWS_COMMAND` / `PRIVACY_GUARD_GOG_COMMAND` で指定可能。
PATHが通っていればデフォルト（`gws` / `gog`）のままでOK。
