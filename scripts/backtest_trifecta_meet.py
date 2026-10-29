"""Checks whether adding 節間成績 (current-meet performance so far) as a 7th
factor changes the hit rate versus the current live model.

Meet boundaries: grade_master's meet_start_date when available (named/graded
events -- a minority of races, confirmed by analysis/scrape_grades backfill),
else computed from date-contiguity at that venue (a new meet starts whenever
there's a gap of more than 1 day since that venue's previous race day). This
covers 100% of races, unlike relying on grade_master alone.

節間成績 for boat X in race R (date D, venue V): average finish-quality point
(7-着順, exception=0) over X's starts at venue V from the meet's start date up
to (not including) D -- so only days of the *current* meet already raced,
strictly before this race. No lookahead.
"""
import itertools
import json
import math
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"
CACHE_PATH = ROOT / "data" / "trifecta_backtest_cache.json"
AUGMENTED_PATH = ROOT / "data" / "trifecta_backtest_cache_meet.json"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5
FALLBACK_CL = 2.0
FALLBACK_MOTOR = 32.4
FALLBACK_MEET = 3.5  # same scale as CA/RF (7-着順 point, exception=0)
STRENGTH_SCALE = 4.0
GRADE_WEIGHT = 2.0
TOP_N = 12

CONFIGS = {
    "現行ライブ・節間無し (CA.29/RF.19/ST.14/WR.28/CL.05/MOTOR.05)": {"ca": 0.29, "rf": 0.19, "st": 0.14, "wr": 0.28, "cl": 0.05, "motor": 0.05},
    "節間軽め (CA.27/RF.18/ST.13/WR.26/CL.05/MOTOR.05/MEET.06)": {"ca": 0.27, "rf": 0.18, "st": 0.13, "wr": 0.26, "cl": 0.05, "motor": 0.05, "meet": 0.06},
    "節間やや重め (CA.24/RF.16/ST.12/WR.23/CL.05/MOTOR.05/MEET.15)": {"ca": 0.24, "rf": 0.16, "st": 0.12, "wr": 0.23, "cl": 0.05, "motor": 0.05, "meet": 0.15},
    "節間重視 (CA.20/RF.13/ST.10/WR.17/CL.05/MOTOR.05/MEET.30)": {"ca": 0.20, "rf": 0.13, "st": 0.10, "wr": 0.17, "cl": 0.05, "motor": 0.05, "meet": 0.30},
    "節間のみRFの代わりに (CA.29/RF.00/ST.14/WR.28/CL.05/MOTOR.05/MEET.19)": {"ca": 0.29, "rf": 0.0, "st": 0.14, "wr": 0.28, "cl": 0.05, "motor": 0.05, "meet": 0.19},
}


def build_meet_start_lookup(con) -> dict:
    """(venue_code, date) -> meet_start_date (YYMMDD string), hybrid of
    grade_master (named events) and date-contiguity (everything else)."""
    rows = con.execute("""
        WITH venue_dates AS (
            SELECT DISTINCT venue_code, date, strptime(date, '%y%m%d')::DATE AS d
            FROM races
        ),
        with_prev AS (
            SELECT venue_code, date, d,
                   lag(d) OVER (PARTITION BY venue_code ORDER BY d) AS prev_d
            FROM venue_dates
        ),
        with_flag AS (
            SELECT venue_code, date, d,
                   CASE WHEN prev_d IS NULL OR d - prev_d > 1 THEN 1 ELSE 0 END AS is_new_meet
            FROM with_prev
        ),
        with_meet_id AS (
            SELECT venue_code, date, d,
                   sum(is_new_meet) OVER (PARTITION BY venue_code ORDER BY d) AS meet_id
            FROM with_flag
        ),
        computed AS (
            SELECT venue_code, date,
                   strftime(min(d) OVER (PARTITION BY venue_code, meet_id), '%y%m%d') AS computed_start
            FROM with_meet_id
        )
        SELECT c.venue_code, c.date,
               COALESCE(strftime(strptime(g.meet_start_date, '%Y-%m-%d'), '%y%m%d'), c.computed_start) AS meet_start
        FROM computed c
        LEFT JOIN grade_master g ON g.venue_code = c.venue_code AND g.date = c.date
    """).fetchall()
    return {(v, d): ms for v, d, ms in rows}


def point_expr(finish, is_exception) -> float:
    if is_exception or finish is None:
        return 0.0
    try:
        f = int(finish)
    except ValueError:
        return 0.0
    if not (1 <= f <= 6):
        return 0.0
    return 7 - f


