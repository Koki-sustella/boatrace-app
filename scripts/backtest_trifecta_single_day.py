"""Runs the CURRENT live model (frontend/src/lib/trifectaPredict.ts's exact
weights, including venue x course bias) against every race on a single given
date, using only data strictly before that date (no lookahead -- as if the
live app had been used on that day), and reports actual hit rate + ROI using
real payout data.
"""
import itertools
import math
import sys
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "boatrace.duckdb"

FALLBACK_POINT = 3.5
FALLBACK_ST = 0.17
FALLBACK_WR = 4.5
FALLBACK_CL = 2.0
FALLBACK_MOTOR = 32.4
FALLBACK_MEET = 3.5
FALLBACK_VC = 0.14
STRENGTH_SCALE = 4.0
GRADE_WEIGHT = 2.0
TOP_N = 12
STAKE_PER_COMBO = 100

# Current live weights (frontend/src/lib/trifectaPredict.ts WEIGHTS.default)
WEIGHTS_DEFAULT = {"ca": 0.19, "rf": 0.12, "st": 0.09, "wr": 0.14, "cl": 0.05, "motor": 0.05, "meet": 0.06, "vc": 0.30}
WEIGHTS_WOMEN = {"ca": 0.5, "rf": 0.2, "st": 0.1, "wr": 0.15, "cl": 0.05}
CLASS_SCORE = {"A1": 4.0, "A2": 3.0, "B1": 2.0, "B2": 1.0}


def point_expr(finish, is_exception) -> float:
    if is_exception or finish is None:
        return 0.0
    try:
        f = int(finish)
    except ValueError:
        return 0.0
    if not (1 <= f <= 6):
        return 0.0
    return 7 - f


def fetch_race_boats(con, venue, date, race_no, reg_by_frame):
    boats = []
    sexes = []
    for frame, reg_no in reg_by_frame.items():
        recent = con.execute(
            """
            SELECT finish, is_exception, grade FROM entries_enriched
            WHERE reg_no=? AND entry_course=? AND date<? ORDER BY date DESC, race_no DESC LIMIT 10
            """,
            [reg_no, frame, date],
        ).fetchall()
        recent_points = [{"point": point_expr(f, exc), "top_grade": g in ("SG", "G1")} for f, exc, g in recent]

        st_row = con.execute(
            "SELECT avg(start_timing) FROM entries_enriched WHERE reg_no=? AND entry_course=? AND date<? AND start_timing IS NOT NULL",
            [reg_no, frame, date],
        ).fetchone()
        st = st_row[0] if st_row else None

        ca_row = con.execute(
            """SELECT avg(CASE WHEN is_exception OR TRY_CAST(finish AS INTEGER) IS NULL THEN 0
                                ELSE 7-TRY_CAST(finish AS INTEGER) END)
               FROM entries_enriched WHERE reg_no=? AND entry_course=? AND date<?""",
            [reg_no, frame, date],
        ).fetchone()
        ca = ca_row[0] if ca_row else None

        rating = con.execute(
            "SELECT national_win_rate, local_win_rate, klass, motor_2rentai_rate FROM program_entries WHERE reg_no=? AND date<? ORDER BY date DESC LIMIT 1",
            [reg_no, date],
        ).fetchone()
        if rating:
            nat, loc, klass, motor = rating
            wr = ((nat or 0) + (loc or 0)) / 2 if (nat is not None or loc is not None) else None
            cl = CLASS_SCORE.get(klass)
        else:
            wr = cl = motor = None

        vc_row = con.execute(
            "SELECT win_rate FROM agg_venue_course_overall WHERE venue_code=? AND entry_course=?",
            [venue, frame],
        ).fetchone()
        vc = vc_row[0] if vc_row else None

        sex_row = con.execute("SELECT sex FROM racers WHERE toroku_no=?", [reg_no]).fetchone()
        sexes.append(sex_row[0] if sex_row else None)

        boats.append({
            "frame": frame, "recent": recent_points, "st": st, "ca": ca,
            "wr": wr, "cl": cl, "motor": motor, "meet": None, "vc_win_rate": vc,
        })

        # 節間成績 (uses the same meet-boundary logic as the live query)
        meet_row = con.execute(
            """
            WITH venue_dates AS (
                SELECT DISTINCT r.date, strptime(r.date,'%y%m%d')::DATE AS d
                FROM races r WHERE r.venue_code=? AND r.date<?
            ),
            with_flag AS (
                SELECT date, d, CASE WHEN lag(d) OVER (ORDER BY d) IS NULL
                                           OR d-lag(d) OVER (ORDER BY d) > 1
                                      THEN 1 ELSE 0 END AS is_new_meet
                FROM venue_dates
            ),
            computed_start AS (SELECT max(date) AS cs FROM with_flag WHERE is_new_meet=1),
            meet_start AS (
                SELECT COALESCE(
                    (SELECT min(strftime(strptime(g.meet_start_date,'%Y-%m-%d'),'%y%m%d'))
                     FROM grade_master g WHERE g.venue_code=? AND g.date=?),
                    (SELECT cs FROM computed_start)
                ) AS ms
            )
            SELECT avg(CASE WHEN e.is_exception OR TRY_CAST(e.finish AS INTEGER) IS NULL THEN 0
                             ELSE 7-TRY_CAST(e.finish AS INTEGER) END), count(*)
            FROM entries e, meet_start
            WHERE e.reg_no=? AND e.venue_code=? AND e.date>=meet_start.ms AND e.date<?
            """,
            [venue, date, venue, date, reg_no, venue, date],
        ).fetchone()
        if meet_row and meet_row[1] and meet_row[1] > 0:
            boats[-1]["meet"] = meet_row[0]

    is_women = len(sexes) == 6 and all(s == "女" for s in sexes)
    return boats, is_women


