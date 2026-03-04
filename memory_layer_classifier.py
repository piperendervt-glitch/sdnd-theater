"""MemoryLayerClassifier ドメインサービス — エントリの記憶層分類ロジック

SDNDの5層記憶構造に基づき、各エントリに memory_layer タグを付与する。
将来の Consolidation エージェント・RAG・ファインチューニングで
記憶層ごとにデータを分類・活用するための基盤（Phase 2.5）。

分類ルール一覧は `python memory_layer_classifier.py rules` で確認できる。
用語定義は ubiquitous_language.md を参照。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

# 有効な scene_type 値（procedural 判定に使用）
_PROCEDURAL_SCENE_TYPES = frozenset({"combat", "dialogue", "exploration", "narration"})


class MemoryLayerClassifier:
    """ドメインサービス：エントリの記憶層を分類する。

    責務：
    - エントリの属性から適切な memory_layer を判定する
    - 分類ルールを明文化し追跡可能にする

    責務外：
    - ファイルの読み書き（CLI の backfill コマンドが担当）
    - semantic 層の付与（Consolidation エージェントのみが担当）
    """

    # 分類ルール（優先順位順）
    _RULES = [
        {
            "priority": 1,
            "layer": "skill",
            "condition": 'role == "GM"',
            "description": "GM の応答はゲーム進行スキルの記録",
        },
        {
            "priority": 2,
            "layer": "skill",
            "condition": 'role == "player"',
            "description": "Player の行動決定はロールプレイスキルの記録",
        },
        {
            "priority": 3,
            "layer": "procedural",
            "condition": "scene_type が combat/dialogue/exploration/narration のいずれか",
            "description": "場面に紐づく手続き的記憶",
        },
        {
            "priority": 4,
            "layer": "episodic",
            "condition": "上記に該当しないエントリ",
            "description": "セッション完了後のエピソード記録",
        },
    ]

    def classify(self, entry: dict) -> str:
        """エントリの属性から記憶層を判定する。

        分類優先順位:
        1. role == "GM"      → "skill"
        2. role == "player"  → "skill"
        3. scene_type が combat/dialogue/exploration/narration → "procedural"
        4. それ以外          → "episodic"

        注: working は実行中セッション内でのみ使用。
            semantic は自動付与禁止（Consolidation エージェントのみ）。

        Returns:
            記憶層名（"skill", "procedural", "episodic" のいずれか）
        """
        role = entry.get("role", "")
        if role in ("GM", "player"):
            return "skill"

        scene_type = entry.get("scene_type", "")
        if scene_type in _PROCEDURAL_SCENE_TYPES:
            return "procedural"

        return "episodic"

    def classify_batch(self, entries: list[dict]) -> list[dict]:
        """エントリリストに一括で memory_layer を付与する。

        既に memory_layer が設定されているエントリはスキップする（冪等）。

        Returns:
            memory_layer が付与された entries（元のリストを変更して返す）
        """
        for entry in entries:
            td = entry.get("training_data", {})
            if "memory_layer" not in td:
                td["memory_layer"] = self.classify(entry)
                entry["training_data"] = td
        return entries

    def list_rules(self) -> list[dict]:
        """分類ルール一覧を返す。"""
        return list(self._RULES)


# ── CLI ─────────────────────────────────────────────


def _cmd_rules():
    """分類ルール一覧を表示する。"""
    classifier = MemoryLayerClassifier()
    rules = classifier.list_rules()

    print("=== MemoryLayerClassifier 分類ルール一覧 ===")
    print(f"{'優先度':>6s}  {'記憶層':<12s}  条件 / 説明")
    print("─" * 65)
    for r in rules:
        print(f"{r['priority']:>6d}  {r['layer']:<12s}  {r['condition']}")
        print(f"{'':>6s}  {'':.<12s}  {r['description']}")
    print("─" * 65)
    print("注: semantic は自動付与禁止（Consolidation エージェントのみ）")
    print("注: working は実行中セッション内でのみ使用（保存済みログには付与しない）")


def _cmd_backfill():
    """sessions/scored/ の全 JSONL ファイルに memory_layer を一括付与する。"""
    scored_dir = Path("sessions/scored")
    if not scored_dir.exists():
        print(f"エラー: ディレクトリが見つかりません: {scored_dir}")
        return

    classifier = MemoryLayerClassifier()
    files = sorted(scored_dir.glob("*.jsonl"))

    if not files:
        print("対象ファイルがありません")
        return

    total_entries = 0
    tagged_entries = 0
    skipped_entries = 0

    for filepath in files:
        lines = filepath.read_text(encoding="utf-8").splitlines()
        updated_lines = []
        file_tagged = 0
        file_skipped = 0

        for line in lines:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            td = entry.get("training_data", {})
            total_entries += 1

            if "memory_layer" in td:
                file_skipped += 1
                skipped_entries += 1
            else:
                td["memory_layer"] = classifier.classify(entry)
                entry["training_data"] = td
                file_tagged += 1
                tagged_entries += 1

            updated_lines.append(json.dumps(entry, ensure_ascii=False))

        filepath.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")

    print("=== backfill 完了 ===")
    print(f"対象ファイル数: {len(files)}")
    print(f"全エントリ数:   {total_entries}")
    print(f"新規タグ付与:   {tagged_entries}")
    print(f"スキップ:       {skipped_entries}（既に memory_layer あり）")


def _cmd_test(jsonl_path: str):
    """JSONL ファイルの各エントリの分類結果を確認する。"""
    path = Path(jsonl_path)
    if not path.exists():
        print(f"エラー: ファイルが見つかりません: {jsonl_path}")
        return

    classifier = MemoryLayerClassifier()
    entries = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))

    if not entries:
        print("エラー: 有効なエントリがありません")
        return

    session_id = entries[0].get("session_id", "不明")[:12]
    print(f"=== memory_layer 分類テスト: {session_id}... ===")
    print(f"{'turn':>5s}  {'role':<8s}  {'scene_type':<14s}  {'memory_layer':<12s}")
    print("─" * 50)

    layer_counts: dict[str, int] = {}
    for entry in entries:
        layer = classifier.classify(entry)
        turn = entry.get("turn", "?")
        role = entry.get("role", "?")
        scene_type = entry.get("scene_type", "-")
        print(f"{str(turn):>5s}  {role:<8s}  {scene_type:<14s}  {layer:<12s}")
        layer_counts[layer] = layer_counts.get(layer, 0) + 1

    print("─" * 50)
    print("集計:")
    for layer, count in sorted(layer_counts.items()):
        print(f"  {layer:<12s}: {count}件")


def main():
    parser = argparse.ArgumentParser(
        description="MemoryLayerClassifier — 5層記憶の分類管理"
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("rules", help="分類ルール一覧を表示")
    sub.add_parser("backfill", help="sessions/scored/ の全ファイルに memory_layer を一括付与")

    p_test = sub.add_parser("test", help="1ファイルの分類結果を確認")
    p_test.add_argument("path", help="JSONL ファイルパス")

    args = parser.parse_args()

    if args.command == "rules":
        _cmd_rules()
    elif args.command == "backfill":
        _cmd_backfill()
    elif args.command == "test":
        _cmd_test(args.path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
