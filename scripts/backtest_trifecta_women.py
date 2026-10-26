"""Splits the cached backtest races (data/trifecta_backtest_cache.json) into
女子レース (all 6 entrants female) vs others, and reports the current live
model's hit rate for each subset.

The cache doesn't store reg_no per boat, so we re-look it up from `entries`
by (venue, date, race_no) the same way backtest_trifecta_sweep2.py's
augment_cache() does, then join against racers.sex.
"""
import json
import math
import sys
from pathlib import Path
from itertools import permutations

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"
CACHE_PATH = ROOT / "data" / "trifecta_backtest_cache.json"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5
FALLBACK_CL = 2.0
STRENGTH_SCALE = 4.0
GRADE_WEIGHT = 2.0
TOP_N = 12

# Current live weights (frontend/src/lib/trifectaPredict.ts)
WEIGHTS = {"ca": 0.30, "rf": 0.20, "st": 0.15, "wr": 0.30, "cl": 0.05}


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


def evaluate(races: list[dict], n: int) -> tuple[int, int]:
    hits = 0
    for race in races:
        topn = predict_top_n(race["boats"], n)
        actual = tuple(race["actual"])
        if any(combo == actual for combo, _ in topn):
            hits += 1
    return hits, len(races)


def tag_women_races(races: list[dict], con) -> None:
    for i, race in enumerate(races):
        venue, date, race_no = race["venue"], race["date"], race["race_no"]
        entries = con.execute(
            "SELECT reg_no FROM entries WHERE venue_code=? AND date=? AND race_no=?",
            [venue, date, race_no],
        ).fetchall()
        reg_nos = [r[0] for r in entries]
        if not reg_nos:
            race["is_women"] = None
            continue
        sexes = con.execute(
            f"SELECT sex FROM racers WHERE toroku_no IN ({','.join('?' * len(reg_nos))})",
            reg_nos,
        ).fetchall()
        race["is_women"] = len(sexes) == len(reg_nos) and all(s[0] == "女" for s in sexes)
        if (i + 1) % 200 == 0:
            print(f"  tagged {i + 1}/{len(races)}", file=sys.stderr)


def main():
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)

    con = duckdb.connect(str(DB_PATH), read_only=True)
    tag_women_races(races, con)

    women = [r for r in races if r.get("is_women") is True]
    others = [r for r in races if r.get("is_women") is False]
    unknown = [r for r in races if r.get("is_women") is None]

    report_path = ROOT / "docs" / "backtest_trifecta_women_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル 女子レース別の的中率\n")
        p(f"キャッシュ総レース数: {len(races)}  (現行ライブ重み CA.30/RF.20/ST.15/WR.30/CL.05, grade_weight=2.0, 上位{TOP_N}点固定)\n")
        p(f"女子レース(出走6名すべて女性): {len(women)}件")
        p(f"それ以外(男子・混合など): {len(others)}件")
        if unknown:
            p(f"選手データ不明で判定不可: {len(unknown)}件")
        p("")
        for label, subset in (("全体", races), ("女子レースのみ", women), ("女子レース以外", others)):
            if not subset:
                p(f"{label}: データなし")
                continue
            hits, n = evaluate(subset, TOP_N)
            p(f"{label}: 的中率 {hits/n*100:.2f}%  ({hits}/{n})")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
