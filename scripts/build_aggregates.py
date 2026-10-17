"""Phase 3: build the pre-computed aggregation cuts described in the spec.

1. agg_racer_course_month  (選手×コース×月)      -- cross-racer growth ranking
2. agg_racer_venue_course  (選手×場×コース)      -- venue x course search / profile grid
3. agg_racer_grade_month   (選手×グレード×月)
4. agg_venue_course_overall(場×コースの全体平均) -- baseline for "vs average" comparison

Design notes (see docs/confirmed_layout.md and the dev spec):
- Every aggregate keeps raw exception-excluded sums AND exception counts
  separately, so "include/exclude exceptions" can be toggled at query time
  without re-aggregating raw rows (spec: 例外の扱いを設定で切替可能に).
- agg_racer_venue_course additionally gets a shrinkage-adjusted avg_finish
  (towards the venue x course overall baseline) while keeping the raw value
  too (spec: 補正前の生の値も保持する).
- agg_racer_course_month carries a per-grade start-count breakdown so a
  cross-racer ranking can show "how many SG/G1 starts" alongside the number
  (spec: SG・G1の出走が多い選手ほど成績が低く出やすいため併記する).
- racer_rolling_form gives the per-start rolling window needed for the
  trend graphs (直近50走 / 直近6か月).
"""
import sys
from pathlib import Path

import duckdb
import yaml

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"
CONFIG_PATH = ROOT / "config" / "app_config.yaml"
REPORT = ROOT / "docs" / "phase3_aggregates_report.txt"


