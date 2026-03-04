"""QualityEvaluator ドメインサービス — エントリの品質評価ロジック

「何を良いデータとするか」の定義を明文化し、
Phase 3（ファインチューニング）で「何を学習させているか」を追跡可能にする。

評価ルール一覧と配点は `python quality_evaluator.py rules` で確認できる。
用語定義は ubiquitous_language.md を参照。
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from memory_layer_classifier import MemoryLayerClassifier
from session_analyzer import WORLD_BREAK_PATTERNS


# ── 評価ルール ──────────────────────────────────────

@dataclass
class EvaluationRule:
    """1つの評価ルールの結果を表すデータクラス。"""

    name: str       # ルール名（例: "response_length"）
    max_score: int   # 最大配点
    score: int       # 実際の得点
    reason: str      # 判定理由（例: "応答が247文字のため満点"）
    passed: bool     # ルールを満たしたか


# エラーメッセージ検出パターン
_ERROR_PATTERNS = ["error", "エラー", "sorry", "申し訳", "cannot", "できません"]


# ── ドメインサービス ─────────────────────────────────

class QualityEvaluator:
    """ドメインサービス：エントリの品質を評価する。

    責務：
    - 各評価ルールを独立したメソッドとして持つ
    - 評価の理由を必ず記録する
    - スコアの意味を ubiquitous_language.md と整合させる

    責務外：
    - ファイルの読み書き（log_pipeline.py が担当）
    - LLM 呼び出し（score_entry_llm() が担当）
    """

    # FT候補の閾値（ubiquitous_language.md: FTCandidate の定義と同期）
    FT_CANDIDATE_THRESHOLD = 70

    _memory_classifier = MemoryLayerClassifier()

    # 評価ルールメソッドの一覧（順序は表示・実行順）
    _RULE_METHODS = [
        "_rule_response_length",
        "_rule_world_consistency",
        "_rule_role_adherence",
        "_rule_no_error",
    ]

    def evaluate(self, entry: dict) -> dict:
        """エントリを評価し、training_data フィールドを更新して返す。

        Returns:
            更新された training_data dict。
        """
        td = entry.get("training_data", {})

        rules: list[EvaluationRule] = []
        for method_name in self._RULE_METHODS:
            rule = getattr(self, method_name)(entry)
            rules.append(rule)

        total_score = sum(r.score for r in rules)
        flags = [r.name for r in rules if not r.passed]

        # 世界観逸脱数は world_consistency ルールから取得
        world_violations = 0
        for r in rules:
            if r.name == "world_consistency":
                # reason から件数を復元（"世界観逸脱キーワードN件" の形式）
                m = re.search(r"(\d+)件", r.reason)
                if m:
                    world_violations = int(m.group(1))
                break

        td["quality_score"] = total_score
        td["quality_flags"] = flags
        td["is_good_example"] = total_score >= self.FT_CANDIDATE_THRESHOLD
        td["world_consistency"] = world_violations
        td["evaluation_detail"] = [asdict(r) for r in rules]
        td["memory_layer"] = self._memory_classifier.classify(entry)

        entry["training_data"] = td
        return td

    # ── 評価ルール（各メソッドが1つのルールに対応） ──

    def _rule_response_length(self, entry: dict) -> EvaluationRule:
        """ルール：応答長
        根拠：短すぎる応答は物語に貢献しない（ubiquitous_language.md 参照）

        配点：
        - 200文字以上: 20点（満点）物語に十分な情報量がある
        - 50〜199文字: 10点       最低限の情報はある
        - 50文字未満:   0点       物語への貢献が不十分
        """
        response = entry.get("response", "")
        resp_len = len(response)

        if resp_len >= 200:
            return EvaluationRule(
                name="response_length", max_score=20, score=20,
                reason=f"応答が{resp_len}文字のため満点",
                passed=True,
            )
        if resp_len >= 50:
            return EvaluationRule(
                name="response_length", max_score=20, score=10,
                reason=f"応答が{resp_len}文字（50〜199文字）のため半点",
                passed=True,
            )
        return EvaluationRule(
            name="response_length", max_score=20, score=0,
            reason=f"応答が{resp_len}文字で50文字未満のため0点",
            passed=False,
        )

    def _rule_world_consistency(self, entry: dict) -> EvaluationRule:
        """ルール：世界観準拠度
        根拠：世界観逸脱はFTデータとして有害（ubiquitous_language.md 参照）

        配点：
        - 違反0件: 40点（満点）
        - 違反1件: 20点
        - 違反2件以上: 0点

        session_analyzer.py の WORLD_BREAK_PATTERNS を使用。
        """
        response = entry.get("response", "")
        violation_count = 0
        matched_words: list[str] = []
        for pattern, _ptype in WORLD_BREAK_PATTERNS:
            m = re.search(pattern, response)
            if m:
                violation_count += 1
                matched_words.append(m.group())

        if violation_count == 0:
            return EvaluationRule(
                name="world_consistency", max_score=40, score=40,
                reason="世界観逸脱キーワード0件",
                passed=True,
            )
        if violation_count == 1:
            return EvaluationRule(
                name="world_consistency", max_score=40, score=20,
                reason=f"世界観逸脱キーワード1件（「{'、'.join(matched_words)}」）",
                passed=False,
            )
        return EvaluationRule(
            name="world_consistency", max_score=40, score=0,
            reason=f"世界観逸脱キーワード{violation_count}件（「{'、'.join(matched_words)}」）",
            passed=False,
        )

    def _rule_role_adherence(self, entry: dict) -> EvaluationRule:
        """ルール：ロール準拠
        根拠：role フィールドが不正なエントリは学習データとして使えない

        配点：
        - "GM" または "player": 20点
        - それ以外: 0点
        """
        role = entry.get("role", "")
        if role in ("GM", "player"):
            return EvaluationRule(
                name="role_adherence", max_score=20, score=20,
                reason=f'role="{role}" は有効なロール',
                passed=True,
            )
        return EvaluationRule(
            name="role_adherence", max_score=20, score=0,
            reason=f'role="{role}" は無効（"GM" または "player" のみ有効）',
            passed=False,
        )

    def _rule_no_error(self, entry: dict) -> EvaluationRule:
        """ルール：エラーなし
        根拠：エラー応答を学習させるとモデルがエラー文言を覚える

        配点：
        - エラーなし: 20点
        - エラーあり / 空応答: 0点

        検出パターン: ["error", "エラー", "sorry", "申し訳", "cannot", "できません"]
        """
        response = entry.get("response", "")
        if not response:
            return EvaluationRule(
                name="no_error", max_score=20, score=0,
                reason="応答が空のため0点",
                passed=False,
            )
        response_lower = response.lower()
        matched = [p for p in _ERROR_PATTERNS if p in response_lower]
        if matched:
            return EvaluationRule(
                name="no_error", max_score=20, score=0,
                reason=f'エラー文言検出（「{"、".join(matched)}」）',
                passed=False,
            )
        return EvaluationRule(
            name="no_error", max_score=20, score=20,
            reason="エラー文言なし",
            passed=True,
        )

    # ── ルール一覧取得 ──

    def list_rules(self) -> list[dict]:
        """全評価ルールの名前・配点・根拠を返す。"""
        rules_info = []
        for method_name in self._RULE_METHODS:
            method = getattr(self, method_name)
            doc = method.__doc__ or ""
            # docstring の1行目からルール名、2行目から根拠を抽出
            lines = [l.strip() for l in doc.strip().split("\n") if l.strip()]
            rule_label = lines[0].replace("ルール：", "") if lines else method_name
            rationale = ""
            for line in lines:
                if line.startswith("根拠："):
                    rationale = line.replace("根拠：", "")
                    break

            # max_score はダミーエントリで取得
            dummy = {"response": "x" * 300, "role": "GM", "training_data": {}}
            result = method(dummy)
            rules_info.append({
                "name": result.name,
                "max_score": result.max_score,
                "label": rule_label,
                "rationale": rationale,
            })
        return rules_info


# ── CLI ─────────────────────────────────────────────


def _cmd_rules():
    """評価ルール一覧を表示する。"""
    evaluator = QualityEvaluator()
    rules = evaluator.list_rules()
    total = sum(r["max_score"] for r in rules)

    print("=== QualityEvaluator 評価ルール一覧 ===")
    print(f"{'ルール名':<22s} {'配点':>4s}  根拠")
    print("─" * 60)
    for r in rules:
        print(f"{r['name']:<22s} {r['max_score']:>3d}点  {r['rationale']}")
    print("─" * 60)
    print(f"{'合計':<22s} {total:>3d}点")
    print(f"{'FT候補閾値':<22s} {evaluator.FT_CANDIDATE_THRESHOLD:>3d}点"
          f"（ubiquitous_language.md準拠）")


def _cmd_test(jsonl_path: str):
    """JSONL ファイルの先頭エントリを評価テストする。"""
    path = Path(jsonl_path)
    if not path.exists():
        print(f"エラー: ファイルが見つかりません: {jsonl_path}")
        return

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entry = json.loads(line)
                break
        else:
            print("エラー: 有効なエントリがありません")
            return

    evaluator = QualityEvaluator()
    td = evaluator.evaluate(entry)

    session_id = entry.get("session_id", "不明")[:12]
    turn = entry.get("turn", "?")
    role = entry.get("role", "?")

    print("=== エントリ評価テスト ===")
    print(f"対象: {session_id} / turn:{turn} / role:{role}")
    print()
    print(f"{'ルール':<22s} {'得点':>7s}   判定理由")
    print("─" * 70)
    for detail in td["evaluation_detail"]:
        score_str = f"{detail['score']}/{detail['max_score']}"
        print(f"{detail['name']:<22s} {score_str:>7s}   {detail['reason']}")
    print("─" * 70)

    total = td["quality_score"]
    max_total = sum(d["max_score"] for d in td["evaluation_detail"])
    print(f"{'合計スコア':<22s} {total}/{max_total}")

    if td["is_good_example"]:
        print(f"{'FT候補判定':<22s} ✅ FT候補（閾値{evaluator.FT_CANDIDATE_THRESHOLD}点以上）")
    else:
        print(f"{'FT候補判定':<22s} ❌ 非候補（閾値{evaluator.FT_CANDIDATE_THRESHOLD}点未満）")


def main():
    parser = argparse.ArgumentParser(description="QualityEvaluator — 評価ルール管理")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("rules", help="評価ルール一覧と配点を表示")

    p_test = sub.add_parser("test", help="1エントリのテスト評価")
    p_test.add_argument("path", help="JSONL ファイルパス")

    args = parser.parse_args()

    if args.command == "rules":
        _cmd_rules()
    elif args.command == "test":
        _cmd_test(args.path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
