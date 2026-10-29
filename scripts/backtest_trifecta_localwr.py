"""Checks whether splitting the combined WR factor (currently
avg(national_win_rate, local_win_rate), weight 0.30) into two independently
normalized factors -- and shifting weight toward 当地勝率 (local_win_rate) --
changes the hit rate versus the current live model.

Phase 1 (augment): re-reads data/trifecta_backtest_cache.json's 1000 general
races and adds separate "wr_nat"/"wr_loc" fields (the cache only has the
pre-averaged "wr"). Needs the reg_no per boat, which isn't cached either, so
it's re-looked-up from `entries` the same way sweep2.py's augment_cache does.

Phase 2 (sweep): CA/RF/ST/CL held at the current live values (0.30/0.20/0.15
/0.05); only the WR budget (0.30) is split between national and local in a
few ways.
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
AUGMENTED_PATH = ROOT / "data" / "trifecta_backtest_cache_localwr.json"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5
FALLBACK_CL = 2.0
STRENGTH_SCALE = 4.0
GRADE_WEIGHT = 2.0
TOP_N = 12

CLASS_SCORE = {"A1": 4.0, "A2": 3.0, "B1": 2.0, "B2": 1.0}

# ca/rf/st/cl held at the current live values; only how the 0.30 WR budget
# splits between national and local win rate varies.
CONFIGS = {
    "現行相当 (national.15/local.15、個別正規化)": {"nat": 0.15, "loc": 0.15},
    "当地やや重視 (national.10/local.20)": {"nat": 0.10, "loc": 0.20},
    "当地重視 (national.05/local.25)": {"nat": 0.05, "loc": 0.25},
    "当地のみ (national.00/local.30)": {"nat": 0.00, "loc": 0.30},
    "全国重視 (national.25/local.05、対照用)": {"nat": 0.25, "loc": 0.05},
}
FIXED = {"ca": 0.30, "rf": 0.20, "st": 0.15, "cl": 0.05}


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
            row = None
            if reg_no is not None:
                row = con.execute(
                    """
                    SELECT national_win_rate, local_win_rate
                    FROM program_entries WHERE venue_code=? AND date=? AND race_no=? AND reg_no=?
                    """,
                    [venue, date, race_no, reg_no],
                ).fetchone()
            if row:
                nat, loc = row
            else:
                nat, loc = None, None
            boat["wr_nat"] = nat
            boat["wr_loc"] = loc

        if (i + 1) % 200 == 0:
            print(f"  augmented {i + 1}/{len(races)}", file=sys.stderr)

    with open(AUGMENTED_PATH, "w", encoding="utf-8") as f:
        json.dump(races, f)
    missing = sum(1 for r in races for b in r["boats"] if b["wr_nat"] is None and b["wr_loc"] is None)
    total = sum(len(r["boats"]) for r in races)
    print(f"Augmented {len(races)} races, saved to {AUGMENTED_PATH}", file=sys.stderr)
    print(f"missing both nat/loc: {missing}/{total}", file=sys.stderr)


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


def predict_top_n(boats: list[dict], wr_weights: dict, n: int):
    rf = [recent_form_score(b["recent"]) for b in boats]
    st_raw = [-(b["st"] if b["st"] is not None else FALLBACK_ST) for b in boats]
    ca = [(b["ca"] if b["ca"] is not None else FALLBACK_POINT) for b in boats]
    cl = [(b.get("cl") if b.get("cl") is not None else FALLBACK_CL) for b in boats]
    nat = [(b.get("wr_nat") if b.get("wr_nat") is not None else FALLBACK_WR) for b in boats]
    loc = [(b.get("wr_loc") if b.get("wr_loc") is not None else FALLBACK_WR) for b in boats]

    norm = {
        "rf": normalize(rf), "st": normalize(st_raw), "ca": normalize(ca), "cl": normalize(cl),
        "nat": normalize(nat), "loc": normalize(loc),
    }
    strength = {}
    for i, b in enumerate(boats):
        composite = (
            FIXED["ca"] * norm["ca"][i] + FIXED["rf"] * norm["rf"][i] + FIXED["st"] * norm["st"][i]
            + FIXED["cl"] * norm["cl"][i] + wr_weights["nat"] * norm["nat"][i] + wr_weights["loc"] * norm["loc"][i]
        )
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


def evaluate(races: list[dict], wr_weights: dict) -> float:
    hits = 0
    for race in races:
        topn = predict_top_n(race["boats"], wr_weights, TOP_N)
        actual = tuple(race["actual"])
        if any(combo == actual for combo, _ in topn):
            hits += 1
    return hits / len(races) if races else 0.0


def sweep():
    with open(AUGMENTED_PATH, encoding="utf-8") as f:
        races = json.load(f)

    report_path = ROOT / "docs" / "backtest_trifecta_localwr_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル 当地勝率を重視した場合の的中率\n")
        p(f"レース数: {len(races)} (CA.30/RF.20/ST.15/CL.05固定、WRのみ national/local に分割, grade_weight=2.0, 上位{TOP_N}点)\n")
        for label, wr_w in CONFIGS.items():
            hr = evaluate(races, wr_w)
            p(f"{label}")
            p(f"  的中率: {hr*100:.2f}%  ({int(round(hr*len(races)))}/{len(races)})\n")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    if mode in ("augment", "all"):
        augment()
    if mode in ("sweep", "all"):
        sweep()