def augment():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)

    meet_start_lookup = build_meet_start_lookup(con)
    print(f"meet_start lookup built: {len(meet_start_lookup)} (venue,date) pairs", file=sys.stderr)

    for i, race in enumerate(races):
        venue, date, race_no = race["venue"], race["date"], race["race_no"]
        meet_start = meet_start_lookup.get((venue, date))
        entries = con.execute(
            "SELECT reg_no, frame FROM entries WHERE venue_code=? AND date=? AND race_no=?",
            [venue, date, race_no],
        ).fetchall()
        reg_by_frame = {int(frame): reg_no for reg_no, frame in entries}

        for boat in race["boats"]:
            reg_no = reg_by_frame.get(boat["frame"])
            meet_point = None
            if reg_no is not None and meet_start is not None:
                rows = con.execute(
                    """
                    SELECT finish, is_exception FROM entries
                    WHERE reg_no = ? AND venue_code = ? AND date >= ? AND date < ?
                    """,
                    [reg_no, venue, meet_start, date],
                ).fetchall()
                if rows:
                    pts = [point_expr(f, exc) for f, exc in rows]
                    meet_point = sum(pts) / len(pts)
            boat["meet"] = meet_point

        if (i + 1) % 200 == 0:
            print(f"  augmented {i + 1}/{len(races)}", file=sys.stderr)

    with open(AUGMENTED_PATH, "w", encoding="utf-8") as f:
        json.dump(races, f)
    missing = sum(1 for r in races for b in r["boats"] if b["meet"] is None)
    total = sum(len(r["boats"]) for r in races)
    print(f"Augmented {len(races)} races, saved to {AUGMENTED_PATH}", file=sys.stderr)
    print(f"missing meet (no prior starts this meet, e.g. day 1): {missing}/{total}", file=sys.stderr)


def recent_form_score(recent: list[dict]) -> float:
    if not recent:
        return FALLBACK_POINT
    wsum = wtot = 0.0
    for r in recent:
        w = GRADE_WEIGHT if r["top_grade"] else 1.0
        wsum += r["point"] * w
        wtot += w
    return wsum / wtot if wtot else FALLBACK_POINT


def normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def predict_top_n(boats: list[dict], weights: dict, n: int):
    rf = [recent_form_score(b["recent"]) for b in boats]
    st_raw = [-(b["st"] if b["st"] is not None else FALLBACK_ST) for b in boats]
    ca = [(b["ca"] if b["ca"] is not None else FALLBACK_POINT) for b in boats]
    wr = [(b.get("wr") if b.get("wr") is not None else FALLBACK_WR) for b in boats]
    cl = [(b.get("cl") if b.get("cl") is not None else FALLBACK_CL) for b in boats]
    motor = [(b.get("motor") if b.get("motor") is not None else FALLBACK_MOTOR) for b in boats]
    meet = [(b.get("meet") if b.get("meet") is not None else FALLBACK_MEET) for b in boats]

    norm = {
        "rf": normalize(rf), "st": normalize(st_raw), "ca": normalize(ca),
        "wr": normalize(wr), "cl": normalize(cl), "motor": normalize(motor),
        "meet": normalize(meet),
    }
    strength = {}
    for i, b in enumerate(boats):
        composite = sum(weights[k] * norm[k][i] for k in weights)
        strength[b["frame"]] = math.exp(STRENGTH_SCALE * composite)

    frames = [b["frame"] for b in boats]
    total = sum(strength.values())
    results = []
    for a, b2, c in itertools.permutations(frames, 3):
        p_a = strength[a] / total
        rem1 = total - strength[a]
        p_b = strength[b2] / rem1 if rem1 > 0 else 0
        rem2 = rem1 - strength[b2]
        p_c = strength[c] / rem2 if rem2 > 0 else 0
        results.append(((a, b2, c), p_a * p_b * p_c))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:n]


def evaluate(races: list[dict], weights: dict) -> float:
    hits = 0
    for race in races:
        topn = predict_top_n(race["boats"], weights, TOP_N)
        actual = tuple(race["actual"])
        if any(combo == actual for combo, _ in topn):
            hits += 1
    return hits / len(races) if races else 0.0


def sweep():
    with open(AUGMENTED_PATH, encoding="utf-8") as f:
        races = json.load(f)

    report_path = ROOT / "docs" / "backtest_trifecta_meet_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル 節間成績を追加した場合の的中率\n")
        p(f"レース数: {len(races)} (grade_weight=2.0, 上位{TOP_N}点)\n")
        for label, weights in CONFIGS.items():
            hr = evaluate(races, weights)
            p(f"{label}")
            p(f"  的中率: {hr*100:.2f}%  ({int(round(hr*len(races)))}/{len(races)})\n")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("augment", "all"):
        augment()
    if mode in ("sweep", "all"):
        sweep()
