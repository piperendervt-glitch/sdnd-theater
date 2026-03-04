"""ログパイプライン — セッションJSONLの検証・スコアリング・FT/DPOペア抽出"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any

from quality_evaluator import QualityEvaluator

# ── スキーマ定義 ──

REQUIRED_FIELDS = {
    "timestamp", "session_id", "turn", "role", "character",
    "provider", "scene_type", "messages", "system_prompt_hash",
    "response", "game_state", "training_data",
}

TRAINING_DATA_FIELDS = {
    "quality_score", "quality_flags", "is_good_example",
    "ft_pair_extracted", "dpo_candidates", "world_consistency",
}


# ── スキーマ検証 ──

def validate_log_schema(entry: dict) -> list[str]:
    """ログエントリが必要なフィールドを持つか検証する。

    Returns:
        エラーメッセージのリスト。空なら有効。
    """
    errors = []
    missing = REQUIRED_FIELDS - set(entry.keys())
    if missing:
        errors.append(f"トップレベルフィールド不足: {missing}")
    td = entry.get("training_data")
    if isinstance(td, dict):
        td_missing = TRAINING_DATA_FIELDS - set(td.keys())
        if td_missing:
            errors.append(f"training_data フィールド不足: {td_missing}")
    elif td is not None:
        errors.append(f"training_data は dict であるべき (実際: {type(td).__name__})")
    return errors


# ── セッション一覧・読み込み ──

def list_sessions(raw_dir: str | Path = "sessions/raw") -> list[Path]:
    """rawディレクトリのセッションJSONLファイル一覧を返す（更新日時順）。"""
    raw = Path(raw_dir)
    if not raw.exists():
        return []
    return sorted(raw.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)


def load_session_log(jsonl_path: str | Path) -> list[dict]:
    """セッションJSONLファイルの全エントリを読み込む。"""
    entries = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"  警告: {jsonl_path}:{line_num} JSONパースエラー: {e}")
    return entries


# ── 品質スコアリング ──

_evaluator = QualityEvaluator()


def score_entry(
    entry: dict,
    observer_violations: list[dict] | None = None,
) -> dict:
    """QualityEvaluator に委譲。シグネチャは従来と同一。

    Returns:
        更新された training_data dict。
    """
    return _evaluator.evaluate(entry)


_LLM_JUDGE_PROMPT = """\
あなたはTRPGセッションの品質評価者です。
以下のAI応答を評価し、JSON形式のみで返してください。

【評価対象】
役割: {role}
シーン種別: {scene_type}
ユーザー入力: {last_user_message}
AI応答: {response}

【評価基準】
- world_quality (0-40): 世界観への準拠度。エルディア世界の設定に沿っているか
- narrative_quality (0-40): 物語への貢献度。展開を豊かにしているか
- character_consistency (0-20): キャラクターの一貫性

