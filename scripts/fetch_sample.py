"""Phase 1 prototype: fetch a handful of sample K-file / B-file days and inspect their raw contents."""
import io
import time
from pathlib import Path

import lhafile
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_K = ROOT / "data" / "raw" / "kfile"
RAW_B = ROOT / "data" / "raw" / "bfile"

HEADERS = {"User-Agent": "Mozilla/5.0 (personal research script; contact: k.kishimoto@sustella-jp.com)"}


def fetch_lzh(url: str) -> bytes:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.content


def extract_lzh(lzh_bytes: bytes) -> dict[str, bytes]:
    lha = lhafile.Lhafile(io.BytesIO(lzh_bytes))
    out = {}
    for info in lha.infolist():
        out[info.filename] = lha.read(info.filename)
    return out


def save_and_report(date_str: str, kind: str, url: str, dest_dir: Path):
    print(f"--- {kind} {date_str} ---")
    print("GET", url)
    raw = fetch_lzh(url)
    lzh_path = dest_dir / f"{kind}{date_str}.lzh"
    lzh_path.write_bytes(raw)
    print("saved", lzh_path, len(raw), "bytes")

    entries = extract_lzh(raw)
    for name, content in entries.items():
        txt_path = dest_dir / name
        txt_path.write_bytes(content)
        print("extracted", name, len(content), "bytes ->", txt_path)
        text = content.decode("cp932", errors="replace")
        lines = text.splitlines()
        print(f"  {len(lines)} lines, first 15:")
        for line in lines[:15]:
            print("   ", repr(line))
    return entries


if __name__ == "__main__":
    # Sample: a few recent days in October 2026. Race results lag by ~1 day.
    sample_days = ["261001", "261002", "261003"]
    for d in sample_days:
        yyyymm = "20" + d[:4]
        k_url = f"https://www1.mbrace.or.jp/od2/K/{yyyymm}/k{d}.lzh"
        b_url = f"https://www1.mbrace.or.jp/od2/B/{yyyymm}/b{d}.lzh"
        try:
            save_and_report(d, "k", k_url, RAW_K)
        except Exception as e:
            print("K fetch failed for", d, ":", e)
        time.sleep(2)
        try:
            save_and_report(d, "b", b_url, RAW_B)
        except Exception as e:
            print("B fetch failed for", d, ":", e)
        time.sleep(2)
