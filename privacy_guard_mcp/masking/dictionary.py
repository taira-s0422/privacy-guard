"""辞書ファイル読み込み・文脈判定モジュール.

日本語姓名・企業名等の辞書を読み込み、テキスト内でのマッチングを行う。
辞書ファイルが存在しない場合は最小サンプルで動作する（後日OSS辞書で拡充予定）。
"""

import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# ========================================
# 初期最小サンプル辞書
# （Phase 5でOSS辞書に置き換え予定）
# ========================================

# 日本語姓の最小サンプル（法務省統計上位100件程度）
_SAMPLE_SURNAMES = [
    "佐藤", "鈴木", "高橋", "田中", "伊藤", "渡辺", "山本", "中村", "小林", "加藤",
    "吉田", "山田", "佐々木", "山口", "松本", "井上", "木村", "林", "斎藤", "清水",
    "山崎", "阿部", "森", "池田", "橋本", "山下", "石川", "中島", "前田", "藤田",
    "小川", "後藤", "岡田", "長谷川", "村上", "近藤", "石井", "斉藤", "坂本", "遠藤",
    "青木", "藤井", "西村", "福田", "太田", "三浦", "岡本", "松田", "中川", "中野",
    "原田", "小野", "田村", "竹内", "金子", "和田", "中山", "藤原", "石田", "上田",
    "森田", "原", "柴田", "酒井", "工藤", "横山", "宮崎", "宮本", "内田", "高木",
    "安藤", "谷口", "大野", "丸山", "今井", "江口", "高田", "菅原", "河野", "多田",
    "上野", "高橋", "岩田", "川口", "大西", "菊地", "横田", "杉山", "千葉", "市川",
    "村田", "古川", "永田", "津田", "平野", "吉川", "矢野", "関", "島田", "望月",
]

# 日本語名の最小サンプル（よくある名前）
_SAMPLE_GIVEN_NAMES = [
    "太郎", "一郎", "次郎", "三郎", "四郎", "五郎",
    "花子", "幸子", "恵子", "久子", "節子", "洋子",
    "健太", "翔太", "大輝", "拓也", "直樹", "雄一",
    "美咲", "優花", "さくら", "あかり", "ひなた", "ゆうか",
    "誠", "博", "隆", "宏", "浩", "聡", "俊", "亮",
    "舞", "葵", "凛", "結衣", "沙織", "彩",
    "達也", "哲也", "徹", "龍", "剛", "猛",
    "明", "光", "豊", "裕", "修", "勉", "勝", "武",
]


