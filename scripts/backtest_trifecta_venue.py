"""Breaks the general 1000-race backtest cache down by venue (競艇場) and
reports each venue's hit rate under the current live model, to find which
venues the model does best/worst on.

Reuses the live app's actual per-race weight selection (default vs. 女子レース
weights) the same way backtest_trifecta_grade.py does.
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
TOP_N = 12

WEIGHTS_DEFAULT = {"ca": 0.30, "rf": 0.20, "st": 0.15, "wr": 0.30, "cl": 0.05}
WEIGHTS_WOMEN = {"ca": 0.50, "rf": 0.20, "st": 0.10, "wr": 0.15, "cl": 0.05}

VENUE_NAMES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
    "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
    "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島",
    "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}


def tag_women(races: list[dict], con) -> None:
    for race in races:
        entries = con.execute(
            "SELECT reg_no FROM entries WHERE venue_code=? AND date=? AND race_no=?",
            [race["venue"], race["date"], race["race_no"]],
        ).fetchall()
        reg_nos = [r[0] for r in entries]
        if not reg_nos:
            race["is_women"] = False
            continue
        sexes = con.execute(
            f"SELECT sex FROM racers WHERE toroku_no IN ({','.join('?' * len(reg_nos))})",
            reg_nos,
        ).fetchall()
        race["is_women"] = len(sexes) == len(reg_nos) and all(s[0] == "女" for s in sexes)


def recent_form_score(recent: list[dict]) -> float:
    if not recent:
        return FALLBACK_POINT
    wsum = wtot = 0.0
    for r in recent:
        w = 2.0 if r["top_grade"] else 1.0
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


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)

    tag_women(races, con)

    by_venue: dict[str, list[int]] = {}  # venue -> [hits, total]
    for race in races:
        weights = WEIGHTS_WOMEN if race["is_women"] else WEIGHTS_DEFAULT
        topn = predict_top_n(race["boats"], weights, TOP_N)
        actual = tuple(race["actual"])
        hit = 1 if any(combo == actual for combo, _ in topn) else 0
        h, t = by_venue.get(race["venue"], [0, 0])
        by_venue[race["venue"]] = [h + hit, t + 1]

    rows = []
    for venue, (h, t) in by_venue.items():
        rows.append((VENUE_NAMES.get(venue, venue), h, t, h / t if t else 0.0))
    rows.sort(key=lambda r: r[3], reverse=True)

    report_path = ROOT / "docs" / "backtest_trifecta_venue_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル 競艇場別の的中率\n")
        p(f"レース数: {len(races)} (現行ライブ重み・女子レース自動判定込み、上位{TOP_N}点)\n")
        p(f"{'場':6s} {'的中率':>8s}  件数")
        for name, h, t, hr in rows:
            p(f"{name:6s} {hr*100:7.2f}%  ({h}/{t})")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
