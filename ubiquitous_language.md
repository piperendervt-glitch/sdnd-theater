# SDND Theater ユビキタス言語辞書

最終更新: 2026-03-04
対象リポジトリ: sdnd-theater

---

## 目的
このファイルはプロジェクト内で使う言葉の定義を統一します。
コード・仕様書・Claude Codeへの指示・コメントで、
このファイルの用語を一貫して使用してください。

---

## セッション関連

### Session（セッション）
- 定義: `theater_session.py` の1回の実行単位。開幕シーンからセッション終了まで
- 同義語として使わない言葉: ゲーム、プレイ、ラウンド
- 関連する概念: Turn, Entry, SessionLog
- コード上の対応: `theater_session.py:main()`, `metadata["session_id"]`

### Turn（ターン）
- 定義: セッション内の1周期。全AIプレイヤーの行動＋各GM応答で1ターン
- 同義語として使わない言葉: ラウンド、フェーズ
- 関連する概念: Session, Entry
- コード上の対応: `theater_session.py` のターンループ, `entry["turn"]`

### Entry（エントリ）
- 定義: LLMへの1回の呼び出し記録。JSONL の1行に対応する
- 同義語として使わない言葉: ログ行、レコード、行
- 関連する概念: SessionLog, ScoredEntry
- コード上の対応: `LLMClient._log_call()` が書き出す1行, `load_session_log()` の戻り値の各要素

### Party（パーティ）
- 定義: セッションに参加するAIプレイヤーキャラクターの集合（1〜3名）
- 同義語として使わない言葉: チーム、グループ
- 関連する概念: Player, Character
- コード上の対応: `build_theater_party_section()`, `select_characters()`

---

## ログ・データ関連

### SessionLog（セッションログ）
- 定義: 1セッション分の全Entry を格納する JSONL ファイル
- 同義語として使わない言葉: ログファイル、データファイル
- 関連する概念: Entry, RawLog
- コード上の対応: `sessions/raw/{session_id}.jsonl`

### ScoredEntry（スコア済みエントリ）
- 定義: `score_entry()` によって `training_data` が評価済みの Entry
- 同義語として使わない言葉: 評価済みログ
- 関連する概念: QualityScore, TrainingData
- コード上の対応: `sessions/scored/{session_id}.jsonl` 内の各行

### TrainingData（トレーニングデータ）
- 定義: Entry 内の `training_data` フィールド。品質スコア・フラグ・FT/DPO 判定を格納する
- 同義語として使わない言葉: メタデータ、学習情報
- 関連する概念: QualityScore, FTCandidate
- コード上の対応: `entry["training_data"]` — キー: `quality_score`, `quality_flags`, `is_good_example`, `ft_pair_extracted`, `dpo_candidates`, `world_consistency`

### Messages（メッセージ履歴）
- 定義: LLM に送信した会話履歴。`role`（user/assistant）と `content` を持つ dict のリスト
- 同義語として使わない言葉: チャットログ、会話
- 関連する概念: Entry
- コード上の対応: `entry["messages"]`, `theater_session.py` の `messages` リスト

---

## スコアリング関連

### QualityScore（品質スコア）
- 定義: Entry の品質を0〜100で評価するルールベーススコア。4軸の合計
- 同義語として使わない言葉: 点数、評価値、レーティング
- 関連する概念: WorldConsistency, RoleAdherence
- コード上の対応: `score_entry()` → `training_data["quality_score"]`
- 評価軸: `response_length`(20) + `world_consistency`(40) + `role_adherence`(20) + `no_error_flag`(20)

### LLMJudge（LLM審査）
- 定義: ClaudeBackend を用いた LLM-as-Judge によるスコアリング。ルールベースを補完する
- 同義語として使わない言葉: AI採点、自動評価
- 関連する概念: QualityScore
- コード上の対応: `score_entry_llm()` → `training_data["llm_score"]`, `training_data["llm_judge"]`

### FTCandidate（FT候補）
- 定義: `is_good_example=True`（QualityScore >= 70）の Entry から抽出した Fine-Tuning 用ペア
- 同義語として使わない言葉: 学習データ、教師データ
- 関連する概念: QualityScore, DPOCandidate
- コード上の対応: `extract_ft_pairs()`, `sessions/ft_pairs/`

### DPOCandidate（DPO候補）
- 定義: Direct Preference Optimization 用の選好比較候補。同一コンテキストで異なるスコアの応答
- 同義語として使わない言葉: 比較ペア
- 関連する概念: FTCandidate, QualityScore
- コード上の対応: `extract_dpo_pairs()`, `sessions/dpo_pairs/`

### WorldConsistency（世界観準拠度）
- 定義: 応答がエルディア世界の設定に沿っているかの評価。現代技術・現代兵器の言及を逸脱として検出する
- 同義語として使わない言葉: 世界観スコア、設定準拠
- 関連する概念: QualityScore, Violation
- コード上の対応: `_count_world_violations()`, `check_world_consistency()`, `ANACHRONISM_PATTERNS`

