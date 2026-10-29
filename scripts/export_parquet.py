"""Phase 4: export DuckDB tables to Parquet files under site/data/ for static
hosting. DuckDB-WASM in the browser reads these directly (spec: 配信は静的
ホスティング、表示はDuckDB-WASMでParquetを直接検索・集計する)."""
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"
OUT_DIR = ROOT / "site" / "data"

TABLES = [
    "races", "entries", "program_entries", "payouts",
    "racers", "racer_history", "racer_period_stats",
    "grade_master",
    "agg_racer_course_month", "agg_racer_venue_course",
    "agg_racer_grade_month", "agg_venue_course_overall",
    "racer_rolling_form",
]


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    total_bytes = 0
    for t in TABLES:
        out_path = OUT_DIR / f"{t}.parquet"
        con.execute(f"COPY {t} TO '{out_path.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        size = out_path.stat().st_size
        total_bytes += size
        print(f"{t}: {size / 1024 / 1024:.2f} MB", file=sys.stderr)

    print(f"\nTotal: {total_bytes / 1024 / 1024:.2f} MB", file=sys.stderr)
    print(f"Exported to {OUT_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
