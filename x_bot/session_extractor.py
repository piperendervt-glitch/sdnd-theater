"""sessions/scored/ からスコア上位セッションを抽出する"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

SCORED_DIR = Path("sessions/scored")
POSTED_LOG = Path("x_posts/posted_ids.json")


def extract_top_sessions(top_n: int = 5, mode: str = "batch") -> list[dict]:
    """
    スコア上位セッションを返す。
    既投稿セッションは除外する（重複投稿防止）。

    Returns:
        [{"session_id": str, "score": float, "entries": [{"content": str, "score": int, ...}]}]
    """
    posted_ids = _load_posted_ids()

    # エントリをセッション単位でグルーピング
    sessions: dict[str, list[dict]] = defaultdict(list)

    for path in sorted(SCORED_DIR.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
        with open(path, encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                sid = data.get("session_id")
                if not sid or sid in posted_ids:
                    continue
                score = data.get("training_data", {}).get("quality_score", 0)
                sessions[sid].append({
                    "content": data.get("response", ""),
                    "score": score,
                    "role": data.get("role", ""),
                    "character": data.get("character"),
                    "scene_type": data.get("scene_type", ""),
                })

    # セッション単位で平均スコア算出
    ranked = []
    for sid, entries in sessions.items():
        avg_score = sum(e["score"] for e in entries) / len(entries) if entries else 0
        ranked.append({
            "session_id": sid,
            "score": avg_score,
            "entries": entries,
        })

    ranked.sort(key=lambda s: s["score"], reverse=True)
    return ranked[:top_n]


def mark_as_posted(session_ids: list[str]):
    """投稿完了セッションIDを記録"""
    posted = _load_posted_ids()
    posted.update(session_ids)
    POSTED_LOG.parent.mkdir(exist_ok=True)
    with open(POSTED_LOG, "w", encoding="utf-8") as f:
        json.dump(list(posted), f, ensure_ascii=False, indent=2)


def _load_posted_ids() -> set:
    if not POSTED_LOG.exists():
        return set()
    with open(POSTED_LOG, encoding="utf-8") as f:
        return set(json.load(f))