def main():
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    shrinkage_k = cfg["aggregation"]["shrinkage_k"]

    con = duckdb.connect(str(DB_PATH))

    # --- 0. grade master + races_with_grade -------------------------------
    grade_parquet = ROOT / "data" / "grade_master.parquet"
    con.execute(f"CREATE OR REPLACE TABLE grade_master AS SELECT * FROM read_parquet('{grade_parquet.as_posix()}')")
    con.execute("""
        CREATE OR REPLACE VIEW races_with_grade AS
        SELECT r.*, COALESCE(g.grade, '一般') AS grade
        FROM races r
        LEFT JOIN grade_master g USING (venue_code, date)
    """)

    # --- entries enriched with grade + year_month --------------------------
    con.execute("""
        CREATE OR REPLACE VIEW entries_enriched AS
        SELECT
            e.*,
            rg.grade,
            substr(e.date, 1, 4) AS year_month,          -- 'YYMM' e.g. '2610'
            CASE WHEN e.is_exception THEN NULL ELSE TRY_CAST(e.finish AS INTEGER) END AS finish_num
        FROM entries e
        JOIN races_with_grade rg
          ON e.venue_code = rg.venue_code AND e.date = rg.date AND e.race_no = rg.race_no
    """)

    # --- 4. agg_venue_course_overall (compute first, used as baseline) -----
    con.execute("""
        CREATE OR REPLACE TABLE agg_venue_course_overall AS
        SELECT
            venue_code,
            entry_course,
            count(*) FILTER (WHERE NOT is_exception) AS starts_valid,
            count(*) FILTER (WHERE is_exception) AS starts_exception,
            avg(finish_num) FILTER (WHERE NOT is_exception) AS avg_finish,
            avg(CASE WHEN finish_num = 1 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS win_rate,
            avg(CASE WHEN finish_num <= 2 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS place2_rate,
            avg(CASE WHEN finish_num <= 3 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS place3_rate,
            avg(start_timing) FILTER (WHERE start_timing IS NOT NULL) AS avg_st
        FROM entries_enriched
        WHERE entry_course IS NOT NULL
        GROUP BY 1, 2
    """)

    # --- 1. agg_racer_course_month ------------------------------------------
    con.execute("""
        CREATE OR REPLACE TABLE agg_racer_course_month AS
        SELECT
            reg_no AS toroku_no,
            entry_course,
            year_month,
            count(*) FILTER (WHERE NOT is_exception) AS starts_valid,
            count(*) FILTER (WHERE is_exception) AS starts_exception,
            sum(finish_num) FILTER (WHERE NOT is_exception) AS sum_finish,
            count(*) FILTER (WHERE finish_num = 1) AS wins,
            count(*) FILTER (WHERE finish_num <= 2) AS place2,
            count(*) FILTER (WHERE finish_num <= 3) AS place3,
            sum(start_timing) FILTER (WHERE start_timing IS NOT NULL) AS sum_st,
            count(start_timing) AS count_st,
            count(*) FILTER (WHERE grade = 'SG') AS starts_sg,
            count(*) FILTER (WHERE grade = 'G1') AS starts_g1,
            count(*) FILTER (WHERE grade = 'G2') AS starts_g2,
            count(*) FILTER (WHERE grade = 'G3') AS starts_g3,
            count(*) FILTER (WHERE grade NOT IN ('SG','G1','G2','G3')) AS starts_other_grade
        FROM entries_enriched
        WHERE entry_course IS NOT NULL
        GROUP BY 1, 2, 3
    """)

    # --- 2. agg_racer_venue_course (+ shrinkage-adjusted avg_finish) --------
    con.execute(f"""
        CREATE OR REPLACE TABLE agg_racer_venue_course AS
        WITH raw AS (
            SELECT
                reg_no AS toroku_no,
                venue_code,
                entry_course,
                count(*) FILTER (WHERE NOT is_exception) AS starts_valid,
                count(*) FILTER (WHERE is_exception) AS starts_exception,
                avg(finish_num) FILTER (WHERE NOT is_exception) AS avg_finish_raw,
                avg(CASE WHEN finish_num = 1 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS win_rate,
                avg(CASE WHEN finish_num <= 2 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS place2_rate,
                avg(CASE WHEN finish_num <= 3 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS place3_rate,
                avg(start_timing) FILTER (WHERE start_timing IS NOT NULL) AS avg_st
            FROM entries_enriched
            WHERE entry_course IS NOT NULL
            GROUP BY 1, 2, 3
        )
        SELECT
            raw.*,
            base.avg_finish AS baseline_avg_finish,
            (raw.starts_valid * raw.avg_finish_raw + {shrinkage_k} * base.avg_finish)
                / (raw.starts_valid + {shrinkage_k}) AS avg_finish_adjusted,
            raw.avg_finish_raw - base.avg_finish AS avg_finish_vs_baseline
        FROM raw
        JOIN agg_venue_course_overall base USING (venue_code, entry_course)
    """)

    # --- 3. agg_racer_grade_month -------------------------------------------
    con.execute("""
        CREATE OR REPLACE TABLE agg_racer_grade_month AS
        SELECT
            reg_no AS toroku_no,
            grade,
            year_month,
            count(*) FILTER (WHERE NOT is_exception) AS starts_valid,
            count(*) FILTER (WHERE is_exception) AS starts_exception,
            avg(finish_num) FILTER (WHERE NOT is_exception) AS avg_finish,
            avg(CASE WHEN finish_num = 1 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS win_rate,
            avg(CASE WHEN finish_num <= 2 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS place2_rate,
            avg(CASE WHEN finish_num <= 3 THEN 1.0 ELSE 0.0 END) FILTER (WHERE NOT is_exception) AS place3_rate,
            avg(start_timing) FILTER (WHERE start_timing IS NOT NULL) AS avg_st
        FROM entries_enriched
        GROUP BY 1, 2, 3
    """)

    # --- rolling form (直近50走 / 直近6か月) ---------------------------------
    rolling_n = cfg["aggregation"]["rolling_starts_window"]
    con.execute(f"""
        CREATE OR REPLACE TABLE racer_rolling_form AS
        SELECT
            reg_no AS toroku_no,
            venue_code, date, race_no, entry_course, finish_num, is_exception,
            avg(finish_num) FILTER (WHERE NOT is_exception) OVER (
                PARTITION BY reg_no ORDER BY date, race_no
                ROWS BETWEEN {rolling_n - 1} PRECEDING AND CURRENT ROW
            ) AS avg_finish_last_{rolling_n},
            count(*) OVER (
                PARTITION BY reg_no ORDER BY date, race_no
                ROWS BETWEEN {rolling_n - 1} PRECEDING AND CURRENT ROW
            ) AS window_size
        FROM entries_enriched
    """)

    # --- report --------------------------------------------------------------
    with open(REPORT, "w", encoding="utf-8") as out:
        def p(*a):
            print(*a, file=out)

        p("# Phase 3 集計ロジック 検証レポート\n")
        for t in ["grade_master", "agg_venue_course_overall", "agg_racer_course_month",
                  "agg_racer_venue_course", "agg_racer_grade_month", "racer_rolling_form"]:
            n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            p(f"{t}: {n} 行")

        p("\n## grade内訳")
        p(con.execute("SELECT grade, count(*) FROM races_with_grade GROUP BY 1 ORDER BY 2 DESC").df().to_string())

        p("\n## 場×コース全体平均（baseline）サンプル")
        p(con.execute("SELECT * FROM agg_venue_course_overall ORDER BY venue_code, entry_course LIMIT 10").df().to_string())

        p("\n## サンプル選手(登録番号4918, K-fileで何度も見た選手)の 選手×場×コース 集計")
        p(con.execute("""
            SELECT * FROM agg_racer_venue_course WHERE toroku_no = '4918' ORDER BY venue_code, entry_course
        """).df().to_string())

        p("\n## 同選手の 選手×コース×月 集計（直近数件）")
        p(con.execute("""
            SELECT * FROM agg_racer_course_month WHERE toroku_no = '4918' ORDER BY year_month DESC LIMIT 10
        """).df().to_string())

        p("\n## 同選手の 選手×グレード×月 集計")
        p(con.execute("""
            SELECT * FROM agg_racer_grade_month WHERE toroku_no = '4918' AND starts_valid + starts_exception > 0
            ORDER BY year_month DESC LIMIT 10
        """).df().to_string())

        p("\n## 同選手の 直近50走移動平均（末尾5件）")
        p(con.execute("""
            SELECT * FROM racer_rolling_form WHERE toroku_no = '4918' ORDER BY date DESC, race_no DESC LIMIT 5
        """).df().to_string())

        p("\n## 補正(shrinkage)の効き方確認: 出走数が少ない組み合わせほどbaselineに寄るか")
        p(con.execute("""
            SELECT toroku_no, venue_code, entry_course, starts_valid, avg_finish_raw, avg_finish_adjusted, baseline_avg_finish
            FROM agg_racer_venue_course
            WHERE starts_valid BETWEEN 1 AND 3
            ORDER BY starts_valid ASC LIMIT 5
        """).df().to_string())

    print("REPORT:", REPORT, file=sys.stderr)


if __name__ == "__main__":
    main()
