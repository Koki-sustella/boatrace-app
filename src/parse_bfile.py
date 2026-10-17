"""Phase 1 prototype parser for the official B-file (番組表データ / pre-race entry list).

Per-boat field offsets confirmed empirically against a real sample file
(docs/derive_offsets_output.txt): frame(1) regno(4) name(4) age(2) branch(2)
weight(2) class(2) then 5/6/5/6/3/6/3/6-wide right-justified numeric fields.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

VENUE_BLOCK_RE = re.compile(r"(\d{2})BBGN\n(.*?)\n\1BEND", re.S)
RACE_HEADER_RE = re.compile(r"^　?(?P<rno>\d{1,2})Ｒ\s+(?P<title>\S.*?)\s{2,}Ｈ(?P<dist>[０-９]+)ｍ")
BOAT_LINE_RE = re.compile(
    r"^(?P<frame>\d) (?P<regno>\d{4})(?P<name>.{4})(?P<age>\d{2})(?P<branch>.{2})(?P<weight>\d{2})"
    r"(?P<klass>[AB][12])(?P<natwin>.{5})(?P<nat2>.{6})(?P<locwin>.{5})(?P<loc2>.{6})"
    r"(?P<motorno>.{3})(?P<motor2>.{6})(?P<boatno>.{3})(?P<boat2>.{6})(?P<tail>.*)$"
)

_ZEN_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def _z2h(s: str) -> str:
    return s.translate(_ZEN_DIGITS)


@dataclass
class EntryRow:
    venue_code: str
    date: str
    race_no: int
    title: str
    distance_m: int | None
    frame: int
    reg_no: str
    name: str
    age: int
    branch: str
    weight: int
    klass: str
    national_win_rate: float | None
    national_2rentai_rate: float | None
    local_win_rate: float | None
    local_2rentai_rate: float | None
    motor_no: int | None
    motor_2rentai_rate: float | None
    boat_no: int | None
    boat_2rentai_rate: float | None


def _f(tok: str) -> float | None:
    tok = tok.strip()
    try:
        return float(tok)
    except ValueError:
        return None


def _i(tok: str) -> int | None:
    tok = tok.strip()
    try:
        return int(tok)
    except ValueError:
        return None


def parse_b_file(text: str, source_date: str):
    entries: list[EntryRow] = []
    for m in VENUE_BLOCK_RE.finditer(text):
        venue_code, block = m.group(1), m.group(2)
        lines = block.splitlines()
        current = None  # (race_no, title, distance)
        for line in lines:
            hm = RACE_HEADER_RE.match(line)
            if hm:
                dist_raw = _z2h(hm.group("dist"))
                current = (int(hm.group("rno")), hm.group("title").replace("　", "").strip(), int(dist_raw) if dist_raw.isdigit() else None)
                continue
            bm = BOAT_LINE_RE.match(line)
            if bm and current is not None:
                race_no, title, distance_m = current
                entries.append(EntryRow(
                    venue_code=venue_code,
                    date=source_date,
                    race_no=race_no,
                    title=title,
                    distance_m=distance_m,
                    frame=int(bm.group("frame")),
                    reg_no=bm.group("regno"),
                    name=bm.group("name").replace("　", "").strip(),
                    age=int(bm.group("age")),
                    branch=bm.group("branch").strip(),
                    weight=int(bm.group("weight")),
                    klass=bm.group("klass"),
                    national_win_rate=_f(bm.group("natwin")),
                    national_2rentai_rate=_f(bm.group("nat2")),
                    local_win_rate=_f(bm.group("locwin")),
                    local_2rentai_rate=_f(bm.group("loc2")),
                    motor_no=_i(bm.group("motorno")),
                    motor_2rentai_rate=_f(bm.group("motor2")),
                    boat_no=_i(bm.group("boatno")),
                    boat_2rentai_rate=_f(bm.group("boat2")),
                ))
    return entries
