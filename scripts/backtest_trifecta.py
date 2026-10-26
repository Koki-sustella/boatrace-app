"""Backtest the 3連単 (trifecta) prediction model against real past races.

Methodology (mirrors the live frontend feature exactly -- see
frontend/src/lib/trifectaPredict.ts for the TypeScript twin):

For each boat, assumed to start from the course matching its 枠番(frame
number) -- the same simplifying assumption the live 直前比較 tool makes,
since actual 進入コース can occasionally differ from frame number:

  1. RF (直近10走, recent form): weighted average of a finish-quality point
     (1st=6 .. 6th=1, exception=0) over that boat's last 10 starts *strictly
     before the race date* in that same course, with a 2x weight for
     SG/G1 races (reflects quality of recent form, not just quantity).
  2. ST: average start timing in that course, all history strictly before
     the race date, all venues (lower is better).
  3. CA (コース適性, all-time course aptitude): average finish-quality point
     in that course, ALL history strictly before the race date, all venues
     (larger sample than RF, long-run baseline).

Each factor is min-max normalized across the race's boats, combined with
weights 0.5/0.3/0.2 (user-specified priority order), turned into a
Plackett-Luce strength (exp(4*composite)), and used to rank all 3-permutations
of the race's boats. Top 12 (by frame number, since that's what you actually
bet on) are the picks.

This script samples real completed races from the dataset, computes picks
using ONLY data available before each race's date (no lookahead), and reports
the 的中率 (hit rate): how often the actual 1-2-3 frame result appears in the
top-12 picks. No payout data is ingested, so this reports accuracy only, not
return on investment.
"""
import itertools
import math
import random
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"

W_RF, W_ST, W_CA = 0.5, 0.3, 0.2
GRADE_WEIGHT = 2.0
FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
STRENGTH_SCALE = 4.0
TOP_N = 12
SAMPLE_SIZE = 500
MIN_DATE_FOR_SAMPLING = "250601"  # leave >=1yr of "before" history for most sampled races


def point_expr(finish: str, is_exception: bool) -> float:
    if is_exception or finish is None:
        return 0.0
    try:
        f = int(finish)
    except ValueError:
        return 0.0
    if not (1 <= f <= 6):
        return 0.0
    return 7 - f


def compute_boat_features(con, reg_no: str, course: int, before_date: str):
    # Recent form: last 10 starts in this course before the race date.
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
    if recent:
        wsum = 0.0
        wtot = 0.0
        for finish, is_exc, grade in recent:
            w = GRADE_WEIGHT if grade in ("SG", "G1") else 1.0
            wsum += point_expr(finish, is_exc) * w
            wtot += w
        rf = wsum / wtot if wtot else FALLBACK_POINT
    else:
        rf = FALLBACK_POINT

    # ST: all-time (all venues), before the race date.
    st_row = con.execute(
        """
        SELECT avg(start_timing) FROM entries_enriched
        WHERE reg_no = ? AND entry_course = ? AND date < ? AND start_timing IS NOT NULL
        """,
        [reg_no, course, before_date],
    ).fetchone()
    st = st_row[0] if st_row and st_row[0] is not None else FALLBACK_ST

    # Course aptitude: all-time (all venues), before the race date.
    ca_row = con.execute(
        """
        SELECT avg(CASE WHEN is_exception OR TRY_CAST(finish AS INTEGER) IS NULL THEN 0
                         ELSE 7 - TRY_CAST(finish AS INTEGER) END)
        FROM entries_enriched
        WHERE reg_no = ? AND entry_course = ? AND date < ?
        """,
        [reg_no, course, before_date],
    ).fetchone()
    ca = ca_row[0] if ca_row and ca_row[0] is not None else FALLBACK_POINT

    return rf, st, ca


def normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def predict_top_n(boats: list[dict], n: int) -> list[tuple[tuple[int, ...], float]]:
    rf_norm = normalize([b["rf"] for b in boats])
    st_norm = normalize([-b["st"] for b in boats])  # lower ST is better -> negate before normalizing
    ca_norm = normalize([b["ca"] for b in boats])

    strengths = {}
    for i, b in enumerate(boats):
        composite = W_RF * rf_norm[i] + W_ST * st_norm[i] + W_CA * ca_norm[i]
        strengths[b["frame"]] = math.exp(STRENGTH_SCALE * composite)

    frames = [b["frame"] for b in boats]
    results = []
    total = sum(strengths.values())
    for a, b2, c in itertools.permutations(frames, 3):
        p_a = strengths[a] / total
        rem1 = total - strengths[a]
        p_b = strengths[b2] / rem1 if rem1 > 0 else 0
        rem2 = rem1 - strengths[b2]
        p_c = strengths[c] / rem2 if rem2 > 0 else 0
        results.append(((a, b2, c), p_a * p_b * p_c))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:n]


