"""Computes actual 回収率 (ROI) for the current live 3連単 model, now that real
payout data exists (scripts/backfill_payouts.py). Reuses the already-cached
1000-race general sample (data/trifecta_backtest_cache.json, from
backtest_trifecta_sweep2.py) and joins each race's actual exacta3 (3連単)
payout amount from the `payouts` table.

Stake model: betting 100 yen on each of the top-N picks every race (the
simplest flat-stake strategy). ROI = total payout received / total staked.
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
STAKE_PER_COMBO = 100

WEIGHTS_DEFAULT = {"ca": 0.30, "rf": 0.20, "st": 0.15, "wr": 0.30, "cl": 0.05}
WEIGHTS_WOMEN = {"ca": 0.50, "rf": 0.20, "st": 0.10, "wr": 0.15, "cl": 0.05}


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


def fetch_exacta3_payouts(races: list[dict], con) -> dict:
    """(venue,date,race_no) -> payout amount in yen (per 100-yen bet), or None
    if void/missing."""
    out = {}
    for race in races:
        row = con.execute(
            "SELECT amount FROM payouts WHERE venue_code=? AND date=? AND race_no=? AND bet_type='exacta3'",
            [race["venue"], race["date"], race["race_no"]],
        ).fetchone()
        out[(race["venue"], race["date"], race["race_no"])] = row[0] if row else None
    return out


def evaluate(races: list[dict], payout_by_race: dict, top_n: int):
    hits = 0
    total_stake = 0
    total_return = 0
    races_with_payout = 0
    for race in races:
        amount = payout_by_race.get((race["venue"], race["date"], race["race_no"]))
        if amount is None:
            continue  # void race or missing payout data -- excluded from ROI
        races_with_payout += 1
        weights = WEIGHTS_WOMEN if race.get("is_women") else WEIGHTS_DEFAULT
        topn = predict_top_n(race["boats"], weights, top_n)
        actual = tuple(race["actual"])
        stake = STAKE_PER_COMBO * len(topn)
        total_stake += stake
        if any(combo == actual for combo, _ in topn):
            hits += 1
            total_return += amount
    return {
        "races": races_with_payout, "hits": hits,
        "hit_rate": hits / races_with_payout if races_with_payout else 0.0,
        "stake": total_stake, "return": total_return,
        "roi": total_return / total_stake if total_stake else 0.0,
    }


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    with open(CACHE_PATH, encoding="utf-8") as f:
        races = json.load(f)

    tag_women(races, con)
    payout_by_race = fetch_exacta3_payouts(races, con)

    report_path = ROOT / "docs" / "backtest_trifecta_roi_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単予想モデル 実際の回収率(ROI)\n")
        p(f"サンプル: {len(races)}レース (現行ライブ重み・女子レース自動判定込み, grade_weight=2.0)")
        p("ステーク方式: 上位N点に各100円均等ベット (フラットベット)\n")

        for n in (4, 8, 12, 18, 24):
            r = evaluate(races, payout_by_race, n)
            p(f"## 上位{n}点")
            p(f"  対象レース数: {r['races']} (払戻データなし/不成立レースは除外)")
            p(f"  的中率: {r['hit_rate']*100:.2f}%  ({r['hits']}/{r['races']})")
            p(f"  投資額: {r['stake']:,}円  払戻額: {r['return']:,}円")
            p(f"  回収率: {r['roi']*100:.1f}%\n")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
