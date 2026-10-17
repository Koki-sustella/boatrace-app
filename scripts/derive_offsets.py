"""Programmatically derive exact 0-based character offsets for known field values
on real sample lines, instead of eyeballing a ruler (avoids full-width-char miscount)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def annotate(line: str, fields: list[tuple[str, str]]):
    """fields: list of (label, expected_substring). Finds each in order, prints [start,end)."""
    pos = 0
    print(repr(line))
    print(f"len={len(line)}")
    for label, val in fields:
        idx = line.find(val, pos)
        if idx == -1:
            print(f"  {label:14s} NOT FOUND (looked for {val!r} from pos {pos})")
            continue
        print(f"  {label:14s} [{idx:3d}:{idx+len(val):3d}) = {val!r}")
        pos = idx + len(val)


def main():
    b = (ROOT / "data" / "raw" / "bfile" / "B261001.TXT").read_bytes().decode("cp932")
    blines = b.splitlines()
    print("###### B-file per-boat line ######")
    line = blines[18]
    annotate(line, [
        ("frame(艇番)", "1"),
        ("reg_no(登番)", "4918"),
        ("name(選手名)", "川島拓郎"),
        ("age(年齢)", "37"),
        ("branch(支部)", "静岡"),
        ("weight(体重)", "53"),
        ("class(級別)", "B1"),
        ("nat_win(全国勝率)", "4.26"),
        ("nat_2rentai", "23.86"),
        ("local_win(当地勝率)", "5.33"),
        ("local_2rentai", "33.33"),
        ("motor_no", "54"),
        ("motor_2rentai", "36.99"),
        ("boat_no", "18"),
        ("boat_2rentai", "22.41"),
    ])
    print("  TAIL (今節成績+早見):", repr(line[len("1 4918川島拓郎37静岡53B1 4.26 23.86 5.33 33.33 54 36.99 18 22.41"):]))

    print()
    print("###### B-file header line (race1) ######")
    print(repr(blines[13]))
    print(f"len={len(blines[13])}")

    print()
    print("###### K-file per-boat line (race1, boat finishing 1st = row for 艇4918 placed 04) ######")
    k = (ROOT / "data" / "raw" / "kfile" / "K261001.TXT").read_bytes().decode("cp932")
    klines = k.splitlines()
    kline = klines[34]  # '  04  1 4918 川　島　　拓　郎 54   18  6.85   1    0.43     1.55.4'
    print(repr(kline))
    print(f"len={len(kline)}")
    annotate(kline, [
        ("finish(着)", "04"),
        ("frame(艇)", "1"),
        ("reg_no(登番)", "4918"),
        ("name(選手名)", "川　島　　拓　郎"),
        ("motor_no", "54"),
        ("boat_no", "18"),
        ("exhibition", "6.85"),
        ("course(進入)", "1"),
        ("ST", "0.43"),
        ("race_time", "1.55.4"),
    ])

    print()
    print("###### K-file race header line ######")
    print(repr(klines[28]))
    print(f"len={len(klines[28])}")

    print()
    print("###### K-file payout lines ######")
    for i in range(37, 47):
        print(i, repr(klines[i]))


if __name__ == "__main__":
    main()
