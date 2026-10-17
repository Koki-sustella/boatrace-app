"""Phase 2: parse all downloaded 期別成績(fan) period files and build
racers (stable attributes) + racer_history (name/branch/class over time) tables.
"""
import sys
from pathlib import Path
from dataclasses import asdict

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parse_fanfile import parse_fan_file  # noqa: E402

PERIOD_FILES = ["fan2410.txt", "fan2504.txt", "fan2510.txt", "fan2604.txt"]


def main():
    all_records = []
    for fn in PERIOD_FILES:
        p = ROOT / "data" / "raw" / "kibetsu" / fn
        raw = p.read_bytes()
        records, errors = parse_fan_file(raw)
        print(f"{fn}: {len(records)} records, {len(errors)} parse errors", file=sys.stderr)
        for e in errors[:5]:
            print("  ERR", e, file=sys.stderr)
        all_records.append((fn, records))

    # sort periods chronologically by (year, period) using the first record's info per file
    all_records.sort(key=lambda t: (t[1][0].year, t[1][0].period))

    racers = {}  # toroku_no -> dict of stable attrs
    history_rows = []  # one row per (toroku_no, period) with name/klass/branch + validity range

    for fn, records in all_records:
        for r in records:
            racers.setdefault(r.toroku_no, {})
            racers[r.toroku_no].update({
                "toroku_no": r.toroku_no,
                "birth_date": r.birth_date,
                "sex": r.sex,
                "training_period": r.training_period,
                "hometown": r.hometown,
            })
            history_rows.append({
                "toroku_no": r.toroku_no,
                "year": r.year,
                "period": r.period,
                "name_kanji": r.name_kanji,
                "name_kana": r.name_kana,
                "branch": r.branch,
                "klass": r.klass,
                "calc_from": r.calc_from,
                "calc_to": r.calc_to,
                "win_rate": r.win_rate,
                "place_rate": r.place_rate,
                "avg_st": r.avg_st,
                "starts": r.starts,
                "source_file": fn,
            })

    racers_df = pd.DataFrame(list(racers.values()))
    history_df = pd.DataFrame(history_rows).sort_values(["toroku_no", "year", "period"])

    # Collapse to "attribute changed" rows: keep a period row only if name/klass/branch
    # differs from the immediately preceding period for that racer (or it's their first).
    changed_rows = []
    for toroku_no, g in history_df.groupby("toroku_no", sort=False):
        prev = None
        for _, row in g.iterrows():
            key = (row["name_kanji"], row["klass"], row["branch"])
            if prev is None or key != prev:
                changed_rows.append(row)
            prev = key
    racer_history_df = pd.DataFrame(changed_rows)

    db_path = ROOT / "data" / "boatrace.duckdb"
    con = duckdb.connect(str(db_path))
    con.register("racers_df", racers_df)
    con.register("history_df", history_df)
    con.register("racer_history_df", racer_history_df)
    con.execute("CREATE OR REPLACE TABLE racers AS SELECT * FROM racers_df")
    con.execute("CREATE OR REPLACE TABLE racer_period_stats AS SELECT * FROM history_df")
    con.execute("CREATE OR REPLACE TABLE racer_history AS SELECT * FROM racer_history_df")

    report = ROOT / "docs" / "phase2_racer_history_report.txt"
    with open(report, "w", encoding="utf-8") as out:
        def p(*a):
            print(*a, file=out)

        p("# racer_history 構築レポート\n")
        p(f"racers (選手マスタ): {len(racers_df)} 人")
        p(f"racer_period_stats (期別成績 全期間分): {len(history_df)} 行")
        p(f"racer_history (氏名/級/支部が変化した行のみ): {len(racer_history_df)} 行\n")

        p("## 期ごとの件数")
        p(con.execute("SELECT year, period, count(*) n FROM racer_period_stats GROUP BY 1,2 ORDER BY 1,2").df().to_string())

        p("\n## 改姓・転籍・昇降級の例（racer_historyの行数が2以上の選手）")
        multi = con.execute("""
            SELECT toroku_no, count(*) n FROM racer_history GROUP BY 1 HAVING count(*) > 1 ORDER BY n DESC LIMIT 10
        """).df()
        p(multi.to_string())
        if len(multi):
            sample_id = multi.iloc[0]["toroku_no"]
            p(f"\n### 選手 {sample_id} の履歴詳細")
            p(con.execute(f"""
                SELECT toroku_no, year, period, name_kanji, klass, branch, calc_from, calc_to
                FROM racer_history WHERE toroku_no = '{sample_id}' ORDER BY year, period
            """).df().to_string())

        p("\n## サンプル: racers 先頭5件")
        p(con.execute("SELECT * FROM racers LIMIT 5").df().to_string())

    print("\nREPORT:", report, file=sys.stderr)


if __name__ == "__main__":
    main()
