"""One-off: populate the `payouts` table from the raw K-files already on disk
(data/raw/kfile/, retained locally from the original ingest -- about 2 years'
worth) into the existing production data/boatrace.duckdb, without touching any
other table. Going forward, daily_update.py keeps `payouts` current on its own.

Safe to re-run: CREATE OR REPLACE.
"""
import sys
from dataclasses import asdict
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parse_kfile import parse_k_file  # noqa: E402

DB_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "boatrace.duckdb"


def main():
    all_payouts = []
    k_file_count = 0
    kdir = ROOT / "data" / "raw" / "kfile"
    for p in sorted(kdir.glob("K*.TXT")):
        if ".utf8" in p.name:
            continue
        date_str = p.stem[1:]
        raw = p.read_bytes()
        try:
            text = raw.decode("cp932", errors="replace")
        except UnicodeDecodeError:
            text = raw.decode("utf-8", errors="replace")
        text = text.replace("\r\n", "\n")
        _races, _boats, payouts, _unparsed = parse_k_file(text, date_str)
        all_payouts += payouts
        k_file_count += 1
        if k_file_count % 200 == 0:
            print(f"  parsed {k_file_count} files, {len(all_payouts)} payout rows so far", file=sys.stderr)

    print(f"K-files parsed: {k_file_count}, payout rows: {len(all_payouts)}", file=sys.stderr)

    payouts_df = pd.DataFrame([asdict(r) for r in all_payouts])
    con = duckdb.connect(str(DB_PATH))
    con.register("payouts_df", payouts_df)
    con.execute("CREATE OR REPLACE TABLE payouts AS SELECT * FROM payouts_df")

    print("\n## 検証: bet_type別の件数・is_void/is_special件数", file=sys.stderr)
    print(con.execute("""
        SELECT bet_type, count(*) n,
               count(*) FILTER (WHERE is_void) n_void,
               count(*) FILTER (WHERE is_special_payout) n_special,
               min(date), max(date)
        FROM payouts GROUP BY bet_type ORDER BY bet_type
    """).df().to_string(), file=sys.stderr)

    print("\n## 検証: races 1件あたりの trio(3連複)行数分布 (正常なら1、不成立なら1(void)が期待値)", file=sys.stderr)
    print(con.execute("""
        SELECT n, count(*) AS race_count FROM (
            SELECT venue_code, date, race_no, count(*) n
            FROM payouts WHERE bet_type = 'trio' GROUP BY 1,2,3
        ) GROUP BY n ORDER BY n
    """).df().to_string(), file=sys.stderr)

    con.close()


if __name__ == "__main__":
    main()
