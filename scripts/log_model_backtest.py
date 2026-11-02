"""Appends real-outcome backtest rows for one or more already-decided dates
into the `model_backtest_log` table, so per-venue/per-period performance can
be tracked over time instead of only looked at one day (or one random
sample) at a time.

Usage:
  python scripts/log_model_backtest.py 261101            # a single date
  python scripts/log_model_backtest.py 261001 261101      # inclusive range
  python scripts/log_model_backtest.py --since-last       # from the day
                                                           # after the latest
                                                           # logged date up
                                                           # to the latest
                                                           # date with payout
                                                           # data (used by
                                                           # daily_update.py)

Safe to re-run: skips (date, venue_code, race_no) rows already logged.
"""
import sys
from datetime import date as _date, timedelta
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from trifecta_live_model import evaluate_race, MODEL_VERSION  # noqa: E402

DB_PATH = ROOT / "data" / "boatrace.duckdb"


def _to_date(yymmdd: str) -> _date:
    return _date(2000 + int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6]))


def _to_yymmdd(d: _date) -> str:
    return d.strftime("%y%m%d")


def ensure_table(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS model_backtest_log (
            date VARCHAR, venue_code VARCHAR, race_no BIGINT,
            is_women BOOLEAN, hit BOOLEAN, stake BIGINT, return_amount DOUBLE,
            model_version VARCHAR
        )
    """)


def date_range(start: str, end: str) -> list[str]:
    d, end_d = _to_date(start), _to_date(end)
    out = []
    while d <= end_d:
        out.append(_to_yymmdd(d))
        d += timedelta(days=1)
    return out


def log_dates(con, dates: list[str]):
    already = set(
        tuple(r) for r in con.execute(
            "SELECT DISTINCT date, venue_code, race_no FROM model_backtest_log"
        ).fetchall()
    )
    new_rows = []
    for date in dates:
        races = con.execute(
            "SELECT venue_code, race_no FROM races WHERE date=? ORDER BY venue_code, race_no", [date]
        ).fetchall()
        logged_this_date = 0
        for venue, race_no in races:
            if (date, venue, race_no) in already:
                continue
            row = evaluate_race(con, venue, date, race_no)
            if row is not None:
                new_rows.append(row)
                logged_this_date += 1
        print(f"{date}: {logged_this_date} new rows ({len(races)} races total)", file=sys.stderr)

    if new_rows:
        df = pd.DataFrame(new_rows)
        con.register("new_backtest_rows", df)
        # Explicit column lists on both sides: INSERT INTO ... SELECT * matches
        # by position, not name, and evaluate_race()'s dict key order doesn't
        # match the table's declared column order (venue_code/date swapped),
        # which silently corrupted every row the first time this ran.
        con.execute("""
            INSERT INTO model_backtest_log (date, venue_code, race_no, is_women, hit, stake, return_amount, model_version)
            SELECT date, venue_code, race_no, is_women, hit, stake, return_amount, model_version FROM new_backtest_rows
        """)
    print(f"Logged {len(new_rows)} new race rows (model_version={MODEL_VERSION})", file=sys.stderr)


def main():
    con = duckdb.connect(str(DB_PATH))
    ensure_table(con)

    args = sys.argv[1:]
    if args and args[0] == "--since-last":
        last_logged = con.execute("SELECT max(date) FROM model_backtest_log").fetchone()[0]
        last_available = con.execute(
            "SELECT max(r.date) FROM races r WHERE EXISTS (SELECT 1 FROM payouts p WHERE p.venue_code=r.venue_code AND p.date=r.date AND p.race_no=r.race_no)"
        ).fetchone()[0]
        if last_available is None:
            print("no payout-backed races available yet", file=sys.stderr)
            return
        start = _to_yymmdd(_to_date(last_logged) + timedelta(days=1)) if last_logged else last_available
        if _to_date(start) > _to_date(last_available):
            print("already up to date", file=sys.stderr)
            return
        dates = date_range(start, last_available)
    elif len(args) == 1:
        dates = [args[0]]
    elif len(args) == 2:
        dates = date_range(args[0], args[1])
    else:
        print("usage: log_model_backtest.py <date> | <start> <end> | --since-last", file=sys.stderr)
        sys.exit(1)

    log_dates(con, dates)
    con.close()


if __name__ == "__main__":
    main()
