"""Phase 2: parse every downloaded K-file/B-file into the main DuckDB database
and run data-quality checks (row-count divisibility, date coverage vs manifest).
"""
import csv
import sys
from pathlib import Path
from dataclasses import asdict

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parse_kfile import parse_k_file  # noqa: E402
from parse_bfile import parse_b_file  # noqa: E402

REPORT = ROOT / "docs" / "phase2_ingest_report.txt"


def iter_txt_files(subdir: str, prefix: str):
    d = ROOT / "data" / "raw" / subdir
    for p in sorted(d.glob(f"{prefix}*")):
        if p.suffix.upper() != ".TXT" or ".utf8" in p.name:
            continue
        yield p


def main():
    all_races, all_boats, all_payouts = [], [], []
    k_file_count = 0
    for p in iter_txt_files("kfile", "K"):
        date_str = p.stem[1:]
        text = p.read_bytes().decode("cp932", errors="replace").replace("\r\n", "\n")
        races, boats, payouts, _ = parse_k_file(text, date_str)
        all_races += races
        all_boats += boats
        all_payouts += payouts
        k_file_count += 1
    print(f"K-files parsed: {k_file_count}, races={len(all_races)}, boat_results={len(all_boats)}, payouts={len(all_payouts)}", file=sys.stderr)

    all_entries = []
    b_file_count = 0
    for p in iter_txt_files("bfile", "B"):
        date_str = p.stem[1:]
        text = p.read_bytes().decode("cp932", errors="replace").replace("\r\n", "\n")
        entries = parse_b_file(text, date_str)
        all_entries += entries
        b_file_count += 1
    print(f"B-files parsed: {b_file_count}, program_entries={len(all_entries)}", file=sys.stderr)

    db_path = ROOT / "data" / "boatrace.duckdb"
    con = duckdb.connect(str(db_path))

    races_df = pd.DataFrame([asdict(r) for r in all_races])
    boats_df = pd.DataFrame([asdict(r) for r in all_boats])
    prog_df = pd.DataFrame([asdict(r) for r in all_entries])
    payouts_df = pd.DataFrame([asdict(r) for r in all_payouts])
    con.register("races_df", races_df)
    con.register("boats_df", boats_df)
    con.register("prog_df", prog_df)
    con.register("payouts_df", payouts_df)
    con.execute("CREATE OR REPLACE TABLE races AS SELECT * FROM races_df")
    con.execute("CREATE OR REPLACE TABLE entries AS SELECT * FROM boats_df")
    con.execute("CREATE OR REPLACE TABLE program_entries AS SELECT * FROM prog_df")
    con.execute("CREATE OR REPLACE TABLE payouts AS SELECT * FROM payouts_df")

    # Load manifest for coverage check
    manifest_path = ROOT / "data" / "raw" / "download_manifest.csv"
    manifest_rows = []
    if manifest_path.exists():
        with open(manifest_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            manifest_rows = list(reader)
    manifest_df = pd.DataFrame(manifest_rows)

    with open(REPORT, "w", encoding="utf-8") as out:
        def p(*a):
            print(*a, file=out)

        p("# Phase 2 本取り込み 検証レポート\n")
        p(f"K-fileファイル数: {k_file_count}")
        p(f"B-fileファイル数: {b_file_count}")
        p(f"races: {len(races_df)} 行")
        p(f"entries (K-file出走結果): {len(boats_df)} 行")
        p(f"program_entries (B-file番組表): {len(prog_df)} 行\n")

        p("## データ品質チェック1: 1レースあたり出走数が6でない行があるか")
        bad = con.execute("""
            SELECT venue_code, date, race_no, count(*) n
            FROM entries GROUP BY 1,2,3 HAVING count(*) <> 6 ORDER BY date, venue_code
        """).df()
        p(f"異常レース数: {len(bad)}")
        if len(bad):
            p(bad.head(30).to_string())

        p("\n## データ品質チェック2: ダウンロードmanifestのステータス内訳")
        if len(manifest_df):
            p(manifest_df.groupby(["kind", "status"]).size().to_string())
        else:
            p("manifest not found")

        p("\n## データ品質チェック3: not_found/errorだった日付一覧（レース開催なし or 取得失敗）")
        if len(manifest_df):
            bad_days = manifest_df[~manifest_df["status"].isin(["ok", "skip_exists"])]
            p(f"件数: {len(bad_days)}")
            p(bad_days.to_string())

        p("\n## データ品質チェック4: 日付カバレッジ（racesテーブルに存在する日付数）")
        p(con.execute("SELECT count(DISTINCT date) AS distinct_dates, min(date), max(date) FROM races").df().to_string())

        p("\n## 例外着順コードの全期間集計")
        p(con.execute("""
            SELECT exception_label, count(*) n FROM entries WHERE is_exception = TRUE
            GROUP BY 1 ORDER BY n DESC
        """).df().to_string())

        p("\n## グレード未付与の確認（races.titleにSG/G1/G2/G3の文字列が無いこと）")
        grade_leak = con.execute("""
            SELECT count(*) FROM races WHERE title LIKE '%SG%' OR title LIKE '%Ｇ１%' OR title LIKE '%Ｇ２%' OR title LIKE '%Ｇ３%'
        """).fetchone()[0]
        p(f"グレード文字列を含むtitle行数: {grade_leak} (0であることを期待)")

    print("\nREPORT:", REPORT, file=sys.stderr)


if __name__ == "__main__":
    main()
