"""QA Observer — invariant違反の監視とセッション品質チェック"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Violation:
    """検出された違反"""

    turn: int
    character: str
    code: str
    description: str
    action_text: str


class Observer:
    """セッション中の invariant 違反を監視する QA Observer"""

    # キーワードベースのハードガード定義
    HARD_GUARDS: list[dict] = [
        {
            "code": "INV-A02",
            "description": "MP上限超過の疑い（大量魔法連発）",
            "patterns": [
                r"連続.{0,5}魔法",
                r"魔法.{0,10}連発",
                r"全力.{0,5}魔法",
                r"無限.{0,5}(魔力|MP|マナ)",
            ],
        },
        {
            "code": "INV-B02",
            "description": "未登録魔法の使用疑い",
            "patterns": [
                r"禁術",
                r"禁忌.{0,5}魔法",
                r"古代魔法",
                r"失われた.{0,5}魔法",
            ],
        },
        {
            "code": "INV-C01",
            "description": "世界観逸脱（現代技術の言及）",
            "patterns": [
                r"スマ[ホー]",
                r"インターネット",
                r"パソコン",
                r"SNS",
                r"電話",
                r"テレビ",
            ],
        },
        {
            "code": "INV-D01",
            "description": "キャラクター逸脱（5歳児の超人的行動）",
            "patterns": [
                r"アル.{0,20}(巨大な剣|重い武器|大剣)",
            ],
        },
    ]

    def __init__(self):
        self.violations: list[Violation] = []
        self.turn_records: list[dict] = []
        self.loop_touches: list[dict] = []
        self.current_turn: int = 0

    def check_action(self, character: str, action: str) -> list[Violation]:
        """アクションテキストを検査し、違反があれば記録して返す"""
        found: list[Violation] = []
        for guard in self.HARD_GUARDS:
            for pattern in guard["patterns"]:
                if re.search(pattern, action):
                    v = Violation(
                        turn=self.current_turn,
                        character=character,
                        code=guard["code"],
                        description=guard["description"],
                        action_text=action[:100],
                    )
                    self.violations.append(v)
                    found.append(v)
                    break  # 同じガード内で複数マッチしても1回だけ記録
        return found

    def record_turn(self, turn: int, actions: list[dict]):
        """ターン結果を記録する

        Args:
            turn: ターン番号
            actions: [{"character": str, "action": str, "gm_response": str}, ...]
        """
        self.current_turn = turn
        self.turn_records.append({"turn": turn, "actions": actions})

    def record_loop_touch(self, turn: int, loop_name: str, description: str):
        """伏線への接触を記録する"""
        self.loop_touches.append(
            {"turn": turn, "loop_name": loop_name, "description": description}
        )

    def generate_report(self) -> str:
        """Markdown形式のObserverレポートを生成する"""
        lines = [
            "# QA Observer レポート",
            f"生成日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"総ターン数: {len(self.turn_records)}",
            "",
        ]

        # 違反サマリ
        lines.append("## Invariant 違反")
        if self.violations:
            lines.append(f"検出数: {len(self.violations)}")
            lines.append("")
            lines.append("| ターン | キャラ | コード | 内容 |")
            lines.append("|--------|--------|--------|------|")
            for v in self.violations:
                lines.append(
                    f"| {v.turn} | {v.character} | {v.code} | {v.description} |"
                )
        else:
            lines.append("違反なし ✅")
        lines.append("")

        # 伏線接触
        lines.append("## 伏線接触")
        if self.loop_touches:
            for touch in self.loop_touches:
                lines.append(
                    f"- ターン{touch['turn']}: **{touch['loop_name']}** — {touch['description']}"
                )
        else:
            lines.append("伏線接触なし")
        lines.append("")

        # 遵守率
        total_actions = sum(len(r["actions"]) for r in self.turn_records)
        violation_count = len(self.violations)
        if total_actions > 0:
            compliance_rate = (1 - violation_count / total_actions) * 100
        else:
            compliance_rate = 100.0
        lines.append("## 遵守率")
        lines.append(
            f"- 総アクション数: {total_actions}"
        )
        lines.append(f"- 違反数: {violation_count}")
        lines.append(f"- 遵守率: {compliance_rate:.1f}%")

        return "\n".join(lines)
