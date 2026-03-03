"""セッション後の分析レポート生成"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path


# 行動カテゴリ判定用キーワード
ACTION_CATEGORIES = {
    "戦闘": ["攻撃", "斬", "切", "殴", "蹴", "防御", "盾", "回避", "構え", "剣", "弓", "魔法攻撃"],
    "探索": ["調べ", "調査", "探", "観察", "解析", "見回", "索敵", "探知", "確認"],
    "対話": ["話", "尋ね", "聞", "交渉", "説得", "会話", "声をかけ", "呼びかけ"],
    "支援": ["回復", "治療", "薬", "援護", "支援", "守", "庇", "応急", "手当"],
}


def categorize_action(action_text: str) -> str:
    """アクションテキストをカテゴリに分類する"""
    scores: dict[str, int] = {}
    for category, keywords in ACTION_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in action_text)
        if score > 0:
            scores[category] = score
    if scores:
        return max(scores, key=scores.get)
    return "その他"


def detect_cooperation(actions: list[dict]) -> list[str]:
    """同一ターン内のアクション間の連携を検出する"""
    cooperations = []
    if len(actions) < 2:
        return cooperations

    for i, a1 in enumerate(actions):
        for a2 in actions[i + 1 :]:
            # 別キャラの名前に言及していたら連携とみなす
            if a2["character"] in a1["action"] or a1["character"] in a2["action"]:
                cooperations.append(
                    f"{a1['character']}と{a2['character']}が連携"
                )
            # 支援→攻撃パターン
            cat1 = categorize_action(a1["action"])
            cat2 = categorize_action(a2["action"])
            if (cat1 == "支援" and cat2 == "戦闘") or (
                cat1 == "戦闘" and cat2 == "支援"
            ):
                cooperations.append(
                    f"{a1['character']}({cat1})→{a2['character']}({cat2})の連携"
                )
    return cooperations


def analyze_session(json_path: str) -> str:
    """JSONログを分析してレポートを生成する"""
    path = Path(json_path)
    if not path.exists():
        return f"エラー: ファイルが見つかりません: {json_path}"

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    metadata = data.get("metadata", {})

    # キャラクター別アクション収集
    char_actions: dict[str, list[str]] = {}
    turn_actions: list[list[dict]] = []
    current_turn_actions: list[dict] = []

    for msg in messages:
        if msg.get("source") == "ai":
            name = msg.get("name", "不明")
            content = msg.get("content", "")
            # 【キャラ名】プレフィックスを除去
            action_text = re.sub(r"^【[^】]+】\s*", "", content)
            char_actions.setdefault(name, []).append(action_text)
            current_turn_actions.append(
                {"character": name, "action": action_text}
            )
        elif msg.get("role") == "assistant" and current_turn_actions:
            # GMレスポンスでターン区切り
            turn_actions.append(current_turn_actions)
            current_turn_actions = []

    if current_turn_actions:
        turn_actions.append(current_turn_actions)

    lines = [
        "# セッション分析レポート",
        "",
        f"- シナリオ: {metadata.get('scenario', '不明')}",
        f"- プレイヤー数: {metadata.get('player_count', '不明')}",
        f"- 総メッセージ数: {len(messages)}",
        "",
    ]

    # キャラクター行動パターン分析
    lines.append("## キャラクター行動パターン")
    lines.append("")

    for char_name, actions in char_actions.items():
        lines.append(f"### {char_name}")
        lines.append(f"- 総行動数: {len(actions)}")

        category_counts = Counter(categorize_action(a) for a in actions)
        total = len(actions)
        for cat in ["戦闘", "探索", "対話", "支援", "その他"]:
            count = category_counts.get(cat, 0)
            if count > 0:
                pct = count / total * 100
                bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
                lines.append(f"  - {cat}: {bar} {pct:.0f}% ({count}回)")
        lines.append("")

    # 連携パターン分析
    lines.append("## 連携パターン")
    all_cooperations = []
    for ta in turn_actions:
        cooperations = detect_cooperation(ta)
        all_cooperations.extend(cooperations)

    if all_cooperations:
        coop_counts = Counter(all_cooperations)
        for coop, count in coop_counts.most_common():
            lines.append(f"- {coop} (×{count})")
    else:
        lines.append("- 明確な連携パターンは検出されませんでした")
    lines.append("")

    # セッション品質スコア
    lines.append("## セッション品質スコア")
    lines.append("")

    # テンポ: 平均アクション長
    all_actions = [a for actions in char_actions.values() for a in actions]
    avg_len = sum(len(a) for a in all_actions) / max(len(all_actions), 1)
    tempo_score = min(10, max(1, 10 - abs(avg_len - 40) / 10))

    # 多様性: カテゴリの分散度
    all_categories = [categorize_action(a) for a in all_actions]
    unique_cats = len(set(all_categories))
    diversity_score = min(10, unique_cats * 2.5)

    # 連携度
    coop_score = min(10, len(all_cooperations) * 2)

    overall = (tempo_score + diversity_score + coop_score) / 3

    lines.append(f"- テンポ: {tempo_score:.1f}/10（平均行動長: {avg_len:.0f}文字）")
    lines.append(f"- 多様性: {diversity_score:.1f}/10（{unique_cats}カテゴリ使用）")
    lines.append(f"- 連携度: {coop_score:.1f}/10（{len(all_cooperations)}回検出）")
    lines.append(f"- **総合: {overall:.1f}/10**")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print("使い方: python session_analyzer.py <session_log.json>")
        sys.exit(1)

    report = analyze_session(sys.argv[1])
    print(report)

    # レポートをファイルにも保存
    json_path = Path(sys.argv[1])
    report_path = json_path.with_name(
        json_path.stem + "_analysis.md"
    )
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nレポートを保存しました: {report_path}")


if __name__ == "__main__":
    main()
