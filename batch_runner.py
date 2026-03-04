"""バッチ実行スクリプト — theater_session.py を繰り返し実行しログを蓄積する

コスト目安（--turns 2 --players 2 の場合）:
  Gemini Flash-Lite: 100セッション ≈ ¥50〜150
  Claude Haiku:      100セッション ≈ ¥150〜500
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ── 定数 ──

MAX_RETRIES = 3
RETRY_WAIT = 30  # 秒
PROGRESS_FILE = Path("sessions/batch_progress.json")
ERROR_LOG = Path("sessions/batch_errors.log")


# ── ヘルパー ──


def _raw_jsonl_files() -> set[str]:
    """sessions/raw/ 内の JSONL ファイル名セットを返す。"""
    raw_dir = Path("sessions/raw")
    if not raw_dir.exists():
        return set()
    return {p.name for p in raw_dir.glob("*.jsonl")}


def _run_session(turns: int, players: int, provider: str | None) -> subprocess.CompletedProcess:
    """theater_session.py をサブプロセスで1回実行する。"""
    cmd = [
        sys.executable, "theater_session.py",
        "--turns", str(turns),
        "--players", str(players),
    ]
    if provider:
        cmd += ["--provider", provider]

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"

    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(Path(__file__).parent),
    )


def _score_session(jsonl_name: str) -> dict | None:
    """log_pipeline.py score をインポートして実行する。"""
    try:
        from log_pipeline import score_session
        summary = score_session(f"sessions/raw/{jsonl_name}")
        return summary
    except Exception as e:
        print(f"    ⚠ スコアリングエラー: {e}")
        return None


def _log_error(session_num: int, error_msg: str):
    """エラーログに追記する。"""
    ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ERROR_LOG, "a", encoding="utf-8") as f:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{ts}] session #{session_num}: {error_msg}\n")


def _save_progress(progress: dict):
    """進捗を JSON に保存する。"""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ── メイン ──


def run_batch(
    count: int,
    turns: int,
    players: int,
    provider: str | None,
    interval: int,
    auto_score: bool,
    dry_run: bool,
):
    provider_display = provider or os.getenv("LLM_PROVIDER", "gemini")

    print()
    print("=== バッチ実行開始 ===")
    print(f"設定: {count}セッション / turns={turns} / players={players} "
          f"/ provider={provider_display}")
    if dry_run:
        print("(ドライラン: 実行しません)")
        print()
        return
    print("─" * 40)
    print()

    success = 0
    failed = 0
    total_entries = 0
    total_good = 0

    progress = {
        "started_at": datetime.now().isoformat(),
        "config": {
            "count": count, "turns": turns,
            "players": players, "provider": provider_display,
        },
        "completed": 0,
        "failed": 0,
        "results": [],
    }

    try:
        for i in range(1, count + 1):
            print(f"[{i}/{count}] 実行中...")

            before = _raw_jsonl_files()
            ok = False

            for attempt in range(MAX_RETRIES + 1):
                t0 = time.time()
                result = _run_session(turns, players, provider)
                elapsed = time.time() - t0

                if result.returncode == 0:
                    ok = True
                    break

                error_msg = result.stderr.strip().split("\n")[-1] if result.stderr else "不明なエラー"
                is_api_error = any(code in error_msg for code in ("503", "429", "APIエラー"))

                if is_api_error and attempt < MAX_RETRIES:
                    print(f"  ❌ APIエラー発生 → {RETRY_WAIT}秒待機後リトライ "
                          f"({attempt + 1}/{MAX_RETRIES})")
                    time.sleep(RETRY_WAIT)
                    continue

                print(f"  ❌ 失敗: {error_msg}")
                _log_error(i, error_msg)
                break

            if ok:
                after = _raw_jsonl_files()
                new_files = after - before
                new_file = new_files.pop() if new_files else "不明"

                print(f"  ✅ 完了 ({elapsed:.1f}秒) → {new_file}")

                session_result = {"session": i, "file": new_file, "elapsed": round(elapsed, 1)}

                if auto_score and new_file != "不明":
                    summary = _score_session(new_file)
                    if summary:
                        avg = summary["avg_quality_score"]
                        rec = summary["recommendation"]
                        good = summary["good_examples"]
                        n = summary["total_entries"]
                        print(f"  📊 スコアリング完了 → avg:{avg} / {rec}")
                        total_entries += n
                        total_good += good
                        session_result["avg_score"] = avg
                        session_result["recommendation"] = rec

                success += 1
                progress["results"].append(session_result)
            else:
                failed += 1

            progress["completed"] = success
            progress["failed"] = failed
            _save_progress(progress)

            # セッション間インターバル
            if i < count:
                time.sleep(interval)

    except KeyboardInterrupt:
        print()
        print("  ⚠ Ctrl+C で中断されました")

    # ── サマリー ──
    print()
    print("─" * 40)
    print("=== バッチ完了 ===")
    print(f"成功: {success} / 失敗: {failed}")
    if total_entries > 0:
        pct = total_good / total_entries * 100
        print(f"総エントリ数: {total_entries}件")
        print(f"FT候補エントリ: {total_good}件 ({pct:.1f}%)")
    cumulative = len(_raw_jsonl_files())
    print(f"累計セッション数: sessions/raw/ 内 {cumulative}件")
    print()

    progress["ended_at"] = datetime.now().isoformat()
    progress["completed"] = success
    progress["failed"] = failed
    _save_progress(progress)


def parse_args():
    parser = argparse.ArgumentParser(description="SDND Theater バッチ実行")
    parser.add_argument("--count", type=int, default=10, help="実行セッション数 (default: 10)")
    parser.add_argument("--turns", type=int, default=2, help="各セッションのターン数 (default: 2)")
    parser.add_argument("--players", type=int, default=2, choices=[1, 2, 3],
                        help="プレイヤー数 (default: 2)")
    parser.add_argument("--provider", type=str, default=None,
                        choices=["gemini", "claude"], help="LLMプロバイダー")
    parser.add_argument("--interval", type=int, default=3,
                        help="セッション間の待機秒数 (default: 3)")
    parser.add_argument("--no-score", action="store_true",
                        help="自動スコアリングを無効化")
    parser.add_argument("--dry-run", action="store_true",
                        help="設定確認のみ（実行しない）")
    return parser.parse_args()


def main():
    args = parse_args()
    run_batch(
        count=args.count,
        turns=args.turns,
        players=args.players,
        provider=args.provider,
        interval=args.interval,
        auto_score=not args.no_score,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
