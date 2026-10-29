"""Checks whether adding motor's 2連対率 (motor_2rentai_rate, from
program_entries -- a point-in-time B-file snapshot, so zero lookahead risk)
as a 6th factor changes the hit rate versus the current live model.

Phase 1 (augment): re-reads data/trifecta_backtest_cache.json's 1000 general
races and adds a "motor" field (re-looks-up reg_no per boat from `entries`,
same as sweep2.py's augment_cache, then motor_2rentai_rate from
program_entries for that exact race).

Phase 2 (sweep): CA/RF/ST/WR/CL weights reshuffled to make room for a MOTOR
slice, a handful of ways.
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
AUGMENTED_PATH = ROOT / "data" / "trifecta_backtest_cache_motor.json"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5
FALLBACK_CL = 2.0
FALLBACK_MOTOR = 32.4  # league-average motor_2rentai_rate
STRENGTH_SCALE = 4.0
GRADE_WEIGHT = 2.0
TOP_N = 12

CONFIGS = {
    "現行ライブ・モーター無し (CA.30/RF.20/ST.15/WR.30/CL.05)": {"ca": 0.30, "rf": 0.20, "st": 0.15, "wr": 0.30, "cl": 0.05},
    "モーター軽め (CA.27/RF.18/ST.13/WR.27/CL.05/MOTOR.10)": {"ca": 0.27, "rf": 0.18, "st": 0.13, "wr": 0.27, "cl": 0.05, "motor": 0.10},
    "モーターやや重め (CA.24/RF.16/ST.12/WR.23/CL.05/MOTOR.20)": {"ca": 0.24, "rf": 0.16, "st": 0.12, "wr": 0.23, "cl": 0.05, "motor": 0.20},
    "モーター重視 (CA.20/RF.14/ST.10/WR.20/CL.05/MOTOR.31)": {"ca": 0.20, "rf": 0.14, "st": 0.10, "wr": 0.20, "cl": 0.05, "motor": 0.31},
    "モーター最重視 (CA.15/RF.10/ST.08/WR.12/CL.05/MOTOR.50)": {"ca": 0.15, "rf": 0.10, "st": 0.08, "wr": 0.12, "cl": 0.05, "motor": 0.50},
}


def augment():
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
            motor = None
            if reg_no is not None:
                row = con.execute(
                    "SELECT motor_2rentai_rate FROM program_entries WHERE venue_code=? AND date=? AND race_no=? AND reg_no=?",
                    [venue, date, race_no, reg_no],
                ).fetchone()
                if row:
                    motor = row[0]
            boat["motor"] = motor

        if (i + 1) % 200 == 0:
            print(f"  augmented {i + 1}/{len(races)}", file=sys.stderr)

    with open(AUGMENTED_PATH, "w", encoding="utf-8") as f:
        json.dump(races, f)
    missing = sum(1 for r in races for b in r["boats"] if b["motor"] is None)
    total = sum(len(r["boats"]) for r in races)
    print(f"Augmented {len(races)} races, saved to {AUGMENTED_PATH}", file=sys.stderr)
    print(f"missing motor: {missing}/{total}", file=sys.stderr)


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

    norm = {
        "rf": normalize(rf), "st": normalize(st_raw), "ca": normalize(ca),
        "wr": normalize(wr), "cl": normalize(cl), "motor": normalize(motor),
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

    report_path = ROOT / "docs" / "backtest_trifecta_motor_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル モーター2連対率を追加した場合の的中率\n")
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
