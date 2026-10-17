"""Parser for the officially-documented 期別成績 (fan) file.

Layout taken verbatim from the official page:
https://www.boatrace.jp/owpc/pc/extra/data/layout.html
Field widths are in BYTES (Shift-JIS), confirmed against a real downloaded
file (fan2604.lzh): summed widths == 416 bytes == actual first-record length.
Unlike the K-file/B-file, this format is fully byte-fixed with no irregularity,
so we slice raw bytes before decoding (each field decoded individually with
errors='replace' so one bad gaiji character doesn't blow up the whole record).
"""
from __future__ import annotations

from dataclasses import dataclass

# (field_name, byte_width)
_FIELDS: list[tuple[str, int]] = [
    ("toroku_no", 4), ("name_kanji", 16), ("name_kana", 15), ("branch", 4), ("klass", 2),
    ("era", 1), ("birth_date", 6), ("sex", 1), ("age", 2), ("height", 3), ("weight", 2), ("blood_type", 2),
    ("win_rate", 4), ("place_rate", 4), ("wins_1st", 3), ("wins_2nd", 3), ("starts", 3),
    ("final_appearances", 2), ("championships", 2), ("avg_st", 3),
]
for _c in range(1, 7):
    _FIELDS += [
        (f"c{_c}_entries", 3), (f"c{_c}_place_rate", 4),
        (f"c{_c}_avg_st", 3), (f"c{_c}_avg_start_rank", 3),
    ]
_FIELDS += [
    ("prev_class", 2), ("prev2_class", 2), ("prev3_class", 2),
    ("prev_index", 4), ("curr_index", 4),
    ("year", 4), ("period", 1), ("calc_from", 8), ("calc_to", 8), ("training_period", 3),
]
for _c in range(1, 7):
    _FIELDS += [
        (f"c{_c}_1st", 3), (f"c{_c}_2nd", 3), (f"c{_c}_3rd", 3),
        (f"c{_c}_4th", 3), (f"c{_c}_5th", 3), (f"c{_c}_6th", 3),
        (f"c{_c}_F", 2), (f"c{_c}_L0", 2), (f"c{_c}_L1", 2),
        (f"c{_c}_K0", 2), (f"c{_c}_K1", 2), (f"c{_c}_S0", 2), (f"c{_c}_S1", 2), (f"c{_c}_S2", 2),
    ]
_FIELDS += [
    ("nc_L0", 2), ("nc_L1", 2), ("nc_K0", 2), ("nc_K1", 2), ("hometown", 6),
]

RECORD_LENGTH = sum(w for _, w in _FIELDS)  # 416

_ERA_BASE = {"M": 1867, "T": 1911, "S": 1925, "H": 1988, "R": 2018}


