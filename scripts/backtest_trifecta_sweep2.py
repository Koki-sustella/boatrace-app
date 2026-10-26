"""Extends backtest_trifecta_sweep.py's cached races with two more candidate
factors, both pulled straight from the historical B-file program_entries row
for that exact race -- a point-in-time snapshot the official data provider
already computed before the race, so there's no lookahead risk at all:

  - WR (全国/当地勝率): average of national_win_rate and local_win_rate as
    published for that race.
  - CL (級別): A1=4, A2=3, B1=2, B2=1, as published for that race.

Augments data/trifecta_backtest_cache.json in place (adds "wr"/"cl" to each
boat), then sweeps a handful of weight configurations reflecting the user's
ask ("級別は軽く、全国/当地勝率はやや重く").
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

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5  # roughly a B1 league-average win_rate
FALLBACK_CL = 2.0  # roughly B1
STRENGTH_SCALE = 4.0
TOP_N = 12

CLASS_SCORE = {"A1": 4.0, "A2": 3.0, "B1": 2.0, "B2": 1.0}


def augment_cache():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)

    for i, race in enumerate(races):
        venue, date, race_no = race["venue"], race["date"], race["race_no"]
        entries = con.execute(
            "SELECT reg_no, frame FROM entries WHERE venue_code=? AND date=? AND race_no=?",
            [venue, date, race_no],
        ).fetchall()
        reg_by_frame = {int(frame): reg_no for reg_no, frame in entries}

        for boat in race["boats"]:
            reg_no = reg_by_frame.get(boat["frame"])
            row = None
            if reg_no is not None:
                row = con.execute(
                    """
                    SELECT national_win_rate, local_win_rate, klass
                    FROM program_entries WHERE venue_code=? AND date=? AND race_no=? AND reg_no=?
                    """,
                    [venue, date, race_no, reg_no],
                ).fetchone()
            if row:
                nat, loc, klass = row
                wr = ((nat or 0) + (loc or 0)) / 2 if (nat is not None or loc is not None) else None
                cl = CLASS_SCORE.get(klass)
            else:
                wr, cl = None, None
            boat["wr"] = wr
            boat["cl"] = cl

        if (i + 1) % 200 == 0:
            print(f"  augmented {i + 1}/{len(races)}", file=sys.stderr)

    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(races, f)
    print(f"Augmented {len(races)} races with wr/cl, saved to {CACHE_PATH}", file=sys.stderr)

    missing_wr = sum(1 for r in races for b in r["boats"] if b["wr"] is None)
    missing_cl = sum(1 for r in races for b in r["boats"] if b["cl"] is None)
    total_boats = sum(len(r["boats"]) for r in races)
    print(f"missing wr: {missing_wr}/{total_boats}, missing cl: {missing_cl}/{total_boats}", file=sys.stderr)


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
        top12 = predict_top_n(race["boats"], weights, grade_weight, TOP_N)
        actual = tuple(race["actual"])
        if any(combo == actual for combo, _ in top12):
            hits += 1
    return hits / len(races) if races else 0.0


def main():
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)

    configs = {
        "比較用ベースライン・WR/CL無し (CA.45/RF.30/ST.25)": {"ca": 0.45, "rf": 0.30, "st": 0.25},
        "WR/CL追加・CL軽め/WRやや重め (CA.30/RF.20/ST.15/WR.25/CL.10)": {"ca": 0.30, "rf": 0.20, "st": 0.15, "wr": 0.25, "cl": 0.10},
        "WRを最重視 (CA.20/RF.15/ST.10/WR.45/CL.10)": {"ca": 0.20, "rf": 0.15, "st": 0.10, "wr": 0.45, "cl": 0.10},
        "WR/CA同程度に重め (CA.25/RF.15/ST.10/WR.30/CL.20)": {"ca": 0.25, "rf": 0.15, "st": 0.10, "wr": 0.30, "cl": 0.20},
        "CL最軽量・WRのみ強調 (CA.30/RF.20/ST.15/WR.30/CL.05)": {"ca": 0.30, "rf": 0.20, "st": 0.15, "wr": 0.30, "cl": 0.05},
    }

    report_path = ROOT / "docs" / "backtest_trifecta_sweep2_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル 追加要素(級別・全国/当地勝率)比較\n")
        p(f"レース数: {len(races)} (grade_weight=2.0 固定)\n")
        for label, weights in configs.items():
            hr = evaluate(races, weights, 2.0)
            p(f"{label}")
            p(f"  的中率: {hr*100:.2f}%  ({int(round(hr*len(races)))}/{len(races)})\n")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("augment", "all"):
        augment_cache()
    if mode in ("sweep", "all"):
        main()
