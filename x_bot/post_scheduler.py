"""スパム対策付き投稿スケジューラー"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime
from pathlib import Path

from x_bot.session_extractor import mark_as_posted

LOG_DIR = Path("x_posts")
DAILY_LIMIT = 16
INTERVAL_MIN = 30 * 60  # 30分
INTERVAL_MAX = 90 * 60  # 90分


class PostScheduler:
    def __init__(self, client, dry_run: bool = False):
        self.client = client
        self.dry_run = dry_run

    def run(self, posts: list[dict]):
        LOG_DIR.mkdir(exist_ok=True)
        log_path = LOG_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        results = []

        for i, post in enumerate(posts[:DAILY_LIMIT]):
            if i > 0:
                interval = random.randint(INTERVAL_MIN, INTERVAL_MAX)
                print(f"次の投稿まで {interval // 60} 分待機...")
                if not self.dry_run:
                    time.sleep(interval)

            result = self._post_one(post)
            results.append(result)

        # ログ保存
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)

        # 投稿済みIDを記録
        posted_ids = [r["session_id"] for r in results if r.get("success")]
        if posted_ids:
            mark_as_posted(posted_ids)

        print(f"\n完了: {len(posted_ids)}/{len(posts)} 件投稿 -> {log_path}")

    def _post_one(self, post: dict) -> dict:
        text = post["text"]
        print(f"\n[{'DRY RUN' if self.dry_run else 'POST'}] {text}")

        if self.dry_run:
            return {**post, "success": True, "dry_run": True, "timestamp": datetime.now().isoformat()}

        try:
            result = self.client.post(text)
            return {**post, "success": True, "timestamp": datetime.now().isoformat(), **result}
        except Exception as e:
            print(f"投稿失敗: {e}")
            return {**post, "success": False, "error": str(e)}
