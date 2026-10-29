"""Checks the current live model's hit rate specifically for SG and G1 races.
The general 1000-race cache only contains 11 G1 and 3 SG races (too few to
measure), so this fetches dedicated samples straight from the SG/G1 candidate
pools, the same way backtest_trifecta_women_sweep.py does for 女子レース.

Reuses the live app's actual per-race weight selection (default vs. 女子レース
weights, see frontend/src/lib/trifectaPredict.ts) so the reported hit rate
matches what the live feature would really produce for these races.
"""
import json
import math
import sys
from pathlib import Path
from itertools import permutations

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5
FALLBACK_CL = 2.0
STRENGTH_SCALE = 4.0
GRADE_WEIGHT = 2.0
TOP_N = 12

CLASS_SCORE = {"A1": 4.0, "A2": 3.0, "B1": 2.0, "B2": 1.0}

# Live weight sets (frontend/src/lib/trifectaPredict.ts)
WEIGHTS_DEFAULT = {"ca": 0.30, "rf": 0.20, "st": 0.15, "wr": 0.30, "cl": 0.05}
WEIGHTS_WOMEN = {"ca": 0.50, "rf": 0.20, "st": 0.10, "wr": 0.15, "cl": 0.05}

GRADE_SAMPLE_SIZE = {"SG": 1000, "G1": 1000}


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


def fetch_grade_races(con, grade: str, max_n: int):
    candidates = con.execute(
        """
        WITH cand AS (
          SELECT venue_code, date, race_no
          FROM entries
          GROUP BY 1, 2, 3
          HAVING count(*) = 6 AND count(*) FILTER (WHERE finish IN ('01','02','03')) = 3
        ),
        cand_grade AS (
          SELECT c.venue_code, c.date, c.race_no, any_value(ee.grade) AS grade
          FROM cand c
          JOIN entries_enriched ee ON ee.venue_code=c.venue_code AND ee.date=c.date AND ee.race_no=c.race_no
          GROUP BY 1, 2, 3
        )
        SELECT venue_code, date, race_no FROM cand_grade WHERE grade = ?
        """,
        [grade],
    ).df()
    print(f"  {grade} candidates: {len(candidates)}", file=sys.stderr)
    sample = candidates.sample(n=min(max_n, len(candidates)), random_state=42).reset_index(drop=True)

    races_out = []
    for idx, race in sample.iterrows():
        venue, date, race_no = race["venue_code"], race["date"], race["race_no"]
        entries = con.execute(
            "SELECT reg_no, frame, finish FROM entries WHERE venue_code=? AND date=? AND race_no=?",
            [venue, date, race_no],
        ).df()
        if len(entries) != 6:
            continue
        try:
            actual = tuple(
                int(entries.loc[entries["finish"] == f, "frame"].iloc[0])
                for f in ("01", "02", "03")
            )
        except IndexError:
            # Malformed/ambiguous finish data for this race (seen in some
            # older archives) -- skip rather than crash the whole fetch.
            continue
        boats = []
        sexes = []
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
            sex_row = con.execute("SELECT sex FROM racers WHERE toroku_no=?", [reg_no]).fetchone()
            sexes.append(sex_row[0] if sex_row else None)
            boats.append({"frame": frame, "wr": wr, "cl": cl, **feat})
        is_women = len(sexes) == 6 and all(s == "女" for s in sexes)
        races_out.append({
            "venue": venue, "date": date, "race_no": int(race_no),
            "boats": boats, "actual": list(actual), "is_women": is_women,
        })
        if (idx + 1) % 200 == 0:
            print(f"    fetched {idx + 1}/{len(sample)}", file=sys.stderr)

    return races_out


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
    for a, b2, c in permutations(frames, 3):
        p_a = strength[a] / total
        rem1 = total - strength[a]
        p_b = strength[b2] / rem1 if rem1 > 0 else 0
        rem2 = rem1 - strength[b2]
        p_c = strength[c] / rem2 if rem2 > 0 else 0
        results.append(((a, b2, c), p_a * p_b * p_c))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:n]


def evaluate(races: list[dict]) -> tuple[int, int]:
    hits = 0
    for race in races:
        weights = WEIGHTS_WOMEN if race.get("is_women") else WEIGHTS_DEFAULT
        topn = predict_top_n(race["boats"], weights, TOP_N)
        actual = tuple(race["actual"])
        if any(combo == actual for combo, _ in topn):
            hits += 1
    return hits, len(races)


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)

    report_path = ROOT / "docs" / "backtest_trifecta_grade_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル SG・G1レース別の的中率\n")
        p("現行ライブの重み付け(通常/女子レース自動判定)で算出。上位12点。\n")

        for grade, max_n in GRADE_SAMPLE_SIZE.items():
            print(f"Fetching {grade}...", file=sys.stderr)
            races = fetch_grade_races(con, grade, max_n)
            women_n = sum(1 for r in races if r["is_women"])
            hits, n = evaluate(races)
            p(f"## {grade}レース")
            p(f"  サンプル数: {n}  (うち女子レース: {women_n}件)")
            p(f"  的中率: {hits/n*100:.2f}%  ({hits}/{n})\n")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
