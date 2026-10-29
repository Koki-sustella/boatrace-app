"""Fills the handful of recent dates whose K-file text isn't retained locally
(CI's daily_update.py downloads and discards it -- only the resulting DB rows
are persisted) but are already present in the `races` table. Re-downloads just
those dates' K-files from the official archive, parses payouts only, and
inserts (races/entries for these dates already exist -- untouched here).
"""
import io
import sys
import time
from dataclasses import asdict
from pathlib import Path

import duckdb
import lhafile
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parse_kfile import parse_k_file  # noqa: E402

DB_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "boatrace.duckdb"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal research script; contact: k.kishimoto@sustella-jp.com)"}


def fetch_k_text(date_str: str) -> str | None:
    yyyymm = "20" + date_str[:2] + date_str[2:4]
    url = f"https://www1.mbrace.or.jp/od2/K/{yyyymm}/k{date_str}.lzh"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        print(f"  {date_str}: HTTP {r.status_code}", file=sys.stderr)
        return None
    lha = lhafile.Lhafile(io.BytesIO(r.content))
    for info in lha.infolist():
        return lha.read(info.filename).decode("cp932", errors="replace").replace("\r\n", "\n")
    return None


def main():
    con = duckdb.connect(str(DB_PATH))
    missing_dates = [
        row[0] for row in con.execute("""
            SELECT DISTINCT r.date FROM races r
            WHERE NOT EXISTS (SELECT 1 FROM payouts p WHERE p.venue_code=r.venue_code AND p.date=r.date AND p.race_no=r.race_no)
            ORDER BY r.date
        """).fetchall()
    ]
    print(f"dates with any missing payout coverage: {len(missing_dates)}", file=sys.stderr)

    all_new_payouts = []
    for date_str in missing_dates:
        text = fetch_k_text(date_str)
        time.sleep(1.2)
        if text is None:
            continue
        _races, _boats, payouts, _unparsed = parse_k_file(text, date_str)
        # Only keep rows for races that are actually missing (skip ones this
        # date already had -- e.g. a date with one レース不成立 race genuinely
        # has no payout rows for that race, which is correct, not missing).
        existing = {
            (r[0], r[1]) for r in con.execute(
                "SELECT venue_code, race_no FROM payouts WHERE date=?", [date_str]
            ).fetchall()
        }
        new_rows = [p for p in payouts if (p.venue_code, p.race_no) not in existing]
        all_new_payouts += new_rows
        print(f"  {date_str}: +{len(new_rows)} payout rows", file=sys.stderr)

    if all_new_payouts:
        df = pd.DataFrame([asdict(r) for r in all_new_payouts])
        con.register("gap_payouts", df)
        con.execute("INSERT INTO payouts SELECT * FROM gap_payouts")

    remaining = con.execute("""
        SELECT count(*) FROM races r
        WHERE NOT EXISTS (SELECT 1 FROM payouts p WHERE p.venue_code=r.venue_code AND p.date=r.date AND p.race_no=r.race_no)
    """).fetchone()[0]
    print(f"remaining races with no payout row: {remaining} (expected: genuine レース不成立 races)", file=sys.stderr)
    con.close()


if __name__ == "__main__":
    main()
