"""X自動投稿ボット エントリポイント

使い方:
  # バッチ完了後に手動起動
  python post_to_x_bot.py --mode batch --top-n 5

  # 毎日定期投稿モード
  python post_to_x_bot.py --mode daily --top-n 10

  # ドライラン（投稿せずログのみ）
  python post_to_x_bot.py --mode batch --dry-run
"""

from __future__ import annotations

import argparse

from x_bot.session_extractor import extract_top_sessions
from x_bot.summarizer import SessionSummarizer
from x_bot.social_client import SocialClientFactory
from x_bot.post_scheduler import PostScheduler


def main():
    parser = argparse.ArgumentParser(description="X自動投稿ボット")
    parser.add_argument("--mode", choices=["batch", "daily"], default="batch")
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--platform", choices=["x", "bluesky"], default="x")
    args = parser.parse_args()

    # 高品質セッション抽出
    print("セッション抽出中...")
    sessions = extract_top_sessions(top_n=args.top_n, mode=args.mode)
    if not sessions:
        print("投稿対象セッションなし")
        return

    print(f"{len(sessions)} セッション抽出完了")

    # ローカルLLMで要約生成
    print("要約生成中...")
    summarizer = SessionSummarizer()
    posts = [summarizer.generate(s) for s in sessions]

    # SNSクライアント取得（dry-runの場合はクライアント不要）
    if args.dry_run:
        client = None
    else:
        client = SocialClientFactory.create(platform=args.platform)

    # スケジューリング投稿
    scheduler = PostScheduler(client, dry_run=args.dry_run)
    scheduler.run(posts)


if __name__ == "__main__":
    main()
