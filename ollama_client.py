"""Ollama バックエンド — ローカル LLM (qwen2.5:3b) を HTTP API 経由で呼び出す"""

from __future__ import annotations

import json
import urllib.request
import urllib.error


class OllamaBackend:
    """Ollama REST API バックエンド。ClaudeBackend / GeminiBackend と同じ .chat() インターフェース。"""

    MODEL = "qwen2.5:3b"
    BASE_URL = "http://localhost:11434"

    def __init__(self, base_url: str | None = None, model: str | None = None):
        if base_url is not None:
            self.BASE_URL = base_url.rstrip("/")
        if model is not None:
            self.MODEL = model

    def chat(
        self,
        system: str,
        messages: list[dict],
        max_output_tokens: int = 1024,
    ) -> str:
        """ClaudeBackend.chat() と同一シグネチャ。

        Args:
            system: システムプロンプト
            messages: 会話履歴 [{"role": "user"|"assistant", "content": "..."}]
            max_output_tokens: 最大出力トークン数

        Returns:
            アシスタントの応答テキスト
        """
        api_messages = [{"role": "system", "content": system}]
        for msg in messages:
            api_messages.append({"role": msg["role"], "content": msg["content"]})

        payload = {
            "model": self.MODEL,
            "messages": api_messages,
            "stream": False,
            "options": {
                "num_predict": max_output_tokens,
            },
        }

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}/api/chat",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.URLError as e:
            raise ConnectionError(
                f"Ollama に接続できません ({self.BASE_URL}): {e}"
            ) from e

        return body["message"]["content"]


if __name__ == "__main__":
    backend = OllamaBackend()
    reply = backend.chat(
        system="あなたはNPCの村人です。日本語で応答してください。",
        messages=[{"role": "user", "content": "こんにちは、この村について教えてください。"}],
    )
    print(reply)
