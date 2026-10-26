"""Checks how the trifecta model's hit rate changes if we show more picks
(topN) than the current live default of 12, using the current live weights
(CA.30/RF.20/ST.15/WR.30/CL.05, grade_weight=2.0 -- see trifectaPredict.ts).

Reuses the already-augmented 1000-race cache from backtest_trifecta_sweep2.py
(data/trifecta_backtest_cache.json, which has wr/cl already merged in).
"""
import json
import math
import sys
from pathlib import Path
from itertools import permutations

ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = ROOT / "data" / "trifecta_backtest_cache.json"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5
FALLBACK_CL = 2.0
STRENGTH_SCALE = 4.0
GRADE_WEIGHT = 2.0

# Current live weights (frontend/src/lib/trifectaPredict.ts)
WEIGHTS = {"ca": 0.30, "rf": 0.20, "st": 0.15, "wr": 0.30, "cl": 0.05}

CLASS_SCORE = {"A1": 4.0, "A2": 3.0, "B1": 2.0, "B2": 1.0}


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


def predict_top_n(boats: list[dict], n: int):
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
        composite = sum(WEIGHTS[k] * norm[k][i] for k in WEIGHTS)
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


def evaluate(races: list[dict], n: int) -> float:
    hits = 0
    for race in races:
        topn = predict_top_n(race["boats"], n)
        actual = tuple(race["actual"])
        if any(combo == actual for combo, _ in topn):
            hits += 1
    return hits / len(races) if races else 0.0


def main():
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)

    report_path = ROOT / "docs" / "backtest_trifecta_topn_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル 表示点数(topN)別の的中率\n")
        p(f"レース数: {len(races)} (現行ライブ重み CA.30/RF.20/ST.15/WR.30/CL.05, grade_weight=2.0 固定)\n")
        p("全組み合わせ数: 120 (6艇から3艇を並べる順列)\n")
        for n in (12, 18, 24):
            hr = evaluate(races, n)
            p(f"上位{n}点  的中率: {hr*100:.2f}%  ({int(round(hr*len(races)))}/{len(races)})  (全体の{n/120*100:.1f}%の点数)")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
