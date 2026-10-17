# ボートレース選手成績データアプリ

個人利用のボートレース選手成績データアプリ。公式サイトの配布データ（競走成績・番組表・
選手期別成績）を取り込み、選手を軸にあらゆる情報を検索できるPWAを作る。

詳細な開発経緯・確定仕様は [`docs/confirmed_layout.md`](docs/confirmed_layout.md) を参照。

## 構成

- `src/` — 固定長テキストのパーサー（K-file/B-file/期別成績）
- `scripts/` — データ取得・集計・エクスポートのスクリプト群
- `config/app_config.yaml` — 集計パラメータ（補正の強さ、例外の扱いなど）
- `.github/workflows/daily_update.yml` — 日次自動更新（取得→パース→集計→Parquet書き出し→GitHub Pages配信）
- `site/` — 静的配信サイト（`site/data/*.parquet` をDuckDB-WASMから直接読む想定。フロントエンド本体はフェーズ5で実装）
- `data-state` ブランチ — 日次更新の状態を保持するDuckDBデータベース（`boatrace.duckdb`）。mainブランチには含めない

## ローカルでの実行

```bash
pip install -r requirements.txt
python scripts/download_range.py     # 初回: 2年分一括取得
python scripts/build_full_db.py      # K-file/B-fileをDuckDBへ
python scripts/build_racer_history.py  # 期別成績からracer_history構築
python scripts/scrape_grades.py      # グレードマスタ取得
python scripts/build_aggregates.py   # 集計テーブル構築
python scripts/export_parquet.py     # site/data/ へParquet書き出し
python scripts/daily_update.py       # 以降は日次差分更新のみ
```
