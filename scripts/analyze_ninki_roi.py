"""市場の効率性チェック: 3連単の人気順位(1-120)別に、「もし毎回その順位の組番に
100円賭け続けたら回収率はどうなるか」を全履歴データから計算する。

人気順位は「その組番が実際に1着~3着で的中した時の、その組番の事前人気」なので、
的中した場合の配当と頻度さえ分かれば、組番の中身を知らなくても
「順位Rに賭け続けた場合のROI」をシミュレートできる(パリミュチュエル方式の性質)。

パリミュチュエル方式は理論上すべての目に同じ還元率(控除率)が働くはずだが、
実際には「本命(人気上位)が過剰に売れて回収率が下がる」「大穴(人気下位)が
売れにくく回収率が上がる」などの偏り(favorite-longshot bias)が実務的に
知られている。これを実データで確認する。
"""
import sys
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"

BUCKETS = [
    (1, 1, "1位(本命)"), (2, 3, "2-3位"), (4, 6, "4-6位"), (7, 12, "7-12位"),
    (13, 24, "13-24位"), (25, 48, "25-48位"), (49, 72, "49-72位"),
    (73, 96, "73-96位"), (97, 120, "97-120位"),
]


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)
    total_races = con.execute("SELECT count(DISTINCT (venue_code,date,race_no)) FROM races").fetchone()[0]

    rows = con.execute("""
        SELECT ninki, amount FROM payouts
        WHERE bet_type = 'exacta3' AND ninki IS NOT NULL AND amount IS NOT NULL
    """).df()

    report_path = ROOT / "docs" / "ninki_roi_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 3連単 人気順位別の回収率(全履歴データ)\n")
        p(f"全レース数: {total_races}\n")
        p(f"{'人気帯':12s} {'的中数':>8s} {'頻度':>8s} {'平均配当':>10s} {'回収率':>8s}")

        for lo, hi, label in BUCKETS:
            sub = rows[(rows["ninki"] >= lo) & (rows["ninki"] <= hi)]
            n_hit = len(sub)
            freq = n_hit / total_races
            avg_payout = sub["amount"].mean() if n_hit else 0
            # EV per 100-yen bet on "this bucket's rank" each race:
            # only meaningful bucket-wide if we spread 1 bet across each rank in
            # the bucket (hi-lo+1 bets of 100 yen), winning amount when that
            # specific rank is the actual winner.
            n_ranks_in_bucket = hi - lo + 1
            stake = total_races * n_ranks_in_bucket * 100
            payout_total = sub["amount"].sum()
            roi = payout_total / stake if stake else 0
            p(f"{label:12s} {n_hit:8d} {freq*100:7.2f}% {avg_payout:10,.0f} {roi*100:7.1f}%")

        p("\n(頻度 = 全レースのうちその人気帯が勝った割合。回収率 = その人気帯の全順位に")
        p(" 均等に100円ずつ賭け続けた場合の払戻/投資。独立した単一順位に絞った場合の")
        p(" 回収率ではなく、帯全体を網羅的に買う場合の数値であることに注意。)\n")

        p("## 参考: 単一順位(1位のみ/120位のみ)に絞った場合")
        for r in (1, 2, 3, 5, 10, 20, 50, 100, 120):
            sub = rows[rows["ninki"] == r]
            n_hit = len(sub)
            stake = total_races * 100
            payout_total = sub["amount"].sum()
            roi = payout_total / stake if stake else 0
            p(f"  人気{r:3d}位のみ: 的中{n_hit}回 ({n_hit/total_races*100:.3f}%)  回収率 {roi*100:.1f}%")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
