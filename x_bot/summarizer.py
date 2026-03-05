"""ローカルLLM（OllamaBackend）を使ってセッションをX投稿用テキストに要約"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")
from ollama_client import OllamaBackend

SYSTEM_PROMPT = """あなたはVTuber「pipe_render」のAI劇場の宣伝担当です。
TRPGセッションのハイライトを、Xに投稿する30〜60文字の日本語ツイートに要約してください。

ルール：
- VTuberらしいキャッチーな口調（「〜w」「〜件」「突然の〜」など）
- 必ずハッシュタグを末尾に付ける：#SDNDTheater #AI劇場 #エルディア
- 末尾に必ず「※AI生成コンテンツ」を付ける
- 140文字以内に収める
- セッションの最も面白い1シーンを選ぶ

出力はツイート本文のみ。説明文は不要。"""

GENERATE_PARAMS = {
    "max_output_tokens": 200,
}


class SessionSummarizer:
    def __init__(self, model: str = "qwen2.5:3b"):
        self.backend = OllamaBackend(model=model)

    def generate(self, session: dict) -> dict:
        """
        セッションデータからX投稿テキストを生成

        Returns:
            {"session_id": str, "text": str, "score": float}
        """
        highlight = self._extract_highlight(session)
        messages = [{"role": "user", "content": f"このセッションを要約してください：\n{highlight}"}]

        text = self.backend.chat(
            system=SYSTEM_PROMPT,
            messages=messages,
            **GENERATE_PARAMS,
        )

        return {
            "session_id": session.get("session_id"),
            "text": text.strip(),
            "score": session.get("score", 0),
        }

    def _extract_highlight(self, session: dict) -> str:
        """スコアの高いエントリを最大3件抽出してテキスト化"""
        entries = session.get("entries", [])
        top = sorted(entries, key=lambda e: e.get("score", 0), reverse=True)[:3]
        return "\n".join(e.get("content", "") for e in top)
