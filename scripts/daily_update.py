"""Phase 4: incremental daily update.

Assumes data/boatrace.duckdb already exists (checked out from the `data-state`
branch by the CI workflow; for local runs it's just the file already built by
phases 1-3). Only fetches/parses days newer than what's already in the DB,
appends them, refreshes the current month's grade schedule, rebuilds the
aggregate tables (cheap -- pure SQL over already-loaded rows), and re-exports
Parquet. Safe to re-run: if already up to date, it's a no-op for the fetch step.
"""
import io
import sys
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import duckdb
import lhafile
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parse_kfile import parse_k_file  # noqa: E402
from parse_bfile import parse_b_file  # noqa: E402
from parse_fanfile import parse_fan_file  # noqa: E402

HEADERS = {"User-Agent": "Mozilla/5.0 (personal research script; contact: k.kishimoto@sustella-jp.com)"}
DELAY_SEC = 1.2
DB_PATH = ROOT / "data" / "boatrace.duckdb"
RAW_DIR = ROOT / "data" / "raw"


def fetch_lzh(url: str) -> bytes | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    return r.content


def download_day(kind: str, d: date) -> Path | None:
    base = "K" if kind == "k" else "B"
    yyyymm = d.strftime("%Y%m")
    yymmdd = d.strftime("%y%m%d")
    url = f"https://www1.mbrace.or.jp/od2/{base}/{yyyymm}/{kind}{yymmdd}.lzh"
    dest_dir = RAW_DIR / ("kfile" if kind == "k" else "bfile")
    dest_dir.mkdir(parents=True, exist_ok=True)
    content = fetch_lzh(url)
    if content is None:
        return None
    (dest_dir / f"{kind}{yymmdd}.lzh").write_bytes(content)
    lha = lhafile.Lhafile(io.BytesIO(content))
    txt_path = None
    for info in lha.infolist():
        data = lha.read(info.filename)
        txt_path = dest_dir / info.filename
        txt_path.write_bytes(data)
    return txt_path


def append_day(con, d: date):
    date_str = d.strftime("%y%m%d")
    k_txt = download_day("k", d)
    time.sleep(DELAY_SEC)
    b_txt = download_day("b", d)
    time.sleep(DELAY_SEC)

    if k_txt is not None:
        text = k_txt.read_bytes().decode("cp932", errors="replace").replace("\r\n", "\n")
        races, boats, _ = parse_k_file(text, date_str)
        if races:
            races_df = pd.DataFrame([asdict(r) for r in races])
            con.register("new_races", races_df)
            con.execute("INSERT INTO races SELECT * FROM new_races")
        if boats:
            boats_df = pd.DataFrame([asdict(r) for r in boats])
            con.register("new_entries", boats_df)
            con.execute("INSERT INTO entries SELECT * FROM new_entries")
        print(f"{date_str}: +{len(races)} races, +{len(boats)} entries", file=sys.stderr)
    else:
        print(f"{date_str}: K-file not available yet, skipping this date", file=sys.stderr)
        return False

    if b_txt is not None:
        text = b_txt.read_bytes().decode("cp932", errors="replace").replace("\r\n", "\n")
        entries = parse_b_file(text, date_str)
        if entries:
            prog_df = pd.DataFrame([asdict(r) for r in entries])
            con.register("new_program", prog_df)
            con.execute("INSERT INTO program_entries SELECT * FROM new_program")
        print(f"{date_str}: +{len(entries)} program_entries", file=sys.stderr)

    return True


