# SDND Theater

シアターモード — AIたちの即興劇場。全キャラクターをAIが操作する自律TRPGセッション。

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env
# .env に GEMINI_API_KEY / ANTHROPIC_API_KEY を設定
```

## 使い方

```bash
# デフォルト実行（3ターン、2人パーティ）
python theater_session.py

# オプション指定
python theater_session.py --turns 5 --players 3 --scenario "嵐の夜" --model gemini-2.5-flash

# セッション分析
python session_analyzer.py sessions/<ログファイル>.json
```

## ⚠ API レート制限について（重要）

シアターモードでは全キャラクターをAIが操作するため、
1ターンあたりのAPIコール数が多くなります。

| パーティ人数 | 1ターンあたりのコール数 | 10ターンの合計 |
|------------|----------------------|--------------|
| 2人 | 約5コール | 約50コール |
| 3人 | 約7コール | 約70コール |

**Gemini 無料枠（RPD 20）ではシアターモードは実質動作しません。**

### 推奨環境

以下のいずれかが必要です:

- **Gemini 有料枠（Tier 1）**（推奨）: クレジットカード登録のみ。
  10ターンセッションのコストは ¥1〜5 程度
- **Anthropic Claude API**: 日本語品質を重視する場合に最適
- **OpenAI API**: GPT-5 mini 等でコスト効率よく運用可能

### コスト目安

| モデル | 10ターン（3人） | 100ターン |
|--------|---------------|----------|
| Gemini Flash-Lite（有料） | ¥1〜5 | ¥10〜50 |
| Gemini Flash（有料） | ¥5〜15 | ¥50〜150 |
| Claude Haiku | ¥15〜45 | ¥150〜450 |

## 機能一覧

### マルチLLMプロバイダー (`llm_client.py`)

Gemini / Claude を `--provider` オプションで切り替え可能。全LLM呼び出しを自動的にJSONLへ記録する。

```bash
python theater_session.py --provider claude
python theater_session.py --provider gemini   # デフォルト
```

### ログパイプライン (`log_pipeline.py`)

セッションで生成されたJSONLログを検証・スコアリングし、ファインチューニング用ペア（FT/DPO）を抽出する。

```bash
python log_pipeline.py validate sessions/raw/  # スキーマ検証
python log_pipeline.py score sessions/raw/      # 品質スコアリング → sessions/scored/
python log_pipeline.py extract sessions/scored/  # FT/DPOペア抽出 → sessions/ft_pairs/, sessions/dpo_pairs/
```

### 品質評価 (`quality_evaluator.py`)

ログエントリを複数の評価ルール（応答長、世界観整合性、記憶層分類など）で自動採点する。

```bash
python quality_evaluator.py rules  # 評価ルール一覧を表示
```

### 記憶層分類 (`memory_layer_classifier.py`)

SDNDの5層記憶構造（episodic / semantic / procedural / working / meta）に基づき、各エントリにタグを付与する。

```bash
python memory_layer_classifier.py rules  # 分類ルール一覧を表示
```

### RAG — 過去セッション参照 (`rag_indexer.py`, `rag_context.py`)

スコアリング済みログをベクトルDB（ChromaDB）にインデックス化し、セッション中に類似場面を参照できるようにする。

```bash
python rag_indexer.py index sessions/scored/  # インデックス構築
python rag_indexer.py stats                    # インデックス統計
python theater_session.py --rag                # RAG有効でセッション実行
```

### バッチ実行 (`batch_runner.py`)

セッションを連続実行してログを大量に蓄積する。リトライ・進捗管理付き。

```bash
python batch_runner.py --count 10 --turns 3 --players 2
```

### セッション分析 (`session_analyzer.py`)

JSONログからロールプレイ品質（没入度・多様性・連携度）を分析し、世界観逸脱の自動検出も行う。

## オプション一覧

| オプション | デフォルト | 説明 |
|---|---|---|
| `--turns` | 3 | ターン数 |
| `--players` | 2 | AIプレイヤー人数（1〜3） |
| `--scenario` | ランダム | シナリオ名 |
| `--model` | (プロバイダー依存) | 使用モデル名 |
| `--provider` | gemini | LLMプロバイダー（`gemini` / `claude`） |
| `--rag` | off | RAG（過去セッション参照）を有効化 |

## 用語辞書

プロジェクト内の用語定義は [ubiquitous_language.md](./ubiquitous_language.md) を参照してください。

## 依存プロジェクト

- [sdnd-trpg](../sdnd-trpg) — ゲームエンジン（同階層に配置）
- [sdnd-eldia](../sdnd-eldia) — 世界設定スペック