def _era_to_date(era: str, yymmdd: str) -> str | None:
    base = _ERA_BASE.get(era.strip().upper())
    if base is None or len(yymmdd) != 6 or not yymmdd.isdigit():
        return None
    yy, mm, dd = int(yymmdd[:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    year = base + yy
    try:
        return f"{year:04d}-{mm:02d}-{dd:02d}"
    except ValueError:
        return None


def _split_fixed(raw: bytes) -> dict[str, bytes]:
    out = {}
    pos = 0
    for name, width in _FIELDS:
        out[name] = raw[pos:pos + width]
        pos += width
    return out


def _decode(b: bytes) -> str:
    return b.decode("cp932", errors="replace").strip()


def _int(b: bytes) -> int | None:
    s = _decode(b)
    return int(s) if s.lstrip("-").isdigit() else None


def _rate(b: bytes, decimals: int) -> float | None:
    s = _decode(b)
    if not s.isdigit():
        return None
    return int(s) / (10 ** decimals)


@dataclass
class RacerPeriodRecord:
    toroku_no: str
    name_kanji: str
    name_kana: str
    branch: str
    klass: str
    birth_date: str | None
    sex: str
    age: int | None
    height: int | None
    weight: int | None
    blood_type: str
    win_rate: float | None
    place_rate: float | None
    wins_1st: int | None
    wins_2nd: int | None
    starts: int | None
    final_appearances: int | None
    championships: int | None
    avg_st: float | None
    prev_class: str
    prev2_class: str
    prev3_class: str
    prev_index: float | None
    curr_index: float | None
    year: int | None
    period: int | None
    calc_from: str | None
    calc_to: str | None
    training_period: int | None
    hometown: str
    course_stats: dict  # {1..6: {entries, place_rate, avg_st, avg_start_rank, 1st..6th, F,L0,L1,K0,K1,S0,S1,S2}}
    no_course_exceptions: dict  # {L0,L1,K0,K1}


def parse_fan_file(raw_bytes: bytes):
    """raw_bytes: the full decompressed .TXT content (not yet decoded)."""
    records: list[RacerPeriodRecord] = []
    errors: list[tuple[int, str]] = []
    lines = raw_bytes.split(b"\r\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if len(line) != RECORD_LENGTH:
            errors.append((i, f"unexpected length {len(line)} (expected {RECORD_LENGTH})"))
            continue
        f = _split_fixed(line)

        course_stats = {}
        for c in range(1, 7):
            course_stats[c] = {
                "entries": _int(f[f"c{c}_entries"]),
                "place_rate": _rate(f[f"c{c}_place_rate"], 1),
                "avg_st": _rate(f[f"c{c}_avg_st"], 2),
                "avg_start_rank": _rate(f[f"c{c}_avg_start_rank"], 2),
                "1st": _int(f[f"c{c}_1st"]), "2nd": _int(f[f"c{c}_2nd"]), "3rd": _int(f[f"c{c}_3rd"]),
                "4th": _int(f[f"c{c}_4th"]), "5th": _int(f[f"c{c}_5th"]), "6th": _int(f[f"c{c}_6th"]),
                "F": _int(f[f"c{c}_F"]), "L0": _int(f[f"c{c}_L0"]), "L1": _int(f[f"c{c}_L1"]),
                "K0": _int(f[f"c{c}_K0"]), "K1": _int(f[f"c{c}_K1"]),
                "S0": _int(f[f"c{c}_S0"]), "S1": _int(f[f"c{c}_S1"]), "S2": _int(f[f"c{c}_S2"]),
            }

        records.append(RacerPeriodRecord(
            toroku_no=_decode(f["toroku_no"]),
            name_kanji=_decode(f["name_kanji"]).replace("　", " ").strip(),
            name_kana=_decode(f["name_kana"]).strip(),
            branch=_decode(f["branch"]),
            klass=_decode(f["klass"]),
            birth_date=_era_to_date(_decode(f["era"]), _decode(f["birth_date"])),
            sex="男" if _decode(f["sex"]) == "1" else ("女" if _decode(f["sex"]) == "2" else _decode(f["sex"])),
            age=_int(f["age"]),
            height=_int(f["height"]),
            weight=_int(f["weight"]),
            blood_type=_decode(f["blood_type"]),
            win_rate=_rate(f["win_rate"], 2),
            place_rate=_rate(f["place_rate"], 1),
            wins_1st=_int(f["wins_1st"]),
            wins_2nd=_int(f["wins_2nd"]),
            starts=_int(f["starts"]),
            final_appearances=_int(f["final_appearances"]),
            championships=_int(f["championships"]),
            avg_st=_rate(f["avg_st"], 2),
            prev_class=_decode(f["prev_class"]),
            prev2_class=_decode(f["prev2_class"]),
            prev3_class=_decode(f["prev3_class"]),
            prev_index=_rate(f["prev_index"], 2),
            curr_index=_rate(f["curr_index"], 2),
            year=_int(f["year"]),
            period=_int(f["period"]),
            calc_from=_decode(f["calc_from"]) or None,
            calc_to=_decode(f["calc_to"]) or None,
            training_period=_int(f["training_period"]),
            hometown=_decode(f["hometown"]),
            course_stats=course_stats,
            no_course_exceptions={
                "L0": _int(f["nc_L0"]), "L1": _int(f["nc_L1"]),
                "K0": _int(f["nc_K0"]), "K1": _int(f["nc_K1"]),
            },
        ))
    return records, errors