### Recommendation（推奨判定）
- 定義: セッション単位の総合判定。平均 QualityScore に基づく3段階
- 値: `FT候補`（avg >= 70）/ `要確認`（avg >= 50）/ `除外推奨`（avg < 50）
- コード上の対応: `score_session()` 戻り値の `recommendation`

---

## RAG関連

### RAGIndex（RAGインデックス）
- 定義: ScoredEntry のうち `is_good_example=True` のものを ChromaDB にベクトル化して格納したもの
- 同義語として使わない言葉: ベクトルDB、検索インデックス
- 関連する概念: RAGHit, ScoredEntry
- コード上の対応: `RAGIndexer`, `sessions/rag_db/`, `COLLECTION_NAME = "sdnd_sessions"`

### RAGHit（RAGヒット）
- 定義: RAG 検索で返された類似エントリ。`role`, `scene_type`, `response`, `score` を含む
- 同義語として使わない言葉: 検索結果、マッチ
- 関連する概念: RAGIndex, RAGContext
- コード上の対応: `RAGIndexer.search()` の戻り値の各要素

### RAGContext（RAGコンテキスト）
- 定義: RAGHit を整形してシステムプロンプトに注入するテキスト。「過去の類似場面（参考）」として付加される
- 同義語として使わない言葉: 参照テキスト
- 関連する概念: RAGHit
- コード上の対応: `build_rag_context()`, `inject_rag_into_system_prompt()`

---

## エージェント・ロール関連

### GM（ゲームマスター）
- 定義: セッションの進行・状況描写・判定を担当するLLMの役割。`role="GM"`
- 同義語として使わない言葉: ナレーター、マスター、DM
- 関連する概念: Player, SceneType
- コード上の対応: `entry["role"] == "GM"`, `build_system_prompt()`

### Player（プレイヤー）
- 定義: キャラクターの行動を決定するAIの役割。`role="player"`
- 同義語として使わない言葉: キャラ、NPC
- 関連する概念: GM, AIPlayer, Character
- コード上の対応: `entry["role"] == "player"`, `AIPlayer.decide_action()`

### AIPlayer（AIプレイヤー）
- 定義: sdnd-trpg の `AIPlayer` クラスのインスタンス。LLMBackend を用いてキャラクターの行動を自律決定する
- 同義語として使わない言葉: ボット、エージェント
- 関連する概念: Player, Character, LLMClient
- コード上の対応: `ai_player.AIPlayer`, `theater_session.py` の `ai_players` リスト

### Character（キャラクター）
- 定義: ゲーム世界内の登場人物。名前（`char_name`）と詳細説明（`detail`）を持つ
- 同義語として使わない言葉: ユニット、アバター
- 関連する概念: Player, Party
- コード上の対応: `PLAYABLE_CHARACTERS`, `entry["character"]`

### SceneType（シーン種別）
- 定義: LLM 呼び出し時の場面分類。コンテキスト設定と RAG フィルタに使用される
- 値: `narration`（状況描写）/ `dialogue`（対話・行動）/ `combat`（戦闘）/ `exploration`（探索）
- コード上の対応: `entry["scene_type"]`, `LLMClient.set_context(scene_type=...)`

---

## パイプライン関連

### RawLog（生ログ）
- 定義: `LLMClient` が自動記録する未加工の JSONL ファイル。`sessions/raw/` に保存される
- 同義語として使わない言葉: 元データ、オリジナルログ
- 関連する概念: SessionLog, ScoredEntry
- コード上の対応: `sessions/raw/{session_id}.jsonl`, `LLMClient._log_call()`

### BatchExecution（バッチ実行）
- 定義: `batch_runner.py` による複数セッションの自動連続実行。自動スコアリング・リトライ・進捗管理を含む
- 同義語として使わない言葉: 一括実行、連続実行
- 関連する概念: Session, RawLog
- コード上の対応: `batch_runner.py:run_batch()`, `sessions/batch_progress.json`

### LLMClient（LLMクライアント）
- 定義: LLMBackend をラップし、全呼び出しを JSONL に記録する統一クライアント。リトライ・RAG・コンテキスト管理を担う
- 同義語として使わない言葉: バックエンド（LLMClient はバックエンドを内包する上位概念）
- 関連する概念: Backend, Entry
- コード上の対応: `llm_client.py:LLMClient`

### Backend（バックエンド）
- 定義: LLM API への実際の通信を担うクラス。`.chat(system, messages, max_output_tokens)` インターフェースを公開
- 同義語として使わない言葉: API、プロバイダー（Provider はバックエンドの種別名として使用）
- 値: `GeminiBackend` / `ClaudeBackend`
- コード上の対応: `llm_client.py:ClaudeBackend`, `llm_backend.py:GeminiBackend`

### Provider（プロバイダー）
- 定義: 使用する LLM サービスの種別名。Backend の選択に使われる文字列
- 値: `"gemini"` / `"claude"`
- コード上の対応: `create_backend(provider)`, `entry["provider"]`, `--provider` CLI オプション

