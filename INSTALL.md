# インストールガイド

導入手順は [README.md](./README.md) の「導入」にまとめています。このファイルは案内だけです。

## 手順の置き場

- Claude アプリだけを使う人: README の「導入」→「2-A」
- Claude Code CLI も使う人: README の「導入」→「2-B」
- うまく動かない時: README の「よくある問題」

## 導入後に必ずやること

Privacy Guard MCP は、入れただけでは防御になりません。通常の Read ツールで読まれたファイルは、マスクされずにそのまま AI に渡ります。

導入が終わったら、[SECURITY_SETUP.md](./SECURITY_SETUP.md) の手順で、機密ファイルへの通常の Read を禁止してください。

## 動作確認

Claude に次のように頼みます。

```text
pg_mask_text で「山田太郎 090-1234-5678 yamada@example.com」をマスクして
```

次のように返れば正常です（番号は 001 から振られます）。

```text
[MASKED_NAME_001] [MASKED_PHONE_001] [MASKED_EMAIL_001]
```
