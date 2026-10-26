"""Dedicated backtest sample for 女子レース (all 6 entrants female), built the
same way as backtest_trifecta_sweep.py/sweep2.py but sampling directly from
the women-only candidate pool instead of filtering a general sample after the
fact (the general 1000-race sample only contained 83 women's races -- too few
to compare weight configs reliably).

Two phases:
  fetch  -- expensive, DB-bound. Samples women-only races and pulls each
            boat's raw features (last-10-in-course points+grade, all-time ST,
            all-time course-aptitude, plus wr/cl from program_entries),
            all with strict date < race_date (no lookahead). Cached to
            data/trifecta_backtest_women_cache.json.
  sweep  -- cheap. Replays several weight configs against the cache.
"""
import itertools
import json
import math
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"
CACHE_PATH = ROOT / "data" / "trifecta_backtest_women_cache.json"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5
FALLBACK_CL = 2.0
STRENGTH_SCALE = 4.0
TOP_N = 12
MAX_SAMPLE = 2000
MIN_DATE_FOR_SAMPLING = "250601"

CLASS_SCORE = {"A1": 4.0, "A2": 3.0, "B1": 2.0, "B2": 1.0}


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


def fetch_raw_features(con, reg_no: str, course: int, before_date: str):
    recent = con.execute(
        """
        SELECT finish, is_exception, grade
        FROM entries_enriched
        WHERE reg_no = ? AND entry_course = ? AND date < ?
        ORDER BY date DESC, race_no DESC
        LIMIT 10
        """,
        [reg_no, course, before_date],
    ).fetchall()
    recent_points = [
        {"point": point_expr(finish, is_exc), "top_grade": grade in ("SG", "G1")}
        for finish, is_exc, grade in recent
    ]

    st_row = con.execute(
        """
        SELECT avg(start_timing) FROM entries_enriched
        WHERE reg_no = ? AND entry_course = ? AND date < ? AND start_timing IS NOT NULL
        """,
        [reg_no, course, before_date],
    ).fetchone()
    st = st_row[0] if st_row and st_row[0] is not None else None

    ca_row = con.execute(
        """
        SELECT avg(CASE WHEN is_exception OR TRY_CAST(finish AS INTEGER) IS NULL THEN 0
                         ELSE 7 - TRY_CAST(finish AS INTEGER) END)
        FROM entries_enriched
        WHERE reg_no = ? AND entry_course = ? AND date < ?
        """,
        [reg_no, course, before_date],
    ).fetchone()
    ca = ca_row[0] if ca_row and ca_row[0] is not None else None

    return {"recent": recent_points, "st": st, "ca": ca}


def do_fetch():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    print("Finding women-only candidate races...", file=sys.stderr)
    candidates = con.execute(
        """
        WITH cand AS (
          SELECT venue_code, date, race_no
          FROM entries
          WHERE date >= ?
          GROUP BY 1, 2, 3
          HAVING count(*) = 6 AND count(*) FILTER (WHERE finish IN ('01','02','03')) = 3
        )
        SELECT c.venue_code, c.date, c.race_no
        FROM cand c
        JOIN entries e ON e.venue_code=c.venue_code AND e.date=c.date AND e.race_no=c.race_no
        JOIN racers r ON r.toroku_no = e.reg_no
        GROUP BY 1, 2, 3
        HAVING count(*) = 6 AND count(*) FILTER (WHERE r.sex='女') = 6
        """,
        [MIN_DATE_FOR_SAMPLING],
    ).df()
    print(f"women-only candidates: {len(candidates)}", file=sys.stderr)
    sample = candidates.sample(n=min(MAX_SAMPLE, len(candidates)), random_state=42).reset_index(drop=True)

    races_out = []
    for idx, race in sample.iterrows():
        venue, date, race_no = race["venue_code"], race["date"], race["race_no"]
        entries = con.execute(
            "SELECT reg_no, frame, finish FROM entries WHERE venue_code=? AND date=? AND race_no=?",
            [venue, date, race_no],
        ).df()
        if len(entries) != 6:
            continue
        boats = []
        for _, e in entries.iterrows():
            reg_no, frame = e["reg_no"], int(e["frame"])
            feat = fetch_raw_features(con, reg_no, frame, date)
            rating = con.execute(
                """
                SELECT national_win_rate, local_win_rate, klass
                FROM program_entries WHERE venue_code=? AND date=? AND race_no=? AND reg_no=?
                """,
                [venue, date, int(race_no), reg_no],
            ).fetchone()
            if rating:
                nat, loc, klass = rating
                wr = ((nat or 0) + (loc or 0)) / 2 if (nat is not None or loc is not None) else None
                cl = CLASS_SCORE.get(klass)
            else:
                wr, cl = None, None
            boats.append({"frame": frame, "wr": wr, "cl": cl, **feat})
        actual = tuple(
            int(entries.loc[entries["finish"] == f, "frame"].iloc[0])
            for f in ("01", "02", "03")
        )
        races_out.append({"venue": venue, "date": date, "race_no": int(race_no), "boats": boats, "actual": list(actual)})
        if (idx + 1) % 200 == 0:
            print(f"  fetched {idx + 1}/{len(sample)}", file=sys.stderr)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(races_out, f)
    print(f"Cached {len(races_out)} women-only races to {CACHE_PATH}", file=sys.stderr)

    missing_wr = sum(1 for r in races_out for b in r["boats"] if b["wr"] is None)
    total_boats = sum(len(r["boats"]) for r in races_out)
    print(f"missing wr/cl: {missing_wr}/{total_boats}", file=sys.stderr)


