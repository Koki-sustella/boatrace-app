"""Parameter sweep for the 3連単 prediction model (see backtest_trifecta.py
for the baseline methodology writeup). Splits the backtest into two phases:

  1. fetch (expensive, DB-bound): for up to MAX_SAMPLE races, pull each boat's
     raw history (last-10-in-course points+grade flags, all-time ST, all-time
     course-aptitude point) using only data strictly before the race date.
     Cached to disk so every subsequent config change is instant.
  2. sweep (cheap, pure arithmetic): replay many (grade_weight, priority
     weight) configurations against the cached raw data, report hit rate for
     each, and for two sample sizes (first 500 of the cache vs. the full
     1000) so sample-size sensitivity is visible from the same underlying
     races -- not two independently-drawn samples.
"""
import itertools
import json
import math
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"
CACHE_PATH = ROOT / "data" / "trifecta_backtest_cache.json"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
STRENGTH_SCALE = 4.0
TOP_N = 12
MAX_SAMPLE = 1000
MIN_DATE_FOR_SAMPLING = "250601"


def point_expr(finish: str | None, is_exception: bool) -> float:
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
    print("Finding candidate races...", file=sys.stderr)
    candidates = con.execute(
        """
        SELECT venue_code, date, race_no
        FROM entries
        WHERE date >= ?
        GROUP BY 1, 2, 3
        HAVING count(*) = 6 AND count(*) FILTER (WHERE finish IN ('01','02','03')) = 3
        """,
        [MIN_DATE_FOR_SAMPLING],
    ).df()
    print(f"candidates: {len(candidates)}", file=sys.stderr)
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
            feat = fetch_raw_features(con, e["reg_no"], int(e["frame"]), date)
            boats.append({"frame": int(e["frame"]), **feat})
        actual = tuple(
            int(entries.loc[entries["finish"] == f, "frame"].iloc[0])
            for f in ("01", "02", "03")
        )
        races_out.append({"venue": venue, "date": date, "race_no": int(race_no), "boats": boats, "actual": list(actual)})
        if (idx + 1) % 100 == 0:
            print(f"  fetched {idx + 1}/{len(sample)}", file=sys.stderr)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(races_out, f)
    print(f"Cached {len(races_out)} races to {CACHE_PATH}", file=sys.stderr)


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


def predict_top_n(boats: list[dict], weights: tuple[float, float, float], grade_weight: float, n: int):
    w_rf, w_st, w_ca = weights
    rf = [recent_form_score(b["recent"], grade_weight) for b in boats]
    st_raw = [-(b["st"] if b["st"] is not None else FALLBACK_ST) for b in boats]
    ca = [(b["ca"] if b["ca"] is not None else FALLBACK_POINT) for b in boats]

    rf_n, st_n, ca_n = normalize(rf), normalize(st_raw), normalize(ca)
    strength = {}
    for i, b in enumerate(boats):
        composite = w_rf * rf_n[i] + w_st * st_n[i] + w_ca * ca_n[i]
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


def evaluate(races: list[dict], weights: tuple[float, float, float], grade_weight: float) -> float:
    hits = 0
    for race in races:
        top12 = predict_top_n(race["boats"], weights, grade_weight, TOP_N)
        actual = tuple(race["actual"])
        if any(combo == actual for combo, _ in top12):
            hits += 1
    return hits / len(races) if races else 0.0


def do_sweep():
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)
    print(f"Loaded {len(races)} cached races", file=sys.stderr)

    races_500 = races[:500]
    races_1000 = races

    grade_weights = [1.0, 1.5, 2.0]
    weight_configs = {
        "RF>ST>CA (現行 0.5/0.3/0.2)": (0.5, 0.3, 0.2),
        "均等 (0.33/0.33/0.33)": (1 / 3, 1 / 3, 1 / 3),
        "ST>CA>RF (0.2/0.5/0.3)": (0.2, 0.5, 0.3),
        "CA>ST>RF (0.2/0.3/0.5)": (0.2, 0.3, 0.5),
        "ST>RF>CA (0.3/0.5/0.2)": (0.3, 0.5, 0.2),
        "CA>RF>ST (0.3/0.2/0.5)": (0.3, 0.2, 0.5),
    }

    report_path = ROOT / "docs" / "backtest_trifecta_sweep_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル パラメータ比較\n")
        p(f"キャッシュ済みレース数: {len(races)} (2025-06以降からサンプリング)\n")

        p("## サンプル数の影響（同一データの先頭500件 vs 全1000件、現行設定 0.5/0.3/0.2, grade_weight=2.0）")
        hr500 = evaluate(races_500, (0.5, 0.3, 0.2), 2.0)
        hr1000 = evaluate(races_1000, (0.5, 0.3, 0.2), 2.0)
        p(f"  500件: {hr500*100:.2f}%  ({int(hr500*500)}/500)")
        p(f" 1000件: {hr1000*100:.2f}%  ({int(round(hr1000*1000))}/1000)")

        p("\n## グレード重みの影響（優先順位は現行 0.5/0.3/0.2 のまま、1000件）")
        for gw in grade_weights:
            hr = evaluate(races_1000, (0.5, 0.3, 0.2), gw)
            label = "重みなし(1.0倍)" if gw == 1.0 else f"{gw}倍"
            p(f"  SG/G1 {label}: {hr*100:.2f}%  ({int(round(hr*1000))}/1000)")

        p("\n## 優先順位（重み配分）の影響（grade_weight=2.0固定、1000件）")
        rows = []
        for label, weights in weight_configs.items():
            hr = evaluate(races_1000, weights, 2.0)
            rows.append((label, hr))
            p(f"  {label}: {hr*100:.2f}%  ({int(round(hr*1000))}/1000)")

        p("\n## 優先順位 x グレード重み 全組み合わせ（1000件）")
        p(f"{'優先順位':35s} {'1.0倍':>8s} {'1.5倍':>8s} {'2.0倍':>8s}")
        for label, weights in weight_configs.items():
            vals = [evaluate(races_1000, weights, gw) for gw in grade_weights]
            p(f"{label:35s} {vals[0]*100:7.2f}% {vals[1]*100:7.2f}% {vals[2]*100:7.2f}%")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("fetch", "all"):
        do_fetch()
    if mode in ("sweep", "all"):
        do_sweep()
