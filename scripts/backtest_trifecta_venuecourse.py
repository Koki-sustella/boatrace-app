"""Checks whether adding 場×コースの構造的な有利不利 (this venue's course win
rate, independent of which racer is in it -- the same signal already shown on
the 場×コース page, but not currently fed into the trifecta model at all) as
an 8th factor changes the hit rate. Computed strictly before each race's date
(no lookahead), unlike the pre-built agg_venue_course_overall table which
covers all history.

Note: the current 直前比較 page doesn't take a venue as input at all (just 6
registration numbers) -- if this factor earns its keep, wiring it into the
live app means adding a venue selector first. This script is the pre-check
before investing in that UI change.
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
AUGMENTED_PATH = ROOT / "data" / "trifecta_backtest_cache_venuecourse.json"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5
FALLBACK_CL = 2.0
FALLBACK_MOTOR = 32.4
FALLBACK_MEET = 3.5
FALLBACK_VC = 0.14  # roughly 1/6 flat if no history
STRENGTH_SCALE = 4.0
GRADE_WEIGHT = 2.0
TOP_N = 12

CONFIGS = {
    "現行ライブ・場コース無し (CA.29/RF.19/ST.14/WR.22/CL.05/MOTOR.05/MEET.06)": {"ca": 0.29, "rf": 0.19, "st": 0.14, "wr": 0.22, "cl": 0.05, "motor": 0.05, "meet": 0.06},
    "場コース軽め (CA.26/RF.17/ST.13/WR.20/CL.05/MOTOR.05/MEET.06/VC.08)": {"ca": 0.26, "rf": 0.17, "st": 0.13, "wr": 0.20, "cl": 0.05, "motor": 0.05, "meet": 0.06, "vc": 0.08},
    "場コースやや重め (CA.23/RF.15/ST.11/WR.18/CL.05/MOTOR.05/MEET.06/VC.17)": {"ca": 0.23, "rf": 0.15, "st": 0.11, "wr": 0.18, "cl": 0.05, "motor": 0.05, "meet": 0.06, "vc": 0.17},
    "場コース重視 (CA.17/RF.11/ST.08/WR.13/CL.05/MOTOR.05/MEET.06/VC.35)": {"ca": 0.17, "rf": 0.11, "st": 0.08, "wr": 0.13, "cl": 0.05, "motor": 0.05, "meet": 0.06, "vc": 0.35},
}


def augment():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)

    for i, race in enumerate(races):
        venue, date = race["venue"], race["date"]
        for boat in race["boats"]:
            row = con.execute(
                """
                SELECT avg(CASE WHEN finish = '01' THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS win_rate,
                       count(*) AS starts
                FROM entries_enriched
                WHERE venue_code = ? AND entry_course = ? AND date < ?
                """,
                [venue, boat["frame"], date],
            ).fetchone()
            boat["vc_win_rate"], boat["vc_starts"] = row

        if (i + 1) % 200 == 0:
            print(f"  augmented {i + 1}/{len(races)}", file=sys.stderr)

    with open(AUGMENTED_PATH, "w", encoding="utf-8") as f:
        json.dump(races, f)
    print(f"Augmented {len(races)} races, saved to {AUGMENTED_PATH}", file=sys.stderr)


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
    vc = [(b.get("vc_win_rate") if b.get("vc_win_rate") is not None else FALLBACK_VC) for b in boats]

    norm = {
        "rf": normalize(rf), "st": normalize(st_raw), "ca": normalize(ca),
        "wr": normalize(wr), "cl": normalize(cl), "motor": normalize(motor),
        "meet": normalize(meet), "vc": normalize(vc),
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

    report_path = ROOT / "docs" / "backtest_trifecta_venuecourse_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル 場×コース構造バイアスを追加した場合の的中率\n")
        p(f"レース数: {len(races)} (grade_weight=2.0, 上位{TOP_N}点, vc=date<race_dateで集計・ルックアヘッド無し)\n")
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
