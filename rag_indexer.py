"""RAG インデクサー — スコアリング済みログをベクトルDBにインデックス化する

初回実行時に sentence-transformers のモデル（約100MB）がダウンロードされます。
使用モデル: paraphrase-multilingual-MiniLM-L12-v2（日本語対応・軽量・ローカル動作）
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from log_pipeline import load_session_log

# ── 定数 ──

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
COLLECTION_NAME = "sdnd_sessions"


class RAGIndexer:
    """scored/ の良質エントリをベクトル DB にインデックス化し、類似検索する。"""

    def __init__(self, db_dir: str | Path = "sessions/rag_db"):
        self.db_dir = Path(db_dir)
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.db_dir))
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        self._model: SentenceTransformer | None = None

    def _get_model(self) -> SentenceTransformer:
        """Embedding モデルの遅延初期化。"""
        if self._model is None:
            self._model = SentenceTransformer(EMBEDDING_MODEL)
        return self._model

    # ── インデックス構築 ──

    def build_index(self, scored_dir: str | Path = "sessions/scored"):
        """scored/ の全 JSONL を読み込み、is_good_example=True のエントリをインデックス化する。

        既存エントリは重複スキップ（session_id + call_index で一意）。
        """
        scored_path = Path(scored_dir)
        if not scored_path.exists():
            print("  scored/ ディレクトリが見つかりません。")
            return

        model = self._get_model()
        existing_ids = set(self._collection.get()["ids"])
        added = 0
        skipped = 0

        for jsonl_file in sorted(scored_path.glob("*.jsonl")):
            entries = load_session_log(jsonl_file)
            for entry in entries:
                td = entry.get("training_data", {})
                if not td.get("is_good_example"):
                    continue

                doc_id = f"{entry.get('session_id', '')}:{entry.get('call_index', 0)}"
                if doc_id in existing_ids:
                    skipped += 1
                    continue

                document = self._build_document(entry)
                embedding = model.encode(document).tolist()
                metadata = {
                    "session_id": entry.get("session_id", ""),
                    "role": entry.get("role", ""),
                    "scene_type": entry.get("scene_type", ""),
                    "quality_score": td.get("quality_score", 0),
                    "turn": entry.get("turn", 0),
                    "call_index": entry.get("call_index", 0),
                }

                self._collection.add(
                    ids=[doc_id],
                    embeddings=[embedding],
                    documents=[document],
                    metadatas=[metadata],
                )
                added += 1

        print(f"  追加: {added}件 / スキップ（既存）: {skipped}件")

    # ── 検索 ──

    def search(
        self,
        query: str,
        scene_type: str | None = None,
        top_k: int = 3,
    ) -> list[dict]:
        """クエリに類似した過去エントリを検索する。

        Returns:
            [{"role": str, "scene_type": str, "response": str,
              "score": float, "session_id": str, "turn": int}, ...]
        """
        if self._collection.count() == 0:
            return []

        model = self._get_model()
        query_embedding = model.encode(query).tolist()

        where_filter = {"scene_type": scene_type} if scene_type else None

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, self._collection.count()),
            where=where_filter,
        )

        hits = []
        if results["documents"] and results["documents"][0]:
            for doc, meta, dist in zip(
                results["documents"][0],
                results["metadatas"][0],
                results["distances"][0],
            ):
                # ChromaDB cosine distance → similarity
                similarity = 1.0 - dist
                # ドキュメントから response 部分を抽出
                response_part = doc.split("\n応答: ", 1)[-1] if "\n応答: " in doc else doc
                hits.append({
                    "role": meta.get("role", ""),
                    "scene_type": meta.get("scene_type", ""),
                    "response": response_part,
                    "score": round(similarity, 3),
                    "session_id": meta.get("session_id", ""),
                    "turn": meta.get("turn", 0),
                })
        return hits

    # ── 統計 ──

    def stats(self) -> dict:
        """インデックスの統計情報を返す。"""
        total = self._collection.count()
        info = {
            "total_entries": total,
            "db_path": str(self.db_dir),
            "scene_type_breakdown": {},
        }

        if total > 0:
            all_data = self._collection.get(include=["metadatas"])
            scene_counts: dict[str, int] = {}
            for meta in all_data["metadatas"]:
                st = meta.get("scene_type", "unknown")
                scene_counts[st] = scene_counts.get(st, 0) + 1
            info["scene_type_breakdown"] = scene_counts

        return info

    # ── 再構築 ──

    def rebuild(self, scored_dir: str | Path = "sessions/scored"):
        """インデックスを全削除して再作成する。"""
        self._client.delete_collection(COLLECTION_NAME)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        print("  インデックスを削除しました。再構築中...")
        self.build_index(scored_dir)

    # ── 内部 ──

    @staticmethod
    def _build_document(entry: dict) -> str:
        """検索対象のドキュメント文字列を構築する。"""
        messages = entry.get("messages", [])
        last_user = ""
        for msg in messages:
            if msg.get("role") == "user":
                last_user = msg["content"]
        response = entry.get("response", "")
        return f"入力: {last_user[:200]}\n応答: {response[:500]}"


# ── CLI ──


def main():
    parser = argparse.ArgumentParser(description="SDND RAG インデクサー")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("build", help="インデックスを構築（差分追加）")
    sub.add_parser("stats", help="インデックス統計を表示")
    sub.add_parser("rebuild", help="インデックスを全削除して再構築")

    p_search = sub.add_parser("search", help="類似検索テスト")
    p_search.add_argument("query", help="検索クエリ")
    p_search.add_argument("--scene-type", default=None, help="scene_type フィルター")
    p_search.add_argument("--top-k", type=int, default=3, help="返却件数")

    args = parser.parse_args()
    indexer = RAGIndexer()

    if args.command == "build":
        print("インデックス構築中...")
        indexer.build_index()
        s = indexer.stats()
        print(f"  総エントリ数: {s['total_entries']}件")

    elif args.command == "stats":
        s = indexer.stats()
        print("=== RAG インデックス統計 ===")
        print(f"総エントリ数: {s['total_entries']}件")
        if s["scene_type_breakdown"]:
            print("scene_type 内訳:")
            for st, cnt in sorted(s["scene_type_breakdown"].items()):
                print(f"  {st:12s}: {cnt}件")
        print(f"DBパス: {s['db_path']}")

    elif args.command == "rebuild":
        print("インデックス再構築中...")
        indexer.rebuild()
        s = indexer.stats()
        print(f"  総エントリ数: {s['total_entries']}件")

    elif args.command == "search":
        results = indexer.search(args.query, scene_type=args.scene_type, top_k=args.top_k)
        if not results:
            print("  結果なし（インデックスが空です。先に build を実行してください）")
        else:
            print(f"検索結果（{len(results)}件）:")
            for r in results:
                print(f"  [{r['score']:.3f}] ({r['role']} / {r['scene_type']}) "
                      f"{r['response'][:80]}...")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
