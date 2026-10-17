"""Derive exact character-column layout from real downloaded sample files."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "layout_inspection.txt"


def ruler(width: int) -> str:
    tens = "".join(str((i // 10) % 10) if i % 10 == 0 else " " for i in range(width))
    ones = "".join(str(i % 10) for i in range(width))
    return tens + "\n" + ones


def dump_lines(path: Path, out, label: str, start: int, count: int):
    text = path.read_bytes().decode("cp932", errors="replace")
    lines = text.splitlines()
    out.write(f"\n=== {label} ({path.name}) lines {start}..{start+count} ===\n")
    out.write(ruler(100) + "\n")
    for i in range(start, min(start + count, len(lines))):
        out.write(f"{i:5d}| {lines[i]}\n")


def main():
    with open(OUT, "w", encoding="utf-8") as out:
        b = ROOT / "data" / "raw" / "bfile" / "B261001.TXT"
        dump_lines(b, out, "B-file race1 header+6boats", 13, 11)

        k = ROOT / "data" / "raw" / "kfile" / "K261001.TXT"
        dump_lines(k, out, "K-file race1 header+6boats+payout", 29, 20)

        # SG race for grade-field sanity check
        ksg = ROOT / "data" / "raw" / "kfile" / "K260528.TXT"
        dump_lines(ksg, out, "K-file SG allstar race1 header+boats", 2269, 10)

    print("wrote", OUT)


if __name__ == "__main__":
    main()
