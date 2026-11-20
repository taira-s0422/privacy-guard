# Privacy Guard MCP

Privacy Guard MCP は、ファイルや Google Workspace の中身を AI に渡す前に、個人情報・機密情報を伏せ字（マスク）に置き換える MCP サーバーです。Python / FastMCP で書かれ、stdio で動きます。

- 守れること: `pg_read_*` などのツールを通した内容から、氏名・メール・電話・住所・API キーなど10種類を検知してマスクする
- 守れないこと: 通常の Read ツールで読まれたファイル。検知の取りこぼし。マスクしても文脈から人物を推測できる文章
- 単体では防御になりません。Claude に `pg_read_*` を使わせる強制設定とセットで使います（[強制経由の設定](#強制経由の設定)）

## 概要

Privacy Guard MCP は、読み取りとマスクを1つのツールにまとめています。ツールがファイルを読み、マスクした結果だけを Claude に返します。

設計の要点は3つです。

1. フェイルクローズ: マスクに失敗したら、元の内容を返さずエラーを返す
2. 元ファイルは変更しない: 読み取り専用で、結果は新しい文字列として返す
3. 対応表はメモリだけ: 元の値は SHA-256 ハッシュでしか保持せず、ディスクに書かない

マスクの例です。

```text
入力:  担当: 山田 太郎 / メール: yamada@example.com / 電話: 090-1234-5678
出力:  担当: [MASKED_NAME_001] / メール: [MASKED_EMAIL_001] / 電話: [MASKED_PHONE_001]
```

同じ値には、1回の呼び出しの中で同じ番号が付きます（山田 太郎が2回出れば、どちらも `[MASKED_NAME_001]`）。番号は呼び出しごとに 001 から振り直されます。

## 守れること・守れないこと

守れること:

- `pg_read_file` / `pg_read_excel` / `pg_read_pdf` / `pg_gws_read` / `pg_mask_text` を通した内容のマスク
- マスク前の値をログやエラー文に出さない（ログに出すのは位置・文字数・マスク ID だけ）
- マスク処理が失敗した時に、元の内容を返さない

守れないこと（防御の限界）:

1. 通常の Read ツールで読まれたファイルは、マスクされずにそのまま AI に渡ります。`pg_read_*` を呼んだ時だけマスクが働きます。
2. 検知は辞書と正規表現です。取りこぼしも誤検知も原理的に起こります。マイナンバーやクレジットカードなど重要な情報は、マスク後の出力も人の目で確認してください。
3. 検知しない形があります。例: 「マイナンバー」「個人番号」の語が近くにない12桁の数字。辞書にない氏名。表記ゆれの強い住所。
4. 文脈から人物が分かる文章（「〇〇市の△△店の店長」など）は、名前を伏せても特定できます。
5. スキャンして作った PDF（画像）は本文が空になることがあります。

このため、機密ファイルへの通常の Read を設定で禁止し、`pg_read_*` しか通らない状態にしてください。手順は [SECURITY_SETUP.md](./SECURITY_SETUP.md) にあります。

## 動作要件

- Python 3.11 以上（推奨 3.12）
- Claude アプリ（デスクトップ）または Claude Code CLI
- Google Workspace を読む場合だけ: `gws`（gwscli）または `gog` コマンド

依存ライブラリ（fastmcp・pyyaml・python-dotenv・chardet・openpyxl・pypdf・pandas・faker）は `pip install` で入ります。

## 導入

手順は2段階です。「1. インストール」は全員共通です。「2. 登録」は、Claude アプリだけの人は A、Claude Code CLI も使う人は B を選びます。

### 1. インストール

ターミナルで次を実行します。

```bash
git clone https://github.com/taira-s0422/privacy-guard.git
cd privacy-guard
python3.12 -m venv .venv
.venv/bin/pip install -e .
pwd   # 表示されたパスを、登録で使う
```

ターミナルを使わない場合は、Claude アプリの「Code」でこのフォルダを開き、「README のインストール手順を実行して」と頼んでも構いません。

Windows の場合は、`.venv/bin/python` を `.venv\Scripts\python.exe` に読み替えます（Windows での動作は未検証です）。

### 2-A. Claude アプリだけを使う場合

Claude アプリは、`claude_desktop_config.json` に書いた MCP サーバーを読み込みます。CLI は要りません。

1. Finder で ⌘⇧G を押し、`~/Library/Application Support/Claude/` を開く
2. `claude_desktop_config.json` をテキストエディットで開く（無ければ作る）
3. `mcpServers` に次を追加する。`<パス>` は手順1の `pwd` の結果に置き換える。既に `mcpServers` がある場合は、その中に `"privacy-guard-mcp": {...}` の部分だけを足す

```json
{
  "mcpServers": {
    "privacy-guard-mcp": {
      "command": "<パス>/.venv/bin/python",
      "args": ["-m", "privacy_guard_mcp.server"],
      "cwd": "<パス>",
      "env": {
        "FAIL_CLOSE": "true",
        "LOG_LEVEL": "INFO"
      }
    }
  }
}
```

4. アプリを ⌘Q で完全に終了し、開き直す
5. 新しい会話で「privacy-guard の pg_check_rules を実行して」と頼む。カテゴリの一覧が返れば成功

### 2-B. Claude Code CLI も使う場合

ユーザースコープで登録します。全プロジェクトで使えます。

```bash
claude mcp add privacy-guard-mcp -s user \
  -e FAIL_CLOSE=true -e LOG_LEVEL=INFO \
  -- "$(pwd)/.venv/bin/python" -m privacy_guard_mcp.server
```

確認は `claude mcp list` で `Connected` と出れば成功です。Claude Code の中では `/mcp` で確認できます。

A と B の両方に同じ名前で登録すると、設定が食い違います。どちらか一方だけにしてください。

アプリは PATH を引き継がないことがあります。python も gws / gog も絶対パスで指定してください。

### 設定ファイルを使う場合（`.mcp.json`）

プロジェクトごとに登録する場合は、[.mcp.json.example](./.mcp.json.example) をコピーして `.mcp.json` にし、`/path/to/privacy-guard` を実際のパスに直します。

### 削除

- A の場合: `claude_desktop_config.json` から `"privacy-guard-mcp": {...}` を消し、アプリを開き直す
- B の場合: `claude mcp remove privacy-guard-mcp -s user`

## 使い方

Claude に「privacy-guard で〜を読んで」と頼みます。通常の Read ではなく、`pg_` のツールを使わせます。会話はマスク後の ID（`[MASKED_NAME_001]` など）で進みます。

### ツール一覧（7個）

| ツール | 用途 | 引数 |
|---|---|---|
| `pg_read_file` | テキスト・CSV・Markdown などを読み、マスクして返す。文字コードは自動判別 | `file_path` |
| `pg_read_excel` | Excel（.xlsx / .xlsm）を読み、マスクして返す。旧形式 .xls は未対応 | `file_path`、`sheet_name`（省略で全シート） |
| `pg_read_pdf` | PDF の本文を読み、マスクして返す | `file_path` |
| `pg_gws_read` | Google スプレッドシート・ドキュメント・ドライブのファイルを読み、マスクして返す | `resource_type`（`sheets` / `docs` / `drive`）、`resource_id`、`sheet_name`、`range_notation` |
| `pg_mask_text` | 渡したテキストをマスクして返す | `text` |
| `pg_check_rules` | 有効なカテゴリ・パターン数・フェイルクローズの設定を確認する | なし |
| `pg_session_info` | サーバーの稼働統計（呼び出し数・マスク件数・エラー数）を返す | なし |

読み取り系ツールの返り値は、`status`（`ok` / `error`）、`data`（マスク済みの本文）、`masking_summary`（カテゴリ別の件数）、`warnings`、`session_id` を含みます。読めるファイルの上限は 50MB です。

### 呼び出しの例

```text
privacy-guard で ~/Documents/顧客リスト.xlsx を読んで、業種別の件数を集計して
```

```text
pg_read_excel で ~/Documents/report.xlsx の「3月」シートを読んで
```

```text
pg_mask_text で「山田太郎 090-1234-5678」をマスクして
```

```text
pg_gws_read で sheets の <スプレッドシートID> を A1:Z100 の範囲で読んで
```

`pg_gws_read` は `gws` または `gog` コマンドを呼び出します。Google Workspace の認証は、そのコマンド側で済ませておきます。

## マスキングの対象カテゴリ

対象は10種類です。

| カテゴリ | マスクのラベル | 検知の方法 | 例 |
|---|---|---|---|
| 日本語の個人名 | `MASKED_NAME` | 辞書＋正規表現 | 山田 太郎 |
| 英語の個人名 | `MASKED_NAME_EN` | 正規表現 | John Smith |
| メールアドレス | `MASKED_EMAIL` | 正規表現 | yamada@example.com |
| 電話番号（日本） | `MASKED_PHONE` | 正規表現 | 090-1234-5678 |
| 住所（日本） | `MASKED_ADDRESS` | 正規表現 | 東京都新宿区西新宿2-8-1 |
| マイナンバー | `MASKED_MY_NUMBER` | 正規表現 | マイナンバー 123456789012 |
| API キー・トークン | `MASKED_API_KEY` | 正規表現＋エントロピー | `sk-…`、`AKIA…`、`ghp_…` |
| パスワード | `MASKED_PASSWORD` | 正規表現 | password=Abcd1234xyz |
| クレジットカード番号 | `MASKED_CC` | 正規表現 | 4111 1111 1111 1111 |
| 企業名 | `MASKED_COMPANY` | 正規表現 | 株式会社サンプル商事 |

補足です。

- マイナンバーは、「マイナンバー」または「個人番号」の語の直後にある12桁だけを検知します。誤検知を避けるためです
- パスワードは、`password=` の部分も含めて全体をマスクします
- 日本語の姓名辞書は、法務省と厚生労働省の公開統計から作っています（`privacy_guard_mcp/config/dictionaries/names_ja.yaml`）

## 設定

### 環境変数

| 変数 | 説明 | 既定値 |
|---|---|---|
| `FAIL_CLOSE` | `false` を指定した時だけ、フェイルクローズが無効になる。本番では `true` のままにする | `true` |
| `LOG_LEVEL` | ログレベル（DEBUG / INFO / WARNING / ERROR）。ログは標準エラー出力に出る | `INFO` |
| `PRIVACY_GUARD_GWS_COMMAND` | `gws` コマンドのパス | PATH から探す |
| `PRIVACY_GUARD_GOG_COMMAND` | `gog` コマンドのパス | PATH から探す |

リポジトリ直下の `.env` に書いても読み込まれます（雛形は [.env.example](./.env.example)）。`.env` は Git にコミットしないでください。

Google Workspace を読む場合は、アプリが PATH を引き継がないことがあるため、絶対パスを指定します。絶対パスはターミナルで `which gws` または `which gog` を実行すると分かります。2-A の `env` に足す場合の例です。

```json
"env": {
  "FAIL_CLOSE": "true",
  "PRIVACY_GUARD_GWS_COMMAND": "<gws の絶対パス>"
}
```

### 辞書と除外語

設定ファイルは `privacy_guard_mcp/config/` にあります。

| ファイル | 内容 | マスクの動作への反映 |
|---|---|---|
| `dictionaries/names_ja.yaml` | 日本語の姓・名の辞書。自社の取引先の人名などを足せる | 反映される |
| `exclusions.yaml` | 人名としてマスクしない語（役職名・敬称など）。`name_exclusion_keywords` の部分 | 反映される |
| `settings.yaml` | サーバー名・ログなどの既定値。`pg_check_rules` が内容を返す | 一部 |
| `masking_rules.yaml` | カテゴリの定義 | コードから読み込まれない。カテゴリを増減するには `privacy_guard_mcp/masking/patterns.py` を直す |

設定を変えたら、MCP サーバーを再起動します（アプリを開き直すか、CLI を再起動します）。

## 強制経由の設定

Claude の通常の Read ツールが機密ファイルを読めない状態にして初めて、Privacy Guard MCP は防御として働きます。要点は4つです。

1. 機密データを置くフォルダを決める（例: `~/work/sensitive/`）
2. ファイル名の規則を決める（例: 名前に「顧客」「面談」「個人情報」を入れる）
3. `settings.json` の `permissions.deny` に、そのフォルダとファイル名の通常 Read を登録する
4. `CLAUDE.md` に「機密は `pg_read_*` で読む」と書く

登録後は、機密フォルダのファイルを通常の Read で読ませて、ブロックされることを確認します。手順・設定例・チェックリストは [SECURITY_SETUP.md](./SECURITY_SETUP.md) にあります。

## テスト

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

テストデータは架空のデータだけです（`faker` の ja_JP で生成）。実在の個人情報は使わないでください。E2E テストは `tests/test_data/dummy/` にダミーファイルを生成します（Git の管理対象外です）。

セッション監査スクリプト（ディスクへの書き出しが無いことなどを静的に確認する）は次のとおりです。

```bash
./scripts/audit_session.sh
```

## よくある問題

| 症状 | 対処 |
|---|---|
| アプリの会話に `pg_*` ツールが出ない | アプリを ⌘Q で完全に終了して開き直す。`claude_desktop_config.json` の JSON 構文（カンマ・括弧）と、`command` のパスを確認する |
| `python3.12: command not found` | Python 3.11 以上を入れる。macOS なら `brew install python@3.12` |
| `pip install` に失敗する | 仮想環境（`.venv`）が有効か、または `.venv/bin/pip` を直接指定しているか確認する |
| `pg_gws_read` が「コマンドが見つからない」と返す | `PRIVACY_GUARD_GWS_COMMAND` または `PRIVACY_GUARD_GOG_COMMAND` に絶対パスを設定する |
| `.xls` が読めない | 旧形式は未対応。`.xlsx` に変換して読む |
| スキャン PDF の本文が空になる | 画像の PDF は文字を取り出せない。文字を含む PDF を使う |
| マスクが足りない・多すぎる | 辞書（`names_ja.yaml`）と除外語（`exclusions.yaml`）を調整する。正規表現は `patterns.py` |
| ログを見たい | ログは標準エラー出力に出る。`LOG_LEVEL=DEBUG` でも元の値は出ない（位置・文字数・マスク ID だけ） |

## ライセンス

MIT