def main():
    random.seed(42)
    con = duckdb.connect(str(DB_PATH), read_only=True)

    print("Finding candidate races...", file=sys.stderr)
    candidates = con.execute(
        """
        SELECT venue_code, date, race_no, count(*) n_boats,
               count(*) FILTER (WHERE finish IN ('01','02','03')) n_top3
        FROM entries
        WHERE date >= ?
        GROUP BY 1, 2, 3
        HAVING count(*) = 6 AND count(*) FILTER (WHERE finish IN ('01','02','03')) = 3
        """,
        [MIN_DATE_FOR_SAMPLING],
    ).df()
    print(f"candidate races with a clean 6-boat / well-defined top-3 result: {len(candidates)}", file=sys.stderr)

    sample = candidates.sample(n=min(SAMPLE_SIZE, len(candidates)), random_state=42)

    hits = 0
    tested = 0
    rank_of_actual = []  # None if not found in full 120-permutation ranking
    rows_out = []

    for _, race in sample.iterrows():
        venue, date, race_no = race["venue_code"], race["date"], race["race_no"]
        entries = con.execute(
            "SELECT reg_no, frame, finish FROM entries WHERE venue_code=? AND date=? AND race_no=?",
            [venue, date, race_no],
        ).df()
        if len(entries) != 6:
            continue

        boats = []
        for _, e in entries.iterrows():
            rf, st, ca = compute_boat_features(con, e["reg_no"], int(e["frame"]), date)
            boats.append({"frame": int(e["frame"]), "rf": rf, "st": st, "ca": ca})

        top12 = predict_top_n(boats, TOP_N)
        actual = tuple(
            int(entries.loc[entries["finish"] == f, "frame"].iloc[0])
            for f in ("01", "02", "03")
        )

        tested += 1
        hit = any(combo == actual for combo, _ in top12)
        if hit:
            hits += 1

        # also find the actual's rank among all 120 for diagnostic purposes
        all120 = predict_top_n(boats, 120)
        rank = next((i + 1 for i, (combo, _) in enumerate(all120) if combo == actual), None)
        rank_of_actual.append(rank)

        rows_out.append({
            "venue": venue, "date": date, "race_no": race_no,
            "actual": "-".join(map(str, actual)), "hit_in_top12": hit, "rank_of_actual_of_120": rank,
        })

    df_out = pd.DataFrame(rows_out)
    hit_rate = hits / tested if tested else 0.0
    avg_rank = sum(r for r in rank_of_actual if r) / len(rank_of_actual) if rank_of_actual else None

    # naive baselines for comparison: fixed order 1-2-3 (most common real-world outcome),
    # and random 12-of-120 picks, each measured the same way.
    naive_123_hits = sum(1 for r in rows_out if r["actual"] == "1-2-3")
    random.seed(7)
    random_hits = 0
    for r in rows_out:
        actual_combo = tuple(map(int, r["actual"].split("-")))
        frames = list(range(1, 7))
        all_perms = list(itertools.permutations(frames, 3))
        random_pick = set(random.sample(all_perms, TOP_N))
        if actual_combo in random_pick:
            random_hits += 1

    report_path = ROOT / "docs" / "backtest_trifecta_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル バックテスト結果\n")
        p(f"対象期間: {MIN_DATE_FOR_SAMPLING} 以降からサンプリング")
        p(f"候補レース数(6艇・着順明確): {len(candidates)}")
        p(f"サンプル数: {tested}")
        p(f"\n## 的中率（上位12点に実際の結果が入っていた割合）")
        p(f"モデル: {hits}/{tested} = {hit_rate*100:.2f}%")
        p(f"参考: 全120通りランダム12点選択: {random_hits}/{tested} = {random_hits/tested*100:.2f}%")
        p(f"参考: 常に 1-2-3 固定で賭けた場合の的中率: {naive_123_hits}/{tested} = {naive_123_hits/tested*100:.2f}%")
        p(f"\n## 診断: 実際の結果が120通り中何位にランクされていたか")
        p(f"平均順位: {avg_rank:.1f}位 / 120通り" if avg_rank else "N/A")
        p(df_out["rank_of_actual_of_120"].describe().to_string())
        p("\n## 直近50件のサンプル結果")
        p(df_out.head(50).to_string())

    print(f"\nHit rate: {hits}/{tested} = {hit_rate*100:.2f}%", file=sys.stderr)
    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