def recent_form_score(recent: list[dict], grade_weight: float) -> float:
    if not recent:
        return FALLBACK_POINT
    wsum = wtot = 0.0
    for r in recent:
        w = grade_weight if r["top_grade"] else 1.0
        wsum += r["point"] * w
        wtot += w
    return wsum / wtot if wtot else FALLBACK_POINT


def normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def predict_top_n(boats: list[dict], weights: dict, grade_weight: float, n: int):
    rf = [recent_form_score(b["recent"], grade_weight) for b in boats]
    st_raw = [-(b["st"] if b["st"] is not None else FALLBACK_ST) for b in boats]
    ca = [(b["ca"] if b["ca"] is not None else FALLBACK_POINT) for b in boats]
    wr = [(b.get("wr") if b.get("wr") is not None else FALLBACK_WR) for b in boats]
    cl = [(b.get("cl") if b.get("cl") is not None else FALLBACK_CL) for b in boats]

    norm = {
        "rf": normalize(rf), "st": normalize(st_raw), "ca": normalize(ca),
        "wr": normalize(wr), "cl": normalize(cl),
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


def evaluate(races: list[dict], weights: dict, grade_weight: float) -> float:
    hits = 0
    for race in races:
        topn = predict_top_n(race["boats"], weights, grade_weight, TOP_N)
        actual = tuple(race["actual"])
        if any(combo == actual for combo, _ in topn):
            hits += 1
    return hits / len(races) if races else 0.0


def do_sweep():
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)
    print(f"Loaded {len(races)} cached women-only races", file=sys.stderr)

    configs = {
        "現行ライブ (CA.30/RF.20/ST.15/WR.30/CL.05)": {"ca": 0.30, "rf": 0.20, "st": 0.15, "wr": 0.30, "cl": 0.05},
        "均等 (各0.20)": {"ca": 0.20, "rf": 0.20, "st": 0.20, "wr": 0.20, "cl": 0.20},
        "コース適性重視 (CA.45/RF.20/ST.15/WR.15/CL.05)": {"ca": 0.45, "rf": 0.20, "st": 0.15, "wr": 0.15, "cl": 0.05},
        "直近10走重視 (CA.20/RF.45/ST.15/WR.15/CL.05)": {"ca": 0.20, "rf": 0.45, "st": 0.15, "wr": 0.15, "cl": 0.05},
        "平均ST重視 (CA.20/RF.15/ST.45/WR.15/CL.05)": {"ca": 0.20, "rf": 0.15, "st": 0.45, "wr": 0.15, "cl": 0.05},
        "勝率重視 (CA.20/RF.15/ST.10/WR.50/CL.05)": {"ca": 0.20, "rf": 0.15, "st": 0.10, "wr": 0.50, "cl": 0.05},
        "級別重視 (CA.20/RF.15/ST.10/WR.25/CL.30)": {"ca": 0.20, "rf": 0.15, "st": 0.10, "wr": 0.25, "cl": 0.30},
    }

    report_path = ROOT / "docs" / "backtest_trifecta_women_sweep_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル 女子レース専用サンプルでの重み比較\n")
        p(f"女子レース数: {len(races)} (2025-06以降からサンプリング, grade_weight=2.0 固定, 上位{TOP_N}点)\n")
        for label, weights in configs.items():
            hr = evaluate(races, weights, 2.0)
            p(f"{label}")
            p(f"  的中率: {hr*100:.2f}%  ({int(round(hr*len(races)))}/{len(races)})\n")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("fetch", "all"):
        do_fetch()
    if mode in ("sweep", "all"):
        do_sweep()
