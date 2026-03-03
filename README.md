# SDND Theater

シアターモード — AIたちの即興劇場。全キャラクターをAIが操作する自律TRPGセッション。

## セットアップ

```bash
pip install -r requirements.txt
cp .env.example .env
# .env に GEMINI_API_KEY を設定
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

## オプション

| オプション | デフォルト | 説明 |
|---|---|---|
| `--turns` | 3 | ターン数 |
| `--players` | 2 | AIプレイヤー人数（1〜3） |
| `--scenario` | ランダム | シナリオ名 |
| `--model` | gemini-2.5-flash-lite | 使用モデル |

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

## 依存プロジェクト

- [sdnd-trpg](../sdnd-trpg) — ゲームエンジン（同階層に配置）
- [sdnd-eldia](../sdnd-eldia) — 世界設定スペック