def recent_form_score(recent):
    if not recent:
        return FALLBACK_POINT
    wsum = wtot = 0.0
    for r in recent:
        w = GRADE_WEIGHT if r["top_grade"] else 1.0
        wsum += r["point"] * w
        wtot += w
    return wsum / wtot if wtot else FALLBACK_POINT


def normalize(values):
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.5] * len(values)
    return [(v - lo) / (hi - lo) for v in values]


def predict_top_n(boats, weights, n):
    rf = [recent_form_score(b["recent"]) for b in boats]
    st_raw = [-(b["st"] if b["st"] is not None else FALLBACK_ST) for b in boats]
    ca = [(b["ca"] if b["ca"] is not None else FALLBACK_POINT) for b in boats]
    wr = [(b.get("wr") if b.get("wr") is not None else FALLBACK_WR) for b in boats]
    cl = [(b.get("cl") if b.get("cl") is not None else FALLBACK_CL) for b in boats]
    motor = [(b.get("motor") if b.get("motor") is not None else FALLBACK_MOTOR) for b in boats]
    meet = [(b.get("meet") if b.get("meet") is not None else FALLBACK_MEET) for b in boats]
    vc = [(b.get("vc_win_rate") if b.get("vc_win_rate") is not None else FALLBACK_VC) for b in boats]

    norm = {"rf": normalize(rf), "st": normalize(st_raw), "ca": normalize(ca), "wr": normalize(wr),
            "cl": normalize(cl), "motor": normalize(motor), "meet": normalize(meet), "vc": normalize(vc)}
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


VENUE_NAMES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島",
    "05": "多摩川", "06": "浜名湖", "07": "蒲郡", "08": "常滑",
    "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島",
    "17": "宮島", "18": "徳山", "19": "下関", "20": "若松",
    "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}


def main(date: str):
    con = duckdb.connect(str(DB_PATH), read_only=True)
    races = con.execute(
        "SELECT venue_code, race_no FROM races WHERE date=? ORDER BY venue_code, race_no", [date]
    ).fetchall()
    print(f"races on {date}: {len(races)}", file=sys.stderr)

    hits = 0
    stake = 0
    ret = 0.0
    n_women = 0
    skipped = 0
    by_venue: dict[str, list] = {}  # venue -> [hits, races, stake, ret]
    for i, (venue, race_no) in enumerate(races):
        entries = con.execute(
            "SELECT reg_no, frame, finish FROM entries WHERE venue_code=? AND date=? AND race_no=?",
            [venue, date, race_no],
        ).fetchall()
        if len(entries) != 6:
            skipped += 1
            continue
        reg_by_frame = {int(frame): reg_no for reg_no, frame, _ in entries}
        actual = None
        finish_map = {f: frame for reg_no, frame, f in entries}
        try:
            actual = tuple(int(finish_map[fk]) for fk in ("01", "02", "03"))
        except KeyError:
            skipped += 1
            continue

        boats, is_women = fetch_race_boats(con, venue, date, race_no, reg_by_frame)
        if is_women:
            n_women += 1
        weights = WEIGHTS_WOMEN if is_women else WEIGHTS_DEFAULT
        topn = predict_top_n(boats, weights, TOP_N)

        payout_row = con.execute(
            "SELECT amount FROM payouts WHERE venue_code=? AND date=? AND race_no=? AND bet_type='exacta3'",
            [venue, date, race_no],
        ).fetchone()
        amount = payout_row[0] if payout_row else None
        if amount is None:
            skipped += 1
            continue

        race_stake = STAKE_PER_COMBO * len(topn)
        race_hit = any(combo == actual for combo, _ in topn)
        race_ret = amount if race_hit else 0.0
        stake += race_stake
        if race_hit:
            hits += 1
            ret += amount

        vh, vr, vs, vret = by_venue.get(venue, [0, 0, 0, 0.0])
        by_venue[venue] = [vh + (1 if race_hit else 0), vr + 1, vs + race_stake, vret + race_ret]

        if (i + 1) % 40 == 0:
            print(f"  processed {i + 1}/{len(races)}", file=sys.stderr)

    evaluated = len(races) - skipped
    report_path = ROOT / "docs" / f"backtest_trifecta_single_day_{date}_report.txt"
    with open(report_path, "w", encoding="utf-8") as f:
        def p(*a):
            print(*a, file=f)

        p(f"# {date} 実績バックテスト（最新ライブモデル）\n")
        p(f"評価対象レース数: {evaluated} (除外: {skipped}, うち女子レース: {n_women})")
        p(f"的中率: {hits/evaluated*100:.2f}%  ({hits}/{evaluated})")
        p(f"投資額: {stake:,}円  払戻額: {ret:,.0f}円")
        p(f"回収率: {ret/stake*100:.1f}%\n")

        p("## 場別内訳")
        rows = []
        for venue in by_venue:
            vh, vr, vs, vret = by_venue[venue]
            rows.append((VENUE_NAMES.get(venue, venue), vh, vr, vs, vret))
        rows.sort(key=lambda r: (r[4] / r[3] if r[3] else 0), reverse=True)
        for name, vh, vr, vs, vret in rows:
            roi = vret / vs * 100 if vs else 0
            p(f"  {name:6s} 的中{vh:2d}/{vr}件 ({vh/vr*100:5.1f}%)  投資{vs:6,}円  払戻{vret:9,.0f}円  回収率{roi:6.1f}%")

    print(f"Report written to {report_path}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "261101")
