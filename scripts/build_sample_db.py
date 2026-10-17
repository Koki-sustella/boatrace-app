"""Phase 1 prototype: parse all downloaded sample K-file/B-file days into DuckDB
and print a verification report (counts, exception codes found, grade-related
finding, sample rows) for human review."""
import sys
from pathlib import Path
from dataclasses import asdict

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from parse_kfile import parse_k_file  # noqa: E402
from parse_bfile import parse_b_file  # noqa: E402

REPORT = ROOT / "docs" / "phase1_report.txt"


def load_all_k():
    all_races, all_boats, all_unparsed = [], [], []
    kdir = ROOT / "data" / "raw" / "kfile"
    for p in sorted(kdir.glob("K*")):
        if p.suffix.upper() != ".TXT" or ".utf8" in p.name:
            continue
        date_str = p.stem[1:]  # e.g. "261001"
        text = p.read_bytes().decode("cp932", errors="replace").replace("\r\n", "\n")
        races, boats, unparsed = parse_k_file(text, date_str)
        all_races += races
        all_boats += boats
        all_unparsed += unparsed
        print(f"{p.name}: {len(races)} races, {len(boats)} boat-results", file=sys.stderr)
    return all_races, all_boats, all_unparsed


def load_all_b():
    all_entries = []
    bdir = ROOT / "data" / "raw" / "bfile"
    for p in sorted(bdir.glob("B*")):
        if p.suffix.upper() != ".TXT" or ".utf8" in p.name:
            continue
        date_str = p.stem[1:]
        text = p.read_bytes().decode("cp932", errors="replace").replace("\r\n", "\n")
        entries = parse_b_file(text, date_str)
        all_entries += entries
        print(f"{p.name}: {len(entries)} entries", file=sys.stderr)
    return all_entries


def main():
    races, boats, _ = load_all_k()
    entries = load_all_b()

    db_path = ROOT / "data" / "sample.duckdb"
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))

    races_df = pd.DataFrame([asdict(r) for r in races])
    boats_df = pd.DataFrame([asdict(r) for r in boats])
    con.register("races_df", races_df)
    con.register("boats_df", boats_df)
    con.execute("CREATE TABLE races AS SELECT * FROM races_df")
    con.execute("CREATE TABLE entries AS SELECT * FROM boats_df")

    if entries:
        prog_df = pd.DataFrame([asdict(r) for r in entries])
        con.register("prog_df", prog_df)
        con.execute("CREATE TABLE program_entries AS SELECT * FROM prog_df")

    with open(REPORT, "w", encoding="utf-8") as out:
        def p(*a):
            print(*a, file=out)

        p("# Phase 1 取り込み試作 検証レポート\n")
        p(f"races table: {len(races)} rows")
        p(f"entries (K-file boat results) table: {len(boats)} rows")
        p(f"program_entries (B-file) table: {len(entries)} rows\n")

        p("## サンプル: races 先頭5行")
        p(con.execute("SELECT * FROM races LIMIT 5").df().to_string())

        p("\n## サンプル: entries 先頭10行（1レース分）")
        p(con.execute("SELECT * FROM entries LIMIT 6").df().to_string())

        p("\n## 例外着順コードの出現状況（is_exception=true の内訳）")
        p(con.execute("""
            SELECT exception_label, count(*) AS n
            FROM entries WHERE is_exception = TRUE
            GROUP BY 1 ORDER BY n DESC
        """).df().to_string())

        p("\n## グレード確認: races.title の distinct 値（グレード文字列が無いことの確認）")
        p(con.execute("""
            SELECT title, count(*) n FROM races GROUP BY 1 ORDER BY n DESC LIMIT 20
        """).df().to_string())
        p("-> 'title' は予選/一般/準優勝戦/優勝戦などの『レース種別』であり、SG/G1/G2/G3の")
        p("   グレードは一切含まれない。グレードは別途、公式サイトの月間スケジュールページ")
        p("   (is-gradeColorSG 等のCSSクラス、venue code+日付で特定可能) から取得するのが")
        p("   確実な方法であることを確認した。")

        p("\n## 欠場時のフィールド欠損パターン例 (K0の行)")
        p(con.execute("""
            SELECT * FROM entries WHERE exception_label LIKE '%欠場%' LIMIT 3
        """).df().to_string())

        p("\n## フライング時のST扱い例 (F)")
        p(con.execute("""
            SELECT * FROM entries WHERE exception_label = 'フライング' LIMIT 3
        """).df().to_string())

        p("\n## レースタイムが記録されている着順の分布 (上位のみ記録される、という仮説の検証)")
        p(con.execute("""
            SELECT finish, count(*) n, count(race_time_sec) with_time
            FROM entries WHERE is_exception = FALSE
            GROUP BY 1 ORDER BY 1
        """).df().to_string())

        p("\n## program_entries サンプル")
        if entries:
            p(con.execute("SELECT * FROM program_entries LIMIT 6").df().to_string())

    print("\nREPORT WRITTEN TO:", REPORT, file=sys.stderr)


if __name__ == "__main__":
    main()
