"""SDND Theater — シアターモード — AIたちの即興劇場"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# sdnd-trpg を sys.path に追加して import
SDND_TRPG_PATH = os.getenv("SDND_TRPG_PATH", "../sdnd-trpg")
sys.path.insert(0, str(Path(SDND_TRPG_PATH).resolve()))

from ai_player import AIPlayer  # noqa: E402
from characters import PLAYABLE_CHARACTERS  # noqa: E402
from llm_backend import GeminiBackend  # noqa: E402
from scenarios import SCENARIOS  # noqa: E402
from spec_loader import load_specs  # noqa: E402
from gm import build_system_prompt  # noqa: E402

from observer import Observer  # noqa: E402

# ── 定数 ──────────────────────────────────────────
MAX_HISTORY = 30

BANNER = """
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    ⚔  SDND Theater  ⚔
    〜 シアターモード — AIたちの即興劇場 〜
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

GAME_START_PROMPT = (
    "ゲームを開始してください。シナリオの状況を描写し、"
    "パーティが最初に直面する場面を臨場感たっぷりに演出してください。"
)


# ── パーティ構築 ──────────────────────────────────
def build_theater_party_section(members: list[tuple[str, str]]) -> str:
    """全員AIプレイヤーのパーティ構成セクションを構築する"""
    lines = ["## AIプレイヤー（シアターモード）"]
    for name, detail in members:
        lines.append(f"\n### {name}")
        lines.append(detail)

    party_size = len(members)
    lines.append(f"\n※ {party_size}人パーティです。全員AIが操作しています。")
    lines.append("NPCとしてではなく、プレイヤーキャラクターとして扱ってください。")
    lines.append("各キャラクターの個性と能力を活かした場面展開を心がけてください。")
    return "\n".join(lines)


