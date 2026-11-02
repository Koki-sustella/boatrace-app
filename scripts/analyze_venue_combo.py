"""場ごとの出目(3連単の実際の着順組み合わせ, 艇番ベース)ランキングを集計する。
あわせて、「その場で過去最頻出だった組み合わせに機械的に賭け続けたら回収率は
どうなるか」も検証し、場別の出目バイアスがROI改善に使えそうかを診断する。
"""
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"

VENUE_NAMES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
    "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
    "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島",
    "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}


def main():
    con = duckdb.connect(str(DB_PATH), read_only=True)

    # Each race's actual finishing combo by frame number (1着-2着-3着).
    con.execute("""
        CREATE OR REPLACE TEMP VIEW race_combo AS
        SELECT venue_code, date, race_no,
               max(CASE WHEN finish = '01' THEN frame END) AS f1,
               max(CASE WHEN finish = '02' THEN frame END) AS f2,
               max(CASE WHEN finish = '03' THEN frame END) AS f3
        FROM entries
        GROUP BY 1, 2, 3
        HAVING f1 IS NOT NULL AND f2 IS NOT NULL AND f3 IS NOT NULL
    """)

    report_path = ROOT / "docs" / "venue_combo_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p("# 場ごとの出目(3連単・艇番ベース)ランキング\n")

        p("## 全場共通トップ10（参考・全場合算）")
        overall = con.execute("""
            SELECT f1 || '-' || f2 || '-' || f3 AS combo, count(*) n
            FROM race_combo GROUP BY 1 ORDER BY n DESC LIMIT 10
        """).df()
        total_all = con.execute("SELECT count(*) FROM race_combo").fetchone()[0]
        for _, row in overall.iterrows():
            p(f"  {row['combo']:8s} {row['n']:6d}件 ({row['n']/total_all*100:5.2f}%)")

        p(f"\n全レース数: {total_all}\n")
        p("## 場別トップ5")

        venues = con.execute("SELECT DISTINCT venue_code FROM race_combo ORDER BY 1").fetchall()
        rows_for_roi = []
        for (venue,) in venues:
            name = VENUE_NAMES.get(venue, venue)
            total = con.execute("SELECT count(*) FROM race_combo WHERE venue_code=?", [venue]).fetchone()[0]
            top = con.execute("""
                SELECT f1 || '-' || f2 || '-' || f3 AS combo, count(*) n
                FROM race_combo WHERE venue_code=? GROUP BY 1 ORDER BY n DESC LIMIT 5
            """, [venue]).df()
            p(f"\n{name}（{venue}） 全{total}レース")
            for i, (_, row) in enumerate(top.iterrows()):
                p(f"  {i+1}. {row['combo']:8s} {row['n']:5d}件 ({row['n']/total*100:5.2f}%)")
            if len(top):
                rows_for_roi.append((venue, name, top.iloc[0]['combo'], total))

        p("\n## 場の最頻出目に機械的に賭け続けた場合のROI（参考・ルックアヘッドあり=理論上限）")
        p("(注: 全期間データから求めた最頻出目を同じ全期間に賭け戻しているため、")
        p(" 実際の運用ではこの通りにはならない参考値です)\n")
        grand_stake = grand_return = 0
        for venue, name, combo, total in rows_for_roi:
            f1, f2, f3 = combo.split("-")
            hits_payout = con.execute("""
                SELECT p.amount
                FROM race_combo rc
                JOIN payouts p ON p.venue_code=rc.venue_code AND p.date=rc.date AND p.race_no=rc.race_no
                WHERE rc.venue_code=? AND rc.f1=? AND rc.f2=? AND rc.f3=? AND p.bet_type='exacta3'
            """, [venue, int(f1), int(f2), int(f3)]).fetchall()
            stake = total * 100
            ret = sum(r[0] for r in hits_payout if r[0] is not None)
            roi = ret / stake if stake else 0
            grand_stake += stake
            grand_return += ret
            p(f"  {name:6s} 最頻出目{combo:8s}  的中{len(hits_payout)}/{total}件  回収率 {roi*100:6.1f}%")

        p(f"\n全場合計: 回収率 {grand_return/grand_stake*100:.1f}%  (投資{grand_stake:,}円 / 払戻{grand_return:,.0f}円)")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
