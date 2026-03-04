"""統一LLMクライアント — 全LLM呼び出しをJSONLに記録するラッパー"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import anthropic


_UNSET = object()  # set_context で「指定なし」と「None を明示指定」を区別する sentinel


# ── Claude バックエンド ──────────────────────────────


class ClaudeBackend:
    """Anthropic Claude API バックエンド。GeminiBackend と同じ .chat() インターフェース。"""

    MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, api_key: str):
        self.client = anthropic.Anthropic(api_key=api_key)
        self._last_request_time = 0.0
        self._min_interval = 1  # 秒

    def chat(
        self,
        system: str,
        messages: list[dict],
        max_output_tokens: int = 1024,
    ) -> str:
        """GeminiBackend.chat() と同一シグネチャ。

        Args:
            system: システムプロンプト
            messages: 会話履歴 [{"role": "user"|"assistant", "content": "..."}]
            max_output_tokens: 最大出力トークン数

        Returns:
            アシスタントの応答テキスト
        """
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

        # Claude API は role が "user" / "assistant" のみ（GeminiBackend と同じ入力形式）
        # source, name 等の非標準キーを除去
        api_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in messages
        ]

        response = self.client.messages.create(
            model=self.MODEL,
            system=system,
            messages=api_messages,
            max_tokens=max_output_tokens,
        )
        return response.content[0].text


# ── バックエンド生成ヘルパー ─────────────────────────


def create_backend(provider: str | None = None):
    """環境変数に基づいてバックエンドを生成する。

    Args:
        provider: "gemini" または "claude"。
                  None の場合は環境変数 LLM_PROVIDER を参照（デフォルト: "gemini"）。

    Returns:
        (backend, provider_name) のタプル
    """
    if provider is None:
        provider = os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider == "claude":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY が設定されていません。.env を確認してください。"
            )
        return ClaudeBackend(api_key), "claude"

    if provider == "gemini":
        # GeminiBackend は sdnd-trpg 側で定義されているため遅延 import
        from llm_backend import GeminiBackend  # noqa: E402

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY が設定されていません。.env を確認してください。"
            )
        return GeminiBackend(api_key), "gemini"

    raise ValueError(f"未対応の provider: {provider!r} ('gemini' または 'claude' を指定)")


class LLMClient:
    """GeminiBackend (または任意の LLMBackend) をラップし、全呼び出しを JSONL に記録する。

    AIPlayer 互換: .chat(system, messages, max_output_tokens) を公開。
    """

    def __init__(
        self,
        backend,
        session_id: str | None = None,
        log_dir: str | Path = "sessions/raw",
        provider: str = "gemini",
        use_rag: bool = False,
        rag_indexer=None,
    ):
        self.backend = backend
        self.session_id = session_id or str(uuid.uuid4())
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.provider = provider
        self._log_path = self.log_dir / f"{self.session_id}.jsonl"
        self._call_count = 0

        # RAG
        self.use_rag = use_rag
        self.rag_indexer = rag_indexer

        # 呼び出しごとのメタデータコンテキスト
        self._context: dict[str, Any] = {
            "turn": 0,
            "role": "GM",
            "character": None,
            "scene_type": "narration",
            "game_state": {},
        }

        # 直近の RAG 情報（ログ記録用）
        self._last_rag_info: dict[str, Any] | None = None

    # ── コンテキスト設定 ──

    def set_context(
        self,
        *,
        turn: int | None = _UNSET,
        role: str | None = _UNSET,
        character: str | None = _UNSET,
        scene_type: str | None = _UNSET,
        game_state: dict | None = _UNSET,
    ) -> None:
        """後続の .chat() 呼び出しに付与するメタデータを更新する。

        None を明示的に渡すとフィールドが None にリセットされる。
        省略（_UNSET）した場合は現在の値を維持する。
        """
        if turn is not _UNSET:
            self._context["turn"] = turn
        if role is not _UNSET:
            self._context["role"] = role
        if character is not _UNSET:
            self._context["character"] = character
        if scene_type is not _UNSET:
            self._context["scene_type"] = scene_type
        if game_state is not _UNSET:
            self._context["game_state"] = game_state

    # ── リトライ設定 ──
    MAX_RETRIES = 3
    BASE_DELAY = 2.0  # 秒

    # ── AIPlayer 互換インターフェース ──

    def chat(
        self,
        system: str,
        messages: list[dict],
        max_output_tokens: int = 1024,
    ) -> str:
        """GeminiBackend.chat() と同じシグネチャ。呼び出しを記録して返す。"""
        effective_system = system
        self._last_rag_info = None

        if self.use_rag and self.rag_indexer:
            effective_system = self._apply_rag(system, messages)

        response = self._call_with_retry(effective_system, messages, max_output_tokens)
        self._log_call(system, messages, response)
        return response

    def _apply_rag(self, system: str, messages: list[dict]) -> str:
        """RAG 検索を実行し、システムプロンプトに注入する。"""
        from rag_context import build_rag_context, inject_rag_into_system_prompt

        # 最後のユーザーメッセージで検索
        last_user = ""
        for msg in messages:
            if msg.get("role") == "user":
                last_user = msg["content"]
        if not last_user:
            return system

        scene_type = self._context.get("scene_type")
        hits = self.rag_indexer.search(last_user[:200], scene_type=scene_type, top_k=3)

        if hits:
            rag_context = build_rag_context(hits)
            self._last_rag_info = {
                "rag_context_used": True,
                "rag_hits": len(hits),
                "rag_entries": [
                    f"{h['session_id']}:{h.get('turn', 0)}" for h in hits
                ],
            }
            return inject_rag_into_system_prompt(system, rag_context)

        self._last_rag_info = {"rag_context_used": False, "rag_hits": 0, "rag_entries": []}
        return system

    def _call_with_retry(
        self,
        system: str,
        messages: list[dict],
        max_output_tokens: int,
    ) -> str:
        """503/429 エラー時にエクスポネンシャルバックオフ付きでリトライする。"""
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                return self.backend.chat(system, messages, max_output_tokens)
            except Exception as e:
                if not self._is_retryable(e) or attempt >= self.MAX_RETRIES:
                    raise
                last_exc = e
                delay = self.BASE_DELAY * (2 ** attempt) + random.uniform(0, 1)
                print(f"⏳ リトライ中 ({attempt + 1}/{self.MAX_RETRIES})... "
                      f"{delay:.1f}秒待機")
                time.sleep(delay)
        raise last_exc  # unreachable, but satisfies type checker

    @staticmethod
    def _is_retryable(exc: Exception) -> bool:
        """例外が 503 または 429 に起因するかを判定する。"""
        exc_str = str(exc).lower()
        for code in ("503", "429"):
            if code in exc_str:
                return True
        # google-genai SDK の例外は status_code 属性を持つ場合がある
        status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
        return status in (503, 429)

    # ── メタデータ付き呼び出し（GM用） ──

    def call(
        self,
        system: str,
        messages: list[dict],
        max_output_tokens: int = 1024,
        *,
        role: str | None = _UNSET,
        character: str | None = _UNSET,
        scene_type: str | None = _UNSET,
        turn: int | None = _UNSET,
        game_state: dict | None = _UNSET,
    ) -> str:
        """chat() + インラインメタデータ指定。コンテキストは呼び出し後に復元される。"""
        saved = dict(self._context)
        self.set_context(
            turn=turn, role=role, character=character,
            scene_type=scene_type, game_state=game_state,
        )
        try:
            return self.chat(system, messages, max_output_tokens)
        finally:
            self._context = saved

    # ── Ollama フォールバック（スタブ） ──

    def chat_ollama(
        self,
        system: str,
        messages: list[dict],
        max_output_tokens: int = 1024,
    ) -> str:
        """Ollama（ローカルLLM）経由の呼び出し。RAM増設後に実装。"""
        raise NotImplementedError(
            "Ollama 対応は未実装です。RAM増設後に実装予定。"
        )

    # ── backend.MODEL プロキシ ──

    @property
    def MODEL(self) -> str:
        return self.backend.MODEL

    @MODEL.setter
    def MODEL(self, value: str):
        self.backend.MODEL = value

    # ── 内部: JSONL 記録 ──

    def _log_call(
        self,
        system: str,
        messages: list[dict],
        response: str,
    ) -> None:
        """1 回の LLM 呼び出しを JSONL に 1 行追記する。"""
        self._call_count += 1
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "call_index": self._call_count,
            "turn": self._context["turn"],
            "role": self._context["role"],
            "character": self._context["character"],
            "provider": self.provider,
            "model": getattr(self.backend, "MODEL", "unknown"),
            "scene_type": self._context["scene_type"],
            "messages": _sanitize_messages(messages),
            "system_prompt_hash": hashlib.sha256(
                system.encode("utf-8")
            ).hexdigest()[:8],
            "response": response,
            "game_state": self._context["game_state"],
            "training_data": {
                "quality_score": None,
                "quality_flags": [],
                "is_good_example": None,
                "ft_pair_extracted": False,
                "dpo_candidates": [],
                "world_consistency": None,
            },
        }
        # RAG 情報があれば追加
        if self._last_rag_info:
            entry.update(self._last_rag_info)
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _sanitize_messages(messages: list[dict]) -> list[dict]:
    """ログ用にメッセージを整理する。role, content, name, source のみ保持。"""
    clean = []
    for msg in messages:
        m = {"role": msg["role"], "content": msg["content"]}
        if "name" in msg:
            m["name"] = msg["name"]
        if "source" in msg:
            m["source"] = msg["source"]
        clean.append(m)
    return clean