# ── セッション保存 ─────────────────────────────────
def save_session(
    messages: list[dict],
    metadata: dict,
    observer: Observer,
    session_dir: Path,
):
    """セッションログをMDとJSONで保存し、Observerレポートも出力する"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"theater_{timestamp}"

    # Markdown ログ
    md_path = session_dir / f"{base_name}.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# SDND Theater Session\n")
        f.write(f"日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"シナリオ: {metadata.get('scenario', '不明')}\n")
        f.write(f"プレイヤー数: {metadata.get('player_count', '不明')}\n")
        f.write(f"ターン数: {metadata.get('turns', '不明')}\n")
        f.write(f"モデル: {metadata.get('model', '不明')}\n\n")
        f.write("---\n\n")
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if msg.get("source") == "ai":
                f.write(f"🤖 {content}\n\n")
            elif role == "user":
                f.write(f"🎮 {content}\n\n")
            elif role == "assistant":
                f.write(f"📖 GM: {content}\n\n")

    # JSON ログ
    json_path = session_dir / f"{base_name}.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {"metadata": metadata, "messages": messages},
            f,
            ensure_ascii=False,
            indent=2,
        )

    # Observer レポート
    report_path = session_dir / f"{base_name}_observer.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(observer.generate_report())

    return md_path, json_path, report_path


# ── メイン ─────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="SDND Theater - AIたちの即興劇場")
    parser.add_argument("--turns", type=int, default=3, help="ターン数 (default: 3)")
    parser.add_argument(
        "--players", type=int, default=2, choices=[1, 2, 3],
        help="AIプレイヤー人数 (default: 2)",
    )
    parser.add_argument("--scenario", type=str, default=None, help="シナリオ名")
    parser.add_argument("--model", type=str, default=None, help="使用モデル名")
    return parser.parse_args()


def select_characters(count: int) -> list[tuple[str, str]]:
    """PLAYABLEキャラからcount人を選択（「オリジナル」除外）"""
    available = [
        (name, data["detail"])
        for name, data in PLAYABLE_CHARACTERS.items()
        if name != "オリジナル" and data.get("detail")
    ]
    if count > len(available):
        count = len(available)
    return available[:count]


def main():
    args = parse_args()

    print(BANNER)

    # ── 初期化 ──
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ GEMINI_API_KEY が設定されていません。.env を確認してください。")
        sys.exit(1)

    print("⚙  初期化中...")

    # specs 読み込み
    specs = load_specs()

    # LLMバックエンド
    backend = GeminiBackend(api_key)
    if args.model:
        backend.MODEL = args.model
        print(f"   モデル: {args.model}")
    else:
        print(f"   モデル: {backend.MODEL}")

    # Observer
    observer = Observer()

    # キャラクター選択
    members = select_characters(args.players)
    char_names = [name for name, _ in members]
    print(f"   パーティ: {', '.join(char_names)}")

    # AIPlayer インスタンス生成
    ai_players = [
        AIPlayer(backend, name, detail) for name, detail in members
    ]

    # シナリオ選択
    if args.scenario and args.scenario in SCENARIOS:
        scenario_name = args.scenario
    else:
        scenario_name = random.choice(list(SCENARIOS.keys()))
    scenario_text = SCENARIOS[scenario_name]
    print(f"   シナリオ: {scenario_name}")

    # パーティセクション＆システムプロンプト構築
    party_section = build_theater_party_section(members)
    system_prompt = build_system_prompt(party_section, scenario_text, specs)

    # セッションディレクトリ
    session_dir = Path(__file__).parent / "sessions"
    session_dir.mkdir(exist_ok=True)

    print()
    print("=" * 50)
    print(f"  🗺️  シナリオ: {scenario_name}")
    print(f"  👥 パーティ: {', '.join(char_names)}")
    print(f"  🔄 ターン数: {args.turns}")
    print("=" * 50)
    print()

    # ── メッセージ履歴 ──
    messages: list[dict] = []
    metadata = {
        "scenario": scenario_name,
        "player_count": len(ai_players),
        "turns": args.turns,
        "model": args.model or backend.MODEL,
        "characters": char_names,
        "started_at": datetime.now().isoformat(),
    }

    # ── 開幕シーン ──
    print("📖 ゲーム開始...")
    print("-" * 40)
    messages.append({"role": "user", "content": GAME_START_PROMPT})

    try:
        opening = backend.chat(system_prompt, messages, max_output_tokens=1024)
    except Exception as e:
        print(f"❌ API エラー: {e}")
        sys.exit(1)

    messages.append({"role": "assistant", "content": opening})
    print(f"📖 GM: {opening}")
    print()

    # ── ターンループ ──
    for turn in range(1, args.turns + 1):
        print(f"{'─' * 20} ターン {turn} {'─' * 20}")
        print()

        turn_actions: list[dict] = []

        for player in ai_players:
            # AI行動決定
            try:
                action = player.decide_action(messages)
            except Exception as e:
                print(f"❌ {player.char_name} の行動生成エラー: {e}")
                action = f"{player.char_name}は様子を見ている。"

            # Observer チェック
            violations = observer.check_action(player.char_name, action)
            for v in violations:
                print(f"⚠️  Observer: [{v.code}] {v.character} — {v.description}")

            # メッセージに追加
            action_msg = {
                "role": "user",
                "content": f"【{player.char_name}】{action}",
                "source": "ai",
                "name": player.char_name,
            }
            messages.append(action_msg)
            print(f"🤖 【{player.char_name}】{action}")

            # GM応答
            try:
                gm_response = backend.chat(system_prompt, messages[-MAX_HISTORY:])
            except Exception as e:
                print(f"❌ GM応答エラー: {e}")
                gm_response = "（GMが応答できませんでした）"
                time.sleep(2)

            messages.append({"role": "assistant", "content": gm_response})
            print(f"📖 GM: {gm_response}")
            print()

            turn_actions.append({
                "character": player.char_name,
                "action": action,
                "gm_response": gm_response,
            })

            # API レート制限対策
            time.sleep(1)

        observer.record_turn(turn, turn_actions)

    # ── セッション終了 ──
    print("=" * 50)
    print("  ⚔  セッション終了  ⚔")
    print("=" * 50)
    print()

    metadata["ended_at"] = datetime.now().isoformat()

    # ログ保存
    md_path, json_path, report_path = save_session(
        messages, metadata, observer, session_dir
    )
    print(f"📝 セッションログ: {md_path}")
    print(f"📝 JSONログ: {json_path}")
    print(f"📝 Observerレポート: {report_path}")
    print()

    # Observer サマリ表示
    report = observer.generate_report()
    violation_count = len(observer.violations)
    total_actions = sum(len(r["actions"]) for r in observer.turn_records)
    if violation_count == 0:
        print(f"✅ Observer: 全{total_actions}アクション — 違反なし")
    else:
        print(f"⚠️  Observer: {violation_count}件の違反を検出（{total_actions}アクション中）")
        for v in observer.violations:
            print(f"   - ターン{v.turn} [{v.code}] {v.character}: {v.description}")
    print()

    print(f"💡 分析コマンド: python session_analyzer.py {json_path}")


if __name__ == "__main__":
    main()