### Observer（オブザーバー）
- 定義: セッション中のキャラクター行動が不変条件に違反していないか監視する QA モジュール
- 同義語として使わない言葉: モニター、チェッカー
- 関連する概念: Violation
- コード上の対応: `observer.py:Observer`

### Violation（違反）
- 定義: Observer が検出した不変条件への抵触。`turn`, `character`, `code`, `description` を持つ
- 同義語として使わない言葉: エラー、警告
- コード上の対応: `observer.py:Violation` dataclass, コード例: `INV-A02`, `INV-B02`, `INV-C01`, `INV-D01`

---

## 使ってはいけない言葉（混乱を避けるための禁止語）

| 禁止語 | 代わりに使う言葉 | 理由 |
|--------|----------------|------|
| ゲーム | Session | セッションはTRPGの1回の遊びの単位。「ゲーム」は曖昧 |
| ログ行 | Entry | JSONL の1行 = 1エントリ。「行」はファイルの物理行と混同する |
| レコード | Entry | 同上 |
| バックエンド | Backend または LLMClient | 文脈による。API通信層は Backend、ラッパー全体は LLMClient |
| API | Provider + Backend | 「API」単体は曖昧。通信先は Provider、通信クラスは Backend |
| 評価値 | QualityScore | 100点満点のルールベーススコアを指す固有名詞として統一 |
| 教師データ | FTCandidate | Fine-Tuning 候補を指す。未加工の Entry とは区別する |
| 検索結果 | RAGHit | RAG の検索結果に限定した用語 |
| NPC | Character または Player | シアターモードでは全員がAI操作の Player。NPC はGMが即興で出す存在 |
| エラー | Violation（Observer文脈）| Observer の検出結果は Violation。エラーはシステム障害を指す |
| ナレーター | GM | TRPG の文脈に沿って GM で統一 |

---

## 5層記憶構造（MemoryLayer）

SDNDの記憶モデル。エントリの性質に応じて5つの層に分類し、Consolidation・RAG・ファインチューニングで活用する。

### Working（作業記憶）
- 定義: 実行中セッション内の一時的な文脈情報。セッション終了後は保存しない
- 同義語として使わない言葉: バッファ、キャッシュ
- コード上の対応: セッション実行中のみ存在。保存済みログには付与しない
- 自動分類: 対象外

### Episodic（エピソード記憶）
- 定義: 「いつ・どこで・何が起きたか」のセッション体験記録。時系列で保持される
- 同義語として使わない言葉: イベントログ、履歴
- コード上の対応: `entry["training_data"]["memory_layer"] == "episodic"`
- 自動分類: role/scene_type で他層に該当しないエントリ

### Semantic（意味記憶）
- 定義: エピソードから抽出された一般化知識。「〜とは何か」「〜はどういう関係か」
- 同義語として使わない言葉: 知識ベース、オントロジー
- コード上の対応: `entry["training_data"]["memory_layer"] == "semantic"`
- 自動分類: 禁止（Consolidation エージェントのみが付与）

### Procedural（手続き記憶）
- 定義: 「〜のときは〜する」という場面に紐づく行動パターン
- 同義語として使わない言葉: ルール、手順
- コード上の対応: `entry["training_data"]["memory_layer"] == "procedural"`
- 自動分類: scene_type が combat/dialogue/exploration/narration のいずれか（role による skill 判定が優先）

### Skill（スキル記憶）
- 定義: GM進行やロールプレイなど、繰り返し実行して熟達するスキルの記録
- 同義語として使わない言葉: 能力、テクニック
- コード上の対応: `entry["training_data"]["memory_layer"] == "skill"`
- 自動分類: role == "GM" または role == "player"

### MemoryLayerClassifier（記憶層分類器）
- 定義: エントリの属性から memory_layer を自動判定するドメインサービス
- 関連する概念: MemoryLayer, TrainingData, QualityEvaluator
- コード上の対応: `memory_layer_classifier.py:MemoryLayerClassifier`
- 制約: semantic は自動付与しない。working は保存済みログに付与しない

---

## 境界づけられたコンテキスト

### セッション実行コンテキスト
- 含まれるファイル: `theater_session.py`, `observer.py`
- 関心事: セッションの進行制御、AIプレイヤーの行動決定、GM応答、ターン管理
- 外部に渡すもの: Messages（会話履歴）→ LLMClient へ、turn_actions → Observer へ

### データ収集コンテキスト
- 含まれるファイル: `llm_client.py`, `batch_runner.py`
- 関心事: LLM 呼び出しの記録（JSONL）、リトライ、RAG 注入、複数セッションの自動実行
- 外部に渡すもの: RawLog（JSONL）→ sessions/raw/ へ

### 学習データコンテキスト
- 含まれるファイル: `log_pipeline.py`, `session_analyzer.py`, `rag_indexer.py`, `rag_context.py`
- 関心事: スコアリング、FT/DPO ペア抽出、RAG インデックス構築、セッション品質分析
- 外部に渡すもの: ScoredEntry → sessions/scored/, FTCandidate → sessions/ft_pairs/, DPOCandidate → sessions/dpo_pairs/, RAGIndex → sessions/rag_db/
