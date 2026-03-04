"""RAG コンテキスト — 類似エントリをプロンプト注入用テキストに整形する"""

from __future__ import annotations


def build_rag_context(similar_entries: list[dict], max_chars: int = 500) -> str:
    """類似エントリをプロンプト注入用テキストに整形する。

    Args:
        similar_entries: RAGIndexer.search() の返却値
        max_chars: 各エントリの応答表示上限文字数

    Returns:
        整形されたコンテキスト文字列。エントリが空なら空文字列。
    """
    if not similar_entries:
        return ""

    lines = ["【過去の類似場面（参考）】"]
    for entry in similar_entries:
        role = entry.get("role", "")
        scene = entry.get("scene_type", "")
        response = entry.get("response", "")
        if len(response) > max_chars:
            response = response[:max_chars] + "…"
        lines.append(f"- ({role} / {scene}) 「{response}」")

    return "\n".join(lines)


def inject_rag_into_system_prompt(original_system: str, rag_context: str) -> str:
    """既存システムプロンプトの末尾に RAG コンテキストを追加する。

    rag_context が空の場合は original_system をそのまま返す。
    """
    if not rag_context:
        return original_system

    return (
        f"{original_system}\n\n"
        f"---\n"
        f"{rag_context}\n"
        f"※ 上記は過去セッションの参考事例です。直接引用せず、"
        f"自然な文脈で活用してください。\n"
    )