class DictionaryMatcher:
    """辞書マッチャー.

    YAMLファイルから辞書を読み込み、テキスト内の人名等を検知する。
    辞書ファイルが存在しない場合はメモリ内サンプルで動作する。
    """

    # 名前語尾文字（辞書登録された名の後に続く可能性が高い文字）.
    # 「○○子」「○○美」「○○樹」「○○実」「○○佳」など、
    # 名の末尾に1文字追加されてフルネームになるケースの取りこぼし防止用。
    # フルネームパターンの末尾に `[…]?` として付与する。
    # 女性語尾: 子・美・恵・香・里・樹・実・佳・代・乃・奈・菜・絵・江
    # 男性語尾: 平・郎・男・夫・雄・也・哉・輔・介・司・史・志・士・成・生・斗・翔・太・健・豪・剛・毅・登・渡
    # 共通: 之・音
    NAME_SUFFIX_CHARS = (
        "子美恵香里樹実佳代乃奈菜絵江"
        "平郎男夫雄也哉輔介司史志士成生斗翔太健豪剛毅登渡"
        "之輝音"
    )

    # 多文字名語尾（2文字以上のサフィックス）.
    # 「○○太郎」「○○次郎」「○○之介」のように単一文字では対応しきれないケース用。
    # フルネームパターンでは `(?:太郎|次郎|...)?` として末尾に付与する。
    NAME_SUFFIX_MULTI = [
        "太郎", "次郎", "三郎", "四郎", "五郎", "之介", "之助", "之輔", "一郎", "二郎",
    ]

    def __init__(
        self,
        dictionary_dir: Optional[str] = None,
        exclusions_path: Optional[str] = None,
    ) -> None:
        """初期化.

        Args:
            dictionary_dir: 辞書ファイルディレクトリ。None の場合はデフォルトパスを使用。
            exclusions_path: 除外設定YAMLパス。None の場合はデフォルトパスを使用。
        """
        self._surnames: List[str] = []
        self._given_names: List[str] = []
        self._company_suffixes: List[str] = []
        self._name_exclusion_keywords: set = set()

        # 辞書を読み込む
        self._load_dictionaries(dictionary_dir)

        # 除外設定を読み込む（列ヘッダ等の誤検知防止）
        self._load_exclusions(exclusions_path)

        # 辞書マッチング用の正規表現を構築
        self._surname_pattern: Optional[re.Pattern] = self._build_name_pattern(self._surnames)
        self._given_name_pattern: Optional[re.Pattern] = self._build_name_pattern(self._given_names)
        self._fullname_pattern: Optional[re.Pattern] = self._build_fullname_pattern()

    def _load_exclusions(self, exclusions_path: Optional[str]) -> None:
        """除外設定（name_exclusion_keywords）を読み込む.

        ファイルが見つからない場合は空集合で動作。
        """
        if exclusions_path is None:
            default_path = Path(__file__).parent.parent / "config" / "exclusions.yaml"
            exclusions_path = str(default_path)

        path = Path(exclusions_path)
        if not path.exists():
            logger.info(f"除外設定ファイルが見つかりません: {path}")
            return
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            keywords = (data.get("exclusions", {}) or {}).get("name_exclusion_keywords", []) or []
            self._name_exclusion_keywords = set(k for k in keywords if isinstance(k, str))
            logger.info(
                f"除外キーワード読み込み完了: {len(self._name_exclusion_keywords)} 件"
            )
        except Exception as e:
            logger.warning(f"除外設定読み込み失敗: {e}")

    def is_name_excluded(self, text: str) -> bool:
        """テキストが人名検知から除外すべきキーワードに該当するか判定する.

        判定ロジック:
        - text 全体が除外語と完全一致 → True
        - text に含まれる空白区切りトークンのいずれかが除外語と完全一致 → True
          （例: 「電話番号 住所」のようなヘッダ連結に対応）
        """
        if not text:
            return False
        kws = self._name_exclusion_keywords
        if not kws:
            return False
        if text in kws:
            return True
        # 空白（半角・全角）で分割して各トークンを判定
        tokens = re.split(r"[\s　]+", text)
        for tok in tokens:
            if tok and tok in kws:
                return True
        return False

    def _load_dictionaries(self, dictionary_dir: Optional[str]) -> None:
        """辞書ファイルを読み込む.

        ファイルが存在しない場合はメモリ内サンプルにフォールバック。

        Args:
            dictionary_dir: 辞書ファイルディレクトリ
        """
        if dictionary_dir is None:
            # デフォルトパス（プロジェクトルートからの相対パス）
            default_dir = Path(__file__).parent.parent / "config" / "dictionaries"
            dictionary_dir = str(default_dir)

        names_ja_path = Path(dictionary_dir) / "names_ja.yaml"

        if names_ja_path.exists():
            try:
                with open(names_ja_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                    self._surnames = data.get("surnames", [])
                    self._given_names = data.get("given_names", [])
                    logger.info(
                        f"辞書読み込み完了: 姓 {len(self._surnames)} 件, "
                        f"名 {len(self._given_names)} 件"
                    )
            except Exception as e:
                logger.warning(f"辞書ファイル読み込み失敗、サンプルにフォールバック: {e}")
                self._surnames = _SAMPLE_SURNAMES
                self._given_names = _SAMPLE_GIVEN_NAMES
        else:
            logger.info("辞書ファイルが見つかりません。最小サンプルで動作します。")
            self._surnames = _SAMPLE_SURNAMES
            self._given_names = _SAMPLE_GIVEN_NAMES

    def _build_name_pattern(self, names: List[str]) -> Optional[re.Pattern]:
        """名前リストから正規表現パターンを構築する.

        Args:
            names: 名前リスト

        Returns:
            コンパイル済みパターン（リストが空なら None）
        """
        if not names:
            return None

        # 長い名前を優先（部分マッチ防止）
        sorted_names = sorted(names, key=len, reverse=True)
        escaped = [re.escape(name) for name in sorted_names]
        pattern_str = r"(?:" + "|".join(escaped) + r")"

        try:
            return re.compile(pattern_str, re.UNICODE)
        except re.error as e:
            logger.error(f"名前パターン構築エラー: {e}")
            return None

    def _build_fullname_pattern(self) -> Optional[re.Pattern]:
        """姓+名の結合パターンを構築する.

        Args:
            なし

        Returns:
            コンパイル済みパターン（辞書が空なら None）
        """
        if not self._surnames or not self._given_names:
            return None

        # 姓リストと名リストから姓名結合パターンを構築
        sorted_surnames = sorted(self._surnames, key=len, reverse=True)
        sorted_given = sorted(self._given_names, key=len, reverse=True)

        surname_part = r"(?:" + "|".join(re.escape(s) for s in sorted_surnames) + r")"
        given_part = r"(?:" + "|".join(re.escape(g) for g in sorted_given) + r")"

        # 姓名の間に空白があってもなくても検知
        # \u59d3\u540d\u306e\u9593\u306e\u7a7a\u767d\uff08\u534a\u89d2\u30fb\u5168\u89d2\uff09\u6709\u7121\u306b\u5bfe\u5fdc\u3002
        # \u3055\u3089\u306b\u3001\u540d\u306e\u672b\u5c3e1\u6587\u5b57\uff08\u5b50\u30fb\u7f8e\u30fb\u6a39\u30fb\u5b9f\u30fb\u4f73 \u7b49\uff09\u304c\u7d9a\u304f\u5834\u5408\u306f\u7bc4\u56f2\u3092\u62e1\u5f35\u3059\u308b
        # \uff08\u8f9e\u66f8\u672a\u53ce\u9332\u306e\u6d3e\u751f\u540d\u300c\u25cb\u25cb\u5b50\u300d\u300c\u25cb\u25cb\u7f8e\u300d\u7b49\u306e\u53d6\u308a\u3053\u307c\u3057\u9632\u6b62\uff09\u3002
        # \u591a\u6587\u5b57\u8a9e\u5c3e\u3092\u512a\u5148\u7684\u306b\u30de\u30c3\u30c1\u3055\u305b\u3001\u7121\u3051\u308c\u3070\u5358\u4e00\u6587\u5b57\u8a9e\u5c3e\u3001\u7121\u3051\u308c\u3070\u7a7a\u306b\u30d5\u30a9\u30fc\u30eb\u30d0\u30c3\u30af.
        # \u4e26\u3073\u9806: \u9577\u3044\u30de\u30c3\u30c1\u512a\u5148\u306e\u305f\u3081\u591a\u6587\u5b57\u8a9e\u5c3e\u3092\u5148\u982d\u306b\u7f6e\u304f\u3002
        multi_suffix = "|".join(re.escape(s) for s in self.NAME_SUFFIX_MULTI)
        single_suffix_class = "[" + re.escape(self.NAME_SUFFIX_CHARS) + "]"
        suffix_class = r"(?:" + multi_suffix + r"|" + single_suffix_class + r")?"
        pattern_str = surname_part + r"[\s\u3000]?" + given_part + suffix_class

        try:
            return re.compile(pattern_str, re.UNICODE)
        except re.error as e:
            logger.error(f"フルネームパターン構築エラー: {e}")
            return None

    def find_names(self, text: str) -> List[Tuple[str, int, int]]:
        """テキスト内の日本語人名を検知する.

        Args:
            text: 対象テキスト

        Returns:
            (マッチした文字列, 開始位置, 終了位置) のリスト
        """
        results: List[Tuple[str, int, int]] = []

        if not text:
            return results

        # フルネームパターンで検索
        if self._fullname_pattern:
            for match in self._fullname_pattern.finditer(text):
                matched = match.group(0)
                # 列ヘッダ等の除外語に該当する場合はスキップ
                if self.is_name_excluded(matched):
                    continue
                results.append((matched, match.start(), match.end()))

        # 重複を除去（フルネームマッチを優先）
        return self._deduplicate_spans(results)

    def _deduplicate_spans(
        self, spans: List[Tuple[str, int, int]]
    ) -> List[Tuple[str, int, int]]:
        """重複スパンを除去する（長いマッチを優先）.

        Args:
            spans: (text, start, end) のリスト

        Returns:
            重複除去済みのリスト
        """
        if not spans:
            return spans

        # 開始位置でソート、同じ開始位置は長い方を優先
        sorted_spans = sorted(spans, key=lambda x: (x[1], -(x[2] - x[1])))

        result = []
        last_end = 0
        for text, start, end in sorted_spans:
            if start >= last_end:
                result.append((text, start, end))
                last_end = end

        return result
