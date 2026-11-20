"""ダミーデータ自動生成スクリプト.

Faker（ja_JP）を使用して架空の個人情報を含むテストデータを生成する。
生成データは実在する個人情報を含まない。

生成ファイル:
    dummy_employees.csv   - 架空の従業員データ（UTF-8）
    dummy_clients.xlsx    - 架空のクライアントデータ
    dummy_email.txt       - 架空のメール文書
    dummy_config.txt      - 架空の設定ファイル（APIキー・パスワード含む）
    dummy_mixed.pdf       - 架空の混在データ（テキストPDF）
    dummy_sjis.csv        - 架空の従業員データ（Shift-JIS）

使い方:
    python tests/generate_dummy_data.py [output_dir]
    # output_dir 省略時は tests/test_data/dummy/ を使用

注意:
    本スクリプトで生成したデータはすべて架空データです。
    実在する人物・企業とは一切関係ありません。
"""

import csv
import io
import os
import sys
from pathlib import Path

from faker import Faker

# Faker（日本語）の初期化
fake = Faker("ja_JP")
fake.seed_instance(42)  # 再現性のためシードを固定


def generate_employees_csv(output_path: Path) -> None:
    """架空の従業員データCSVを生成する（UTF-8）."""
    rows = []
    for i in range(20):
        rows.append({
            "社員ID": f"EMP{i+1:04d}",
            "氏名": fake.name(),
            "メールアドレス": fake.ascii_email(),
            "電話番号": fake.phone_number(),
            "住所": fake.address().replace("\n", " "),
            "部署": fake.company_prefix() + "部",
            "入社日": fake.date_of_birth(minimum_age=22, maximum_age=60).strftime("%Y-%m-%d"),
        })

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"[生成] {output_path} ({len(rows)}件)")


def generate_clients_xlsx(output_path: Path) -> None:
    """架空のクライアントデータExcelを生成する."""
    try:
        import openpyxl
    except ImportError:
        print("[スキップ] openpyxl未インストール: dummy_clients.xlsx をスキップ")
        return

    wb = openpyxl.Workbook()

    # シート1: 個人クライアント
    ws1 = wb.active
    ws1.title = "個人クライアント"
    headers = ["顧客ID", "氏名", "メール", "電話番号", "住所", "契約種別"]
    ws1.append(headers)
    for i in range(10):
        ws1.append([
            f"CLI{i+1:04d}",
            fake.name(),
            fake.ascii_email(),
            fake.phone_number(),
            fake.address().replace("\n", " "),
            fake.random_element(["A", "B", "C"]),
        ])

    # シート2: 法人クライアント
    ws2 = wb.create_sheet("法人クライアント")
    corp_headers = ["法人ID", "会社名", "担当者", "メール", "電話番号", "住所"]
    ws2.append(corp_headers)
    for i in range(5):
        ws2.append([
            f"CORP{i+1:04d}",
            fake.company(),
            fake.name(),
            fake.ascii_email(),
            fake.phone_number(),
            fake.address().replace("\n", " "),
        ])

    wb.save(output_path)
    print(f"[生成] {output_path} (個人10件 + 法人5件)")


def generate_email_txt(output_path: Path) -> None:
    """架空のメール文書を生成する."""
    sender_name = fake.name()
    sender_email = fake.ascii_email()
    recipient_name = fake.name()
    recipient_email = fake.ascii_email()
    company = fake.company()
    phone = fake.phone_number()
    address = fake.address().replace("\n", " ")

    content = f"""From: {sender_name} <{sender_email}>
To: {recipient_name} <{recipient_email}>
Subject: ご連絡の件

{recipient_name} 様

お世話になっております。
{company} の {sender_name} と申します。

先日のお打ち合わせの件についてご連絡差し上げます。

ご確認の上、下記連絡先までお知らせください。

TEL: {phone}
住所: {address}

何卒よろしくお願い申し上げます。

--
{sender_name}
{company}
{sender_email}
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[生成] {output_path}")


def generate_config_txt(output_path: Path) -> None:
    """架空の設定ファイル（APIキー・パスワード含む）を生成する.

    注意: このファイルはマスキングテスト専用の架空データです。
    実際のAPIキーやパスワードではありません。
    """
    # 架空のAPIキー（ランダム文字列、実際のサービスとは無関係）
    fake_api_key = "sk-" + fake.lexify(text="?" * 48, letters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    fake_db_pass = fake.password(length=16, special_chars=True, digits=True, upper_case=True)
    fake_aws_key = "AKIA" + fake.lexify(text="?" * 16, letters="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
    fake_gh_token = "ghp_" + fake.lexify(text="?" * 36, letters="abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")

    content = f"""# 架空設定ファイル（テスト専用）