def refresh_grade_schedule(con):
    """Re-scrape the current and next month's schedule (events can be added/
    updated as a meet approaches) and upsert into grade_master."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from scrape_grades import fetch_month, parse_month  # local import to reuse logic

    today = date.today()
    months = [(today.year, today.month)]
    nm = today.month + 1
    ny = today.year + (1 if nm > 12 else 0)
    nm = 1 if nm > 12 else nm
    months.append((ny, nm))

    new_rows = []
    for y, m in months:
        try:
            html = fetch_month(y, m)
        except requests.RequestException as e:
            print(f"grade fetch failed for {y}-{m:02d}: {e}", file=sys.stderr)
            continue
        new_rows += parse_month(html, y, m)
        time.sleep(1.0)

    if not new_rows:
        return
    new_df = pd.DataFrame(new_rows)
    con.register("new_grades", new_df)
    con.execute("""
        DELETE FROM grade_master WHERE (venue_code, date) IN (SELECT venue_code, date FROM new_grades)
    """)
    con.execute("INSERT INTO grade_master SELECT * FROM new_grades")


def maybe_refresh_racer_history(con):
    """Check for a newly-published 期別成績(fan) period file and, if found,
    re-derive racers/racer_history/racer_period_stats from all fan files on disk."""
    kibetsu_dir = RAW_DIR / "kibetsu"
    kibetsu_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()
    # candidate next period filenames: fan{YY}04 / fan{YY}10 for the current and next year
    candidates = set()
    for y in (today.year - 1, today.year, today.year + 1):
        yy = y % 100
        candidates.add(f"fan{yy:02d}04.lzh")
        candidates.add(f"fan{yy:02d}10.lzh")

    existing = {p.name for p in kibetsu_dir.glob("fan*.lzh")}
    new_found = False
    for fn in sorted(candidates):
        if fn in existing:
            continue
        url = f"https://www.boatrace.jp/static_extra/pc_static/download/data/kibetsu/{fn}"
        content = fetch_lzh(url)
        time.sleep(DELAY_SEC)
        if content is None:
            continue
        (kibetsu_dir / fn).write_bytes(content)
        lha = lhafile.Lhafile(io.BytesIO(content))
        for info in lha.infolist():
            (kibetsu_dir / info.filename).write_bytes(lha.read(info.filename))
        print(f"new period file found: {fn}", file=sys.stderr)
        new_found = True

    if not new_found:
        return

    all_records = []
    for p in sorted(kibetsu_dir.glob("fan*.txt")):
        records, _errors = parse_fan_file(p.read_bytes())
        all_records.append(records)
    all_records.sort(key=lambda recs: (recs[0].year, recs[0].period))

    racers, history_rows = {}, []
    for records in all_records:
        for r in records:
            racers.setdefault(r.toroku_no, {})
            racers[r.toroku_no].update({
                "toroku_no": r.toroku_no, "birth_date": r.birth_date, "sex": r.sex,
                "training_period": r.training_period, "hometown": r.hometown,
            })
            history_rows.append({
                "toroku_no": r.toroku_no, "year": r.year, "period": r.period,
                "name_kanji": r.name_kanji, "name_kana": r.name_kana,
                "branch": r.branch, "klass": r.klass,
                "calc_from": r.calc_from, "calc_to": r.calc_to,
                "win_rate": r.win_rate, "place_rate": r.place_rate,
                "avg_st": r.avg_st, "starts": r.starts,
            })

    racers_df = pd.DataFrame(list(racers.values()))
    history_df = pd.DataFrame(history_rows).sort_values(["toroku_no", "year", "period"])
    changed_rows = []
    for _, g in history_df.groupby("toroku_no", sort=False):
        prev = None
        for _, row in g.iterrows():
            key = (row["name_kanji"], row["klass"], row["branch"])
            if prev is None or key != prev:
                changed_rows.append(row)
            prev = key
    racer_history_df = pd.DataFrame(changed_rows)

    con.register("racers_df2", racers_df)
    con.register("history_df2", history_df)
    con.register("racer_history_df2", racer_history_df)
    con.execute("CREATE OR REPLACE TABLE racers AS SELECT * FROM racers_df2")
    con.execute("CREATE OR REPLACE TABLE racer_period_stats AS SELECT * FROM history_df2")
    con.execute("CREATE OR REPLACE TABLE racer_history AS SELECT * FROM racer_history_df2")


def main():
    con = duckdb.connect(str(DB_PATH))

    last_date_str = con.execute("SELECT max(date) FROM races").fetchone()[0]
    last_date = date(2000 + int(last_date_str[:2]), int(last_date_str[2:4]), int(last_date_str[4:6]))
    yesterday = date.today() - timedelta(days=1)

    d = last_date + timedelta(days=1)
    any_appended = False
    while d <= yesterday:
        ok = append_day(con, d)
        any_appended = any_appended or ok
        d += timedelta(days=1)

    maybe_refresh_racer_history(con)
    refresh_grade_schedule(con)
    con.close()

    # build_aggregates / export_parquet open their own connections to the same
    # DB file -- keep this one closed first to avoid lock contention.
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_aggregates
    build_aggregates.main()  # always rebuild (cheap) to pick up the grade refresh too

    import export_parquet
    export_parquet.main()

    print("daily_update.py: done", file=sys.stderr)


if __name__ == "__main__":
    main()
