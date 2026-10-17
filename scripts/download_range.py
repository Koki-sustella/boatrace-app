"""Phase 2: bulk-download 2 years of K-file/B-file daily archives.

Resumable: skips any (date, kind) whose .lzh already exists on disk.
Polite: fixed delay between requests so we don't hammer the official site.
Logs every attempt (ok / not_found / error) to data/raw/download_manifest.csv
so a later QA pass can see exactly which days are missing and why.
"""
from __future__ import annotations

import csv
import io
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import lhafile
import requests

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"User-Agent": "Mozilla/5.0 (personal research script; contact: k.kishimoto@sustella-jp.com)"}
DELAY_SEC = 1.2

MANIFEST = ROOT / "data" / "raw" / "download_manifest.csv"


def fetch_one(kind: str, d: date) -> str:
    """kind: 'k' or 'b'. Returns status string."""
    base = "K" if kind == "k" else "B"
    yyyymm = d.strftime("%Y%m")
    yymmdd = d.strftime("%y%m%d")
    url = f"https://www1.mbrace.or.jp/od2/{base}/{yyyymm}/{kind}{yymmdd}.lzh"
    dest_dir = ROOT / "data" / "raw" / ("kfile" if kind == "k" else "bfile")
    lzh_path = dest_dir / f"{kind}{yymmdd}.lzh"
    txt_glob = list(dest_dir.glob(f"{base}{yymmdd}.TXT"))

    if lzh_path.exists() and txt_glob:
        return "skip_exists"

    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
    except requests.RequestException as e:
        return f"error:{e}"

    if r.status_code == 404:
        return "not_found"
    if r.status_code != 200:
        return f"http_{r.status_code}"

    content = r.content
    if len(content) < 10:
        return "empty_response"

    lzh_path.write_bytes(content)
    try:
        lha = lhafile.Lhafile(io.BytesIO(content))
        names = lha.infolist()
        if not names:
            return "lzh_empty"
        for info in names:
            data = lha.read(info.filename)
            (dest_dir / info.filename).write_bytes(data)
    except Exception as e:
        return f"lzh_error:{e}"

    return "ok"


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main():
    start = date(2024, 10, 17)
    end = date(2026, 10, 16)

    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    write_header = not MANIFEST.exists()
    existing_keys = set()
    if MANIFEST.exists():
        with open(MANIFEST, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) >= 2:
                    existing_keys.add((row[0], row[1]))

    total_days = (end - start).days + 1
    done = 0
    with open(MANIFEST, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(["date", "kind", "status"])
        for d in daterange(start, end):
            dstr = d.isoformat()
            for kind in ("k", "b"):
                key = (dstr, kind)
                if key in existing_keys:
                    continue
                status = fetch_one(kind, d)
                writer.writerow([dstr, kind, status])
                f.flush()
                if status not in ("skip_exists",):
                    time.sleep(DELAY_SEC)
            done += 1
            if done % 20 == 0:
                print(f"{done}/{total_days} days processed ({dstr})", file=sys.stderr, flush=True)

    print("DONE", file=sys.stderr)


if __name__ == "__main__":
    main()