# 実際のAPIキー・パスワードは含みません

[database]
host = localhost
port = 5432
database = testdb
password = {fake_db_pass}

[api]
openai_api_key = {fake_api_key}
aws_access_key_id = {fake_aws_key}
github_token = {fake_gh_token}

[app]
debug = false
log_level = INFO
"""

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    print(f"[生成] {output_path}")


def generate_mixed_pdf(output_path: Path) -> None:
    """架空のPDFを生成する（pypdfでテキスト層あり）."""
    try:
        from reportlab.pdfgen import canvas as rl_canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        # 日本語フォント登録
        pdfmetrics.registerFont(UnicodeCIDFont("HeiseiMin-W3"))

        name = fake.name()
        email = fake.ascii_email()
        phone = fake.phone_number()

        c = rl_canvas.Canvas(str(output_path))
        c.setFont("HeiseiMin-W3", 12)
        c.drawString(50, 750, f"氏名: {name}")
        c.drawString(50, 730, f"メール: {email}")
        c.drawString(50, 710, f"電話番号: {phone}")
        c.save()
        print(f"[生成] {output_path} (reportlab使用)")

    except ImportError:
        # reportlab未インストール時はダミーPDFを fpdf で試みる
        try:
            from fpdf import FPDF

            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            pdf.cell(200, 10, txt=f"Name: {fake.last_romanized_name()} {fake.first_romanized_name()}", ln=True)
            pdf.cell(200, 10, txt=f"Email: {fake.ascii_email()}", ln=True)
            pdf.cell(200, 10, txt=f"Phone: {fake.phone_number()}", ln=True)
            pdf.output(str(output_path))
            print(f"[生成] {output_path} (fpdf使用)")

        except ImportError:
            # どちらも未インストールの場合は最小PDFをバイナリ生成
            name_en = f"{fake.last_romanized_name()} {fake.first_romanized_name()}"
            email = fake.ascii_email()
            _write_minimal_pdf(output_path, name_en, email)
            print(f"[生成] {output_path} (最小PDFバイナリ)")


def _write_minimal_pdf(output_path: Path, name: str, email: str) -> None:
    """最小構成のPDFをバイナリで生成する（ライブラリ不要）."""
    # 最小構成のPDF（テキスト層あり）
    stream_content = f"BT /F1 12 Tf 50 750 Td (Name: {name}) Tj 0 -20 Td (Email: {email}) Tj ET"
    stream_bytes = stream_content.encode("latin-1")
    stream_length = len(stream_bytes)

    pdf_content = f"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj

2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj

3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj

4 0 obj
<< /Length {stream_length} >>
stream
{stream_content}
endstream
endobj

5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj

xref
0 6
0000000000 65535 f
trailer
<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF"""

    with open(output_path, "wb") as f:
        f.write(pdf_content.encode("latin-1"))


def generate_sjis_csv(output_path: Path) -> None:
    """架空の従業員データCSVを生成する（Shift-JIS）."""
    rows = []
    for i in range(10):
        rows.append({
            "社員ID": f"EMP{i+1:04d}",
            "氏名": fake.name(),
            "メール": fake.ascii_email(),
            "電話": fake.phone_number(),
        })

    with open(output_path, "w", newline="", encoding="shift_jis", errors="replace") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)

    print(f"[生成] {output_path} ({len(rows)}件, Shift-JIS)")


def main(output_dir: str = None) -> None:
    """ダミーデータを生成する."""
    if output_dir is None:
        # デフォルト: tests/test_data/dummy/
        output_dir = Path(__file__).parent / "test_data" / "dummy"
    else:
        output_dir = Path(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"[出力先] {output_dir}")
    print()

    # 各ファイルを生成
    generate_employees_csv(output_dir / "dummy_employees.csv")
    generate_clients_xlsx(output_dir / "dummy_clients.xlsx")
    generate_email_txt(output_dir / "dummy_email.txt")
    generate_config_txt(output_dir / "dummy_config.txt")
    generate_mixed_pdf(output_dir / "dummy_mixed.pdf")
    generate_sjis_csv(output_dir / "dummy_sjis.csv")

    print()
    print(f"[完了] {output_dir} にダミーデータを生成しました")
    return str(output_dir)


if __name__ == "__main__":
    out_dir = sys.argv[1] if len(sys.argv) > 1 else None
    main(out_dir)
