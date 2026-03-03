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

## 依存プロジェクト

- [sdnd-trpg](../sdnd-trpg) — ゲームエンジン（同階層に配置）
- [sdnd-eldia](../sdnd-eldia) — 世界設定スペック
