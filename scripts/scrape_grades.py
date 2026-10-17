"""Phase 3: scrape the official monthly schedule calendar to build a
(venue_code, date) -> grade master table. Named/colored event blocks (SG, G1,
G2, G3, オールレディース, ヴィーナスシリーズ, ルーキーシリーズ, マスターズリーグ,
named 一般 meets) are extracted with their venue+start date+day-span (colspan).
Any (venue_code, date) in our race data NOT covered by one of these blocks is
treated as 一般 by default (the vast majority of races).
"""
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"User-Agent": "Mozilla/5.0 (personal research script; contact: k.kishimoto@sustella-jp.com)"}

CELL_RE = re.compile(
    r'<td([^>]*)>\s*<a href="/owpc/pc/race/(?:assen|raceindex)\?jcd=(\d{2})&(?:amp;)?hd=(\d{8})"[^>]*>(.*?)</a>\s*</td>',
    re.S
)
CLASS_RE = re.compile(r'class\s*=\s*"([^"]*)"')

GRADE_MAP = {
    "is-gradeColorSG": "SG",
    "is-gradeColorG1": "G1",
    "is-gradeColorG2": "G2",
    "is-gradeColorG3": "G3",
    "is-gradeColorIppan": "一般",
    "is-gradeColorLady": "オールレディース",
    "is-gradeColorVenus": "ヴィーナスシリーズ",
    "is-gradeColorRookie": "ルーキーシリーズ",
    "is-gradeColorTakumi": "マスターズリーグ",
}


def month_range(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m > 12:
            m = 1
            y += 1


def fetch_month(year: int, month: int) -> str:
    url = f"https://www.boatrace.jp/owpc/pc/race/monthlyschedule?ym={year}{month:02d}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    r.encoding = "cp932"
    return r.text


def parse_month(html: str, year: int, month: int) -> list[dict]:
    rows = []
    for attrs, jcd, hd, title in CELL_RE.findall(html):
        cls_m = CLASS_RE.search(attrs)
        cls = cls_m.group(1) if cls_m else None
        grade = GRADE_MAP.get(cls, cls)
        colspan_m = re.search(r'colspan\s*=\s*"(\d+)"', attrs)
        days = int(colspan_m.group(1)) if colspan_m else 1
        start_d = date(int(hd[:4]), int(hd[4:6]), int(hd[6:8]))
        title_clean = re.sub(r"<[^>]+>", "", title).strip()
        for i in range(days):
            d = start_d + timedelta(days=i)
            rows.append({
                "venue_code": jcd,
                "date": d.strftime("%y%m%d"),
                "grade": grade,
                "event_title": title_clean,
                "meet_start_date": start_d.isoformat(),
                "meet_days": days,
            })
    return rows


def main():
    start = date(2024, 10, 1)
    end = date(2026, 10, 1)
    all_rows = []
    for y, m in month_range(start, end):
        try:
            html = fetch_month(y, m)
        except requests.RequestException as e:
            print(f"FAILED {y}-{m:02d}: {e}", file=sys.stderr)
            continue
        rows = parse_month(html, y, m)
        all_rows += rows
        print(f"{y}-{m:02d}: {len(rows)} venue-days", file=sys.stderr)
        time.sleep(1.0)

    df = pd.DataFrame(all_rows)
    # Dedup: same (venue_code, date) might appear from overlapping meet blocks at month
    # boundaries (a meet spanning month-end is listed once per month view it appears in).
    df = df.drop_duplicates(subset=["venue_code", "date"], keep="first")
    out_path = ROOT / "data" / "grade_master.parquet"
    df.to_parquet(out_path, index=False)
    df.to_csv(ROOT / "data" / "grade_master.csv", index=False, encoding="utf-8-sig")
    print(f"\nTotal rows: {len(df)}", file=sys.stderr)
    print(df["grade"].value_counts().to_string(), file=sys.stderr)
    print("Saved to", out_path, file=sys.stderr)


if __name__ == "__main__":
    main()