【出力形式】JSON のみ、前置き・後置き不要
{{"world_quality": 整数, "narrative_quality": 整数, "character_consistency": 整数, "llm_score_total": 合計整数, "llm_judge_reason": "1〜2文の評価理由"}}"""


def score_entry_llm(entry: dict, backend) -> dict:
    """LLM-as-Judge によるスコアリング。training_data を補完する。

    注意: 1エントリ1APIコール。大量実行時はコストに注意。
    Haiku で 1コール ≈ ¥0.1〜0.5 程度。100エントリ ≈ ¥10〜50。
    """
    td = entry.get("training_data", {})
    response = entry.get("response", "")
    messages = entry.get("messages", [])

    last_user = ""
    for msg in messages:
        if msg.get("role") == "user":
            last_user = msg["content"]

    prompt = _LLM_JUDGE_PROMPT.format(
        role=entry.get("role", ""),
        scene_type=entry.get("scene_type", ""),
        last_user_message=last_user[:300],
        response=response[:500],
    )

    try:
        raw = backend.chat(
            system="あなたはJSON評価器です。JSON以外を出力しないでください。",
            messages=[{"role": "user", "content": prompt}],
            max_output_tokens=256,
        )
        # JSON 部分だけ抽出（前後の余計なテキスト対策）
        json_match = re.search(r"\{[^{}]+\}", raw, re.DOTALL)
        if not json_match:
            raise ValueError(f"JSON が見つかりません: {raw[:100]}")
        result = json.loads(json_match.group())

        td["llm_score"] = result.get("llm_score_total")
        td["llm_judge"] = {
            "world_quality": result.get("world_quality"),
            "narrative_quality": result.get("narrative_quality"),
            "character_consistency": result.get("character_consistency"),
            "reason": result.get("llm_judge_reason", ""),
        }
    except Exception as e:
        print(f"    LLM-Judge エラー（スキップ）: {e}")
        td["llm_score"] = None
        td["llm_judge"] = None

    entry["training_data"] = td
    return td


def score_session(
    jsonl_path: str | Path,
    observer_report_path: str | Path | None = None,
    use_llm: bool = False,
) -> dict:
    """セッション全エントリをスコアリングし sessions/scored/ に出力する。

    Args:
        jsonl_path: raw JSONL ファイルパス
        observer_report_path: Observer レポート MD パス（任意）
        use_llm: True の場合 LLM-as-Judge も実行

    Returns:
        セッションサマリー dict
    """
    entries = load_session_log(jsonl_path)

    violations: list[dict] = []
    if observer_report_path:
        violations = _parse_observer_violations(observer_report_path)

    # ルールベーススコアリング
    for entry in entries:
        score_entry(entry, violations)

    # LLM-as-Judge（オプション）
    if use_llm:
        from llm_client import ClaudeBackend
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            print("  ⚠ ANTHROPIC_API_KEY 未設定。LLM-Judge をスキップします。")
        else:
            judge_backend = ClaudeBackend(api_key)
            for i, entry in enumerate(entries):
                print(f"    LLM-Judge: {i + 1}/{len(entries)}...")
                score_entry_llm(entry, judge_backend)

    # scored/ に出力
    scored_dir = Path("sessions/scored")
    scored_dir.mkdir(parents=True, exist_ok=True)
    out_path = scored_dir / Path(jsonl_path).name

    with open(out_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # サマリー生成
    scores = [e["training_data"]["quality_score"] for e in entries]
    good_count = sum(1 for e in entries if e["training_data"].get("is_good_example"))
    total_world = sum(e["training_data"].get("world_consistency", 0) for e in entries)
    avg_score = sum(scores) / max(len(scores), 1)

    if avg_score >= 70:
        recommendation = "FT候補"
    elif avg_score >= 50:
        recommendation = "要確認"
    else:
        recommendation = "除外推奨"

    session_id = entries[0].get("session_id", Path(jsonl_path).stem) if entries else ""

    summary = {
        "session_id": session_id,
        "total_entries": len(entries),
        "good_examples": good_count,
        "avg_quality_score": round(avg_score, 1),
        "world_violations": total_world,
        "recommendation": recommendation,
        "scored_path": str(out_path),
    }
    return summary


def _parse_observer_violations(report_path: str | Path) -> list[dict]:
    """Observer Markdownレポートから違反レコードを抽出する。"""
    violations = []
    try:
        text = Path(report_path).read_text(encoding="utf-8")
        for match in re.finditer(
            r"\|\s*(\d+)\s*\|\s*(\S+)\s*\|\s*(INV-\w+)\s*\|\s*(.+?)\s*\|", text
        ):
            violations.append({
                "turn": int(match.group(1)),
                "character": match.group(2),
                "code": match.group(3),
                "description": match.group(4),
            })
    except FileNotFoundError:
        pass
    return violations


# ── FT ペア抽出 ──

def extract_ft_pairs(
    scored_path: str | Path,
    output_dir: str | Path = "sessions/ft_pairs",
    min_score: float = 70.0,
) -> Path:
    """is_good_example=True のエントリから FT 用 input/output ペアを抽出する。"""
    entries = load_session_log(scored_path)
    ft_dir = Path(output_dir)
    ft_dir.mkdir(parents=True, exist_ok=True)
    out_path = ft_dir / Path(scored_path).name

    with open(out_path, "w", encoding="utf-8") as f:
        for entry in entries:
            td = entry.get("training_data", {})
            score = td.get("quality_score", 0)
            if score < min_score:
                continue

            messages = entry.get("messages", [])
            last_user = ""
            for msg in messages:
                if msg["role"] == "user":
                    last_user = msg["content"]

            # 直近6メッセージをコンテキストとして保持
            pair = {
                "instruction": last_user,
                "input": json.dumps(messages[-6:], ensure_ascii=False),
                "output": entry["response"],
                "metadata": {
                    "session_id": entry.get("session_id"),
                    "turn": entry.get("turn"),
                    "role": entry.get("role"),
                    "quality_score": score,
                    "system_prompt_hash": entry.get("system_prompt_hash"),
                },
            }
            f.write(json.dumps(pair, ensure_ascii=False) + "\n")

    return out_path


# ── DPO 候補抽出 ──

def extract_dpo_pairs(
    scored_path: str | Path,
    output_dir: str | Path = "sessions/dpo_pairs",
) -> Path:
    """DPO 用の選好候補を抽出する。セッション間で同一コンテキストの比較に使用。"""
    entries = load_session_log(scored_path)
    dpo_dir = Path(output_dir)
    dpo_dir.mkdir(parents=True, exist_ok=True)
    out_path = dpo_dir / Path(scored_path).name

    with open(out_path, "w", encoding="utf-8") as f:
        for entry in entries:
            td = entry.get("training_data", {})
            score = td.get("quality_score")
            if score is None:
                continue

            messages = entry.get("messages", [])
            last_user = ""
            for msg in messages:
                if msg["role"] == "user":
                    last_user = msg["content"]

            candidate = {
                "prompt": last_user,
                "context": json.dumps(messages[-6:], ensure_ascii=False),
                "response": entry["response"],
                "quality_score": score,
                "session_id": entry.get("session_id"),
                "turn": entry.get("turn"),
                "role": entry.get("role"),
                "scene_type": entry.get("scene_type"),
                "system_prompt_hash": entry.get("system_prompt_hash"),
            }
            f.write(json.dumps(candidate, ensure_ascii=False) + "\n")

    return out_path


# ── 一括処理 ──

def _process_all():
    """未処理の全 raw セッションをスコアリング＋抽出する。"""
    scored_dir = Path("sessions/scored")
    already_scored = (
        {p.name for p in scored_dir.glob("*.jsonl")} if scored_dir.exists() else set()
    )

    raw_sessions = list_sessions()
    if not raw_sessions:
        print("  raw セッションが見つかりません。")
        return

    for raw_path in raw_sessions:
        if raw_path.name in already_scored:
            print(f"  スキップ（処理済み）: {raw_path.name}")
            continue
        print(f"  処理中: {raw_path.name}...")
        summary = score_session(raw_path)
        scored_path = summary["scored_path"]
        ft = extract_ft_pairs(scored_path)
        dpo = extract_dpo_pairs(scored_path)
        print(f"    scored   -> {scored_path}")
        print(f"    ft_pairs -> {ft}")
        print(f"    dpo_pairs -> {dpo}")
        print(f"    avg: {summary['avg_quality_score']}  "
              f"good: {summary['good_examples']}/{summary['total_entries']}  "
              f"→ {summary['recommendation']}")


def _show_summary():
    """スコアリング済みセッションのサマリーを表示する。"""
    scored_dir = Path("sessions/scored")
    if not scored_dir.exists():
        print("  scored/ ディレクトリが見つかりません。先に score を実行してください。")
        return

    scored_files = sorted(scored_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime)
    if not scored_files:
        print("  スコアリング済みセッションなし")
        return

    print("=== スコアリング済みセッション一覧 ===")
    total_entries = 0
    total_good = 0

    for sf in scored_files:
        entries = load_session_log(sf)
        if not entries:
            continue
        scores = [e["training_data"]["quality_score"] for e in entries
                  if e.get("training_data", {}).get("quality_score") is not None]
        good = sum(1 for e in entries if e.get("training_data", {}).get("is_good_example"))
        avg = sum(scores) / max(len(scores), 1)

        if avg >= 70:
            rec = "FT候補"
        elif avg >= 50:
            rec = "要確認"
        else:
            rec = "除外推奨"

        session_id = entries[0].get("session_id", sf.stem)[:12]
        print(f"  {session_id}  avg:{avg:.1f}  good:{good}/{len(entries)}  → {rec}")
        total_entries += len(entries)
        total_good += good

    print("---")
    print(f"合計エントリ: {total_entries}件 / FT候補: {total_good}件")


# ── CLI ──

def main():
    parser = argparse.ArgumentParser(description="SDND ログパイプライン")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="raw セッション一覧を表示")

    p_val = sub.add_parser("validate", help="JSONL スキーマ検証")
    p_val.add_argument("path", help="JSONL ファイルパス")

    p_score = sub.add_parser("score", help="セッションをスコアリング")
    p_score.add_argument("path", help="raw JSONL ファイルパス")
    p_score.add_argument("--observer", default=None, help="Observer レポート MD パス")
    p_score.add_argument("--llm", action="store_true", help="LLM-as-Judge も実行")

    sub.add_parser("summary", help="スコアリング済みセッションのサマリー表示")

    p_ft = sub.add_parser("extract-ft", help="FT ペアを抽出")
    p_ft.add_argument("path", help="scored JSONL ファイルパス")
    p_ft.add_argument("--min-score", type=float, default=70.0)

    p_dpo = sub.add_parser("extract-dpo", help="DPO 候補を抽出")
    p_dpo.add_argument("path", help="scored JSONL ファイルパス")

    sub.add_parser("process-all", help="全未処理セッションを一括処理")

    args = parser.parse_args()

    if args.command == "list":
        sessions = list_sessions()
        if not sessions:
            print("  セッションなし")
        else:
            print(f"  {len(sessions)} セッション:")
            for s in sessions:
                entries = load_session_log(s)
                print(f"    {s.name}  ({len(entries)} calls)")

    elif args.command == "validate":
        entries = load_session_log(args.path)
        total_errors = 0
        for i, entry in enumerate(entries):
            errors = validate_log_schema(entry)
            if errors:
                total_errors += len(errors)
                for e in errors:
                    print(f"  エントリ {i}: {e}")
        if total_errors == 0:
            print(f"  全 {len(entries)} エントリ: 有効 ✅")
        else:
            print(f"  {total_errors} 件のエラー検出")

    elif args.command == "score":
        summary = score_session(
            args.path,
            getattr(args, "observer", None),
            use_llm=getattr(args, "llm", False),
        )
        print(f"  スコアリング完了 -> {summary['scored_path']}")
        print(f"  avg: {summary['avg_quality_score']}  "
              f"good: {summary['good_examples']}/{summary['total_entries']}  "
              f"→ {summary['recommendation']}")

    elif args.command == "summary":
        _show_summary()

    elif args.command == "extract-ft":
        out = extract_ft_pairs(args.path, min_score=args.min_score)
        print(f"  FT ペア抽出完了 -> {out}")

    elif args.command == "extract-dpo":
        out = extract_dpo_pairs(args.path)
        print(f"  DPO 候補抽出完了 -> {out}")

    elif args.command == "process-all":
        _process_all()

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
